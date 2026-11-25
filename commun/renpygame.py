"""Jeux Ren'Py (visual novels) : lire les dialogues et les choix, puis ajouter la traduction au jeu.

Lecture (sans jamais exécuter le code du jeu) :
  - scripts compilés .rpyc : on parcourt leur contenu octet par octet (pickletools) sans le charger, et on garde les
    textes rangés sous « what » (dialogues) et les choix de menu ;
  - archives .rpa (format standard de Ren'Py, non chiffré) : on lit leur table des fichiers avec un lecteur qui refuse
    tout objet autre que des nombres et des textes ;
  - scripts sources .rpy (quand le jeu les fournit et qu'il n'y a pas de .rpyc).

Écriture : aucun fichier du jeu n'est modifié. TradUp AJOUTE dans « game » :
  - tradup_traduction.json : la table « texte d'origine → traduction » ;
  - zz_tradup_traduction.rpy : quelques lignes que Ren'Py charge au démarrage, qui remplacent chaque dialogue et chaque
    choix par sa traduction (réglage officiel de Ren'Py « config.say_menu_text_filter »).
« Remettre l'original » supprime ces fichiers (et la version compilée que Ren'Py en fait).
"""
import ast, io, json, os, pickle, pickletools, re, struct, time, zlib

import bundle
from protect import renpy_problem

JSON_NAME = "tradup_traduction.json"
RPY_NAME = "zz_tradup_traduction.rpy"
ADDED = [JSON_NAME, RPY_NAME, RPY_NAME + "c", RPY_NAME[:-4] + ".rpyb"]
STR_OPS = {"SHORT_BINUNICODE", "BINUNICODE", "BINUNICODE8", "UNICODE", "SHORT_BINSTRING", "BINSTRING", "STRING"}
LETTERS = re.compile(r"[A-Za-zÀ-ÿ]{2}")
NOT_TEXT = re.compile(r"^[\w./\\-]+\.(png|jpe?g|webp|ogg|mp3|wav|opus|webm|ttf|otf|rpy|rpyc|json|txt)$|^[a-z_][\w.]*$", re.I)
KEYWORDS = {"show", "scene", "hide", "play", "queue", "stop", "voice", "sound", "music", "jump", "call", "label", "define",
            "default", "image", "init", "python", "if", "elif", "else", "while", "menu", "return", "window", "with",
            "pause", "transform", "screen", "style", "translate", "old", "new", "camera", "at", "nvl", "extend_attr",
            "$", "use", "text", "add", "key", "font", "config", "renpy", "pass"}
SAY = re.compile(r'''^\s*(?:([A-Za-z_][\w.]*)(?:\s+[\w-]+)*\s+)?(?P<q>"|')(?P<s>(?:\\.|(?!(?P=q)).)*)(?P=q)'''
                 r'''(?:\s+(?:with\s+\w+|nointeract|id\s+\w+|\(.*\)))*\s*$''')
CHOICE = re.compile(r'''^\s*(?P<q>"|')(?P<s>(?:\\.|(?!(?P=q)).)*)(?P=q)(?:\s+\(.*\))?(?:\s+if\s+.+)?\s*:\s*$''')

FILTER_CODE = '''# Traduction ajoutée par TradUp (logiciel de traduction de jeux : https://gelatine-studio.itch.io/tradup).
# Pour l'enlever : « Remettre l'original » dans TradUp, ou supprimer ce fichier, sa version .rpyc
# et tradup_traduction.json. Aucun autre fichier du jeu n'a été modifié.
init 999 python:
    import json as _tradup_json
    def _tradup_load():
        try:
            opener = getattr(renpy, "open_file", None) or renpy.file
            f = opener("tradup_traduction.json")
            data = f.read()
            f.close()
            if not isinstance(data, type(u"")):
                data = data.decode("utf-8")
            return _tradup_json.loads(data)
        except Exception:
            return {}
    _tradup_table = _tradup_load()
    _tradup_previous = config.say_menu_text_filter
    def _tradup_filter(s):
        if _tradup_previous is not None:
            s = _tradup_previous(s)
        return _tradup_table.get(s, s)
    config.say_menu_text_filter = _tradup_filter
'''


