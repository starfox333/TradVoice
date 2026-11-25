"""Phrases proches : reprendre la mémoire de traduction quand une phrase n'est PAS identique au caractère près.

Deux cas, cherchés seulement pour les lignes que memoire.lookup n'a pas trouvées :
- « chiffres » : la phrase ne diffère que par ses numéros (« Level 3 » / « Level 12 », « Boost II » / « Boost IV »).
  La traduction connue est reprise avec les nouveaux numéros, sans IA. Jamais pour une ligne avec des codes du jeu
  ({0}, %s, <b>…) : leurs chiffres ne doivent pas être touchés.
- « proche » : la phrase ressemble beaucoup à une phrase déjà validée (au moins 85 %). Rien n'est rempli : la paire
  connue est donnée à l'IA comme modèle à adapter, pour garder les mêmes mots d'un jeu à l'autre.
"""
import os
import re
from contextlib import closing
from difflib import SequenceMatcher

from memoire import COMMON, _connect, _lang, _texts

NEAR_MIN = 0.85      # ressemblance minimale pour « proche »
MAX_SOURCES = 5000   # lignes examinées au plus par appel
CANDIDATES = 30      # phrases de la mémoire comparées pour chaque ligne
NUMRX = re.compile(r"\d+(?:[.,]\d+)*|\b(?:II|III|IV|V|VI|VII|VIII|IX|X)\b")
WORDS = re.compile(r"[^\W\d_]{2,}")


def key(text):
    """La phrase sans ses numéros : « Level 3 » et « Level 12 » ont la même clé."""
    return NUMRX.sub("#", text)


def adapt(src, tgt, other):
    """Traduction « tgt » de « src », refaite pour « other » (mêmes mots, autres numéros). None si impossible."""
    if src == other:
        return tgt
    a, b, t = NUMRX.findall(src), NUMRX.findall(other), NUMRX.findall(tgt)
    if len(a) != len(b) or t != a:
        return None
    numbers = iter(b)
    return NUMRX.sub(lambda m: next(numbers), tgt)


def _query(text):
    """Recherche plein texte. Une phrase ressemblante à 85 % garde presque toujours au moins deux de ses quatre mots
    les plus longs : on cherche les phrases qui en contiennent une paire (bien plus rapide qu'un simple OR)."""
    words = list(dict.fromkeys(w.lower() for w in WORDS.findall(text)))
    rare = [w for w in words if len(w) >= 4 and w not in COMMON]
    chosen = ['"%s"' % w for w in sorted(rare or words, key=len, reverse=True)[:4]]  # lettres seules : rien à échapper
    if len(chosen) < 2:
        return " OR ".join(chosen)
    return " OR ".join("(%s AND %s)" % (a, b) for i, a in enumerate(chosen) for b in chosen[i + 1:])


def _ratio(matcher, text, least):
    """Ressemblance de 0 à 1 entre « text » et la ligne préparée dans « matcher » ;
    0 dès qu'un calcul rapide montre qu'elle restera sous « least »."""
    b = matcher.b
    if abs(len(text) - len(b)) > (1 - least) * (len(text) + len(b)):
        return 0.0  # longueurs trop différentes : la ressemblance ne peut pas atteindre « least »
    matcher.set_seq1(text.lower())
    if matcher.real_quick_ratio() < least or matcher.quick_ratio() < least:
        return 0.0
    return matcher.ratio()


def near(path, tgt, sources, min_ratio=NEAR_MIN, has_codes=None):
    """Pour chaque phrase sans traduction identique : la phrase connue la plus proche.
    Renvoie {source: {"kind": "chiffres" | "proche", "from": phrase connue, "target": traduction, "score": 0..1}}.
    Pour « chiffres », « target » est déjà refaite avec les numéros de la nouvelle phrase."""
    tgt = _lang(tgt)
    out = {}
    if not os.path.exists(path):
        return out
    want = list(dict.fromkeys(_texts(sources)))[:MAX_SOURCES]
    with closing(_connect(path)) as db:
        for src in want:
            query = _query(src)
            if not query:
                continue  # rien que des chiffres ou des codes
            rows = db.execute("SELECT m.source, m.target FROM mem_fts JOIN mem m ON m.rowid = mem_fts.rowid "
                              "WHERE mem_fts MATCH ? AND m.tgt = ? ORDER BY bm25(mem_fts) LIMIT ?",
                              (query, tgt, CANDIDATES)).fetchall()
            if any(s == src for s, _ in rows):
                continue  # déjà connue telle quelle : c'est le travail de memoire.lookup
            codes = bool(has_codes and has_codes(src))
            matcher = SequenceMatcher(None, "", src.lower(), autojunk=False)  # la ligne n'est préparée qu'une fois
            best = None
            for s, t in rows:
                if not codes and key(s) == key(src):
                    done = adapt(s, t, src)
                    if done is not None:
                        best = {"kind": "chiffres", "from": s, "target": done, "score": 1.0}
                        break
                r = _ratio(matcher, s, min_ratio)
                if r >= min_ratio and (best is None or r > best["score"]):
                    best = {"kind": "proche", "from": s, "target": t, "score": round(r, 3)}
            if best:
                out[src] = best
    return out
