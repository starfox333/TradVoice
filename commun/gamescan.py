"""Retrouver un jeu (raccourci, dossier, Steam) et chercher où sont ses textes."""
import os, re, json, struct, subprocess, time

TEXT_EXT = {".json", ".csv", ".tsv", ".po", ".xliff", ".xlf", ".txt", ".xml", ".yaml", ".yml",
            ".ini", ".lang", ".loc", ".strings", ".srt", ".properties"}
SKIP_DIRS = {"monobleedingedge", "_commonredist", "redist", "directx", "vcredist", "__pycache__",
             "d3d12", "binaries", "crashreportclient", "plugins", "managed", "il2cpp_data", "easyanticheat",
             "battleye", "steamworks shared", ".git", "mono"}  # mono : moteur .NET des vieux jeux Unity
LOC_HINT = re.compile(r"(locali[sz]|language|lang|i18n|l10n|translat|text|string|dialog|english|\ben\b|_en\b)", re.I)
WORD = re.compile(r"[A-Za-z][a-z']+")
COMMON = set("the you and to of is a i it in for this that my your me we be are was not have with on what do can just so but all at if no yes get go don't i'm it's you're".split())
TECH = re.compile(r"UnityEngine|System\.|Assembly-CSharp|Version=|PublicKeyToken|null|::|=>|\(\)|\w+_\w+_\w+|https?://")
LANG_OTHER = re.compile(r"(^|[\\/_\-. ])(french|fran[cç]ais|german|deutsch|spanish|espa[nñ]ol|russian|chinese|japanese|korean|filipino|croatian|polish|portuguese|brazilian|italian|turkish|ukrainian|czech|dutch|swedish|hungarian|thai|vietnamese|arabic|fr|de|es|ru|zh|ja|ko|pt|it|pl|tr|uk|cs|nl|sv|hu|th|vi|ar|zh[-_]\w+|pt[-_]br|es[-_]\w+)([\\/_\-. ]|$)", re.I)
LANG_EN = re.compile(r"(^|[\\/_\-. ])(english|en|en[-_]us|en[-_]gb|default|base)([\\/_\-. ]|$)", re.I)
LANG_FR = re.compile(r"(^|[\\/_\-. ])(french|fran[cç]ais|fr|fr[-_]fr|fr[-_]ca)([\\/_\-. ]|$)", re.I)
# Fichiers de texte qui ne sont pas des textes du jeu (licences, listes techniques, guides…)
NOT_GAME_TEXT = re.compile(r"link\.xml$|manifest_|[\\/]legal[\\/]|licen[sc]e|eula|privacy|terms.?of.?service|third.?party|"
                           r"troubleshoot|readme|lisez.?moi|changelog|steam_appid|credits?\.txt$|"
                           r"output_log|player(-prev)?\.log|browscap\.ini$|[\\/]mono[\\/]|"
                           r"(^|[\\/])(log|traceback|errors|lint)\.txt$", re.I)  # journaux (Unity, Ren'Py…)
BACKUP = re.compile(r"\.(original\w*|bak|backup|orig)$|_sauvegarde|backup", re.I)


def is_sentence(s):
    """Vraie phrase en anglais (et pas un nom technique)."""
    if TECH.search(s):
        return False
    words = [w.lower() for w in WORD.findall(s)]
    return len(words) >= 2 and (any(w in COMMON for w in words) or len(words) >= 4 and s.strip()[-1:] in ".!?")


# ------------------------------------------------------------------ Steam
def steam_libraries():
    libs = []
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
            steam = winreg.QueryValueEx(k, "SteamPath")[0]
        libs.append(os.path.normpath(steam))
        vdf = os.path.join(steam, "steamapps", "libraryfolders.vdf")
        if os.path.exists(vdf):
            for m in re.finditer(r'"path"\s+"([^"]+)"', open(vdf, encoding="utf-8", errors="ignore").read()):
                libs.append(os.path.normpath(m.group(1).replace("\\\\", "\\")))
    except Exception:
        pass
    out = []
    for l in libs:
        if l.lower() not in [o.lower() for o in out] and os.path.isdir(os.path.join(l, "steamapps")):
            out.append(l)
    return out


def _acf(path):
    txt = open(path, encoding="utf-8", errors="ignore").read()
    get = lambda k: (re.search(rf'"{k}"\s+"([^"]*)"', txt) or [None, ""])[1]
    return {"appid": get("appid"), "name": get("name"), "installdir": get("installdir")}


def steam_games():
    games = []
    for lib in steam_libraries():
        sa = os.path.join(lib, "steamapps")
        for f in os.listdir(sa):
            if f.startswith("appmanifest_") and f.endswith(".acf"):
                g = _acf(os.path.join(sa, f))
                d = os.path.join(sa, "common", g["installdir"])
                if g["installdir"] and os.path.isdir(d) and not re.search(r"redist|steamworks|steamvr|proton|runtime", g["name"], re.I):
                    games.append({"appid": g["appid"], "name": g["name"] or g["installdir"], "path": d})
    return sorted(games, key=lambda g: g["name"].lower())


_LANG_CACHE = {}
LANG_CACHE_FILE = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "TradUp", "steam_langues.json")
LANG_CACHE_DAYS = 7  # une fiche Steam change rarement ; on la relit au plus une fois par semaine
# Nom des langues sur la fiche Steam (demandée en français), pour chaque langue « Vers » de TradUp
STEAM_LANG_NAMES = {"fr": ("français", "french"), "en": ("anglais", "english"), "de": ("allemand", "german"),
                    "es": ("espagnol", "spanish"), "it": ("italien", "italian"), "pt": ("portugais", "portuguese"),
                    "nl": ("néerlandais", "dutch"), "pl": ("polonais", "polish"), "ru": ("russe", "russian"),
                    "uk": ("ukrainien", "ukrainian"), "ja": ("japonais", "japanese"), "ko": ("coréen", "korean"),
                    "zh": ("chinois simplifié", "simplified chinese")}


