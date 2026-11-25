"""TradVoice : donner une voix française aux personnages d'un jeu, tout sur le PC.

Même squelette que TradUp : une fenêtre pywebview qui affiche static/index.html, et la classe Api appelée par
l'interface (window.pywebview.api.*). Le moteur de TradUp est repris tel quel dans commun/.

Étape actuelle (voir SPEC_tradvoice.md) : ouvrir un jeu Ren'Py, trouver qui parle, proposer et régler une fiche voix
par personnage (description, jamais un clonage). Le moteur de voix n'est pas encore branché : rien n'est encore
écrit dans le jeu.

Lancer : python app.py        Vérifier sans fenêtre : python app.py --autotest
"""
import json, os, re, sys, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "commun")]

import fiches, personnages  # noqa: E402
import gamescan, localai, renpygame  # noqa: E402  (commun/, repris de TradUp)

VERSION = "0.1"
DEMO = os.path.join(HERE, "demo", "Mistvale")


def projects_dir():
    d = os.path.join(os.path.expanduser("~"), "Documents", "TradVoice", "projets")
    os.makedirs(d, exist_ok=True)
    return d


def safe_name(name):
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", name).strip(" .")[:80] or "jeu"


def project_path(name):
    return os.path.join(projects_dir(), safe_name(name) + ".json")