# ------------------------------------------------------------------ lecture sans danger
class _SafeUnpickler(pickle.Unpickler):
    """Lecteur qui refuse tout objet « programme » : seuls nombres, textes, listes et dictionnaires passent.
    Seule exception : codecs.encode, qui sert uniquement à recréer un bloc d'octets (format des archives Ren'Py)."""
    def find_class(self, module, name):
        if (module, name) in (("_codecs", "encode"), ("codecs", "encode")):
            import codecs
            return lambda s, enc="latin-1": codecs.encode(s, "latin-1") if enc.lower().replace("_", "-") in ("latin-1", "latin1") \
                else (_ for _ in ()).throw(pickle.UnpicklingError("contenu refusé"))
        if (module, name) in (("__builtin__", "bytes"), ("builtins", "bytes")):
            return _small_bytes  # bloc d'octets vide ou court (début de fichier dans l'archive)
        raise pickle.UnpicklingError("contenu refusé")


def _small_bytes(*args):
    if not args:
        return b""
    if isinstance(args[0], (list, tuple)) and len(args[0]) <= 4096:
        return bytes(args[0])
    raise pickle.UnpicklingError("contenu refusé")


def _fix(s):
    """Textes écrits par Python 2 (anciens jeux) : on remet l'UTF-8 d'origine."""
    if isinstance(s, bytes):
        return s.decode("utf-8", "replace")
    try:
        return s.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


def rpa_index(path):
    """Table des fichiers d'une archive .rpa : {nom: (position, taille, début)}."""
    with open(path, "rb") as f:
        head = f.readline().split()
        if not head:
            raise ValueError("archive vide")
        if head[0] == b"RPA-3.0":
            offset, key = int(head[1], 16), int(head[2], 16)
        elif head[0] == b"RPA-2.0":
            offset, key = int(head[1], 16), 0
        else:
            raise ValueError("archive Ren'Py non standard (protégée par le studio)")
        f.seek(offset)
        index = _SafeUnpickler(io.BytesIO(zlib.decompress(f.read())), encoding="latin-1").load()
    out = {}
    for name, entries in index.items():
        e = entries[0] if isinstance(entries[0], (list, tuple)) else entries
        prefix = e[2] if len(e) > 2 else b""
        if isinstance(prefix, str):
            prefix = prefix.encode("latin-1")
        out[_fix(name)] = (e[0] ^ key, e[1] ^ key, prefix)
    return out


def rpa_read(path, entry):
    off, length, prefix = entry
    with open(path, "rb") as f:
        f.seek(off)
        return prefix + f.read(max(0, length - len(prefix)))


def rpyc_texts(data, kinds=None):
    """Dialogues et choix d'un script compilé .rpyc, dans l'ordre, sans charger son contenu.
    kinds : liste remplie en parallèle avec « dialogue » ou « choix »."""
    if data.startswith(b"RENPY RPC2"):
        pos, slots = 10, {}
        while pos + 12 <= len(data):
            slot, start, length = struct.unpack("<III", data[pos:pos + 12])
            pos += 12
            if slot == 0:
                break
            slots[slot] = data[start:start + length]
        raw = zlib.decompress(slots[1])
    else:
        raw = zlib.decompress(data)
    # Un texte déjà rencontré n'est pas réécrit mais « rappelé » (mémo) : on suit ces rappels pour ne rien rater.
    out, prev, last, memo = [], None, None, {}
    for op, arg, _ in pickletools.genops(raw):
        name = op.name
        if name in ("PUT", "BINPUT", "LONG_BINPUT"):
            memo[int(arg)] = last
            continue
        if name == "MEMOIZE":
            memo[len(memo)] = last
            continue
        if name in ("GET", "BINGET", "LONG_BINGET"):
            s = memo.get(int(arg))
        elif name in STR_OPS and isinstance(arg, (str, bytes)):
            s = _fix(arg) if name in ("SHORT_BINSTRING", "BINSTRING", "STRING") or isinstance(arg, bytes) else arg
        else:
            last = None
            continue
        last = s
        if not isinstance(s, str):
            continue
        if prev == "what" and _is_text(s):  # Say : la valeur rangée sous la clé « what »
            out.append(s)
            if kinds is not None:
                kinds.append("dialogue")
        elif s == "True" and prev is not None and prev != "what" and _is_text(prev):  # Menu : (choix, « True », bloc)
            out.append(prev)
            if kinds is not None:
                kinds.append("choix")
        prev = s
    return out


