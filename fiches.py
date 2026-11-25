"""Fiches voix : une voix par personnage, décrite avec des mots (pas clonée).

Chaque fiche dit comment la voix doit sonner : genre, âge, timbre, ton, débit, plus une phrase libre.
Le moteur de voix (branché plus tard, voir SPEC_tradvoice.md) fabrique la voix à partir de cette description.
Règle de TradVoice : une voix peut avoir le même TON qu'un rôle, jamais imiter une personne réelle (acteur, célébrité).

L'IA locale (commun/localai.py, celle de TradUp) :
  - propose une fiche pour chaque personnage, d'après le contexte du jeu et ses répliques ;
  - comprend les demandes écrites dans la barre « Demande à l'IA » (« une voix de vieux marin bourru pour Bram »).
Sans IA (mode démo), une proposition simple est faite à partir du nom et du rôle.
"""
import json, re, unicodedata

GENRES = ["femme", "homme", "enfant", "neutre"]
AGES = ["enfant", "jeune", "adulte", "âgé"]
TIMBRES = ["grave", "médium", "aigu"]
DEBITS = ["lent", "normal", "rapide"]
FIELDS = {"genre": GENRES, "age": AGES, "timbre": TIMBRES, "debit": DEBITS}

RULES = (
    "Never imitate or name a real person (actor, voice actor, singer, celebrity, politician): describe only how the "
    "voice sounds. If the user asks for a real person's voice, describe an ORIGINAL voice with a similar mood instead. "
    "Write every text value in French."
)
PROPOSE_SYSTEM = (
    "You are a casting director for the French voice cast of a video game. For each character, describe the voice "
    "that fits them. Two important characters must never get the same voice (vary gender, age, pitch or tone). "
    "The narrator gets a calm, clear storytelling voice. " + RULES + " "
    'Answer ONLY with JSON: {"voices": [{"name": "...", "genre": "femme|homme|enfant|neutre", '
    '"age": "enfant|jeune|adulte|âgé", "timbre": "grave|médium|aigu", "ton": "2 to 4 French adjectives", '
    '"debit": "lent|normal|rapide", "description": "one short French sentence describing the voice"}]}'
)
ASK_SYSTEM = (
    "You help the user design the French voices of a video game's characters. The user writes a request; find which "
    "character it is about (exactly one name from the list, or null if none is named) and describe the requested "
    "voice. " + RULES + " "
    'Answer ONLY with JSON: {"name": "... or null", "genre": "...", "age": "...", "timbre": "...", "ton": "...", '
    '"debit": "...", "description": "...", "reply": "one short French sentence telling the user what you did"}'
)


def empty(name, narrator=False):
    return {"name": name, "genre": "neutre", "age": "adulte", "timbre": "médium",
            "ton": "posé, clair" if narrator else "", "debit": "normal", "description": "",
            "source": "vide", "verrouille": False, "narrator": narrator}


def _plain(s):
    return "".join(c for c in unicodedata.normalize("NFD", str(s or "").strip().lower()) if unicodedata.category(c) != "Mn")


def _norm(value, allowed, default):
    v = _plain(value)
    for a in allowed:
        if v and (v == _plain(a) or v.startswith(_plain(a)[:4])):
            return a
    return default


def _clean_text(s, limit):
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s[:limit]


def clean(card, base):
    """Fiche renvoyée par l'IA, remise dans les valeurs permises (le reste reprend `base`)."""
    out = dict(base)
    for k, allowed in FIELDS.items():
        out[k] = _norm(card.get(k), allowed, base[k])
    for k, lim in (("ton", 80), ("description", 240)):
        if card.get(k):
            out[k] = _clean_text(card[k], lim)
    return out


def _json(content):
    s = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", content or "")
    for st in [m.start() for m in re.finditer(r"\{", s)][:20]:
        try:
            obj, _ = json.JSONDecoder().raw_decode(s[st:])
            if isinstance(obj, dict):
                return obj
        except ValueError:
            continue
    return {}


def propose_request(chars, context=""):
    """Message pour l'IA : les personnages, leur nombre de répliques et quelques répliques d'exemple."""
    parts = []
    if context.strip():
        parts.append("About the game: " + context.strip())
    for c in chars:
        ex = " / ".join(c.get("examples", [])[:3])
        parts.append(f"- {c['name']}{' (narrator)' if c.get('narrator') else ''}: {c.get('lines', 0)} lines. "
                     f"Examples: {ex}")
    return "\n".join(parts)


