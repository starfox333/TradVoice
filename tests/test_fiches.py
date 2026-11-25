import json, os, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [BASE, os.path.join(BASE, "commun")]
import fiches  # noqa: E402

CHARS = [{"name": "Elda", "lines": 40, "examples": ["Welcome to Mistvale."]},
         {"name": "Narrateur", "lines": 30, "examples": ["The fog rolled in."], "narrator": True},
         {"name": "Bram", "lines": 25, "examples": ["Aye."]}]


def test_demo_voix_differentes():
    cards = fiches.propose(CHARS)
    assert set(cards) == {"Elda", "Narrateur", "Bram"}
    assert cards["Narrateur"]["ton"].startswith("posé")
    assert fiches.look_alikes(cards, CHARS) == []


def test_proposition_ia_nettoyee_et_verrou():
    answer = json.dumps({"voices": [
        {"name": "elda", "genre": "Femme", "age": "agé", "timbre": "medium", "ton": "douce, mystérieuse",
         "debit": "lent", "description": "Voix douce de vieille gardienne."},
        {"name": "Bram", "genre": "robot", "age": "adulte", "timbre": "grave", "ton": "bourru", "debit": "vite"}]})
    locked = {"Narrateur": dict(fiches.empty("Narrateur", True), ton="mon ton", verrouille=True)}
    cards = fiches.propose(CHARS, "Conte maritime.", locked, ask=lambda s, u: answer)
    assert cards["Elda"]["genre"] == "femme" and cards["Elda"]["age"] == "âgé" and cards["Elda"]["timbre"] == "médium"
    assert cards["Bram"]["genre"] == "neutre"  # valeur inconnue → valeur de départ
    assert cards["Narrateur"]["ton"] == "mon ton"  # verrouillée : jamais changée


def test_demande_libre():
    cards = fiches.propose(CHARS)
    ans = json.dumps({"name": "Bram", "genre": "homme", "age": "âgé", "timbre": "grave", "ton": "bourru, rauque",
                      "debit": "lent", "description": "Vieux marin bourru.", "reply": "Bram a maintenant une voix de vieux marin."})
    name, cards2, reply = fiches.apply_answer(ans, CHARS, cards)
    assert name == "Bram" and cards2["Bram"]["source"] == "décrite par toi" and "marin" in reply
    # demande sans nom : le personnage ouvert à l'écran
    name, _, _ = fiches.apply_answer(json.dumps({"name": None, "ton": "joyeux"}), CHARS, cards, selected="Elda")
    assert name == "Elda"
    name, _, reply = fiches.apply_answer(json.dumps({"name": None}), CHARS, cards)
    assert name is None and "personnage" in reply


def test_regle_pas_de_personne_reelle():
    assert "real person" in fiches.PROPOSE_SYSTEM and "real person" in fiches.ASK_SYSTEM


def test_confusion_detectee():
    cards = {n: dict(fiches.empty(n), genre="femme", age="adulte", timbre="médium") for n in ("Elda", "Bram")}
    assert fiches.look_alikes(cards, CHARS) == [("Elda", "Bram")]