def _is_text(s):
    s = s.strip()
    return bool(s) and bool(LETTERS.search(s)) and not NOT_TEXT.match(s) and not s.startswith(("renpy.", "store."))


def _unescape(s):
    s = re.sub(r"\s+", " ", s)
    return re.sub(r"\\(.)", lambda m: {"n": "\n", "t": "\t"}.get(m.group(1), m.group(1)), s)


def rpy_texts(text, kinds=None):
    """Dialogues et choix d'un script source .rpy (kinds : « dialogue » ou « choix » pour chacun)."""
    out, skip_indent = [], None
    for line in text.splitlines():
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())
        if skip_indent is not None:
            if stripped and indent <= skip_indent:
                skip_indent = None
            else:
                continue
        if not stripped or stripped.startswith("#"):
            continue
        first = re.split(r"[\s:(]", stripped, 1)[0]
        if first in ("python", "init", "screen", "transform", "style", "translate", "image") and stripped.endswith(":"):
            skip_indent = indent  # blocs de code ou d'interface : pas des dialogues
            continue
        if first in KEYWORDS or first.startswith("$"):
            continue
        c = CHOICE.match(line)
        m = c or SAY.match(line)
        if m and _is_text(_unescape(m.group("s"))):
            out.append(_unescape(m.group("s")))
            if kinds is not None:
                kinds.append("choix" if c else "dialogue")
    return out


# ------------------------------------------------------------------ jeu complet
def game_dir(root):
    return os.path.join(root, "game")


def is_renpy(root):
    g = game_dir(root)
    return os.path.isdir(g) and any(f.lower().endswith((".rpy", ".rpyc", ".rpa")) for f in os.listdir(g))


def _skip(rel):
    low = rel.replace("\\", "/").lower()
    return (low.startswith(("tl/", "renpy/", "common/")) or "/tl/" in low or os.path.basename(low) in ADDED
            or low.startswith("cache/"))


def scripts(root, progress=None, prefer_source=False):
    """{nom: contenu} des scripts du jeu (.rpyc de préférence, sinon .rpy), dossiers et archives .rpa compris.
    prefer_source : le .rpy quand il existe (plus sûr pour retrouver les textes d'écran)."""
    g = game_dir(root)
    found = {}
    for dp, dns, fns in os.walk(g):
        dns[:] = [d for d in dns if d.lower() not in ("tl", "saves", "cache")]
        for f in fns:
            low = f.lower()
            rel = os.path.relpath(os.path.join(dp, f), g)
            if _skip(rel):
                continue
            if low.endswith((".rpy", ".rpyc")):
                found[rel.replace("\\", "/")] = lambda p=os.path.join(dp, f): open(p, "rb").read()
            elif low.endswith(".rpa"):
                try:
                    index = rpa_index(os.path.join(dp, f))
                except Exception:
                    continue  # archive protégée par le studio : on n'insiste pas
                for name, entry in index.items():
                    if name.lower().endswith((".rpy", ".rpyc")) and not _skip(name):
                        found.setdefault(name, lambda p=os.path.join(dp, f), e=entry: rpa_read(p, e))
    keep = {}
    for name, read in found.items():
        if not prefer_source and name.lower().endswith(".rpy") and (name + "c") in found:
            continue  # le .rpyc est ce que le jeu utilise vraiment
        if prefer_source and name.lower().endswith(".rpyc") and name[:-1] in found:
            continue
        keep[name] = read
    return keep


def extract(root, progress=None):
    """Entrées du tableau (un texte = une ligne ; un texte répété n'est traduit qu'une fois)."""
    seen, entries = set(), []
    files = scripts(root)
    for n, name in enumerate(sorted(files), 1):
        if progress and n % 20 == 0:
            progress(f"Ren'Py : script {n}/{len(files)}…")
        try:
            data = files[name]()
            texts = rpyc_texts(data) if name.lower().endswith(".rpyc") else rpy_texts(data.decode("utf-8", "replace"))
        except Exception:
            continue
        for t in texts:
            if t in seen or not t.strip():
                continue
            seen.add(t)
            entries.append({"key": f"renpy|{len(entries)}", "source": t, "target": "", "skip": False,
                            "field": os.path.basename(name)})
    return entries