def _disk_cache():
    try:
        return json.load(open(LANG_CACHE_FILE, encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def steam_store(appid, fetch=True):
    """Fiche Steam publique d'un jeu : {"langs": langues officielles, "cats": numéros de ses catégories (Solo,
    Coopération en ligne, JcJ en ligne…), "genres": numéros de ses genres}. Seul le numéro du jeu est envoyé à Steam.
    Gardée une semaine sur ce PC. None si inconnue (pas d'Internet, fiche retirée…).
    fetch=False : seulement ce qui est déjà connu, sans aller sur Internet."""
    if not appid:
        return None
    appid = str(appid)
    if appid in _LANG_CACHE:
        return _LANG_CACHE[appid]
    disk = _disk_cache()
    hit = disk.get(appid)
    if hit and time.time() - hit.get("t", 0) < LANG_CACHE_DAYS * 86400 and ("cats" in hit or not fetch):
        if "cats" in hit:  # fiche complète (les anciennes n'avaient que les langues : relues au besoin)
            _LANG_CACHE[appid] = hit
        return hit
    if not fetch:
        return None
    import urllib.request, html
    url = f"https://store.steampowered.com/api/appdetails?appids={int(appid)}&l=french&filters=basic,categories,genres"
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.loads(r.read()).get(appid, {}).get("data") or {}
        raw = data.get("supported_languages", "")
        txt = re.sub(r"<[^>]+>", "", html.unescape(raw.split("<br>")[0]))
        info = {"t": time.time(), "langs": [l.strip(" *") for l in txt.split(",") if l.strip(" *")] or None,
                "cats": sorted({int(c["id"]) for c in data.get("categories", []) if str(c.get("id", "")).isdigit()}),
                "genres": sorted({str(g["id"]) for g in data.get("genres", []) if g.get("id") is not None})}
    except Exception:
        return None  # pas d'Internet : on réessaiera plus tard (rien de gardé)
    _LANG_CACHE[appid] = info
    try:
        disk[appid] = info
        os.makedirs(os.path.dirname(LANG_CACHE_FILE), exist_ok=True)
        json.dump(disk, open(LANG_CACHE_FILE, "w", encoding="utf-8"), ensure_ascii=False)
    except OSError:
        pass
    return info


def steam_languages(appid, fetch=True):
    """Langues officielles d'un jeu d'après sa fiche Steam (voir steam_store). None si inconnu."""
    info = steam_store(appid, fetch)
    return info.get("langs") if info else None


# ------------------------------------------------------------------ jeux en ligne (1.16)
# Modifier un jeu en ligne peut faire bannir le compte du joueur et va contre les règles de ces jeux. D'après la fiche
# Steam (numéros de catégories, les mêmes dans toutes les langues) : MMO, ou JcJ en ligne sans mode solo → refusé ;
# jeu solo avec un JcJ en ligne en option, coopération ou multijoueur en ligne → avertissement (traduire, mais jouer
# en solo). Hors Steam : anti-triche → refusé ; bibliothèques
# réseau connues dans les fichiers → avertissement.
CAT_SOLO, CAT_MULTI, CAT_MMO, CAT_ONLINE_PVP, CAT_ONLINE_COOP = 2, 1, 20, 36, 38
CAT_LOCAL = {24, 37, 39, 47, 48}  # écran partagé, LAN : du multijoueur qui n'est pas en ligne
GENRE_MMO = "29"
ONLINE_LIBS = [("Photon", re.compile(r"^photon\w*\.dll$", re.I)), ("Mirror", re.compile(r"^mirror(\.\w+)?\.dll$", re.I)),
               ("Fish-Net", re.compile(r"^fishnet\w*\.dll$", re.I)),
               ("Netcode for GameObjects", re.compile(r"^unity\.netcode\.\w+\.dll$", re.I)),
               ("Epic Online Services", re.compile(r"^eossdk-win\d+-shipping\.dll$", re.I))]
_ONLINE_CACHE = {}


def _appid_of(root):
    """Numéro Steam du jeu rangé dans ce dossier (bibliothèques Steam, ou steam_appid.txt), sinon None."""
    norm = os.path.normcase(os.path.abspath(root)).rstrip("\\/")
    try:
        for gm in steam_games():
            p = os.path.normcase(os.path.abspath(gm["path"])).rstrip("\\/")
            if norm == p or norm.startswith(p + os.sep):
                return gm["appid"]
    except Exception:
        pass
    for d in (root, os.path.dirname(root)):
        try:
            txt = open(os.path.join(d, "steam_appid.txt"), encoding="utf-8", errors="ignore").read().strip()
            if txt.isdigit():
                return txt
        except OSError:
            continue
    return None


def online_from_steam(info):
    """Niveau d'après une fiche Steam : ("refuse" | "warn" | None, raison)."""
    if not info or "cats" not in info:
        return None, ""
    cats, genres = set(info.get("cats") or []), set(info.get("genres") or [])
    if CAT_MMO in cats or GENRE_MMO in genres:
        return "refuse", "d'après sa fiche Steam, c'est un jeu massivement multijoueur en ligne"
    if CAT_ONLINE_PVP in cats and CAT_SOLO not in cats:
        return "refuse", "d'après sa fiche Steam, on y affronte d'autres joueurs en ligne (JcJ en ligne)"
    if CAT_ONLINE_PVP in cats:  # jeu solo avec des combats en ligne en option (ex. Monster Hunter Stories)
        return "warn", "d'après sa fiche Steam, il a des combats en ligne contre d'autres joueurs, en option"
    if CAT_ONLINE_COOP in cats:
        return "warn", "d'après sa fiche Steam, il a un mode coopération en ligne"
    if CAT_MULTI in cats and CAT_SOLO not in cats and not (cats & CAT_LOCAL):
        return "warn", "d'après sa fiche Steam, c'est un jeu multijoueur"
    return None, ""


def online(root, appid=None, fetch=True):
    """Le jeu est-il en ligne ? {"level": "refuse" | "warn" | None, "why": raison en français}. Gardé pendant la
    séance (appelé avant chaque « Appliquer au jeu »)."""
    if not root or not os.path.isdir(root):
        return {"level": None, "why": ""}
    key = os.path.normcase(os.path.abspath(root))
    if key in _ONLINE_CACHE:
        return _ONLINE_CACHE[key]
    res = {"level": None, "why": ""}
    ac = anticheat(root)
    if ac:
        res = {"level": "refuse", "why": f"il est protégé par un anti-triche ({ac})"}
    else:
        level, why = online_from_steam(steam_store(appid or _appid_of(root), fetch))
        if level:
            res = {"level": level, "why": why}
        else:
            base = root.rstrip("\\/").count(os.sep)
            for dp, dns, fns in os.walk(root):
                if dp.count(os.sep) - base >= 4:
                    dns[:] = []
                hit = next((name for f in fns for name, rx in ONLINE_LIBS if rx.match(f)), None)
                if hit:
                    res = {"level": "warn", "why": f"il contient une partie en ligne ({hit})"}
                    break
    if res["level"] or fetch:  # sans Internet, on ne garde pas un « rien trouvé » (on réessaiera)
        _ONLINE_CACHE[key] = res
    return res


ONLINE_REFUSED = ("Ce jeu se joue en ligne contre d'autres joueurs : {why}. Modifier ses fichiers peut faire bannir "
                  "ton compte et va contre les règles du jeu, alors TradUp ne le traduit pas.")
ONLINE_WARNING = ("Ce jeu a une partie en ligne : {why}. Avec la traduction, joue seulement en solo ; pour jouer en "
                  "ligne, remets d'abord l'original (« Remettre l'original »), sinon tu risques des problèmes avec les "
                  "autres joueurs ou un bannissement.")


def has_language(langs, tgt):
    """Le jeu est-il officiellement dans la langue tgt (code TradUp : fr, de…) ? None si on ne sait pas."""
    if langs is None:
        return None
    names = STEAM_LANG_NAMES.get(tgt, (tgt,))
    return any(l.lower().startswith(names) for l in langs)


def has_french(langs):
    return has_language(langs, "fr")


def steam_game_path(appid):
    for g in steam_games():
        if g["appid"] == str(appid):
            return g["path"], g["name"]
    return None, None


# ------------------------------------------------------------------ raccourcis
def _lnk_target(path):
    """(cible, arguments) d'un raccourci Windows. Le chemin passe par une variable d'environnement et la réponse en
    UTF-8 : en argument, PowerShell coupait le chemin aux espaces et perdait les accents (« andré » → « andr »)."""
    ps = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
          "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:TRADUP_LNK);"
          "Write-Output $s.TargetPath; Write-Output $s.Arguments")
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], capture_output=True, text=True,
                       encoding="utf-8", errors="ignore", env={**os.environ, "TRADUP_LNK": os.path.abspath(path)},
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    lines = (r.stdout or "").splitlines() + ["", ""]
    return lines[0].strip(), lines[1].strip()


