"""Mode « jeu complet » : textes répartis dans de nombreux fichiers (ex. dialogues Godot en .cfg).

On repère des valeurs "clé": "texte" pour une liste de clés connues, on les présente dans un seul
tableau, puis on les réécrit à leur place dans le jeu, avec sauvegarde des fichiers d'origine.
"""
import os, re, json, shutil, hashlib, time

# Clés qui contiennent du texte affiché au joueur (les noms de personnages restent tels quels)
TEXT_KEYS = ("dialogue", "text", "line", "subtitle", "description", "act_name", "act_description",
             "level_name", "title", "subtitle_text", "tooltip", "message")
STR = re.compile(r'"(\w+)"(\s*:\s*)"((?:[^"\\]|\\.)*)"')
BACKUP_DIR = "_sauvegarde_traduction"
SKIP = re.compile(r"\.bak|_sauvegarde|[\\/]mods[\\/]|[\\/]\.godot[\\/]", re.I)
LETTERS = re.compile(r"[A-Za-z]")

# Avertissement « usage personnel » posé dans le dossier d'un jeu traduit (TradUp Gaming, idée de l'utilisateur 18/11) :
# si quelqu'un zippe le jeu traduit pour le diffuser, l'avertissement part avec. « Remettre l'original » l'enlève.
NOTICE_NAME = "TradUp_LISEZ-MOI.txt"
NOTICE_TEXT = """TRADUCTION FAITE AVEC TRADUP GAMING
===================================
Ce jeu a été traduit avec TradUp Gaming (Gelatine Studio), pour un usage personnel.
Le jeu et ses textes appartiennent à son studio : ne diffuse pas ces fichiers traduits
(textes, images) sans l'accord du studio.
Gelatine Studio n'est pas responsable de la diffusion de cette traduction : la personne
qui la diffuse en répond seule.

Remettre le jeu d'origine : bouton « Remettre l'original » dans TradUp.
Traduire tes propres jeux : https://gelatine-studio.itch.io/tradup

TRANSLATED WITH TRADUP GAMING
=============================
This game was translated with TradUp Gaming (Gelatine Studio), for personal use only.
The game and its text belong to its studio: do not distribute these translated files
(text, images) without the studio's permission.
Gelatine Studio is not responsible for any distribution of this translation: whoever
distributes it is solely responsible.

Restore the original game: "Restore original" button in TradUp.
Translate your own games: https://gelatine-studio.itch.io/tradup
"""
# même avertissement, en commentaire en haut des fichiers de traduction Ren'Py (invisible dans le jeu)
NOTICE_RPY = ("# Traduit avec TradUp Gaming pour un usage personnel : ne diffuse pas ce fichier sans l'accord du studio\n"
              "# du jeu. Gelatine Studio n'est pas responsable de sa diffusion (voir TradUp_LISEZ-MOI.txt).\n"
              "# Translated with TradUp Gaming for personal use only: do not distribute this file without the game\n"
              "# studio's permission. Gelatine Studio is not responsible for its distribution.\n")


def write_notice(root):
    """Pose TradUp_LISEZ-MOI.txt dans le dossier du jeu (Bloc-notes : UTF-8 avec BOM, fins de ligne Windows)."""
    p = inside(root, NOTICE_NAME)
    tmp = p + ".tmp_trad"
    with open(tmp, "w", encoding="utf-8-sig", newline="\r\n") as f:
        f.write(NOTICE_TEXT)
    os.replace(tmp, p)
    return p


def remove_notice(root):
    """Enlève l'avertissement, seulement s'il vient bien de TradUp (première ligne reconnue)."""
    p = os.path.join(root, NOTICE_NAME)
    try:
        if os.path.isfile(p) and not os.path.islink(p):
            with open(p, encoding="utf-8-sig") as f:
                first = f.readline().strip()
            if first == NOTICE_TEXT.split("\n", 1)[0]:
                os.remove(p)
                return True
    except OSError:
        pass
    return False