# ------------------------------------------------------------------ noms des personnages (lexique)
CHARACTER = re.compile(r"""\b(?:Character|DynamicCharacter|NVLCharacter|ADVCharacter)\(\s*(?:_\(\s*)?(["'])((?:(?!\1).){1,40})\1""")


# rôles et titres déclarés comme personnages (« Priestess », « Guard »…) : ceux-là se traduisent
GENERIC_ROLES = {"priestess", "priest", "baron", "baroness", "guard", "guards", "maid", "shopkeeper", "merchant", "girl", "boy",
                 "man", "woman", "old man", "old woman", "narrator", "villager", "soldier", "king", "queen", "prince",
                 "princess", "knight", "receptionist", "bartender", "waitress", "waiter", "teacher", "student", "mother",
                 "father", "mom", "dad", "sister", "brother", "stranger", "voice", "everyone", "all", "both", "crowd",
                 "monster", "goddess", "god", "demon", "boss", "master", "servant", "customer", "clerk", "doctor", "nurse",
                 "captain", "chief", "elder", "thug", "bandit", "thief", "adventurer", "adventurers", "hero", "player", "you"}


def character_names(root):
    """Noms des personnages déclarés par le jeu (define x = Character("Darkness", …)) : ils ne se traduisent pas.
    Lus dans les scripts (sources .rpy ou code gardé dans les .rpyc), sans rien exécuter."""
    names = set()
    for name, read in scripts(root, prefer_source=True).items():
        try:
            data = read()
            texts = [data.decode("utf-8", "replace")] if name.lower().endswith(".rpy") else \
                [a for op, a, _ in pickletools.genops(_rpyc_raw(data)) if op.name in STR_OPS and isinstance(a, str) and "Character" in a]
        except Exception:
            continue
        for t in texts:
            for m in CHARACTER.finditer(t):
                n = m.group(2).strip()
                if len(n) >= 2 and re.search(r"[A-Za-zÀ-ÿ]", n) and not re.search(r"[\[\]{}?%]", n) and n.lower() not in GENERIC_ROLES:
                    names.add(n)
    return sorted(names)


def _rpyc_raw(data):
    if data.startswith(b"RENPY RPC2"):
        pos, slots = 10, {}
        while pos + 12 <= len(data):
            slot, start, length = struct.unpack("<III", data[pos:pos + 12])
            pos += 12
            if slot == 0:
                break
            slots[slot] = data[start:start + length]
        return zlib.decompress(slots[1])
    return zlib.decompress(data)


# ------------------------------------------------------------------ place réelle des textes (alerte « trop longue »)
# Ren'Py passe à la ligne tout seul : une réplique n'est trop longue que si elle ne tient plus dans la boîte de
# dialogue. On lit la taille de cette boîte et du texte dans gui.rpy (et la hauteur des choix dans screens.rpy).
GUI_DEFAULT = {"dialogue_width": 1116, "text_size": 33, "textbox_height": 278, "choice_button_width": 1185}  # modèle 1920×1080


def _gui_values(text):
    vals, num = {}, re.compile(r"^\s*define\s+gui\.(\w+)\s*=\s*(.+?)\s*(?:#.*)?$", re.M)
    for name, expr in num.findall(text):
        expr = expr.strip()
        if re.fullmatch(r"-?\d+(?:\.\d+)?", expr):
            vals[name] = float(expr)
        elif re.fullmatch(r"gui\.\w+", expr) and expr[4:] in vals:
            vals[name] = vals[expr[4:]]
    m = re.search(r"gui\.init\(\s*(\d+)\s*,\s*(\d+)\s*\)", text)
    return vals, (int(m.group(1)) if m else 1920)