def resolve(path):
    """Renvoie {"path": dossier du jeu, "name": nom} à partir d'un raccourci, d'un .exe ou d'un dossier."""
    path = os.path.normpath(path)
    low = path.lower()
    appid = None
    if os.path.isdir(path):
        for gm in steam_games():  # dossier d'un jeu Steam : on récupère son vrai nom et son numéro
            if os.path.normcase(gm["path"]) == os.path.normcase(path):
                return {"path": path, "name": gm["name"], "appid": gm["appid"]}
        return {"path": path, "name": os.path.basename(path)}
    if low.endswith(".url"):
        m = re.search(r"steam://rungameid/(\d+)", open(path, encoding="utf-8", errors="ignore").read())
        if m:
            appid = m.group(1)
    elif low.endswith(".lnk"):
        target, args = _lnk_target(path)
        m = re.search(r"steam://rungameid/(\d+)", target + " " + args) or re.search(r"-applaunch\s+(\d+)", args)
        if m:
            appid = m.group(1)
        elif target and os.path.exists(target):
            return resolve(target)
    elif low.endswith(".exe"):
        d = os.path.dirname(path)
        # remonte jusqu'au dossier du jeu dans steamapps\common si besoin
        parts = d.split(os.sep)
        for i, p in enumerate(parts):
            if p.lower() == "common" and i > 0 and parts[i - 1].lower() == "steamapps" and i + 1 < len(parts):
                d = os.sep.join(parts[:i + 2])
                break
        return resolve(d) if os.path.isdir(d) else {"path": d, "name": os.path.basename(d)}
    if appid:
        p, name = steam_game_path(appid)
        if p:
            return {"path": p, "name": name, "appid": appid}
        raise ValueError(f"Jeu Steam n°{appid} introuvable dans tes bibliothèques (est-il installé ?).")
    raise ValueError("Je ne reconnais pas ce fichier : dépose un raccourci de jeu, le .exe du jeu ou son dossier.")


NOT_GAME_EXE = re.compile(r"crash|unins|setup|install|redist|vc_?redist|dxsetup|ffmpeg|ffprobe|unitycrashhandler|"
                          r"\.console\.|easyanticheat|battleye|ue4prereq|uploader|reporter|cefprocess|helper", re.I)


def main_exe(root):
    """Programme principal d'un jeu : le plus gros .exe du dossier (hors installateurs, rapports de plantage…)."""
    if not root or not os.path.isdir(root):
        return None
    found = []
    for dp, dns, fns in os.walk(root):
        depth = os.path.relpath(dp, root).count(os.sep) + (0 if dp == root else 1)
        if depth > 4:
            dns[:] = []
            continue
        dns[:] = [d for d in dns if d.lower() not in SKIP_DIRS - {"binaries"} and not BACKUP.search(d)]
        for f in fns:
            if f.lower().endswith(".exe") and not NOT_GAME_EXE.search(f):
                p = os.path.join(dp, f)
                found.append((depth, -os.path.getsize(p), p))
    if not found:
        return None
    found.sort()
    top = [x for x in found if x[0] == found[0][0]]  # le plus près de la racine, puis le plus gros
    return min(top, key=lambda x: x[1])[2]


# ------------------------------------------------------------------ anti-triche
ANTICHEAT = [("EasyAntiCheat", re.compile(r"easyanticheat|eac_launcher|start_protected_game", re.I)),
             ("BattlEye", re.compile(r"battleye|beservice", re.I)),
             ("Vanguard", re.compile(r"vanguard|vgc\.exe", re.I)),
             ("nProtect GameGuard", re.compile(r"gameguard", re.I)),
             ("XIGNCODE", re.compile(r"xigncode", re.I)),
             ("Denuvo Anti-Cheat", re.compile(r"denuvo.?anti.?cheat", re.I))]


def anticheat(root, max_depth=3):
    """Nom de l'anti-triche qui protège le jeu (jeux en ligne), sinon None. Modifier leurs fichiers peut faire bannir."""
    if not root or not os.path.isdir(root):
        return None
    base = root.rstrip("\\/").count(os.sep)
    for dp, dns, fns in os.walk(root):
        if dp.count(os.sep) - base >= max_depth:
            dns[:] = []
        for n in dns + fns:
            for name, rx in ANTICHEAT:
                if rx.search(n):
                    return name
    return None