def load_project(name):
    try:
        with open(project_path(name), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_project(proj):
    proj["saved"] = time.strftime("%Y-%m-%d %H:%M")
    tmp = project_path(proj["name"]) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(proj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, project_path(proj["name"]))


def recent(limit=6):
    out = []
    for f in sorted(os.listdir(projects_dir()), key=lambda f: -os.path.getmtime(os.path.join(projects_dir(), f))):
        if f.endswith(".json"):
            try:
                with open(os.path.join(projects_dir(), f), encoding="utf-8") as fh:
                    p = json.load(fh)
                out.append({"name": p.get("name", f[:-5]), "path": p.get("path", ""), "chars": len(p.get("cards", {})),
                            "lines": p.get("lines", 0), "kind": p.get("kind", "")})
            except (OSError, ValueError):
                continue
        if len(out) >= limit:
            break
    return out


def ai_ready():
    try:
        return localai.model_ready() and localai.SERVER_EXE.exists()
    except Exception:
        return False


def friendly_error(e):
    if isinstance(e, localai.LocalAIError):
        return str(e)
    return f"Problème inattendu : {e}"


class Api:
    def __init__(self):
        self._win = None
        self.game = None  # {"name", "path", "lines", "chars", "kind"}
        self.proj = {}

    # ------------------------------------------------------------------ état
    def status(self):
        return {"version": VERSION, "ai": ai_ready(), "voice": False, "recent": recent(), "demo": os.path.isdir(DEMO)}

    def _state(self):
        g, p = self.game, self.proj
        return {"name": g["name"], "kind": p.get("kind", g["kind"]), "lines": len(g["lines"]), "chars": g["chars"],
                "cards": p.get("cards", {}), "context": p.get("context", ""),
                "alikes": fiches.look_alikes(p.get("cards", {}), g["chars"])}

    # ------------------------------------------------------------------ ouvrir un jeu
    def open_game(self, path):
        try:
            info = gamescan.resolve(path)
            root = info["path"]
            ac = gamescan.anticheat(root)
            if ac:
                return {"error": f"Ce jeu est protégé par {ac} (jeu en ligne) : le modifier peut faire bannir ton compte. "
                                 "TradVoice ne le touche pas."}
            if not renpygame.is_renpy(root):
                return {"error": "Pour l'instant, TradVoice sait lire les jeux Ren'Py (visual novels). "
                                 "Les autres moteurs arrivent ensuite."}
            lines = personnages.extract(root)
            if not lines:
                return {"error": "Aucune réplique trouvée dans ce jeu (scripts protégés par le studio ?)."}
            chars = personnages.summary(lines)
            self.game = {"name": info["name"], "path": root, "lines": lines, "chars": chars,
                         "kind": personnages.game_kind(lines)}
            self.proj = load_project(info["name"]) or {"name": info["name"], "path": root, "kind": self.game["kind"],
                                                       "context": "", "cards": {}}
            self.proj["lines"] = len(lines)
            if set(self.proj.get("cards", {})) != {c["name"] for c in chars}:
                self.proj["cards"] = fiches.propose(chars, self.proj.get("context", ""), self.proj.get("cards"))
            save_project(self.proj)
            return self._state()
        except Exception as e:
            return {"error": friendly_error(e)}

    def open_demo(self):
        return self.open_game(DEMO)

    def pick_folder(self):
        import webview
        p = self._win.create_file_dialog(webview.FileDialog.FOLDER)
        return self.open_game(p[0]) if p else None

    def on_drop(self, e):
        files = e.get("dataTransfer", {}).get("files", [])
        paths = [f.get("pywebviewFullPath") for f in files if f.get("pywebviewFullPath")]
        if paths and self._win:
            res = self.open_game(paths[0])
            self._win.evaluate_js(f"window.onGameOpened({json.dumps(res, ensure_ascii=False)})")

    # ------------------------------------------------------------------ fiches voix
    def save_context(self, kind, context):
        if not self.game:
            return None
        self.proj["kind"] = kind if kind in ("dialogues", "textuel") else self.proj.get("kind")
        self.proj["context"] = str(context or "")[:2000]
        save_project(self.proj)
        return self._state()

    def save_card(self, name, card):
        if not self.game or name not in self.proj.get("cards", {}):
            return None
        base = self.proj["cards"][name]
        new = fiches.clean(card, base)
        new["verrouille"] = bool(card.get("verrouille", base.get("verrouille")))
        if any(new[k] != base[k] for k in ("genre", "age", "timbre", "ton", "debit", "description")):
            new["source"] = "modifiée par toi"
        self.proj["cards"][name] = new
        save_project(self.proj)
        return self._state()

    def propose(self):
        """Repropose toutes les voix non verrouillées (avec l'IA locale si elle est installée)."""
        if not self.game:
            return None
        try:
            ask = localai.chat if ai_ready() else None
            self.proj["cards"] = fiches.propose(self.game["chars"], self.proj.get("context", ""), self.proj["cards"], ask)
            save_project(self.proj)
            st = self._state()
            st["message"] = "Voix proposées par l'IA locale." if ask else \
                "Voix proposées sans IA (installe l'IA de TradUp pour des propositions selon le caractère de chacun)."
            return st
        except Exception as e:
            return {"error": friendly_error(e)}

    def ask(self, text, selected=None):
        """Barre « Demande à l'IA » : « une voix de vieux marin bourru pour Bram »."""
        if not self.game:
            return {"reply": "Ouvre d'abord un jeu : je pourrai ensuite régler la voix de ses personnages."}
        if not str(text or "").strip():
            return {"reply": "Écris ce que tu veux, par exemple : « une voix de vieux marin bourru pour Bram »."}
        if not ai_ready():
            return {"reply": "L'IA locale n'est pas installée sur ce PC (c'est la même que TradUp : installe-la depuis "
                             "TradUp, « IA intégrée »). En attendant, règle la voix à la main dans la fiche du personnage."}
        try:
            content = localai.chat(fiches.ASK_SYSTEM, fiches.ask_request(text, self.game["chars"], self.proj["cards"],
                                                                         self.proj.get("context", "")), temperature=0.5)
            name, self.proj["cards"], reply = fiches.apply_answer(content, self.game["chars"], self.proj["cards"], selected)
            save_project(self.proj)
            st = self._state()
            st["reply"], st["changed"] = reply, name
            return st
        except Exception as e:
            return {"reply": friendly_error(e)}

    def lines_of(self, name, limit=40):
        if not self.game:
            return []
        return [ln["text"] for ln in self.game["lines"] if ln["name"] == name][:limit]

    def quit(self):
        threading.Thread(target=lambda: (time.sleep(0.2), os._exit(0)), daemon=True).start()


def autotest():
    """Vérifie le parcours sans fenêtre, sur le jeu de démonstration (projet temporaire)."""
    import tempfile
    global projects_dir
    tmp = tempfile.mkdtemp()
    projects_dir = lambda: tmp  # noqa: E731
    api = Api()
    st = api.open_demo()
    assert "error" not in st, st
    names = [c["name"] for c in st["chars"]]
    assert "Elda" in names and "Narrateur" in names, names
    st = api.save_card("Elda", {"genre": "femme", "age": "âgé", "ton": "douce, mystérieuse", "verrouille": True})
    assert st["cards"]["Elda"]["source"] == "modifiée par toi" and st["cards"]["Elda"]["verrouille"]
    st = api.propose()
    assert st["cards"]["Elda"]["ton"] == "douce, mystérieuse"  # verrouillée : gardée
    assert api.open_demo()["cards"]["Elda"]["age"] == "âgé"  # projet relu depuis le disque
    print(f"autotest OK : {st['lines']} répliques, personnages : {', '.join(names)}")


def main():
    import webview
    from webview.dom import DOMEventHandler
    api = Api()
    with open(os.path.join(HERE, "static", "index.html"), encoding="utf-8") as f:
        html = f.read()
    win = webview.create_window("TradVoice", html=html, js_api=api, width=1280, height=820, min_size=(900, 600))
    api._win = win

    def bind_drop():
        win.dom.document.events.dragover += DOMEventHandler(lambda e: None, True, True)
        win.dom.document.events.drop += DOMEventHandler(api.on_drop, True, True)

    win.events.loaded += bind_drop
    webview.start()


if __name__ == "__main__":
    autotest() if "--autotest" in sys.argv else main()
