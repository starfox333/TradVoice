"""Mise à l'abri des balises, variables et codes avant traduction.

« Hello <b>{name}</b>!\\n » devient « Hello [T1][T2][T3]![T4] » : l'IA ne voit que
des jetons simples, qu'on remet ensuite à leur place.
"""
import re

PATTERNS = [
    r"\[\[",                            # « [[ » de Ren'Py = un vrai crochet affiché (sinon « [Mot] » devient une variable)
    r"(?:!_[A-Za-z0-9_]+|!MARKER|!\$CHEAT)+",  # codes cachés dans les choix de certains jeux Ren'Py (« Parler!_talk_to_eris »)
    r"<[^<>\n]{1,80}>",                 # balises riches : <i>, </b>, <size=70%>, <color=#fff>
    r"\{\{[^{}]{0,40}\}\}",              # {{variable}}
    r"\{[^{}\n]{0,40}\}",                # {0}, {name}, {i} (Ren'Py)
    # Balises entre crochets (BBCode Godot, variables Ren'Py) : [/shake], [color=red], [shake rate=20], [b], [player_name],
    # [PLAYER]. Mais un texte entre crochets comme « [Go to Sleep] » ou « [Yes] » est un choix affiché : on le traduit.
    r"\[/[A-Za-z_][\w-]*\]",
    r"\[[A-Za-z_][\w-]*(?:=|\s+[\w-]+=)[^\[\]\n]{0,40}\]",
    r"\[(?:[a-z_][\w-]*|[A-Z0-9_]{2,}|\w*[_\d]\w*)\]",
    r"%[A-Za-z_][A-Za-z0-9_]*%",          # %NAME%, %PRONOUN_POSSESSIVE% : marqueurs remplacés par le jeu (AVANT %s)
    # %s, %d, %1$s, %.2f — sans l'espace comme option : « %NAME% came » donnait le faux code « % c » (→ « %NAME% cvient »,
    # Adventurer Trainer, 16/11) et « 50% sure » le faux code « % s »
    r"%(?:\d+\$)?[-+0#]*\d*(?:\.\d+)?[sdifuxXeEgGc@%]",
    r"\$\{?[A-Za-z_]\w*\}?",              # $var, ${var}
    r"\\[nrt]",                          # \n écrit en toutes lettres
    r"\n",                               # vrai retour à la ligne
]
RX = re.compile("|".join(f"(?:{p})" for p in PATTERNS))
TOKEN = re.compile(r"\[T(\d+)\]")


def protect(text):
    codes = []
    def sub(m):
        codes.append(m.group(0))
        return f"[T{len(codes)}]"
    return RX.sub(sub, text), codes


RENPY_TAG = re.compile(r"(?<!\{)\{(/?)([A-Za-z_]+)[^{}]*\}")
RENPY_SELF = {"w", "p", "nw", "fast", "done", "image", "space", "vspace", "clear"}  # balises sans fermeture
GAME_CODES = re.compile(r"!_[A-Za-z0-9_]+|!MARKER|!\$CHEAT")
RENPY_VAR = re.compile(r"\[[^\[\]]+\]")


def _renpy_tags(s):
    """Balises {…} encore ouvertes à la fin (triées), ou None si une fermeture ne correspond à rien."""
    st = []
    for m in RENPY_TAG.finditer(s):
        close, tag = m.group(1), m.group(2)
        if tag in RENPY_SELF:
            continue
        if not close:
            st.append(tag)
        elif not st or st.pop() != tag:
            return None
    return sorted(st)


def renpy_problem(source, target):
    """Contrôle d'une traduction Ren'Py : mêmes balises {…} bien fermées, mêmes « [[ » et mêmes variables [x] que
    l'original. Sinon Ren'Py peut afficher une erreur en pleine partie. Renvoie None si tout va bien.
    (Les balises longues comme {lore=…} ne sont pas mises à l'abri : l'IA traduit leur texte, d'où ce contrôle.)"""
    if not target:
        return None
    a, b = _renpy_tags(source), _renpy_tags(target)
    if b is None and a is not None:
        return "balises {…} mal fermées"
    if a != b:
        return "balises {…} différentes de l'original"
    if GAME_CODES.findall(source) != GAME_CODES.findall(target):
        return "codes du jeu (!_…) différents de l'original"
    if source.count("[[") != target.count("[["):
        return "crochets « [[ » différents de l'original"
    if sorted(RENPY_VAR.findall(source.replace("[[", ""))) != sorted(RENPY_VAR.findall(target.replace("[[", ""))):
        return "variables […] différentes de l'original"
    return None


def restore(text, codes):
    """Remet les codes. Renvoie (texte, problème) ; problème vaut None si tout est en place."""
    found = [int(n) for n in TOKEN.findall(text)]
    out = TOKEN.sub(lambda m: codes[int(m.group(1)) - 1] if 0 < int(m.group(1)) <= len(codes) else "", text)
    want = list(range(1, len(codes) + 1))
    if sorted(found) != want:
        missing = [codes[i - 1] for i in want if i not in found]
        return out, ("codes manquants : " + " ".join(missing)) if missing else "codes en double"
    return out, None