def box(root):
    """Place des textes dans ce jeu : {"dialogue": {"cpl", "lines"}, "choice": {"cpl", "lines"}, "choices": [...]}.
    cpl = caractères par ligne (environ), lines = lignes visibles avant de déborder."""
    files = scripts(root, prefer_source=True)
    text = lambda n: next((files[k]().decode("utf-8", "replace") for k in files if k.lower().split("/")[-1] == n), "")
    vals, width = _gui_values(text("gui.rpy"))
    scale = width / 1920
    get = lambda k: vals.get(k, GUI_DEFAULT.get(k, 0) * scale)
    size, csize = get("text_size") or 33 * scale, vals.get("choice_button_text_size") or get("text_size") or 33 * scale
    dialogue = {"cpl": max(20, int(get("dialogue_width") / (size * 0.52))),
                "lines": max(2, min(6, int(get("textbox_height") / (size * 1.3))))}
    choice_lines = 2
    sc = re.search(r"^screen\s+choice\b.*?(?=^screen\s|\Z)", text("screens.rpy"), re.S | re.M)
    if sc:
        ym = re.search(r"ymaximum\s+(\d+)", sc.group(0))
        if ym:
            choice_lines = max(1, int(int(ym.group(1)) / (csize * 1.15)))
    choice = {"cpl": max(15, int(get("choice_button_width") / (csize * 0.52))), "lines": choice_lines}
    choices = set()
    for name in files:
        try:
            data, kinds = files[name](), []
            texts = rpyc_texts(data, kinds) if name.lower().endswith(".rpyc") else rpy_texts(data.decode("utf-8", "replace"), kinds)
            choices.update(t for t, k in zip(texts, kinds) if k == "choix")
        except Exception:
            continue
    return {"dialogue": dialogue, "choice": choice, "choices": sorted(choices)}


# ------------------------------------------------------------------ textes d'écran (panneaux, menus, objets…)
# Ren'Py traduit tout texte affiché à l'écran grâce aux blocs officiels « translate <langue> strings » (old → new),
# rangés dans game/tl/<langue>. C'est ce que font les traductions de fans. Une traduction en trop ne casse rien : elle
# ne sert que si ce texte exact s'affiche. TradUp écrit son propre fichier dans ce dossier, sans toucher au jeu.
SCREEN_FILE = "tradup_textes_ecran.rpy"
RENPY_LANG = {"fr": ("french", "Français"), "de": ("german", "Deutsch"), "es": ("spanish", "Español"),
              "it": ("italian", "Italiano"), "pt": ("portuguese", "Português"), "nl": ("dutch", "Nederlands"),
              "pl": ("polish", "Polski"), "ru": ("russian", "Русский"), "uk": ("ukrainian", "Українська"),
              "ja": ("japanese", "日本語"), "ko": ("korean", "한국어"), "zh": ("schinese", "简体中文"),
              "en": ("english", "English")}
