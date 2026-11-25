# SPEC — TradVoice : les jeux (et plus tard les animés) parlent français

## Objectif
Tout en local sur le PC, sans compte ni clé, avec l'IA de TradUp :

| Cas | Ce que fait TradVoice |
|---|---|
| **Donner une voix** (jeu muet) | chaque personnage reçoit **sa** voix française, décrite par mots (genre, âge, timbre, ton, débit) |
| **Narrateur** (jeu tout en texte) | une voix de conteur lit toute l'histoire |
| **Doubler en français** (jeu doublé) | **réécriture vocale** : la réplique française garde le jeu de l'acteur (émotion, rythme, pauses, intensité), avec une voix **nouvelle** de même ton |
| **Plus tard** | vidéos (animés pas encore sortis en français), traduction vocale instantanée (voir « Idées à cadrer ») |

Toujours : originaux sauvegardés, « Remettre l'original », refus des jeux en ligne et anti-triche (règles TradUp).

## Décisions prises
- **Usage personnel uniquement, diffusion interdite** (texte complet : `USAGE PERSONNEL - à lire.txt`). TradVoice ne remplace pas les comédiens. À rappeler : au premier lancement (case à cocher obligatoire), sur l'accueil, dans le LISEZ-MOI, et plus tard sur chaque fichier fabriqué (nom ou étiquette « usage personnel »). Aucune fonction de partage ou de mise en ligne dans le logiciel.
- **Application séparée** (dépôt `TradVoice`), même squelette que TradUp : pywebview + `static/index.html`, Python 3.11, Nuitka.
- **Moteur TradUp repris tel quel** dans `commun/` (copie de TradUp `f26f51e`, voir `commun/ORIGINE.txt`). Un correctif TradUp se recopie, rien n'est réécrit.
- **L'IA locale est celle de TradUp** (même `llama-server`, même modèle dans `%LOCALAPPDATA%\TradUp\modeles`) : rien à retélécharger si TradUp est installé.
- **Voix par description, pas de clonage** : une voix peut avoir le même TON qu'un rôle, jamais imiter une personne réelle. C'est ce qui rend TradVoice vendable. Les consignes de l'IA le disent (`fiches.RULES`).
- **Interface** : fusion TradUp × ElevenLabs (menu à gauche, accueil centré avec barre « Demande à l'IA », cartes, parcours et couleurs de TradUp). Maquette validée.
- **Contexte par personnage** : chaque voix est rattachée au personnage qui parle (nom lu dans le jeu), avec son nombre de répliques et des exemples ; alerte si deux personnages importants ont la même voix.

## Réécriture vocale (doublage) — comment
Pour chaque réplique d'origine, TradVoice **mesure** au lieu de copier la voix :
1. **Durée, pauses, débit** (syllabes par seconde) ;
2. **Hauteur et intensité** (courbe de la voix : monte, descend, crie, chuchote) ;
3. **Émotion** (étiquette proposée par l'IA d'après le texte + ces mesures : neutre, colère, peur, tristesse, joie, chuchoté, cri).

La réplique est traduite (moteur TradUp, raccourcie si besoin pour tenir dans la même durée ±15 %), puis dite par la **voix décrite du personnage** avec ces réglages. On garde le jeu d'acteur, pas son timbre.
Par personnage, l'IA peut aussi **décrire** la voix d'origine (âge, timbre, ton) pour proposer une fiche « même ton, voix différente ».

## Où on en est (v0.1, 25/11)
Fait et testé (`python -m pytest -q tests`, `python app.py --autotest`) :
- `personnages.py` : qui parle dans un jeu Ren'Py (`.rpy` sûr ; `.rpyc` en best effort, **à vérifier sur un vrai jeu**), narrateur, résumé par personnage, jeu « tout en texte » détecté.
- `fiches.py` : fiches voix, proposition par l'IA (ou sans IA), demandes libres (« une voix de vieux marin pour Bram »), verrou, alerte de voix trop proches.
- `app.py` + `static/index.html` : Accueil, Voix du jeu (type de jeu, contexte, personnages), Fiche personnage. Projets enregistrés dans `Documents\TradVoice\projets`.
- Pas encore : aucune voix n'est générée, rien n'est écrit dans le jeu.

## Étapes suivantes
| # | Étape | Bloqué par |
|---|---|---|
| 1 | **Moteur de voix** : `voixlocale.py` (processus séparé, comme `localai.py`), `synth(texte, fiche, émotion, débit)` | choix du moteur (VOX NATIVE ? sinon un moteur local qui crée une voix par description, licence commerciale) |
| 2 | Bouton « Écouter un essai » dans la fiche | 1 |
| 3 | `audio.py` (ffmpeg) : durée, volume, accélération légère, conversion `.ogg` | — |
| 4 | Générer toutes les répliques (pause / reprise / carillon, comme TradUp) | 1, 3 |
| 5 | Ren'Py : appliquer au jeu (`game/tradvoice.rpy` + `voice_fr/`, voix automatique), remettre l'original | 4 |
| 6 | Vérifier la lecture des `.rpyc` sur 2-3 vrais jeux | un vrai jeu sur ton PC |
| 7 | Utiliser les traductions TradUp déjà faites (jeu traduit → on fait parler le texte français) | — |
| 8 | Réécriture vocale (jeux doublés) : mesures, émotion, durée | 1, 3 |
| 9 | Unity (greffon BepInEx), puis autres moteurs | 5 |

## Idées à cadrer (pas commencées)
- **Animés / vidéos** : même chaîne (transcription → traduction → voix décrite + réécriture vocale) sur un fichier vidéo, puis une nouvelle piste audio. Usage personnel sur une vidéo que tu possèdes ; TradVoice ne doit rien mettre en ligne ni partager (droits d'auteur).
- **Mangas** : à préciser — lire à voix haute un manga déjà traduit (bulles par personnage), ou traduire les images (TradUp sait déjà traduire le texte des images) ?
- **Traduction vocale instantanée** : écouter un son en direct (jeu, vidéo, micro) et le redire en français avec 1 à 3 s de retard. Faisable en local (transcription + IA + voix), mais c'est un mode à part. Nom du logiciel dont tu veux t'inspirer : à donner.

- **Mode « Mes textes » (accessibilité)** : pour les personnes qui ont du mal à parler devant un micro (vidéastes, YouTube…). On écrit son propre texte, on choisit ou on décrit une voix, TradVoice le lit (et peut le traduire dans une autre langue), puis exporte un fichier audio.
  - Ici, **la diffusion est permise** : le texte appartient à la personne et la voix est créée par description (ce n'est la voix de personne). La règle « diffusion interdite » reste valable pour tout ce qui vient d'un jeu, d'un animé ou d'une œuvre d'un tiers.
  - À faire avant : nouvelle version des conditions (`TERMS_VERSION = 2`) avec ces deux régimes ; moteur de voix dont la licence autorise l'usage commercial **des sons produits** ; rappel que certaines plateformes demandent de signaler une voix de synthèse.
  - **Deux choix de voix** : une voix créée par description, OU **sa propre voix**, enregistrée par la personne elle-même.
  - Garde-fous pour « ma voix » (pour qu'on ne puisse pas copier la voix de quelqu'un d'autre) :
    - enregistrement **uniquement au micro, dans TradVoice** : pas d'import de fichier audio pour ce mode ;
    - **phrase de vérification** tirée au hasard et affichée à l'écran, à lire en direct (une voix prise dans une vidéo ne peut pas la dire) ;
    - case « c'est ma propre voix » ; la voix reste sur le PC, chiffrée, et ne s'exporte pas comme modèle ;
    - supprimable en un clic ;
    - jamais utilisable dans les modes jeux / animés (ce n'est pas un outil pour se doubler dans une œuvre d'un tiers… sauf si on décide autrement plus tard).
  - Contrainte technique : le moteur de voix doit savoir **à la fois** créer une voix par description et reproduire une voix enregistrée, avec une licence qui autorise la publication et la vente des sons produits.

## Questions ouvertes
1. Moteur de voix : que contient VOX NATIVE (moteur, licence) ?
2. Mangas : lecture à voix haute ou traduction des images ?
3. Traduction instantanée : quel logiciel sert de modèle ?
