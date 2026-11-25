"""Mémoire de traduction : les phrases déjà traduites ET appliquées à un jeu sont retenues sur ce PC.

Quand une phrase identique revient (dans un autre jeu, ou après une mise à jour), TradUp la remet tout seul : sans IA
et sans coût. Quelques phrases proches sont aussi données à l'IA en exemple, pour qu'elle garde le même vocabulaire et
le même ton d'un jeu à l'autre. Plus on traduit, plus la mémoire est riche.

On retient des PHRASES ENTIÈRES (jamais des mots isolés : une langue ne se traduit pas mot à mot). Une mémoire par
langue de traduction. On ne retient jamais une ligne ignorée, « à vérifier » ou identique à l'original.
Tout reste dans un petit fichier de ce PC, jamais envoyé ailleurs : les textes appartiennent aux studios des jeux.
"""
import json, os, re, sqlite3, time
from collections import Counter
from contextlib import closing

FILE = "memoire-traduction.sqlite"
MAX_LEN = 2000       # au-delà : un texte trop long pour être une « phrase » qui revient
MAX_GAMES = 8        # noms de jeux gardés par phrase (affichage « vu dans »)
LANG = re.compile(r"[a-z]{2,3}(-[A-Za-z]{2,4})?$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS mem (
  tgt TEXT NOT NULL, source TEXT NOT NULL, target TEXT NOT NULL,
  games TEXT NOT NULL DEFAULT '[]', uses INTEGER NOT NULL DEFAULT 1, updated REAL NOT NULL,
  PRIMARY KEY (tgt, source));
CREATE VIRTUAL TABLE IF NOT EXISTS mem_fts USING fts5(source, content='mem', content_rowid='rowid');
CREATE TRIGGER IF NOT EXISTS mem_ai AFTER INSERT ON mem BEGIN
  INSERT INTO mem_fts(rowid, source) VALUES (new.rowid, new.source); END;
CREATE TRIGGER IF NOT EXISTS mem_ad AFTER DELETE ON mem BEGIN
  INSERT INTO mem_fts(mem_fts, rowid, source) VALUES ('delete', old.rowid, old.source); END;
CREATE TRIGGER IF NOT EXISTS mem_au AFTER UPDATE OF source ON mem BEGIN
  INSERT INTO mem_fts(mem_fts, rowid, source) VALUES ('delete', old.rowid, old.source);
  INSERT INTO mem_fts(rowid, source) VALUES (new.rowid, new.source); END;
"""

# Mots trop courants pour dire de quoi parle une phrase (choix des exemples donnés à l'IA)
WORD = re.compile(r"[^\W\d_]{4,}")
COMMON = set("""that this with have from your what they there would could should about been were when will them then
than just like into some more over only also very here know want need going make take come back well yeah okay right
their these those where which while after before again never always really maybe something nothing anything everything
someone thing things good great much many still even because does done dont cant wont didnt isnt youre thats""".split())


def _connect(path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    db.executescript(SCHEMA)
    return db


def _lang(tgt):
    tgt = str(tgt or "")
    if not LANG.match(tgt):
        raise ValueError("langue inconnue : " + tgt[:20])
    return tgt


def _texts(items):
    return [s for s in (items or []) if isinstance(s, str) and s.strip() and len(s) <= MAX_LEN]


def _games(raw):
    try:
        g = json.loads(raw)
        return [str(x) for x in g] if isinstance(g, list) else []
    except ValueError:
        return []


def _worth(source, target):
    """Une paire vaut-elle d'être retenue ?"""
    if not isinstance(source, str) or not isinstance(target, str):
        return False
    s, t = source.strip(), target.strip()
    return bool(s and t) and s != t and len(source) <= MAX_LEN and len(target) <= MAX_LEN * 2


# ------------------------------------------------------------------ apprendre
def learn(path, tgt, pairs, game=""):
    """Retient des phrases validées (source, traduction). Renvoie {"added": n, "updated": n}."""
    tgt, now = _lang(tgt), time.time()
    game = str(game or "").strip()[:80]
    added = updated = 0
    with closing(_connect(path)) as db, db:
        for pair in pairs or []:
            if not isinstance(pair, (list, tuple)) or len(pair) != 2 or not _worth(*pair):
                continue
            s, t = pair
            row = db.execute("SELECT target, games, uses FROM mem WHERE tgt=? AND source=?", (tgt, s)).fetchone()
            if row is None:
                db.execute("INSERT INTO mem(tgt, source, target, games, uses, updated) VALUES (?,?,?,?,1,?)",
                           (tgt, s, t, json.dumps([game] if game else [], ensure_ascii=False), now))
                added += 1
                continue
            games, uses = _games(row[1]), row[2]
            new_game = bool(game) and game not in games
            if new_game:  # « uses » = nombre de jeux différents où la phrase a été appliquée
                games, uses = (games + [game])[-MAX_GAMES:], uses + 1
            if row[0] != t or new_game:
                db.execute("UPDATE mem SET target=?, games=?, uses=?, updated=? WHERE tgt=? AND source=?",
                           (t, json.dumps(games, ensure_ascii=False), uses, now, tgt, s))
                updated += row[0] != t
    return {"added": added, "updated": updated}


# ------------------------------------------------------------------ reprendre
def lookup(path, tgt, sources):
    """Traductions déjà connues pour ces phrases (identiques au caractère près) : {source: traduction}."""
    tgt, want = _lang(tgt), list(dict.fromkeys(_texts(sources)))
    out = {}
    if not want or not os.path.exists(path):
        return out
    with closing(_connect(path)) as db:
        for k in range(0, len(want), 400):
            chunk = want[k:k + 400]
            q = "SELECT source, target FROM mem WHERE tgt=? AND source IN (%s)" % ",".join("?" * len(chunk))
            out.update(db.execute(q, [tgt] + chunk).fetchall())
    return out


