import os, sys, tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [BASE, os.path.join(BASE, "commun")]
import personnages  # noqa: E402

SCRIPT = '''define e = Character("Elda", color="#f2c46d")
define n = Character(None, what_italic=True)
define b = Character(_("Bram"))
define p = Character("[player_name]")

label start:
    n "The fog rolled in from the sea, thick and silver."
    "Somewhere, a light was turning."
    e happy "Welcome to Mistvale, traveler. You picked a strange night."
    b "Aye, a strange night indeed, stranger."
    "Lise" "Look, the lighthouse is shining again!"
    p "Who am I, really?"
    menu:
        e "So, where will you go?"
        "Go to the lighthouse":
            jump lighthouse
    $ renpy.quit()
'''


def _game(script):
    root = tempfile.mkdtemp()
    os.makedirs(os.path.join(root, "game"))
    with open(os.path.join(root, "game", "script.rpy"), "w", encoding="utf-8") as f:
        f.write(script)
    return root


def test_qui_parle():
    lines = personnages.extract(_game(SCRIPT))
    got = [(ln["name"], ln["text"][:12]) for ln in lines]
    assert got == [("Narrateur", "The fog roll"), ("Narrateur", "Somewhere, a"), ("Elda", "Welcome to M"),
                   ("Bram", "Aye, a stran"), ("Lise", "Look, the li"), ("p", "Who am I, re"), ("Elda", "So, where wi")]
    assert all(ln["kind"] == "dialogue" for ln in lines)  # le choix « Go to the lighthouse » n'est dit par personne


def test_resume_et_type_de_jeu():
    lines = personnages.extract(_game(SCRIPT))
    s = personnages.summary(lines)
    assert [c["name"] for c in s][:2] == ["Elda", "Narrateur"]
    assert s[1]["narrator"] and s[0]["lines"] == 2
    assert personnages.game_kind(lines) == "dialogues"
    texte = personnages.extract(_game('label start:\n    "Il était une fois un phare."\n    "Et un brouillard."\n'))
    assert personnages.game_kind(texte) == "textuel"


def test_demo_mistvale():
    lines = personnages.extract(os.path.join(BASE, "demo", "Mistvale"))
    names = {c["name"]: c["lines"] for c in personnages.summary(lines)}
    assert set(names) == {"Elda", "Narrateur"} and names["Elda"] > 10 and names["Narrateur"] > 5
