"""Lexique automatique : repérer les noms et termes qui reviennent dans un jeu, puis demander à l'IA comment
les écrire toujours pareil en français (personnages, lieux, races, objets…).

Le repérage se fait sur ce PC (aucune IA) ; seule la liste des termes trouvés, avec une phrase d'exemple chacun,
est envoyée à l'IA choisie.
"""
import re
from collections import Counter

from protect import RX as CODES

# Mots anglais courants qui prennent une majuscule sans être des noms du jeu
COMMON = set("""i i'm i'll i've i'd you we he she it they me my your our his her their this that these those there here
the a an and or but so if then when what why who how where which oh ah eh uh um hmm hey hi hello yes yeah yep no nope
okay ok well now just maybe please thanks thank sorry wait look come go let let's don't can't won't isn't it's that's
what's there's here's you're we're they're i'm well alright sure really right good great nice fine wow huh mr mrs ms
sir madam lady lord miss dear god damn hell shit fuck haha hehe ahah mm mmm hmph ugh tsk not all any some every one
two three four five six seven eight nine ten first second next last day night morning today tomorrow yesterday
monday tuesday wednesday thursday friday saturday sunday january february march april may june july august
september october november december english french is are was were be been do does did have has had will would
could should might must shall can also only even still yet too very more most much many few other another such
same new old big small little long short high low left right up down in on at to of for with from by as about into
over under after before again never always sometimes often here there everyone everything nothing something someone
anyone anything nobody somebody press click hold use""".split())
COMMON |= set("am being let's i'd we'll you'll it'd anyways anyway probably actually see tell give take make get "
               "stick stop try keep open close start end".split())
WORDPART = r"[A-Z][A-Za-z'’-]*"
# Mots à majuscule qui se suivent sur la même ligne (« Lady Eydis », « Frozen Land of the Spirits »)
NAME = re.compile(WORDPART + r"(?: (?:of the |of |the )?" + WORDPART + r")*")
SENTENCE_START = re.compile(r"(^|[.!?…:\"“]\s*|\n\s*|^\s*[-*•]\s*)$")


def _clean(term):
    term = re.sub(r"['’]s$", "", term.strip(" '’-"))  # « Ara's » → « Ara »
    return term


def _common(word):
    w = word.lower()
    return w in COMMON or re.split(r"['’]", w)[0] in COMMON  # « You'll », « We'd »…


def candidates(sources, limit=60):
    """Termes qui reviennent (noms propres surtout), triés par fréquence, avec une phrase d'exemple chacun."""
    count, inside, example = Counter(), Counter(), {}
    lower = Counter()
    for src in dict.fromkeys(sources):  # un texte répété 100 fois (menu…) ne compte qu'une fois
        text = CODES.sub("\n", src or "")  # un code (retour à la ligne, {wc}…) coupe la phrase
        for w in re.findall(r"\b[a-z][a-z'’-]+\b", text):
            lower[w] += 1
        for m in NAME.finditer(text):
            term = _clean(m.group(0))
            words = term.split()
            if not term or all(_common(w) for w in words) or any(c.isdigit() for c in term):
                continue
            while len(words) > 1 and _common(words[0]):  # « Hey Ara » → « Ara »
                words = words[1:]
            while len(words) > 1 and _common(words[-1]):  # « Sadly I » → « Sadly »
                words = words[:-1]
            term = " ".join(words)
            if len(words) == 1 and (len(term) < 3 or term.isupper()):  # « Ok », cris en majuscules (« AHHH »)
                continue
            if re.match(r"^[A-Za-z]{1,2}-", term) and _common(term.split("-", 1)[1]):  # bégaiement : « I-I'm », « D-Don't »
                continue
            count[term] += 1
            # majuscule au milieu d'une phrase : c'est un vrai nom (en début de phrase, tous les mots en ont une)
            inside[term] += not SENTENCE_START.search(text[:m.start()])
            example.setdefault(term, re.sub(r"\s+", " ", text).strip()[:140])
    out = []
    for term, n in count.most_common():
        words = term.split()
        if len(words) == 1:
            # un nom : jamais écrit en minuscules dans le jeu, ou bien avec une majuscule même au milieu des phrases
            low = lower[term.lower()]
            keep = n >= 2 and (low == 0 or inside[term] >= 2 and low <= inside[term])
        else:
            keep = n >= 2 and len(words) <= 5
        if keep:
            out.append({"term": term, "count": n, "example": example[term]})
        if len(out) >= limit:
            break
    return out


import textes_ia  # prompts (brouillés dans la version vendue)
VO_RULE = textes_ia.GLOSSARY_VO  # texte déplacé dans textes_ia.py pour pouvoir être brouillé


def build_request(cands, src_name, tgt_name, context, names=(), vo=False):
    """Consignes et question envoyées à l'IA pour fabriquer le lexique (names : personnages déclarés par le jeu ;
    vo : édition pro, garder en version originale noms, titres, compétences et créatures — choix d'un vrai
    traducteur pour Adventurer Trainer, 16/11/2026)."""
    import json
    T = textes_ia
    system = T.GLOSSARY_SYSTEM.format(src=src_name, tgt=tgt_name)
    user = (T.GLOSSARY_HEAD.format(src=src_name)
            + (T.GLOSSARY_NAMES.format(names=", ".join(names[:80])) if names else "")
            + (T.GLOSSARY_VO.format(tgt=tgt_name) if vo else T.GLOSSARY_DEFAULT.format(tgt=tgt_name))
            + T.GLOSSARY_SKIP
            + (T.GLOSSARY_CONTEXT.format(context=context.strip()) if (context or "").strip() else "")
            + T.GLOSSARY_ANSWER  # accolades littérales : pas de .format()
            + json.dumps(cands, ensure_ascii=False))
    return system, user


def keep_names(text, proposed, names):
    """Les personnages déclarés par le jeu gardent leur nom : « Darkness = Ténèbres » devient « Darkness = Darkness »,
    dans la proposition de l'IA comme dans le lexique déjà là. Renvoie (lexique, proposition, noms remis tels quels)."""
    keep = {n.lower(): n for n in names}
    fixed = []

    def fix(line):
        if "=" not in line:
            return line
        term, tr = (x.strip() for x in line.split("=", 1))
        n = keep.get(term.lower())
        if n and tr != term:
            fixed.append(f"{term} (pas « {tr} »)")
            return f"{term} = {term}"
        return line
    text = "\n".join(fix(l) for l in (text or "").splitlines())
    proposed = [fix(l) for l in proposed]
    return text, proposed, list(dict.fromkeys(fixed))


def merge(existing, proposed):
    """Ajoute au lexique les lignes « Terme = Traduction » proposées dont le terme n'y est pas déjà."""
    have = {l.split("=", 1)[0].strip().lower() for l in (existing or "").splitlines() if "=" in l}
    added = []
    for line in proposed:
        if "=" not in line:
            continue
        term, fr = (x.strip() for x in line.split("=", 1))
        if term and fr and term.lower() not in have:
            have.add(term.lower())
            added.append(f"{term} = {fr}")
    text = (existing or "").rstrip()
    return (text + "\n" if text else "") + "\n".join(added), added