def examples(path, tgt, sources, limit=12, has_codes=None):
    """Phrases déjà validées qui parlent des mêmes choses que « sources » : des exemples pour l'IA (vocabulaire, ton)."""
    tgt = _lang(tgt)
    if not os.path.exists(path):
        return []
    texts = _texts(sources)
    words = Counter(w.lower() for s in texts for w in WORD.findall(s) if w.lower() not in COMMON)
    terms = [w for w, _ in words.most_common(40)]
    if not terms:
        return []
    query = " OR ".join('"%s"' % w for w in terms)  # mots faits uniquement de lettres : rien à échapper
    skip = set(texts)
    with closing(_connect(path)) as db:
        rows = db.execute("SELECT m.source, m.target FROM mem_fts JOIN mem m ON m.rowid = mem_fts.rowid "
                          "WHERE mem_fts MATCH ? AND m.tgt = ? ORDER BY bm25(mem_fts) LIMIT ?",
                          (query, tgt, int(limit) * 6)).fetchall()
    out = []
    for s, t in rows:
        if s in skip or len(s) > 160 or len(t) > 240 or (has_codes and has_codes(s)):
            continue
        out.append((s, t))
        if len(out) >= limit:
            break
    return out


# ------------------------------------------------------------------ consulter et corriger (« Ma mémoire »)
def stats(path):
    """Nombre de phrases retenues par langue : {"fr": 1234, …}."""
    if not os.path.exists(path):
        return {}
    with closing(_connect(path)) as db:
        return dict(db.execute("SELECT tgt, COUNT(*) FROM mem GROUP BY tgt").fetchall())


def _where(tgt, query):
    where, args = "tgt=?", [_lang(tgt)]
    q = str(query or "").strip()[:200]
    if q:
        like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        where += " AND (source LIKE ? ESCAPE '\\' OR target LIKE ? ESCAPE '\\')"
        args += [like, like]
    return where, args


def search(path, tgt, query="", offset=0, limit=100):
    """Phrases retenues (les plus récentes d'abord), filtrées par un mot de l'original ou de la traduction."""
    where, args = _where(tgt, query)
    if not os.path.exists(path):
        return {"total": 0, "rows": []}
    limit, offset = max(1, min(int(limit), 500)), max(0, int(offset))
    with closing(_connect(path)) as db:
        total = db.execute(f"SELECT COUNT(*) FROM mem WHERE {where}", args).fetchone()[0]
        rows = db.execute(f"SELECT source, target, games, uses FROM mem WHERE {where} ORDER BY updated DESC "
                          "LIMIT ? OFFSET ?", args + [limit, offset]).fetchall()
    return {"total": total, "rows": [{"source": s, "target": t, "games": _games(g), "uses": u} for s, t, g, u in rows]}


def edit(path, tgt, source, target):
    """Corrige la traduction retenue d'une phrase."""
    tgt = _lang(tgt)
    if not isinstance(source, str) or not isinstance(target, str) or not target.strip() or len(target) > MAX_LEN * 2:
        raise ValueError("traduction vide ou trop longue")
    with closing(_connect(path)) as db, db:
        n = db.execute("UPDATE mem SET target=?, updated=? WHERE tgt=? AND source=?", (target, time.time(), tgt, source)).rowcount
    return n


def _undo_path(path):
    return path + ".annuler.json"


def delete(path, tgt, query="", sources=None):
    """Supprime les phrases trouvées par « query » (toutes si vide), ou la liste « sources ».
    Garde de quoi annuler la dernière suppression. Renvoie le nombre de phrases supprimées."""
    if not os.path.exists(path):
        return 0
    with closing(_connect(path)) as db, db:
        if sources is not None:
            tgt, rows, wanted = _lang(tgt), [], _texts(sources)
            for k in range(0, len(wanted), 400):
                chunk = wanted[k:k + 400]
                cond = "tgt=? AND source IN (%s)" % ",".join("?" * len(chunk))
                rows += db.execute(f"SELECT tgt, source, target, games, uses, updated FROM mem WHERE {cond}", [tgt] + chunk).fetchall()
                db.execute(f"DELETE FROM mem WHERE {cond}", [tgt] + chunk)
        else:
            where, args = _where(tgt, query)
            rows = db.execute(f"SELECT tgt, source, target, games, uses, updated FROM mem WHERE {where}", args).fetchall()
            db.execute(f"DELETE FROM mem WHERE {where}", args)
    tmp = _undo_path(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False)
    os.replace(tmp, _undo_path(path))
    return len(rows)


def can_undo(path):
    return os.path.exists(_undo_path(path))


def undo(path):
    """Remet les phrases de la dernière suppression. Renvoie leur nombre."""
    p = _undo_path(path)
    if not os.path.exists(p):
        return 0
    rows = json.load(open(p, encoding="utf-8"))
    good = [r for r in rows if isinstance(r, list) and len(r) == 6 and LANG.match(str(r[0])) and _worth(r[1], r[2])]
    with closing(_connect(path)) as db, db:
        db.executemany("INSERT OR IGNORE INTO mem(tgt, source, target, games, uses, updated) VALUES (?,?,?,?,?,?)",
                       [(r[0], r[1], r[2], str(r[3]), int(r[4]), float(r[5])) for r in good])
    os.remove(p)
    return len(good)