STRING_LIT = re.compile(r'"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'')
IDENT = re.compile(r"^[a-z_][\w.]*$")
CODE_ID = re.compile(r"^(?:[A-Z0-9]+_[A-Z0-9_]+|[A-Z][a-z]+(?:[A-Z][a-z0-9]+)+)$")  # ENEMY_LURK, CommonFish : des noms internes
FILE_EXT = re.compile(r"\.(png|jpe?g|webp|gif|ogg|mp3|wav|opus|webm|mp4|ttf|otf|rpyc?|rpa|json|txt|py)$", re.I)
SKIP_DIRS = ("tl", "saves", "cache", "renpy", "lib")


CODE_LIKE = re.compile(r"[A-Za-z0-9]_[A-Za-z0-9]|==|!=|\w\(|\)\.|\bnot None\b|\bis None\b")  # code du jeu


def _screen_text(s):
    """Texte qui peut s'afficher à l'écran (et pas un nom de fichier, une variable, un code…)."""
    t = s.strip()
    bare = re.sub(r"\{[^{}]*\}|\[[^\[\]]*\]", "", t)  # balises et variables : pas du code
    return (bool(re.search(r"[A-Za-zÀ-ÿ]{2}", t)) and len(t) < 2000 and not IDENT.match(t) and not CODE_ID.match(t)
            and not CODE_LIKE.search(bare)
            and not FILE_EXT.search(t) and "/" not in t.replace("{/", "").replace("[/", "")
            and not t.startswith(("renpy.", "store.", "#", "config.", "persistent.")))


def _literal(s):
    try:
        v = ast.literal_eval(s)
    except Exception:
        return None
    return v if isinstance(v, str) else None


def rpy_strings(text):
    """Tous les textes entre guillemets d'un script source .rpy."""
    out = []
    for line in text.splitlines():
        st = line.strip()
        if not st or st.startswith("#"):
            continue
        out += [v for v in (_literal(m.group(0)) for m in STRING_LIT.finditer(line)) if v is not None]
    return out


def rpyc_strings(data):
    """Textes entre guillemets gardés comme code dans un script compilé (écrans : text "…", _("…"), arguments…)."""
    if data.startswith(b"RENPY RPC2"):
        pos, slots = 10, {}
        while pos + 12 <= len(data):
            slot, start, length = struct.unpack("<III", data[pos:pos + 12])
            pos += 12
            if slot == 0:
                break
            slots[slot] = data[start:start + length]
        raw = zlib.decompress(slots[1])
    else:
        raw = zlib.decompress(data)
    out = []
    for op, arg, _ in pickletools.genops(raw):
        if op.name in STR_OPS and isinstance(arg, str) and ('"' in arg or "'" in arg):
            out += [v for v in (_literal(m.group(0)) for m in STRING_LIT.finditer(arg)) if v is not None]
    return out


def _json_strings(o):
    if isinstance(o, str):
        yield o
    elif isinstance(o, dict):
        for v in o.values():
            yield from _json_strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from _json_strings(v)


def existing_strings(root, lang):
    """Textes déjà traduits dans game/tl/<lang> par un autre que TradUp (Ren'Py refuse un même texte deux fois)."""
    d = os.path.join(game_dir(root), "tl", lang)
    done = set()
    if not os.path.isdir(d):
        return done
    for dp, dns, fns in os.walk(d):
        for f in fns:
            if f.lower().endswith(".rpy") and f != SCREEN_FILE:
                try:
                    text = open(os.path.join(dp, f), encoding="utf-8", errors="replace").read()
                except OSError:
                    continue
                for m in re.finditer(r'^\s*old\s+("(?:\\.|[^"\\])*")', text, re.M):
                    v = _literal(m.group(1))
                    if v is not None:
                        done.add(v)
    return done


def screen_extract(root, progress=None):
    """Textes d'écran du jeu : écrans et menus, bulles d'aide, objets et compétences (fichiers de données .json).
    Les dialogues et choix (déjà dans « Tous les dialogues et choix ») sont laissés de côté."""
    dialogue = {e["source"] for e in extract(root)}
    found, order = set(), []

    def add(texts, field):
        for t in texts:
            if t not in found and t not in dialogue and _screen_text(t):
                found.add(t)
                order.append((t, field))

    files = scripts(root, prefer_source=True)
    for n, name in enumerate(sorted(files), 1):
        if progress and n % 20 == 0:
            progress(f"Ren'Py : textes d'écran, script {n}/{len(files)}…")
        try:
            data = files[name]()
            add(rpyc_strings(data) if name.lower().endswith(".rpyc") else rpy_strings(data.decode("utf-8", "replace")),
                os.path.basename(name))
        except Exception:
            continue
    g = game_dir(root)
    for dp, dns, fns in os.walk(g):
        dns[:] = [d for d in dns if d.lower() not in SKIP_DIRS]
        for f in sorted(fns):
            if f.lower().endswith(".json") and f not in ADDED and not f.lower().startswith("tradup_"):
                try:
                    add(_json_strings(json.load(open(os.path.join(dp, f), encoding="utf-8"))), f)
                except Exception:
                    continue
    # un texte qui est exactement le nom d'un personnage du jeu (affiché au-dessus des répliques) : jamais traduit
    # (cas réel : « Darkness » → « Ténèbres », « Baron » → « Baronneur » dans Adventurer Trainer, 16/11)
    noms = set(character_names(root))
    return [{"key": f"renpyecran|{i}", "source": t, "target": "", "skip": t.strip() in noms,
             "autoskip": t.strip() in noms, "field": field}
            for i, (t, field) in enumerate(order)]


def _rpy_quote(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def _game_version(root):
    g = game_dir(root)
    names = ["options.rpy"] + sorted(f for f in os.listdir(g) if f.endswith(".rpy") and f != "options.rpy")
    for name in names:
        try:
            m = re.search(r'config\.version\s*=\s*"([^"]+)"', open(os.path.join(game_dir(root), name), encoding="utf-8").read())
            if m:
                return m.group(1)
        except OSError:
            pass
    return ""


def _flag(path, tgt):
    """Petit drapeau pour l'écran des langues du jeu (s'il en a un)."""
    from PIL import Image, ImageDraw
    colors = {"fr": ["#0055a4", "#ffffff", "#ef4135"], "it": ["#009246", "#ffffff", "#ce2b37"],
              "de": ["#000000", "#dd0000", "#ffce00"], "nl": ["#ae1c28", "#ffffff", "#21468b"],
              "es": ["#aa151b", "#f1bf00", "#aa151b"], "pl": ["#ffffff", "#dc143c"], "uk": ["#0057b7", "#ffd700"],
              "ru": ["#ffffff", "#0039a6", "#d52b1e"]}.get(tgt)
    im = Image.new("RGB", (192, 128), "#444444")
    d = ImageDraw.Draw(im)
    if colors and tgt in ("fr", "it"):
        for i, c in enumerate(colors):
            d.rectangle([i * 64, 0, i * 64 + 63, 127], fill=c)
    elif colors:
        h = 128 / len(colors)
        for i, c in enumerate(colors):
            d.rectangle([0, round(i * h), 191, round((i + 1) * h) - 1], fill=c)
    else:
        d.text((80, 56), tgt.upper(), fill="#ffffff")
    im.save(path)


def apply_screens(root, entries, tgt="fr", log=print, notice=""):
    """Ajoute la traduction des textes d'écran : game/tl/<langue>/tradup_textes_ecran.rpy (+ manifest.json et
    drapeau si TradUp crée ce dossier). Aucun fichier du jeu n'est modifié. Renvoie {texte: problème} des lignes
    écartées (balises cassées)."""
    g = game_dir(root)
    if not os.path.isdir(g):
        raise RuntimeError("Dossier « game » introuvable : ce n'est pas un jeu Ren'Py.")
    lang, local = RENPY_LANG.get(tgt, (tgt, tgt))
    rel_dir = os.path.join("game", "tl", lang)
    d = bundle.inside(root, rel_dir)
    created = not os.path.isdir(d)
    others = existing_strings(root, lang)  # une traduction de fans déjà là : on ne double aucun de ses textes
    noms = set(character_names(root))  # noms des personnages : jamais traduits (même dans un ancien projet)
    lines, bad, seen = [], {}, set()
    for e in entries:
        src, tr = e.get("source") or "", e.get("target") or ""
        if not tr or e.get("skip") or tr == src or src in seen or src in others or src.strip() in noms:
            continue
        problem = renpy_problem(src, tr)
        if problem:
            bad[src] = problem
            continue
        seen.add(src)
        lines.append(f"    old {_rpy_quote(src)}\n    new {_rpy_quote(tr)}\n")
    os.makedirs(d, exist_ok=True)
    man = bundle._manifest(root)
    added = set(man.get("_ajoutes", []))
    if created or os.path.join(rel_dir, "manifest.json") in man.get("_ajoutes_tl", []):
        mpath = os.path.join(d, "manifest.json")
        json.dump({"language": lang, "localized_language": local, "version": _game_version(root),
                   "ml_translated": True, "contributors": ["TradUp"]},
                  open(mpath, "w", encoding="utf-8"), ensure_ascii=False, indent=4)
        if not os.path.exists(os.path.join(d, "flag.png")):
            try:
                _flag(os.path.join(d, "flag.png"), tgt)
            except Exception:
                pass
        man["_ajoutes_tl"] = sorted(set(man.get("_ajoutes_tl", [])) | {os.path.join(rel_dir, "manifest.json"),
                                                                      os.path.join(rel_dir, "flag.png")})
        man["_dossiers_tl"] = sorted(set(man.get("_dossiers_tl", [])) | {rel_dir})
    head = (notice + "# Textes d'écran traduits par TradUp (panneaux, menus, objets…). « Remettre l'original » dans TradUp\n"
            "# enlève ce fichier. Aucun autre fichier du jeu n'a été modifié.\n"
            "init 1000 python:\n"
            "    # Au premier lancement après la traduction, le jeu passe dans cette langue (une seule fois :\n"
            "    # ensuite, le choix du joueur dans les Préférences est respecté).\n"
            "    if not persistent._tradup_langue_" + lang + ":\n"
            "        persistent._tradup_langue_" + lang + " = True\n"
            "        if _preferences.language is None:\n"
            f"            _preferences.language = {_rpy_quote(lang)}\n\n")
    body = (f"translate {lang} strings:\n\n" + "\n".join(lines)) if lines else ""
    p = os.path.join(d, SCREEN_FILE)
    tmp = p + ".tmp_trad"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(head + body)
    os.replace(tmp, p)
    for old in (p + "c", p[:-4] + ".rpyb"):
        if os.path.exists(old):
            os.remove(old)  # Ren'Py recompilera au prochain lancement
    man["_ajoutes"] = sorted(added | {os.path.join(rel_dir, n) for n in (SCREEN_FILE, SCREEN_FILE + "c")})
    man["_date"] = time.strftime("%Y-%m-%d %H:%M")
    bdir = os.path.join(root, bundle.BACKUP_DIR)
    os.makedirs(bdir, exist_ok=True)
    json.dump(man, open(os.path.join(bdir, "manifest.json"), "w", encoding="utf-8"), indent=1)
    log(f"Ren'Py : {len(lines)} texte(s) d'écran traduits ajoutés au jeu" + (f", {len(bad)} laissé(s) en version originale (balises cassées)" if bad else ""))
    return bad


def apply(root, entries, log=print, notice=""):
    """Ajoute la traduction au jeu (fichiers ajoutés dans « game », aucun fichier du jeu modifié).
    notice : avertissement « usage personnel » (TradUp Gaming) mis en commentaire en haut du .rpy et, dans la table,
    sous une clé qu'aucun texte du jeu ne porte."""
    g = game_dir(root)
    if not os.path.isdir(g):
        raise RuntimeError("Dossier « game » introuvable : ce n'est pas un jeu Ren'Py.")
    table, bad = {}, {}
    for e in entries:
        if not e.get("target") or e.get("skip") or e["target"] == e["source"]:
            continue
        problem = renpy_problem(e["source"], e["target"])
        if problem:  # balise mal fermée, « [[ » ou variable perdue : Ren'Py afficherait une erreur → on garde l'original
            bad[e["source"]] = problem
            continue
        table[e["source"]] = e["target"]
    jpath = bundle.inside(root, os.path.join("game", JSON_NAME))
    rpath = bundle.inside(root, os.path.join("game", RPY_NAME))
    out = {"_TradUp_avertissement": " ".join(l.lstrip("# ") for l in notice.splitlines()), **table} if notice else table
    for p, content in ((jpath, json.dumps(out, ensure_ascii=False, indent=0)), (rpath, notice + FILTER_CODE)):
        tmp = p + ".tmp_trad"
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        os.replace(tmp, p)
    old = bundle.inside(root, os.path.join("game", RPY_NAME + "c"))
    if os.path.exists(old):
        os.remove(old)  # Ren'Py recompilera le fichier au prochain lancement
    bdir = os.path.join(root, bundle.BACKUP_DIR)
    os.makedirs(bdir, exist_ok=True)
    man = bundle._manifest(root)
    man["_ajoutes"] = sorted(set(man.get("_ajoutes", [])) | {os.path.join("game", n) for n in ADDED})
    man["_date"] = time.strftime("%Y-%m-%d %H:%M")
    json.dump(man, open(os.path.join(bdir, "manifest.json"), "w", encoding="utf-8"), indent=1)
    log(f"Ren'Py : {len(table)} texte(s) traduits ajoutés au jeu" + (f", {len(bad)} laissé(s) en version originale (balises cassées)" if bad else ""))
    return bad
