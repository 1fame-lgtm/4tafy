# 4tafy 🎵

Lecteur de musique **open source** façon Spotify, écrit en Python.
Importe tes sons depuis **YouTube, YouTube Music, Spotify, TikTok, SoundCloud, Bandcamp**
(et ~1000 autres sites) ou depuis tes **fichiers MP3 / FLAC / WAV / OGG / M4A**, puis écoute-les hors-ligne
dans une interface entièrement personnalisable.

## Fonctionnalités

- **Import par lien** : colle un ou plusieurs liens (un par ligne)
  - titre seul, **playlist entière**, album, profil TikTok…
  - **Spotify** : titres, albums et playlists publiques. Comme l'audio Spotify est protégé (DRM),
    4tafy lit les infos (titre, artiste, durée exacte, pochette officielle) puis retrouve **la bonne version**
    sur YouTube : plusieurs candidats sont notés (titre, artiste, durée à la seconde près, chaîne officielle
    « Topic » / VEVO) et les reprises, remixes, live, sped up, karaoké… sont écartés.
    Les correspondances douteuses sont marquées « ⚠ à vérifier ».
  - **Corriger le son** (clic droit) : si un son n'est pas le bon, choisis la bonne version dans la liste
    classée ou colle un lien ; le titre, l'artiste et la pochette sont conservés.
  - anti-doublons : un son déjà importé n'est pas re-téléchargé
- **Import local** : fichiers, dossiers entiers (récursif) et playlists `.m3u`
  (titre, artiste, album et pochette lus depuis les tags)
- **Glisser-déposer** des fichiers, dossiers ou liens n'importe où sur la fenêtre
- **Lecteur complet** : lecture/pause, suivant/précédent, aléatoire, répéter (tout / un titre),
  barre de progression cliquable, volume, file d'attente, « lire ensuite »
- **Playlists** : créer, renommer, description, pochette perso, réordonner, exporter en `.m3u`
- **8D sur toute une playlist** (clic droit sur la playlist) : intensité en %, réverbe d'ambiance, nouvelle
  playlist « Nom (8D 60 %) » ou remplacement des sons — les originaux restent dans la bibliothèque
- **Titres likés** ♥, recherche instantanée, tri par colonne, « tes plus écoutés »
- **Modifier les infos** d'un titre (titre, artiste, album, pochette)
- **Studio** 🎛️ : modifie n'importe quel son (de la bibliothèque ou d'une playlist, ou clic droit → *Ouvrir dans le Studio*)
  - égaliseur 6 bandes avec courbe en direct (sub-basses, basses, médiums, présence, aigus…)
  - volume en dB, **impact des beats**, compression, normalisation, indicateur de crête / niveau
  - vitesse « vinyle » (slowed / nightcore), **tonalité** sans changer le tempo, détection du **BPM**
  - réverbération, **audio 8D**, largeur stéréo, lo-fi
  - découpe sur la forme d'onde, fondus d'entrée / sortie
  - préréglages : Bass Boost, Slowed + Reverb, Nightcore, 8D, Lo-fi, Voix claire, Club
  - **rendu en direct** : lance la lecture et bouge les curseurs, tu entends le résultat instantanément,
    avec vumètre et comparaison **Original / Modifié**. Moteur temps réel dans un fil dédié (pas de
    craquements), réglages lissés (pas de clics), vitesse en interpolation cubique, vrai limiteur
    anti-saturation. **Le fichier enregistré est exactement ce que tu entends** (même moteur).
  - **réglages mémorisés pour chaque son** (marqués « ✎ modifié »), retrouvés à la prochaine ouverture
  - enregistre le résultat comme nouveau titre (dans les mêmes playlists) ou exporte en MP3 / WAV
  - **enregistrer tous les sons** d'une playlist ou de la bibliothèque avec les mêmes réglages, en un clic
- **Look macOS** : fenêtre sans bordure avec coins arrondis et ombre douce, boutons
  rouge / jaune / vert, barre latérale avec recherche, navigation précédent / suivant (`Alt + ←/→`),
  menus arrondis, en-têtes teintés selon la pochette. Glisse la barre du haut pour déplacer la fenêtre,
  double-clique pour l'agrandir, tire sur les bords pour la redimensionner.
- **Personnalisation totale** (onglet *Personnaliser*) :
  - 13 thèmes intégrés (macOS Sombre / Clair / Bleu, 4tafy, Spotify Classic, Minuit, Océan, Dracula, Matrix, Sakura…)
  - chaque couleur modifiable (fond, panneaux, accent, texte…)
  - **fond d'écran** perso (PNG/JPG/WEBP ou **GIF animé**) avec assombrissement et flou réglables
  - opacité des panneaux (effet verre), coins arrondis, police et taille du texte
  - **export / import de thèmes** en `.json` pour les partager
  - **icône de l'application** : n'importe quelle image (PNG, JPG, WEBP, ICO…), arrondie façon macOS si tu veux,
    appliquée à la fenêtre, à la barre des tâches et au logo, sans compiler. Un bouton crée un raccourci
    « 4tafy » sur le Bureau avec cette icône.

## Plugins 🧩

Catégorie **Plugins** : des transformations qu'on ajoute à 4tafy sans toucher au code de l'appli.
Choisis un plugin, un son, règle les paramètres, écoute un **aperçu de 30 s**, puis **Appliquer et enregistrer**
(le résultat devient un nouveau titre, l'original n'est pas modifié). Aussi accessible par clic droit sur un son →
*Plugins*.