# ------------------------------------------------------------------ moteur du jeu
def detect_engine(root, _depth=0):
    """Moteur du jeu. Si le jeu est rangé un dossier plus bas (ex. « MGI Prologue/MGI Prologue/MGI.exe »),
    on le cherche dans les sous-dossiers ; le résultat indique alors ce dossier dans « root »."""
    eng = _detect_engine_here(root)
    if eng["engine"] in ("Inconnu", "Non installé") and _depth < 2:
        for d in sorted(os.listdir(root)):
            sub = os.path.join(root, d)
            if os.path.isdir(sub) and d.lower() not in SKIP_DIRS and not BACKUP.search(d):
                inner = detect_engine(sub, _depth + 1)
                if inner["engine"] not in ("Inconnu", "Non installé"):
                    inner.setdefault("root", sub)
                    return inner
    return eng


def _detect_engine_here(root):
    names = {n.lower() for n in os.listdir(root)}
    has_exe = any(n.endswith(".exe") for n in names) or any(
        f.lower().endswith(".exe") for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))
        for f in os.listdir(os.path.join(root, d))[:200])
    if not has_exe:
        return {"engine": "Non installé"}
    data_dirs = [n for n in os.listdir(root) if n.lower().endswith("_data") and os.path.isdir(os.path.join(root, n))]
    if data_dirs and any(os.path.exists(os.path.join(root, d, f)) for d in data_dirs for f in ("globalgamemanagers", "data.unity3d", "mainData")):
        il2cpp = "gameassembly.dll" in names
        return {"engine": "Unity", "detail": "IL2CPP" if il2cpp else "Mono", "data": os.path.join(root, data_dirs[0])}
    if "renpy" in names or os.path.isdir(os.path.join(root, "game")) and any(f.endswith((".rpy", ".rpyc", ".rpa")) for f in os.listdir(os.path.join(root, "game"))):
        return {"engine": "Ren'Py"}
    for base in (root, os.path.join(root, "www")):
        if os.path.exists(os.path.join(base, "data", "System.json")):
            return {"engine": "RPG Maker MV/MZ", "data": os.path.join(base, "data")}
    if "engine" in names and any(os.path.isdir(os.path.join(root, n, "Content", "Paks")) for n in os.listdir(root) if os.path.isdir(os.path.join(root, n))):
        return {"engine": "Unreal Engine"}
    if "data.win" in names:
        return {"engine": "GameMaker"}
    if any(n.endswith(".pck") or "godot" in n for n in names):
        return {"engine": "Godot"}
    return {"engine": "Inconnu"}


# ------------------------------------------------------------------ fichiers de texte
CODE_LINE = re.compile(r"^\s*(--|//|#|local\s|function\b|end\b|return\b|if\b.*\bthen\b|for\b.*\bdo\b|[{}\[\]();,]+\s*$)|"
                       r"\brequire\s*\(|[;{]\s*$|^\s*\w+(\.\w+)*\s*=\s*\S")


def looks_like_code(txt):
    """Script (Lua, C#, JSON technique…) plutôt que texte à lire : plus d'un tiers des lignes ressemblent à du code."""
    lines = [l for l in txt[:100_000].splitlines() if l.strip()]
    return len(lines) >= 5 and sum(1 for l in lines if CODE_LINE.search(l)) > len(lines) / 3


# Noms internes du jeu rangés à côté des textes (ex. « met Ara 0 », « MetGirls(0) ») : à ne pas traduire
INTERNAL_NAME = re.compile(r"^[^.!?…]{1,40}(\(\d+\)|\s\d+)$")


def english_score(sample):
    lines = [l for l in sample.splitlines() if l.strip()]
    return sum(1 for l in lines if is_sentence(l))


WORDLIST_NAME = re.compile(r"(sensitive|bad[_ -]?words?|banned|forbidden|profan|black[_ -]?list|block[_ -]?list|censor|"
                           r"swear|curse|dirty[_ -]?words?|word[_ -]?filter|chat[_ -]?filter|敏感|屏蔽|违禁|过滤|脏话)", re.I)


def is_word_list(rel, txt):
    """Liste de mots interdits du jeu (filtre du tchat) : jamais affichée, et l'IA refuse ses mots grossiers.
    Reconnue à son nom, ou à son contenu : des milliers de lignes d'un seul mot, sans phrase (une liste d'objets
    ou de noms, elle, dépasse rarement quelques centaines de lignes)."""
    if WORDLIST_NAME.search(os.path.basename(rel)):
        return True
    lines = [l.strip() for l in txt.splitlines() if l.strip()]
    if len(lines) < 2000:
        return False
    single = sum(1 for l in lines if len(l) <= 16 and not re.search(r"[\s.!?。！？,，:：=\"'{}<>]", l))
    return single / len(lines) > 0.9


