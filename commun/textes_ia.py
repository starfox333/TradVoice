"""Textes envoyés à l'IA (prompts) : le vrai savoir-faire de TradUp, regroupé ici pour pouvoir être CHIFFRÉ dans la
version vendue (voir protection.py et outils/fabriquer.py).

En développement (lancé depuis les sources), ces constantes sont lisibles telles quelles.
À la fabrication, outils/fabriquer.py réécrit CE fichier dans le dossier de build : chaque texte y devient un bloc
chiffré rendu seulement en mémoire par protection.reveal(...). Le binaire livré ne contient donc pas ces textes en
clair (un simple listage des chaînes du .exe ne sort rien d'exploitable, rien à copier dans une IA).

Ne rien importer d'autre ici : ce module doit rester une simple liste de textes (le build le régénère entièrement).
"""

# --- prompt de traduction (build_prompt dans engine.py) -------------------------------------------------------------
# {s} = langue d'origine, {t} = langue cible (remplies à l'exécution)
RULE_ROLE = "You are an expert video game localizer. Translate from {s} into natural, idiomatic {t}."

RULES_FIXED = [
    "Keep the tone of each character: slang, humor, swearing and adult or sexual content must be translated "
    "faithfully, never censored or softened.",
    "Tokens like [T1], [T2] are code placeholders: copy each one exactly once, unchanged, at the right place.",
    "Keep proper names of characters and places unless the glossary says otherwise.",
    "Some items are isolated words or short labels with no sentence around them (menu entries, buttons, items, "
    "skills, stats, character or place names): translate them as short game UI labels, the way the official "
    "localized version of a game would; keep proper names, abbreviations (HP, MP, LV, EXP…), numbers and codes "
    "unchanged; never answer with an explanation, a question or several alternatives.",
    "Keep the structure of the original: put each [T] token (line breaks included) at the matching place, so that "
    "each line of your translation corresponds to the same line of the original, in the same order and with a "
    "similar length. Keep each line short enough for a game UI; do not add explanations.",
    'Answer ONLY with JSON: {"t": ["translation 1", "translation 2", ...]} with exactly as many items as the input, '
    "in the same order.",
]

GLOSSARY_INTRO = "Glossary (always use these translations):\n"
CONTEXT_INTRO = "About the game: "
EXAMPLES_INTRO = ("Translations already validated by the user in other games. They are examples, not lines to "
                  "translate: reuse their vocabulary and style when the same words or phrases appear.\n")

# --- raccourcir des traductions trop longues (engine.py) ------------------------------------------------------------
SHORTEN_TASK = ("Each item is a game line whose translation is too long for its text box: 'source' is the original, "
                "'current' its current translation, 'max' the maximum length in characters ([T1]-style tokens count as zero), "
                "and 'max_per_line' (when present) the maximum length of each line, in order. Rewrite 'current' in the same "
                "language so it is clearly shorter: keep the meaning, the tone and the character's voice, keep every [T] token "
                "exactly once AT THE SAME PLACE as in 'source' (line breaks included), so that each line of the result "
                "matches the same line of the original and stays within its limit. Drop filler words before dropping "
                "meaning. Answer ONLY with JSON {\"t\": [...]}: one shortened line per item, same order.\nItems:\n")

# --- exemples tirés de la mémoire de traduction (engine.py) ---------------------------------------------------------
HINTS_INTRO = ("Very similar sentences already validated by the user. When an item is almost the same as one of them, "
               "adapt that translation (same words and style) instead of translating from scratch:\n")

# --- aide à la relecture, clic droit (édition pro, app.py) ----------------------------------------------------------
REVIEW_SYSTEM = ("You help a human translator review video game translations. You never invent content, you keep "
                 "formatting tags like {i}…{/i}, [variables], %codes% and line breaks exactly as they are.")

REVIEW_TASKS = {
    "litteral": ("Give a LITERAL, word-for-word {tgt} translation of this {src} game line, only to check its exact "
                 "meaning. Answer with that literal translation only.\n\nLine: {source}"),
    "propositions": ("Give 3 different natural {tgt} translations of this {src} game line, one per line, without "
                     "numbering or comments.\nGame context: {context}\nGlossary (keep these names): {glossary}\n\n"
                     "Line: {source}\nCurrent translation: {target}"),
    "expliquer": ("Explain briefly in {ui} (3 to 5 short sentences) what this {src} game line really means: idioms, "
                  "slang, wordplay, tone, intention. Do not just translate it.\n\nLine: {source}"),
    "grammaire": ("Check this {tgt} translation of a game line: spelling, grammar, agreement, punctuation and typography "
                  "of {tgt}. Answer in {ui}: one problem per line starting with '- ', then a last line starting with "
                  "'FIX: ' followed by the corrected translation. If it is all correct, answer only 'FIX: ' and the "
                  "translation.\n\nOriginal ({src}): {source}\nTranslation: {target}"),
}

# --- fabrication du lexique (glossary.py) ---------------------------------------------------------------------------
# {src}/{tgt} = langues, {names} = personnages déclarés, {context} = contexte du jeu (remplis à l'exécution).
# GLOSSARY_ANSWER contient des accolades littérales {"t": …} : à concaténer, jamais passer à .format().
GLOSSARY_SYSTEM = ("You are an expert video game localizer preparing the glossary used to translate a game from {src} "
                   "into {tgt}, so that every recurring term is always written the same way.")
GLOSSARY_HEAD = ("Below are terms that recur in the game, each with its number of occurrences and one example line. "
                 "Build the glossary:\n- character names: keep them unchanged (e.g. \"Ara = Ara\"), including honorifics "
                 "like -chan, EVEN when the name is an ordinary {src} word (a character called \"Darkness\" stays "
                 "\"Darkness = Darkness\");\n")
GLOSSARY_NAMES = "- the game declares these characters, keep each one EXACTLY unchanged: {names};\n"
GLOSSARY_DEFAULT = ("- places, peoples or species, titles, items, game systems and menus: give the natural {tgt} form "
                    "(e.g. \"Spirit Queen = Reine des Esprits\"); invented names that sound like proper nouns may stay "
                    "unchanged;\n")
GLOSSARY_VO = ("- the translator wants names in the ORIGINAL language, as the fans know them: keep UNCHANGED every proper "
               "name and nickname, title and rank (\"Archwizard = Archwizard\", \"Lady Eris = Lady Eris\"), class name, "
               "skill and spell name, named monster or creature, group or clan, and uniquely named object; translate "
               "into {tgt} ONLY ordinary places, common nouns and menus (\"Guild = Guilde\", \"Forest = Forêt\");\n")
GLOSSARY_SKIP = "- skip ordinary words, interjections, sounds and anything that is not a recurring game term.\n"
GLOSSARY_CONTEXT = "About the game: {context}\n"
GLOSSARY_ANSWER = "Answer ONLY with JSON {\"t\": [\"Term = Translation\", ...]}.\nTerms:\n"
