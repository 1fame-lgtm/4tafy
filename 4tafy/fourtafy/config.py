"""Chemins, constantes et réglages persistants de 4tafy."""
import copy
import json
import os
from pathlib import Path

APP_NAME = "4tafy"
VERSION = "1.0.0"

# Toutes les données vivent dans ~/4tafy (modifiable avec la variable FOURTAFY_HOME)
DATA_DIR = Path(os.environ.get("FOURTAFY_HOME", Path.home() / "4tafy"))
MUSIC_DIR = DATA_DIR / "music"
COVERS_DIR = DATA_DIR / "covers"
WALLPAPER_DIR = DATA_DIR / "wallpapers"
THEMES_DIR = DATA_DIR / "themes"
ICON_DIR = DATA_DIR / "icon"
ICON_ICO = ICON_DIR / "4tafy.ico"   # icône Windows utilisée par le raccourci du Bureau
LIBRARY_FILE = DATA_DIR / "library.json"
SETTINGS_FILE = DATA_DIR / "settings.json"

AUDIO_EXTENSIONS = {
    ".mp3", ".flac", ".wav", ".ogg", ".oga", ".opus", ".m4a", ".aac",
    ".wma", ".webm", ".mp4", ".aiff", ".aif", ".alac",
}
IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.webp *.bmp *.gif)"


def ensure_dirs():
    for d in (DATA_DIR, MUSIC_DIR, COVERS_DIR, WALLPAPER_DIR, THEMES_DIR, ICON_DIR):
        d.mkdir(parents=True, exist_ok=True)


UI_VERSION = 2  # incrémenté quand le look par défaut change

DEFAULT_SETTINGS = {
    "ui_version": UI_VERSION,
    "preset": "macOS Sombre",
    "colors": {
        "bg": "#1c1c1e",
        "panel": "#28282b",
        "card": "#2c2c2e",
        "hover": "#3a3a3c",
        "accent": "#fa2d48",
        "text": "#f5f5f7",
        "subtext": "#98989d",
        "border": "#3a3a3c",
    },
    "wallpaper": "",          # chemin d'une image (png/jpg/webp/gif animé)
    "wallpaper_dim": 55,      # 0-100 : assombrissement du fond
    "wallpaper_blur": 0,      # 0-40 : flou du fond
    "panel_opacity": 92,      # 0-100 : opacité des panneaux
    "radius": 12,             # coins arrondis (px)
    "font_family": "Inter",
    "font_size": 10,
    "window_shadow": True,    # ombre portée autour de la fenêtre (style macOS)
    "custom_icon": "",        # image choisie comme icône de l'application ("" = icône 4tafy)
    "icon_round": True,       # arrondir l'icône perso façon macOS
    "plugins_disabled": [],   # identifiants des plugins désactivés
    "plugin_params": {},      # derniers réglages utilisés pour chaque plugin
    "accent_glow": True,      # dégradé coloré en haut des pages
    "clean_titles": True,     # retire "(Official Video)" etc. des titres
    "volume": 70,
    "shuffle": False,
    "repeat": 0,              # 0 = off, 1 = tout, 2 = un seul titre
}


class Settings:
    def __init__(self, path=SETTINGS_FILE):
        self.path = Path(path)
        self.data = copy.deepcopy(DEFAULT_SETTINGS)
        self.load()

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                saved = json.load(f)
        except (OSError, ValueError):
            return
        if saved.get("ui_version", 1) < UI_VERSION:
            # nouveau look par défaut : on garde les réglages de lecture, pas l'ancien thème
            saved = {k: saved[k] for k in ("volume", "shuffle", "repeat", "clean_titles") if k in saved}
        colors = saved.pop("colors", {})
        self.data.update({k: v for k, v in saved.items() if k in DEFAULT_SETTINGS})
        self.data["colors"].update({k: v for k, v in colors.items() if k in DEFAULT_SETTINGS["colors"]})

    def save(self):
        ensure_dirs()
        tmp = self.path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, self.path)

    def reset_look(self):
        keep = {k: self.data[k] for k in ("volume", "shuffle", "repeat", "plugins_disabled", "plugin_params",
                                           "custom_icon", "icon_round")}
        self.data = copy.deepcopy(DEFAULT_SETTINGS)
        self.data.update(keep)

    def __getitem__(self, key):
        return self.data[key]

    def __setitem__(self, key, value):
        self.data[key] = value

    @property
    def colors(self):
        return self.data["colors"]
