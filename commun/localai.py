"""IA intégrée de TradUp : llama.cpp (llama-server.exe) lancé par TradUp lui-même, avec un modèle GGUF.

Processus séparé : si l'IA plante, TradUp reste ouvert et la relance. Écoute sur 127.0.0.1 uniquement,
sur un port libre choisi au démarrage. Seule connexion à internet : le téléchargement du modèle, une fois.
"""
import atexit, json, os, socket, subprocess, sys, threading, time, urllib.error, urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent
SERVER_EXE = BASE / "third_party" / "llama" / "llama-server.exe"
MODELS_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "TradUp" / "modeles"
MODEL_FILE = "Mistral-Nemo-Instruct-2407-Q4_K_M.gguf"
MODEL_URL = ("https://huggingface.co/bartowski/Mistral-Nemo-Instruct-2407-GGUF/resolve/main/"
             "Mistral-Nemo-Instruct-2407-Q4_K_M.gguf")
MODEL_SIZE = 7477208192  # octets : un fichier incomplet n'est pas pris pour un modèle prêt
CTX = 4096  # mémoire de travail (jetons) : assez pour un paquet de lignes, et le modèle tient mieux sur la carte
# Une seule traduction à la fois (TradUp n'en demande jamais deux en même temps) et mémoire de travail compacte
# (attention rapide + mémoire en 8 bits) : tout tient mieux dans une carte de 8 Go. Mesuré le 14/11 sur une RTX 3050 8 Go
# (Adventurer Trainer, 120 lignes, 2 mesures) : 3 044 → 3 695 lignes par heure en moyenne (+21 %). Laisser une partie
# du modèle hors de la carte est plus lent (2 547 lignes/h avec 36 couches sur 41, 1 723 avec 32) : tout reste sur la carte.
FAST = ["-np", "1", "-fa", "on", "-ctk", "q8_0", "-ctv", "q8_0"]


class LocalAIError(RuntimeError):
    """Erreur de l'IA intégrée, avec un message déjà en français clair."""


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def build_command(exe: Path, model: Path, port: int, ctx: int = CTX, fast: bool = True) -> list[str]:
    return [str(exe), "-m", str(model), "--host", "127.0.0.1", "--port", str(port), "-c", str(ctx),
            "-ngl", "99", "--no-webui"] + (FAST if fast else ["-np", "1"])


def model_path() -> Path:
    return MODELS_DIR / MODEL_FILE


def model_ready() -> bool:
    p = model_path()
    return p.is_file() and (MODEL_SIZE <= 0 or p.stat().st_size == MODEL_SIZE)


class Server:
    def __init__(self):
        self.proc = None
        self.port = None

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def start(self, timeout: float = 180.0) -> None:
        if self.alive():
            return
        try:
            self._start(timeout, fast=True)
        except LocalAIError:
            if not SERVER_EXE.exists() or not model_path().exists():
                raise
            self._start(timeout, fast=False)  # carte qui refuse la mémoire compacte : réglage simple, plus lent

    def _start(self, timeout: float, fast: bool) -> None:
        if not SERVER_EXE.exists():
            raise LocalAIError("Composant IA manquant : réinstalle TradUp.")
        if not model_path().exists():
            raise LocalAIError("Modèle d'IA pas encore téléchargé : clique sur « IA intégrée » en haut.")
        self.port = free_port()
        log = MODELS_DIR.parent / "llama.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        with open(log, "ab") as fh:  # le serveur garde sa propre copie du fichier ouvert
            self.proc = subprocess.Popen(build_command(SERVER_EXE, model_path(), self.port, fast=fast), stdout=fh,
                                         stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, creationflags=flags)
        end = time.monotonic() + timeout
        while time.monotonic() < end and self.alive():
            try:
                with urllib.request.urlopen(self.url("/health"), timeout=2) as r:
                    if r.status == 200:
                        return
            except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
                pass  # modèle encore en chargement (503) ou serveur pas encore à l'écoute
            time.sleep(0.5)
        self.stop()
        raise LocalAIError("L'IA n'a pas pu démarrer (mémoire de la carte graphique insuffisante ?).")

    def stop(self) -> None:
        if self.proc is not None:
            if self.proc.poll() is None:
                self.proc.terminate()
                try:
                    self.proc.wait(10)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
        self.proc = None
        self.port = None