def _unescape(v):
    try:
        return json.loads('"' + v + '"')
    except Exception:
        return v


def _escape(s):
    return json.dumps(s, ensure_ascii=False)[1:-1]


CFG_EXT = (".cfg", ".tres", ".tscn")


def scan_cfg(root, exts=CFG_EXT):
    """Liste des fichiers du jeu contenant des textes (clé connue + lettres)."""
    found = []
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if not SKIP.search(os.sep + d + os.sep)]
        for f in fns:
            p = os.path.join(dp, f)
            if not f.lower().endswith(exts) or SKIP.search(p) or os.path.getsize(p) > 5_000_000:
                continue
            try:
                t = open(p, encoding="utf-8").read()
            except (UnicodeDecodeError, OSError):
                continue
            n = sum(1 for k, _, v in STR.findall(t) if k in TEXT_KEYS and LETTERS.search(v))
            if n:
                found.append((os.path.relpath(p, root), n))
    return found


def inside(root, rel):
    """Chemin d'un fichier du jeu, seulement s'il est vraiment DANS le dossier du jeu (sécurité : un projet ou une
    sauvegarde piégés ne peuvent pas écrire ailleurs, ni avec « ..\\ », ni par un dossier-raccourci)."""
    base = os.path.realpath(root)
    p = os.path.realpath(os.path.join(root, rel))
    if os.path.isabs(rel) or os.path.commonpath([base, p]) != base or p == base:
        raise RuntimeError(f"Chemin refusé (hors du dossier du jeu) : {rel}")
    return os.path.join(root, os.path.relpath(p, base))


def _manifest(root):
    try:
        return json.load(open(os.path.join(root, BACKUP_DIR, "manifest.json"), encoding="utf-8"))
    except Exception:
        return {}


def original_path(root, rel, man=None):
    """Fichier d'origine (anglais) : la sauvegarde si le fichier du jeu porte encore notre traduction.
    Si le jeu a été mis à jour depuis, son fichier est le nouvel original."""
    man = _manifest(root) if man is None else man
    cur, bak = os.path.join(root, rel), os.path.join(root, BACKUP_DIR, rel)
    patched = (man.get(rel) or {}).get("patched")
    if patched and os.path.exists(bak) and os.path.exists(cur) and _sha(cur) == patched:
        return bak
    return cur


def extract(root, files):
    entries = []
    man = _manifest(root)
    for rel in files:
        t = open(original_path(root, rel, man), encoding="utf-8").read()
        for k, (key, _, v) in enumerate(STR.findall(t)):
            if key in TEXT_KEYS and LETTERS.search(v):
                entries.append({"key": f"{rel}|{k}", "source": _unescape(v), "target": "", "skip": False,
                                "field": key})
    return entries


