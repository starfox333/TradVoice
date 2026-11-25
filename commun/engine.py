"""Moteurs de traduction : l'IA intégrée (llama.cpp, voir localai.py) et un mode démo pour tester l'interface."""
import json, os, re

import localai
import textes_ia  # prompts (chiffrés dans la version vendue)

LANG_NAMES = {"fr": "French", "en": "English", "de": "German", "es": "Spanish", "it": "Italian",
              "pt": "Brazilian Portuguese", "nl": "Dutch", "pl": "Polish", "ru": "Russian", "uk": "Ukrainian",
              "ja": "Japanese", "zh": "Simplified Chinese", "ko": "Korean", "auto": "the source language"}



# Ce qu'on demande à l'IA pour un paquet : traduire (par défaut) ou raccourcir des traductions trop longues
TRANSLATE_TASK = "Translate these lines:\n"
SHORTEN_TASK = textes_ia.SHORTEN_TASK


def build_prompt(src, tgt, glossary, context, examples=""):
    s, t = LANG_NAMES.get(src, src), LANG_NAMES.get(tgt, tgt)
    if src == "zh":  # un jeu peut être en chinois simplifié OU traditionnel : l'IA lit les deux
        s = "Chinese"
    rules = [textes_ia.RULE_ROLE.format(s=s, t=t)] + list(textes_ia.RULES_FIXED)
    if glossary.strip():
        rules.append(textes_ia.GLOSSARY_INTRO + glossary.strip())
    if context.strip():
        rules.append(textes_ia.CONTEXT_INTRO + context.strip())
    if examples.strip():  # mémoire de traduction de l'utilisateur (identiques pour tout un lancement : mises en cache)
        rules.append(textes_ia.EXAMPLES_INTRO + examples.strip())
    return "\n".join(rules)


# ------------------------------------------------------------------ IA intégrée (llama.cpp, voir localai.py)
# Nom historique gardé : app.py et glossary affichent ces erreurs telles quelles (messages déjà en français clair).
ClaudeError = localai.LocalAIError


# Mémoire de travail de l'IA (en jetons), fixée au lancement du serveur : voir localai.CTX.
CTX = localai.CTX


def _tokens(text):
    return len(text) / 3.2  # estimation prudente (anglais / français)


# Phrases presque identiques déjà validées (proches.py) : données dans le message du paquet, pas dans les consignes
# générales, qui restent les mêmes pendant tout un lancement (mises en cache).
HINTS_INTRO = textes_ia.HINTS_INTRO


def translate_batch(lines, src, tgt, model, glossary="", context="", previous=None, task=TRANSLATE_TASK, examples="",
                    hints=""):
    """Traduit une liste de lignes (déjà protégées). Renvoie une liste de même longueur."""
    if model == "demo":
        return [demo_shorten(l) if isinstance(l, dict) else demo(l, tgt) for l in lines]
    system = build_prompt(src, tgt, glossary, context, examples)
    user = HINTS_INTRO + hints.strip() + "\n\n" if hints.strip() else ""
    if previous:
        user += "Previous lines (context only, do not translate): " + json.dumps(previous, ensure_ascii=False) + "\n\n"
    user += task + json.dumps(lines, ensure_ascii=False)
    # paquet trop long pour la mémoire de travail (question + réponse) : on le coupe en deux
    need = _tokens(system) + _tokens(user) + sum(_tokens(l if isinstance(l, str) else l["current"]) * 1.4 + 8 for l in lines) + 150
    if need > CTX * 0.9 and len(lines) > 1:
        h = len(lines) // 2
        return (translate_batch(lines[:h], src, tgt, model, glossary, context, previous, task, examples, hints)
                + translate_batch(lines[h:], src, tgt, model, glossary, context, (previous or [])[-2:] + lines[max(0, h - 2):h], task, examples, hints))
    content = localai.chat(system, user)
    out = parse_list(content, len(lines))
    if out is not None:
        return out
    if len(lines) == 1:
        m = re.search(r'"t"\s*:\s*\[\s*"(.*)"\s*\]', content, re.S)
        if m:
            try:
                return [json.loads('"' + m.group(1) + '"')]
            except ValueError:
                return [m.group(1).replace('\\n', '\n').replace('\\"', '"')]
        return [""]  # réponse illisible : la ligne restera « à vérifier », la traduction continue
    # Réponse mal formée : on retraduit ligne par ligne
    return [translate_batch([l], src, tgt, model, glossary, context, previous, task, examples, hints)[0] for l in lines]