def parse_proposals(content, chars, cards=None):
    """Fiches proposées par l'IA → {nom: fiche} ; les fiches verrouillées ne bougent pas."""
    cards = dict(cards or {})
    found = {}
    for v in _json(content).get("voices", []) or []:
        if isinstance(v, dict) and v.get("name"):
            found[str(v["name"]).strip().lower()] = v
    for c in chars:
        name = c["name"]
        base = cards.get(name) or empty(name, c.get("narrator", False))
        if base.get("verrouille"):
            cards[name] = base
            continue
        v = found.get(name.lower())
        cards[name] = dict(clean(v, base), source="proposée par l'IA") if v else base
    return cards


def demo_proposals(chars, cards=None):
    """Sans IA : une voix simple et différente pour chacun (narrateur posé, puis alternance femme/homme)."""
    cards = dict(cards or {})
    cycle = [("femme", "adulte", "médium", "chaleureux, vif"), ("homme", "adulte", "grave", "calme, assuré"),
             ("femme", "jeune", "aigu", "enjoué, curieux"), ("homme", "âgé", "grave", "bourru, lent"),
             ("homme", "jeune", "médium", "nerveux, rapide"), ("femme", "âgé", "médium", "doux, mystérieux")]
    i = 0
    for c in chars:
        name = c["name"]
        base = cards.get(name) or empty(name, c.get("narrator", False))
        if base.get("verrouille"):
            cards[name] = base
            continue
        if c.get("narrator"):
            g, a, t, ton = "neutre", "adulte", "grave", "posé, conteur"
        else:
            g, a, t, ton = cycle[i % len(cycle)]
            i += 1
        cards[name] = dict(base, genre=g, age=a, timbre=t, ton=ton, debit="lent" if a == "âgé" else "normal",
                           description=f"Voix {ton} ({g}, {a}, timbre {t}).", source="proposée (démo)")
    return cards


def propose(chars, context="", cards=None, ask=None):
    """Fiches pour tous les personnages. ask(system, user) -> texte : l'IA locale ; None → proposition démo."""
    if ask is None:
        return demo_proposals(chars, cards)
    return parse_proposals(ask(PROPOSE_SYSTEM, propose_request(chars, context)), chars, cards)


def ask_request(text, chars, cards, context=""):
    names = ", ".join(c["name"] for c in chars)
    current = "\n".join(f"- {n}: {c.get('description') or c.get('ton') or '(pas encore de voix)'}" for n, c in cards.items())
    return (("About the game: " + context.strip() + "\n") if context.strip() else "") + \
        f"Characters: {names}\nCurrent voices:\n{current}\n\nUser request: {text.strip()}"


def apply_answer(content, chars, cards, selected=None):
    """Réponse de l'IA à une demande libre → (nom changé ou None, fiches, phrase pour l'utilisateur).
    selected : personnage ouvert à l'écran, utilisé si la demande ne nomme personne."""
    ans = _json(content)
    names = {c["name"].lower(): c["name"] for c in chars}
    name = names.get(str(ans.get("name") or "").strip().lower()) or selected
    if not name or name not in {c["name"] for c in chars}:
        return None, cards, "Je n'ai pas compris de quel personnage tu parles : écris son nom dans ta demande."
    cards = dict(cards)
    base = cards.get(name) or empty(name, name.lower() == "narrateur")
    if base.get("verrouille"):
        return None, cards, f"La voix de {name} est verrouillée : déverrouille-la pour la changer."
    cards[name] = dict(clean(ans, base), source="décrite par toi")
    reply = _clean_text(ans.get("reply"), 200) or f"Nouvelle voix pour {name}."
    return name, cards, reply


def look_alikes(cards, chars, min_lines=20):
    """Paires de personnages importants qui auraient la même voix (même genre, âge et timbre) : risque de confusion."""
    big = [c["name"] for c in chars if c.get("lines", 0) >= min_lines and c["name"] in cards]
    out = []
    for i, a in enumerate(big):
        for b in big[i + 1:]:
            ca, cb = cards[a], cards[b]
            if all(ca[k] == cb[k] for k in ("genre", "age", "timbre")):
                out.append((a, b))
    return out