**Plugin intégré : Hardtekk** — accélère le son vers ~170 BPM (voix aiguës ou tonalité gardée), suit les temps
du morceau pour poser un **kick hardtekk distordu** sur chaque temps, une basse en contretemps (note détectée
automatiquement), des hi-hats, un clap, du **sidechain** qui fait pomper le morceau, nettoie ses basses
d'origine et coupe les kicks dans les passages calmes.

### Écrire son propre plugin

Un plugin = **un fichier `.py`** placé dans `~/4tafy/plugins/` (ou installé via *Installer un plugin…*).
Le bouton *Créer un plugin (modèle)* génère un exemple complet (un écho) à modifier.

```python
PLUGIN = {
    "id": "mon_effet", "name": "Mon effet", "version": "1.0", "author": "Moi",
    "description": "Ce que fait le plugin.", "suffix": "Mon effet",
    "params": [   # l'interface est générée automatiquement
        {"key": "force", "label": "Force", "type": "slider", "min": 0, "max": 100, "step": 1, "default": 50, "unit": " %"},
        {"key": "inverse", "label": "Inverser", "type": "bool", "default": False},
        {"key": "mode", "label": "Mode", "type": "choice", "choices": ["Doux", "Fort"], "default": "Doux"},
    ],
}

def process(audio, sr, params, ctx):
    # audio : numpy float32 (échantillons, 2) entre -1 et 1 ; sr = 44100
    # ctx.bpm, ctx.progress(0..1, "texte"), ctx.limit(x), ctx.dsp.beat_track(audio, bpm), ctx.dsp.*
    return audio * (params["force"] / 100)
```

⚠️ Un plugin est du code Python exécuté sur ton ordinateur : installe uniquement ceux qui viennent d'une source
de confiance.

## Installation

Il faut **Python 3.10+**.

```bash
pip install -r requirements.txt
python main.py
```

Sous Windows tu peux aussi double-cliquer sur **`lancer_4tafy.bat`** (installe/maj les dépendances puis lance l'appli).

> 💡 **Optionnel** : si [FFmpeg](https://ffmpeg.org) est installé (dans le PATH), les sons téléchargés
> sont automatiquement convertis en vrais `.mp3`. Sans FFmpeg, ils sont gardés en `.m4a`/`.webm`
> (même qualité, lus sans problème par 4tafy).

## Raccourcis clavier

| Touche | Action |
|---|---|
| `Espace` | Lecture / pause |
| `Ctrl + →` / `Ctrl + ←` | Titre suivant / précédent |
| `Ctrl + ↑` / `Ctrl + ↓` | Volume + / − |
| `Ctrl + F` | Rechercher |
| `Ctrl + I` | Importer |
| `Ctrl + L` | Liker le titre en cours |
| `Ctrl + S` / `Ctrl + R` | Aléatoire / Répéter |

## Où sont mes fichiers ?

Tout est dans `~/4tafy` (`C:\Users\<toi>\4tafy` sous Windows) :

```
4tafy/
├── music/          sons téléchargés
├── covers/         pochettes
├── wallpapers/     fonds d'écran
├── themes/         thèmes exportés
├── library.json    ta bibliothèque et tes playlists
└── settings.json   tes réglages
```

Change cet emplacement avec la variable d'environnement `FOURTAFY_HOME`.

## Structure du code

```
main.py                    point d'entrée
fourtafy/
├── app.py                 création de l'application Qt
├── main_window.py         fenêtre : barre latérale, barre de lecture, menus
├── pages.py               pages Accueil / Titres / Import / File d'attente
├── settings_page.py       page Personnaliser
├── chrome.py              fenêtre style macOS (sans bordure, ombre, boutons ronds)
├── widgets.py             table des titres, cartes, curseurs…
├── player.py              lecteur audio (QtMultimedia) + file d'attente
├── studio_page.py         page Studio (forme d'onde, égaliseur, pré-écoute)
├── studio_dsp.py          moteur audio du Studio (numpy / scipy)
├── studio_live.py         moteur de rendu du Studio (direct + enregistrement, limiteur)
├── matcher.py             recherche de la bonne version YouTube d'un titre Spotify
├── plugins.py             système de plugins (chargement, installation, exécution)
├── plugins_page.py        page Plugins
├── plugins_builtin/       plugins livrés avec 4tafy (hardtekk.py)
├── playlist_fx.py         « Mettre toute la playlist en 8D »
├── fix_dialog.py          fenêtre « Corriger le son »
├── importer.py            import YouTube / Spotify / TikTok / fichiers (yt-dlp, mutagen)
├── library.py             bibliothèque & playlists (JSON)
├── themes.py              thèmes prédéfinis + feuille de style
├── graphics.py            icônes vectorielles et pochettes générées
└── config.py              chemins et réglages par défaut
```

**Ajouter un thème intégré** : ajoute une entrée dans `PRESETS` (`fourtafy/themes.py`).
**Ajouter une icône** : ajoute un cas dans `_draw()` (`fourtafy/graphics.py`).

## Dépannage

- **Un import YouTube/TikTok échoue** → ces sites changent souvent : *Personnaliser → Mettre à jour yt-dlp*
  (ou `pip install -U yt-dlp`), puis redémarre 4tafy.
- **Playlist Spotify incomplète** → la page publique de Spotify ne donne qu'une partie des très grandes
  playlists (environ 100 titres). La playlist doit être publique.

## Mention légale

4tafy est un outil personnel. Ne télécharge que des contenus que tu as le droit de télécharger
(contenus libres, tes propres créations, ou ce que la loi de ton pays autorise pour un usage privé),
et respecte les conditions d'utilisation des plateformes.

## Licence

MIT — fais-en ce que tu veux. Voir [LICENSE](LICENSE).
