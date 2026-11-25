"""Qui parle ? Les répliques d'un jeu Ren'Py, chacune rattachée à son personnage.

Sans jamais exécuter le code du jeu (mêmes lecteurs que TradUp, dans commun/renpygame.py) :
  - scripts sources .rpy : `e "Bonjour"` → réplique de la variable `e` ; `"Bonjour"` seul → narrateur ;
    `"Elda" "Bonjour"` → réplique d'un personnage nommé directement ;
  - scripts compilés .rpyc : on suit les clés « who » et « what » rangées dans le fichier (best effort : à vérifier
    sur de vrais jeux, voir SPEC_tradvoice.md étape 6) ;
  - `define e = Character("Elda", …)` relie la variable au nom affiché ; `Character(None, …)` = narrateur.

Résultat : une liste de répliques {id, who, name, text, kind, file} et un résumé par personnage
(nombre de répliques, exemples) qui sert à proposer une voix et à éviter les confusions.
"""
import pickletools, re

import renpygame

NARRATOR = "Narrateur"
DEFINE = re.compile(r"""^\s*define\s+([A-Za-z_]\w*)\s*=\s*(?:Character|DynamicCharacter|NVLCharacter|ADVCharacter)\(\s*"""
                    r"""(?:_\(\s*)?(?:(["'])((?:(?!\2).){0,60})\2|(None))""", re.M)
CHAR_CALL = re.compile(r"""(?:Character|DynamicCharacter|NVLCharacter|ADVCharacter)\(\s*(?:_\(\s*)?(?:(["'])((?:(?!\1).){0,60})\1|(None))""")
NAMED_SAY = re.compile(r'''^\s*(?P<q1>"|')(?P<who>(?:\\.|(?!(?P=q1)).){1,40})(?P=q1)\s+(?P<q>"|')(?P<s>(?:\\.|(?!(?P=q)).)*)(?P=q)\s*$''')


def _clean_name(n):
    n = (n or "").strip()
    if not n or re.search(r"[\[\]{}%]", n):
        return None  # nom calculé par le jeu ([player_name]…) : on garde la variable
    return n


def speakers_rpy(text):
    """{variable: nom affiché} déclarés par un script .rpy (None → narrateur)."""
    out = {}
    for m in DEFINE.finditer(text):
        var, name, none = m.group(1), m.group(3), m.group(4)
        out[var] = NARRATOR if none else (_clean_name(name) or var)
    return out


def lines_rpy(text):
    """[(variable ou nom, réplique, genre)] d'un script .rpy, dans l'ordre ; variable None = narrateur."""
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
        first = re.split(r"[\s:(]", stripped, maxsplit=1)[0]
        if first in ("python", "init", "screen", "transform", "style", "translate", "image") and stripped.endswith(":"):
            skip_indent = indent
            continue
        if first in renpygame.KEYWORDS or first.startswith("$"):
            continue
        if renpygame.CHOICE.match(line):
            continue  # un choix n'est dit par personne
        n = NAMED_SAY.match(line)
        if n:
            text_ = renpygame._unescape(n.group("s"))
            if renpygame._is_text(text_):
                out.append(("=" + renpygame._unescape(n.group("who")), text_, "dialogue"))
            continue
        m = renpygame.SAY.match(line)
        if m:
            text_ = renpygame._unescape(m.group("s"))
            if renpygame._is_text(text_):
                out.append((m.group(1), text_, "dialogue"))
    return out


def lines_rpyc(data):
    """Même chose pour un .rpyc, sans le charger : on suit « who » puis « what » dans le flux du fichier.
    Renvoie (répliques, {variable: nom}) ; les define sont lus dans le code gardé en texte par Ren'Py."""
    raw = renpygame._rpyc_raw(data)
    out, speakers, memo = [], {}, {}
    prev, last, who, pending_who, varname = None, None, None, False, None
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
        elif name in renpygame.STR_OPS and isinstance(arg, (str, bytes)):
            s = renpygame._fix(arg) if name in ("SHORT_BINSTRING", "BINSTRING", "STRING") or isinstance(arg, bytes) else arg
        else:
            if pending_who and name == "NONE":
                who, pending_who = None, False
            last = None
            continue
        last = s
        if not isinstance(s, str):
            continue
        if pending_who:
            who, pending_who = s, False
        elif prev == "varname":
            varname = s
        elif varname and "Character" in s:
            m = CHAR_CALL.search(s)
            if m:
                speakers[varname] = NARRATOR if m.group(3) else (_clean_name(m.group(2)) or varname)
            varname = None
        if s == "who":
            pending_who = True
        elif prev == "what" and renpygame._is_text(s):
            out.append((who, s, "dialogue"))
            who = None
        prev = s
    return out, speakers


def extract(root, progress=None):
    """Répliques du jeu avec leur personnage : [{id, who, name, text, kind, file}]."""
    files = renpygame.scripts(root, prefer_source=True)
    speakers, raw = {}, []
    for n, fname in enumerate(sorted(files), 1):
        if progress and n % 20 == 0:
            progress(f"Ren'Py : script {n}/{len(files)}…")
        try:
            data = files[fname]()
            if fname.lower().endswith(".rpyc"):
                lines, sp = lines_rpyc(data)
            else:
                text = data.decode("utf-8-sig", "replace")
                lines, sp = lines_rpy(text), speakers_rpy(text)
        except Exception:
            continue
        speakers.update(sp)
        raw += [(fname, w, t, k) for w, t, k in lines]
    out = []
    for fname, who, text, kind in raw:
        if who is None:
            name = NARRATOR
        elif who.startswith("="):
            name = _clean_name(who[1:]) or who[1:]
        else:
            name = speakers.get(who, who)  # variable inconnue : on garde son nom (l'utilisateur pourra renommer)
        out.append({"id": f"r{len(out)}", "who": who, "name": name, "text": text, "kind": kind,
                    "file": fname.replace("\\", "/")})
    return out


def summary(lines, examples=3):
    """Un personnage par nom, du plus bavard au moins bavard : [{name, lines, examples, narrator}]."""
    by = {}
    for ln in lines:
        c = by.setdefault(ln["name"], {"name": ln["name"], "lines": 0, "examples": [], "narrator": ln["name"] == NARRATOR})
        c["lines"] += 1
        if len(c["examples"]) < examples and len(ln["text"]) >= 12:
            c["examples"].append(ln["text"])
    return sorted(by.values(), key=lambda c: (-c["lines"], c["name"]))


def game_kind(lines):
    """« textuel » si tout est narration (jeu entièrement en texte : une voix de narrateur lit l'histoire),
    sinon « dialogues »."""
    if lines and all(ln["name"] == NARRATOR for ln in lines):
        return "textuel"
    return "dialogues"