def find_text_files(root, limit_s=40):
    t0 = time.time()
    found = []
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d.lower() not in SKIP_DIRS and not BACKUP.search(d)]
        if time.time() - t0 > limit_s:
            break
        for f in fns:
            ext = os.path.splitext(f)[1].lower()
            if ext not in TEXT_EXT or BACKUP.search(f) or NOT_GAME_TEXT.search(os.path.join(dp, f)):
                continue
            p = os.path.join(dp, f)
            try:
                size = os.path.getsize(p)
                if size < 200 or size > 60_000_000:
                    continue
                with open(p, "rb") as fh:
                    raw = fh.read(300_000)
                if b"\x00" in raw[:2000] and not raw.startswith((b"\xff\xfe", b"\xfe\xff")):
                    continue
                txt = raw.decode("utf-8", "ignore") if not raw.startswith((b"\xff\xfe", b"\xfe\xff")) else raw.decode("utf-16", "ignore")
            except OSError:
                continue
            score = english_score(txt)
            if score < 5:
                continue
            rel = os.path.relpath(p, root)
            bonus = 3 if LOC_HINT.search(rel) else 1
            if LANG_EN.search(rel):
                bonus *= 3
            elif LANG_OTHER.search(rel):
                bonus *= 0.2
            sample = next((l.strip() for l in txt.splitlines() if is_sentence(l)), "")[:160]
            words = len(WORD.findall(txt)) * max(1, size // max(1, len(raw)))
            wl = is_word_list(rel, txt)
            found.append({"kind": "file", "path": p, "label": rel, "lines": score, "words": 0 if wl else words,
                          "rank": score * bonus * (0.001 if wl else 1), "sample": sample,
                          "french": bool(LANG_FR.search(rel)), "wordlist": wl})
    found.sort(key=lambda x: -x["rank"])
    return found[:40]


# ------------------------------------------------------------------ textes cachés dans Unity
def _prefixed_strings(raw, strict=True):
    """Chaînes Unity (longueur + texte UTF-8). strict=True : seulement de vraies phrases (pour la détection) ;
    strict=False : tout texte lisible (pour l'extraction d'un bloc déjà choisi)."""
    from formats import looks_like_id
    out, i, n = [], 0, len(raw)
    while i + 4 <= n:
        L = struct.unpack_from("<i", raw, i)[0]
        if 2 <= L <= 6000 and i + 4 + L <= n:
            b = raw[i + 4:i + 4 + L]
            try:
                s = b.decode("utf-8")
            except UnicodeDecodeError:
                s = None
            if s is not None and s.isprintable() or (s and all(c.isprintable() or c in "\n\r\t" for c in s)):
                ok = (" " in s and is_sentence(s)) if strict else (not looks_like_id(s) and not TECH.search(s) and not re.match(r"^(line|title|node):", s))
                if ok and not re.search(r"[\\/]\w+\.\w{2,4}\b|^\w+\.\w+\.\w+", s):
                    out.append((i, s))
                i += 4 + L + ((-L) % 4)
                continue
        i += 4
    return out


KNOWN_SCRIPTS = {"Say": "Dialogues", "Menu": "Choix de réponses", "Text": "Textes à l'écran",
                 "TextMeshProUGUI": "Textes à l'écran", "TextMeshPro": "Textes à l'écran", "Block": "Noms de scènes",
                 "Flowchart": "Scénario", "LocalizedString": "Textes traduits", "DialogueDatabase": "Dialogues"}


def scan_unity(data_dir, limit_s=150, progress=None):
    """Cherche les objets Unity qui contiennent des phrases (dialogues, menus, tables de langue)."""
    import UnityPy, bundle
    t0 = time.time()
    results = []
    files = []
    game_dir = os.path.dirname(os.path.abspath(data_dir))
    man = bundle._manifest(game_dir)
    for dp, dns, fns in os.walk(data_dir):
        dns[:] = [d for d in dns if not BACKUP.search(d)]
        for f in fns:
            low = f.lower()
            if BACKUP.search(f):
                continue
            if low.endswith((".ress", ".resource", ".dll", ".json", ".config", ".bytes", ".info", ".txt", ".xml", ".tmp_trad")):
                continue
            p = os.path.join(dp, f)
            if os.path.getsize(p) > 2_000_000_000:
                continue
            files.append(p)
    files.sort(key=os.path.getsize)
    for k, p in enumerate(files):
        if time.time() - t0 > limit_s:
            results.append({"kind": "note", "label": "Analyse arrêtée au bout de %d s (jeu très gros)" % limit_s})
            break
        if progress:
            progress(f"Analyse Unity : {os.path.basename(p)} ({k + 1}/{len(files)})")
        try:
            # si une traduction est déjà appliquée, on analyse l'original anglais gardé dans la sauvegarde
            env = UnityPy.load(bundle.original_path(game_dir, os.path.relpath(p, game_dir), man))
        except Exception:
            continue
        for obj in env.objects:
            tname = obj.type.name
            if tname not in ("MonoBehaviour", "TextAsset"):
                continue
            try:
                if tname == "TextAsset":
                    d = obj.read()
                    content = d.m_Script
                    txt = content if isinstance(content, str) else bytes(content).decode("utf-8", "ignore")
                    if NOT_GAME_TEXT.search(d.m_Name) or re.match(r"copying$", d.m_Name, re.I) or looks_like_code(txt):
                        continue  # licences et scripts (Lua…) livrés avec le jeu : pas des textes à traduire
                    sc = english_score(txt[:300_000])
                    if sc >= 5:
                        results.append({"kind": "unity_textasset", "file": p, "path_id": obj.path_id,
                                        "label": f"Texte « {d.m_Name} » ({os.path.basename(p)})",
                                        "lines": sc, "words": len(WORD.findall(txt)), "rank": sc * 2,
                                        "sample": txt.strip()[:160]})
                    continue
                raw = obj.get_raw_data()
                if len(raw) < 40 or len(raw) > 30_000_000:
                    continue
                strs = _prefixed_strings(raw)
                if not strs:
                    continue
                try:
                    script = obj.read(check_read=False).m_Script.read().m_Name
                except Exception:
                    script = "?"
                results.append({"kind": "unity_object", "file": p, "path_id": obj.path_id, "script": script,
                                "lines": len(strs), "words": sum(len(WORD.findall(s)) for _, s in strs),
                                "rank": len(strs), "sample": strs[0][1][:160]})
            except Exception:
                continue
    # regroupe les petits objets d'un même type (ex. 300 textes de menu TextMeshPro)
    grouped, small = [], {}
    for r in results:
        if r["kind"] == "unity_object" and r["lines"] < 20:
            key = (r["script"],)
            g = small.setdefault(key, {"kind": "unity_group", "script": r["script"], "items": [], "lines": 0, "words": 0, "sample": r["sample"]})
            g["items"].append([r["file"], r["path_id"]]); g["lines"] += r["lines"]; g["words"] += r["words"]
        else:
            grouped.append(r)
    for g in small.values():
        g["rank"] = g["lines"]
        nice = KNOWN_SCRIPTS.get(g["script"], "Textes")
        g["label"] = f"{nice} « {g['script']} » ({len(g['items'])} objets)"
        grouped.append(g)
    for r in grouped:
        if r["kind"] == "unity_object":
            r["label"] = f"Bloc de texte « {r['script']} » ({os.path.basename(r['file'])})"
    grouped.sort(key=lambda x: -x.get("rank", 0))
    return grouped[:40]


# ------------------------------------------------------------------ Unreal Engine
def scan_unreal(root, progress=None):
    """Fichiers de langue (.locres) d'un jeu Unreal : en clair dans le dossier ou dans les archives .pak."""
    import unrealpak, locres
    sources, notes = [], []
    # 1) .locres posés en clair dans le dossier du jeu
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if not BACKUP.search(d)]
        for f in fns:
            if f.lower().endswith(".locres"):
                p = os.path.join(dp, f)
                try:
                    ents = locres.read_entries(open(p, "rb").read())
                except Exception:
                    continue
                rel = os.path.relpath(p, root)
                en = bool(LANG_EN.search(rel))
                sources.append({"kind": "file", "path": p, "label": rel, "lines": len(ents),
                                "words": sum(len(WORD.findall(e["source"])) for e in ents), "rank": len(ents) * (3 if en else 1),
                                "sample": next((e["source"] for e in ents if " " in e["source"]), "")[:160],
                                "french": bool(LANG_FR.search(rel))})
    # 2) .locres rangés dans les archives .pak
    counts = {"chiffrée": 0, "oodle": 0}
    for dp, dns, fns in os.walk(root):
        for f in fns:
            if not f.lower().endswith(".pak"):
                continue
            p = os.path.join(dp, f)
            if progress:
                progress(f"Analyse Unreal : {f}")
            try:
                ft, files = unrealpak.list_files(p)
            except unrealpak.PakError as e:
                if "chiffr" in str(e):
                    counts["chiffrée"] += 1
                continue
            except Exception:
                continue  # archive d'un autre type (ex. navigateur intégré) ou variante non reconnue
            for k, e in files.items():
                low = k.lower()
                if not low.endswith(".locres") or low.startswith("engine/"):
                    continue  # on ne garde que les textes du jeu, pas ceux du moteur
                method = ft["methods"][e["method"] - 1] if e["method"] else "aucune"
                readable = not e["encrypted"] and unrealpak.readable_method(method)
                if not readable:
                    counts["oodle" if method.lower() == "oodle" else "chiffrée"] += 1
                    continue
                try:
                    ents = locres.read_entries(unrealpak.read_file(p, e, ft["methods"]))
                except Exception:
                    continue
                en = bool(LANG_EN.search(k))
                sources.append({"kind": "unreal_locres", "pak": p, "path": k, "label": f"{k} (dans {f})",
                                "lines": len(ents), "words": sum(len(WORD.findall(x["source"])) for x in ents),
                                "rank": len(ents) * (3 if en else 1), "french": bool(LANG_FR.search(k)),
                                "sample": next((x["source"] for x in ents if " " in x["source"]), "")[:160]})
    if counts["chiffrée"]:
        notes.append("Archives chiffrées : sans la clé du studio, leurs textes sont illisibles. Le plus simple est de demander "
                     "les textes aux développeurs (export .po depuis l'outil de traduction d'Unreal, que ce logiciel sait traduire).")
    if counts["oodle"]:
        notes.append(f"{counts['oodle']} fichier(s) de langue compressé(s) en Oodle : leur lecture n'est pas encore prise en charge.")
    if not sources and not counts["chiffrée"] and not counts["oodle"]:
        notes.append("Unreal Engine : aucun fichier de langue du jeu trouvé (.locres).")
    sources.sort(key=lambda s: -s["rank"])
    return sources[:30], notes