def parse_list(content, n):
    """Lit la liste de traductions renvoyée par l'IA, même s'il y a du texte en trop autour
    (deux réponses collées, balises ```json, explication…). Renvoie None si c'est impossible."""
    s = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", content or "")
    dec = json.JSONDecoder()
    starts = [0] + [m.start() for m in re.finditer(r"[\[{]", s)][:30]
    for st in starts:
        try:
            obj, _ = dec.raw_decode(s[st:].lstrip())
        except ValueError:
            continue
        if isinstance(obj, dict):
            obj = obj["t"] if "t" in obj else next((v for v in obj.values() if isinstance(v, list)), None)
        if isinstance(obj, str) and n == 1:
            obj = [obj]
        if isinstance(obj, list) and len(obj) == n and all(isinstance(x, str) for x in obj):
            return obj
    return None


# ------------------------------------------------------------------ question libre (ex. lexique automatique)
def parse_any(content):
    """Liste de textes renvoyée par l'IA, quelle que soit sa longueur (lexique…)."""
    if isinstance(content, dict):
        content = json.dumps(content, ensure_ascii=False)
    s = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", content or "")
    for st in [0] + [m.start() for m in re.finditer(r"[\[{]", s)][:30]:
        try:
            obj, _ = json.JSONDecoder().raw_decode(s[st:].lstrip())
        except ValueError:
            continue
        if isinstance(obj, dict):
            obj = obj["t"] if "t" in obj else next((v for v in obj.values() if isinstance(v, list)), None)
        if isinstance(obj, list):
            return [x for x in obj if isinstance(x, str)]
    return []


def ask_list(user, system, model, cfg):
    """Pose une question dont la réponse est une liste de textes. Renvoie (liste, coût en $ : toujours 0, IA locale).
    `cfg` n'est plus utilisé (plus de clé) ; gardé pour ne pas changer les appels."""
    if model == "demo":
        return [], 0.0
    return parse_any(localai.chat(system, user)), 0.0


_DEMO = None


def _demo_table():
    """Traductions toutes prêtes du jeu de démonstration (demo/traductions.json), pour essayer sans IA."""
    global _DEMO
    if _DEMO is None:
        _DEMO = {"lines": {}, "short": {}, "terms": {}}
        try:
            from protect import protect
            data = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "demo", "traductions.json"),
                                  encoding="utf-8"))
            for src, fr in data.get("lignes", []):
                _DEMO["lines"][protect(src)[0]] = protect(fr)[0]
            for src, fr in data.get("raccourcis", []):
                _DEMO["short"][protect(src)[0]] = protect(fr)[0]
            _DEMO["terms"] = data.get("lexique", {})
        except Exception:
            pass
    return _DEMO


def demo(line, tgt):
    """Mode Démo (sans IA) : la vraie traduction pour le jeu de démonstration, sinon une ligne marquée [FR]."""
    t = _demo_table()["lines"].get(line) if tgt == "fr" else None
    return t if t is not None else f"[{tgt.upper()}] " + line


def demo_shorten(item):
    """Mode Démo : version courte toute prête, sinon la phrase coupée proprement."""
    t = _demo_table()["short"].get(item["source"])
    if t is not None:
        return t
    cur, mx = item["current"], max(1, item["max"])
    return cur if len(cur) <= mx else cur[:mx].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def demo_term(term):
    return _demo_table()["terms"].get(term, term)