SERVER = Server()
atexit.register(SERVER.stop)


def _post(url: str, payload: dict, timeout: float) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _chat(system: str, user: str, temperature: float = 0.2, timeout: float = 600.0) -> str:
    """Une question → le texte de la réponse (JSON demandé). Relance l'IA une fois si elle ne répond plus."""
    payload = {"messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
               "temperature": temperature, "response_format": {"type": "json_object"}, "stream": False}
    for attempt in (1, 2):
        SERVER.start()
        try:
            res = _post(SERVER.url("/v1/chat/completions"), payload, timeout)
            return res["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            raise LocalAIError(f"L'IA locale a eu un problème (erreur {e.code}), souvent par manque de mémoire.")
        except (urllib.error.URLError, ConnectionError):
            if attempt == 2:
                raise LocalAIError("L'IA locale ne répond plus : relance la traduction.")
            SERVER.stop()  # le serveur a sans doute planté : on le relance une fois
        except (KeyError, IndexError, TypeError, json.JSONDecodeError):
            raise LocalAIError("L'IA a renvoyé une réponse illisible.")
        except (TimeoutError, socket.timeout):
            raise LocalAIError("L'IA locale met trop de temps à répondre : baisse « Lignes par paquet » (par exemple à 8).")
    raise LocalAIError("L'IA locale ne répond plus : relance la traduction.")


# Quand TradUp ne traduit plus, l'IA rend la mémoire de la carte graphique (sinon les jeux ralentissent).
# Elle se recharge toute seule à la traduction suivante (quelques secondes).
IDLE_STOP = 90.0  # secondes sans aucune demande avant de libérer la carte graphique
_lock = threading.Lock()
_active = 0
_idle = None


def _idle_stop() -> None:
    with _lock:
        if _active == 0:
            SERVER.stop()


def chat(system: str, user: str, temperature: float = 0.2, timeout: float = 600.0) -> str:
    """Une question → le texte de la réponse (JSON demandé). Libère la carte graphique après IDLE_STOP secondes sans demande."""
    global _active, _idle
    with _lock:
        _active += 1
        if _idle is not None:
            _idle.cancel()
            _idle = None
    try:
        return _chat(system, user, temperature, timeout)
    finally:
        with _lock:
            _active -= 1
            if _active == 0:
                _idle = threading.Timer(IDLE_STOP, _idle_stop)
                _idle.daemon = True
                _idle.start()


# ------------------------------------------------------------------ téléchargement du modèle (une seule fois)
def _open(url: str, start: int):
    req = urllib.request.Request(url, headers={"Range": f"bytes={start}-"} if start > 0 else {})
    return urllib.request.urlopen(req, timeout=60)


def download_model(progress=None, chunk: int = 1 << 20) -> Path:
    """Télécharge le modèle dans un fichier .part (repris s'il existe), puis le renomme. progress(reçu, total)."""
    if not MODEL_URL:
        raise LocalAIError("Adresse du modèle non configurée.")
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    final = model_path()
    part = final.with_name(final.name + ".part")
    start = part.stat().st_size if part.exists() else 0
    try:
        r = _open(MODEL_URL, start)
        try:
            if start and getattr(r, "status", 206) == 200:  # le serveur ignore la reprise : on recommence
                start = 0
            total = start + int(r.headers.get("Content-Length") or 0)
            done = start
            with open(part, "ab" if start else "wb") as f:
                while True:
                    buf = r.read(chunk)
                    if not buf:
                        break
                    f.write(buf)
                    done += len(buf)
                    if progress:
                        progress(done, total)
        finally:
            close = getattr(r, "close", None)
            if close:
                close()
    except (urllib.error.URLError, ConnectionError, TimeoutError, socket.timeout):
        raise LocalAIError("Téléchargement interrompu : relance-le, il reprendra où il s'est arrêté.")
    if MODEL_SIZE > 0 and part.stat().st_size != MODEL_SIZE:
        raise LocalAIError("Téléchargement incomplet : relance-le, il reprendra où il s'est arrêté.")
    part.replace(final)
    return final