# ------------------------------------------------------------------ analyse complète
def _gamemaker_source(root, sources, notes):
    """Jeu GameMaker (data.win) : ajoute « Tous les textes du jeu ». Renvoie False si ses textes sont illisibles."""
    import bundle, gamemaker
    try:
        ents = gamemaker.extract(root)
        accents = gamemaker.info(root)["accents"]
    except Exception as e:
        notes.append(f"GameMaker : {e}")
        return True
    if not ents:
        return False
    sources.insert(0, {"kind": "gamemaker", "root": root, "script": "*", "rank": 10**6,
                       "label": "Tous les textes du jeu (GameMaker)", "lines": len(ents),
                       "words": sum(len(e["source"].split()) for e in ents),
                       "sample": next((e["source"] for e in ents if len(e["source"]) > 25), ents[0]["source"])[:160]})
    notes.append("GameMaker : le logiciel remet la traduction dans le fichier data.win du jeu (original sauvegardé, "
                 "« Remettre l'original » le remet). Les lignes trop longues sont recoupées à la largeur des bulles du jeu.")
    if not accents:
        notes.append("Les polices de ce jeu n'ont pas d'accents : ils seront remplacés par des lettres simples (é → e) "
                     "pour rester lisibles.")
    if bundle.is_applied(root):
        notes.insert(0, "Une traduction faite avec ce logiciel est déjà appliquée à ce jeu (sauvegarde présente).")
    return True


def _godot_pck_source(root, sources, notes):
    """Jeu Godot (3 ou 4) dont les fichiers sont dans une archive .pck : ajoute « Tous les textes du jeu »."""
    import bundle, godotpck
    if not godotpck.pck_file(root):
        return False
    major = godotpck.godot_major(root)
    try:
        ents = godotpck.extract(root)
    except Exception as e:
        notes.append(f"Godot : {e}")
        return False
    if not ents:
        return False
    sources.insert(0, {"kind": "godotpck", "root": root, "script": "*", "rank": 10**6, "godot4": major >= 4,
                       "label": "Tous les textes du jeu (Godot)", "lines": len(ents),
                       "words": sum(len(e["source"].split()) for e in ents),
                       "sample": next((e["source"] for e in ents if len(e["source"]) > 25), ents[0]["source"])[:160]})
    if major >= 4:
        notes.append("Godot 4 (nouveau, en test sur la version perso) : les textes du jeu sont lus et tu peux les traduire. "
                     "La remise automatique dans le jeu arrive à la prochaine mise à jour — pour l'instant, Godot 4 ne se "
                     "réécrit pas encore dans le jeu.")
    else:
        notes.append("Godot : le logiciel remet la traduction dans l'archive .pck du jeu (original sauvegardé, « Remettre "
                     "l'original » le remet). Les menus, boutons et textes des scripts sont traduits ; les noms internes ne "
                     "bougent pas.")
    if bundle.is_applied(root):
        notes.insert(0, "Une traduction faite avec ce logiciel est déjà appliquée à ce jeu (sauvegarde présente).")
    return True


def _personal_roots():
    """Dossiers personnels qu'on ne doit jamais analyser en entier (sinon TradUp lit tout ce qui traîne autour du jeu)."""
    home = os.path.expanduser("~")
    noms = ("", "Desktop", "Bureau", "Downloads", "Téléchargements", "Documents", "Pictures", "Images",
            "Music", "Musique", "Videos", "Vidéos", "OneDrive", r"OneDrive\Desktop", r"OneDrive\Bureau",
            r"OneDrive\Documents", r"OneDrive\Downloads", r"OneDrive\Téléchargements")
    return {os.path.normcase(os.path.abspath(os.path.join(home, n))) for n in noms}


def _is_personal_root(p):
    try:
        return os.path.normcase(os.path.abspath(p)) in _personal_roots()
    except Exception:
        return False