def _sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def apply(root, entries, log=print):
    """Réécrit les traductions dans le jeu. Sauvegarde chaque fichier une seule fois avant de le modifier."""
    bdir = os.path.join(root, BACKUP_DIR)
    mpath = os.path.join(bdir, "manifest.json")
    man = json.load(open(mpath, encoding="utf-8")) if os.path.exists(mpath) else {}
    by_file = {}
    for e in entries:
        if e.get("target") and not e.get("skip"):
            rel, idx = e["key"].rsplit("|", 1)
            by_file.setdefault(rel, {})[int(idx)] = e["target"]
    changed = 0
    for rel, tr in by_file.items():
        if not rel.lower().endswith(CFG_EXT):
            raise RuntimeError(f"Fichier refusé (pas un fichier de texte du jeu) : {rel}")
        cur = inside(root, rel)
        bak = inside(root, os.path.join(BACKUP_DIR, rel))
        if not os.path.exists(bak):  # première fois : on garde l'original anglais
            os.makedirs(os.path.dirname(bak), exist_ok=True)
            shutil.copy2(cur, bak)
            man[rel] = {"orig": _sha(bak)}
        elif _sha(cur) not in (man.get(rel, {}).get("orig"), man.get(rel, {}).get("patched")):
            shutil.copy2(cur, bak)  # le jeu a été mis à jour entre-temps : nouvel original
            man[rel] = {"orig": _sha(bak)}
        text = open(bak, encoding="utf-8", newline="").read()  # on repart toujours de l'original (fins de ligne gardées)
        count = [-1]

        def sub(m):
            count[0] += 1
            if count[0] in tr:
                return f'"{m.group(1)}"{m.group(2)}"{_escape(tr[count[0]])}"'
            return m.group(0)

        new = STR.sub(sub, text)
        tmp = cur + ".tmp_trad"
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            f.write(new)
        os.replace(tmp, cur)
        man[rel]["patched"] = _sha(cur)
        changed += 1
    os.makedirs(bdir, exist_ok=True)
    man["_date"] = time.strftime("%Y-%m-%d %H:%M")
    json.dump(man, open(mpath, "w", encoding="utf-8"), indent=1)
    log(f"{changed} fichier(s) traduits, originaux sauvegardés dans {BACKUP_DIR}")
    return changed


def restore(root):
    """Remet tous les fichiers d'origine et supprime la sauvegarde.
    Un fichier que le jeu a changé depuis notre traduction (mise à jour Steam, vérification d'intégrité) n'est PAS
    remplacé : remettre l'ancien original mélangerait deux versions du jeu (le jeu plante)."""
    bdir = os.path.join(root, BACKUP_DIR)
    remove_notice(root)  # avertissement « usage personnel » : pas un fichier du jeu, il part avec la traduction
    if not os.path.isdir(bdir):
        return 0
    man, n = _manifest(root), 0
    for dp, dns, fns in os.walk(bdir):
        if dp == bdir:
            dns[:] = [d for d in dns if d != "images_retouchees"]  # images retouchées : pas des fichiers du jeu
        for f in fns:
            if f in ("manifest.json", "unity_traductions.json", "unity_images.json") and dp == bdir:
                continue
            src = os.path.join(dp, f)
            if os.path.islink(src):
                continue  # raccourci glissé dans la sauvegarde : ignoré
            rel = os.path.relpath(src, bdir)
            dst = inside(root, rel)
            known = man.get(rel) if isinstance(man.get(rel), dict) else None
            if known and os.path.exists(dst) and _sha(dst) not in (known.get("orig"), known.get("patched")):
                continue  # le jeu a été mis à jour depuis : son fichier actuel est le bon
            shutil.copy2(src, dst)
            n += 1
    # fichiers AJOUTÉS par TradUp (ex. traduction Ren'Py) : supprimés. Seulement ceux de TradUp, dans le jeu.
    man = _manifest(root)
    for rel in man.get("_ajoutes", []):
        if not os.path.basename(rel).lower().startswith(("tradup_", "zz_tradup_")):
            continue
        p = inside(root, rel)
        if os.path.isfile(p):
            os.remove(p)
            n += 1
    # dossier de langue créé par TradUp (Ren'Py : game/tl/<langue>) : son fiche-langue et son drapeau, puis le dossier
    # s'il est vide (s'il contient autre chose, ce n'est plus seulement à TradUp : on le laisse)
    for rel in man.get("_ajoutes_tl", []):
        if os.path.basename(rel) in ("manifest.json", "flag.png") and rel.replace("\\", "/").split("/")[:2] == ["game", "tl"]:
            p = inside(root, rel)
            if os.path.isfile(p):
                os.remove(p)
    for rel in man.get("_dossiers_tl", []):
        p = inside(root, rel)
        if os.path.isdir(p) and not os.listdir(p):
            os.rmdir(p)
    shutil.rmtree(bdir)
    return n


def is_applied(root):
    return os.path.exists(os.path.join(root, BACKUP_DIR, "manifest.json"))