def analyse(path, progress=None, mode="jeu"):
    """mode « logiciel » (TradUp perso/pro, 18/11) : mêmes moteurs que pour un jeu, plus les textes écrits dans le code
    des programmes Unity IL2CPP (il2cppmeta), où vit souvent toute l'interface d'un logiciel (ex. VRoid Studio)."""
    soft = mode == "logiciel"
    g = resolve(path)
    root = g["path"]
    eng = detect_engine(root)
    root = eng.get("root", root)  # jeu rangé dans un sous-dossier
    if _is_personal_root(root):  # garde-fou (24/11) : un .exe posé en vrac sur le Bureau résolvait vers tout le Bureau
        raise ValueError("Ce dossier est un de tes dossiers personnels (Bureau, Téléchargements, Documents…), pas un jeu. "
                         "Range le jeu dans son propre dossier, puis glisse ce dossier (ou le .exe du jeu) : sinon TradUp "
                         "lirait tous les fichiers qui traînent autour.")
    if root != g["path"] and not g.get("appid"):  # jeu trouvé dans un sous-dossier : afficher SON nom, pas celui du parent
        g["name"] = os.path.basename(root.rstrip("\\/")) or g["name"]
    if progress and soft:
        progress(f"Logiciel trouvé : {g['name']} — moteur {eng['engine']}. Recherche des fichiers de texte…")
    elif progress:
        progress(f"Jeu trouvé : {g['name']} — moteur {eng['engine']}. Recherche des fichiers de texte…")
    sources = find_text_files(root)
    notes = []
    # Textes répartis dans beaucoup de fichiers de configuration (ex. dialogues des jeux Godot)
    import bundle
    cfgs = bundle.scan_cfg(root)
    total = sum(n for _, n in cfgs)
    if total >= 5:
        sources.insert(0, {"kind": "bundle", "root": root, "files": [f for f, _ in cfgs],
                           "label": f"Dialogues et textes du jeu ({len(cfgs)} fichiers .cfg)",
                           "lines": total, "words": 0, "rank": 10**6, "sample": ""})
        try:
            ex = bundle.extract(root, [f for f, _ in cfgs][:40])
            sources[0]["sample"] = next((e["source"] for e in ex if " " in e["source"]), "")[:160]
            sources[0]["words"] = sum(len(e["source"].split()) for e in bundle.extract(root, [f for f, _ in cfgs]))
        except Exception:
            pass
        if bundle.is_applied(root):
            notes.insert(0, "Une traduction faite avec ce logiciel est déjà appliquée à ce jeu (sauvegarde présente).")
    if eng["engine"] == "Unity":
        u = scan_unity(eng["data"], progress=progress)
        groups = [s for s in u if s["kind"] in ("unity_group", "unity_object")]
        if len(groups) >= 2:  # tout le jeu dans un seul tableau : une traduction, un seul « Appliquer au jeu »
            items = [it for s in groups for it in (s.get("items") or [[s["file"], s["path_id"]]])]
            u.insert(0, {"kind": "unity_group", "script": "*", "items": items, "rank": 10**6,
                         "label": "Tous les textes du jeu (dialogues, choix, descriptions…)",
                         "lines": sum(s["lines"] for s in groups), "words": sum(s["words"] for s in groups),
                         "sample": groups[0].get("sample", "")})
        sources += u
        notes.append("Unity : le logiciel remet la traduction dans le jeu (originaux sauvegardés). Seuls les textes "
                     "affichés sont traduits ; les noms internes du jeu sont laissés de côté.")
        if bundle.is_applied(root):
            notes.insert(0, "Une traduction faite avec ce logiciel est déjà appliquée à ce jeu (sauvegarde présente).")
        if eng.get("detail") == "IL2CPP" and soft:
            import il2cppmeta
            try:
                n_ok, n_prudence, n_words, sample = il2cppmeta.count(root)
            except Exception as e:
                n_ok = 0
                notes.append(f"Unity IL2CPP : textes du programme illisibles ({e}).")
            if n_ok:
                sources.insert(0, {"kind": "il2cpp", "root": root, "script": "*", "rank": 10**6 + 1,
                                   "label": "Textes de l'interface écrits dans le programme (menus, boutons, messages)",
                                   "lines": n_ok, "words": n_words, "sample": sample[:160]})
                notes.append(f"Unity IL2CPP : {n_ok} textes de l'interface trouvés dans le programme. {n_prudence} autres "
                             "(mots qui servent aussi de noms internes, messages techniques) sont mis de côté dans « Ignorées » : "
                             "inclus-les seulement s'ils s'affichent dans le logiciel. Après « Appliquer », vérifie que tout "
                             "marche ; sinon « Remettre l'original » remet le programme comme avant.")
        elif eng.get("detail") == "IL2CPP":
            notes.append("Unity IL2CPP : les textes écrits dans le code du jeu ne sont pas modifiables, mais ceux des fichiers de données le sont.")
    elif eng["engine"] == "Ren'Py":
        import renpygame
        try:
            rp = renpygame.extract(root, progress=progress)
        except Exception:
            rp = []
        # fichiers du moteur Ren'Py lui-même (dossiers renpy/ et lib/) : pas des textes du jeu
        sources = [s for s in sources if not (s.get("path") and os.path.relpath(s["path"], root).replace("\\", "/")
                                              .split("/")[0].lower() in ("renpy", "lib"))]
        if rp:
            sources.insert(0, {"kind": "renpy", "root": root, "script": "*", "rank": 10**6,
                               "label": "Tous les dialogues et choix du jeu (Ren'Py)", "lines": len(rp),
                               "words": sum(len(e["source"].split()) for e in rp),
                               "sample": next((e["source"] for e in rp if len(e["source"]) > 25), rp[0]["source"])[:160]})
            try:
                ecran = renpygame.screen_extract(root)
            except Exception:
                ecran = []
            if ecran:  # 2e morceau : panneaux, menus, objets… (traduit et appliqué à part, puis réuni dans le jeu)
                sources.insert(1, {"kind": "renpyecran", "root": root, "script": "*", "rank": 10**6 - 1,
                                   "label": "Panneaux, menus et textes d'écran (Ren'Py)", "lines": len(ecran),
                                   "words": sum(len(e["source"].split()) for e in ecran),
                                   "sample": next((e["source"] for e in ecran if len(e["source"]) > 25), ecran[0]["source"])[:160]})
            notes.append("Ren'Py : le jeu se traduit en deux morceaux, chacun avec son tableau et son « Appliquer au jeu » : "
                         "les dialogues et choix, puis les panneaux, menus et textes d'écran (bulles d'aide, objets, "
                         "compétences…). Le logiciel ajoute la traduction au jeu sans modifier ses fichiers ; « Remettre "
                         "l'original » l'enlève.")
        else:
            notes.append("Ren'Py : aucun dialogue lisible trouvé (archives protégées par le studio ?).")
    elif eng["engine"] == "Unreal Engine":
        u_sources, u_notes = scan_unreal(root, progress)
        sources = u_sources + sources
        notes += u_notes
    elif eng["engine"] == "RPG Maker MV/MZ":
        notes.append("RPG Maker : les dialogues sont dans les fichiers .json du dossier « data » ; ils se traduisent directement.")
    elif eng["engine"] == "GameMaker" and _gamemaker_source(root, sources, notes):
        pass
    elif eng["engine"] == "Godot" and _godot_pck_source(root, sources, notes):
        pass
    elif eng["engine"] in ("GameMaker", "Godot"):
        if total >= 5:
            notes.append(f"{eng['engine']} : les dialogues sont dans des fichiers lisibles (traduisibles directement) ; "
                         "les menus, eux, sont rangés dans l'archive du jeu et restent en anglais pour l'instant.")
        else:
            notes.append(f"{eng['engine']} : les textes sont souvent rangés dans une archive du jeu ; la traduction demande un outil spécialisé.")
    langs = steam_languages(g.get("appid"))
    fr_official = has_french(langs)
    if fr_official is False:  # déjà dans la langue choisie : avertissement bien visible dans l'interface (steam_langs)
        notes.insert(0, "Pas de français officiel d'après la fiche Steam (langues : " + ", ".join(langs[:8]) +
                     ("…" if len(langs) > 8 else "") + ") : bon candidat pour une traduction.")
    fr_files = [x for x in sources if x.get("french")]
    fr_tables = [x for x in sources if x["kind"] == "unity_textasset" and re.search(r"(^|[	,;])fr([	,;]|$)", x.get("sample", ""), re.M)]
    if (fr_files or fr_tables) and fr_official is not True:
        where = (fr_files or fr_tables)[0]["label"]
        notes.insert(0, f"Ce jeu semble déjà avoir une traduction française (par exemple : {where}). Vérifie dans ses options avant de le traduire !")
    if eng["engine"] == "Non installé":
        notes.insert(0, "Ce dossier ne contient pas de jeu installé (aucun .exe) : installe-le depuis Steam puis relance l'analyse.")
    sources = [s for s in sources if s.get("kind") != "note"] + [s for s in sources if s.get("kind") == "note"]
    sources.sort(key=lambda s: s.get("script") != "*")  # « Tous les textes du jeu » toujours en premier
    # « Tous les textes du jeu » (script "*") regroupe les autres sources : on ne le compte pas deux fois
    words = sum(s.get("words", 0) for s in sources
                if s.get("kind") != "note" and not (s.get("script") == "*" and s.get("kind") == "unity_group"))
    wl = [s for s in sources if s.get("wordlist")]
    if wl:
        notes.append(f"« {wl[0]['label']} » ressemble à la liste des mots interdits du jeu (filtre du tchat) : ne la traduis pas. "
                     "Elle ne s'affiche jamais, et l'IA refuserait ses mots grossiers.")
    plain = [s for s in sources if s["kind"] in ("file", "bundle", "unreal_locres") and not s.get("wordlist")]
    unity = [s for s in sources if s["kind"].startswith("unity")]
    if any(s["kind"] == "il2cpp" for s in sources):
        verdict = ("possible", "Les textes de l'interface de ce logiciel ont été trouvés dans son programme : TradUp peut "
                               "les traduire puis les remettre dans le programme (original sauvegardé).")
    elif any(s["kind"] == "renpy" for s in sources):
        verdict = ("facile", "Les dialogues et les choix de ce jeu Ren'Py ont été trouvés : le logiciel peut les traduire "
                             "puis ajouter la traduction au jeu.")
    elif any(s["kind"] == "godotpck" for s in sources):
        if any(s["kind"] == "godotpck" and s.get("godot4") for s in sources):
            verdict = ("possible", "Les textes de ce jeu Godot 4 ont été trouvés : tu peux les traduire dès maintenant. La "
                                   "remise automatique dans le jeu arrive à la prochaine mise à jour (en test sur la perso).")
        else:
            verdict = ("facile", "Les textes de ce jeu Godot ont été trouvés dans son archive : le logiciel peut les traduire "
                                 "puis les remettre dans le jeu.")
    elif any(s["kind"] == "gamemaker" for s in sources):
        verdict = ("facile", "Les textes de ce jeu GameMaker ont été trouvés : le logiciel peut les traduire puis les "
                             "remettre dans le jeu.")
    elif plain and plain[0]["lines"] >= 30:
        verdict = ("facile", "Des fichiers de langue lisibles ont été trouvés : traduction directe possible.")
    elif unity:
        verdict = ("possible", "Les textes sont rangés dans les fichiers du jeu : le logiciel peut les traduire puis les remettre dans le jeu.")
    elif plain:
        verdict = ("possible", "Quelques fichiers de texte trouvés ; à vérifier.")
    elif eng["engine"] == "Non installé":
        verdict = ("difficile", "Le jeu n'est pas installé.")
    elif eng["engine"] == "Unreal Engine" and not plain:
        verdict = ("difficile", "Les textes du jeu sont enfermés dans ses archives (chiffrées ou compressées) : "
                                "il faudrait que le studio fournisse ses fichiers de traduction.")
    else:
        verdict = ("difficile", "Aucun texte trouvé automatiquement : le jeu les range sans doute dans une archive ou dans son code.")
    ac = anticheat(g["path"])
    on = online(g["path"], g.get("appid"))
    if on["level"] == "refuse":  # jeu en ligne compétitif (ou protégé) : refusé
        verdict = ("refuse", ONLINE_REFUSED.format(why=on["why"]))
    return {"game": g, "engine": eng, "sources": sources, "notes": notes, "words": words, "verdict": verdict, "anticheat": ac,
            "languages": langs, "french_official": fr_official, "online": on}


# ------------------------------------------------------------------ extraction vers le tableau
def extract_unity(source):
    """Textes d'une source Unity : {"entries", "root"} (objets, groupes) ou {"text", "name"} (TextAsset)."""
    items = source.get("items") or [[source["file"], source["path_id"]]]
    if source["kind"] == "unity_textasset":
        import UnityPy, tables
        for obj in UnityPy.load(source["file"]).objects:
            if obj.path_id == source["path_id"]:
                d = obj.read()
                c = d.m_Script
                text = c if isinstance(c, str) else bytes(c).decode("utf-8", "ignore")
                if tables.plain_rows(text) is None:  # vrai fichier de texte : traduit comme un fichier
                    return {"text": text, "name": d.m_Name}
                break  # tableau de langue : traduit ligne par ligne puis remis dans le jeu (unitypatch)
        else:
            raise ValueError("texte introuvable dans le fichier du jeu")
    import unitypatch  # lecture champ par champ (voir unitypatch.py)
    entries, root = unitypatch.extract(items)
    return {"entries": entries, "root": root}
