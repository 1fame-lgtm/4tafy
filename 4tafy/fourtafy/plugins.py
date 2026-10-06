"""Système de plugins de 4tafy.

Un plugin est un simple fichier Python (.py) qui définit :

    PLUGIN = {
        "id": "mon_plugin",              # identifiant unique (lettres, chiffres, _)
        "name": "Mon plugin",
        "version": "1.0",
        "author": "Moi",
        "description": "Ce que fait le plugin.",
        "suffix": "Mon plugin",          # ajouté au nom du son créé : « Titre (Mon plugin) »
        "params": [                      # réglages affichés automatiquement dans 4tafy
            {"key": "force", "label": "Force", "type": "slider", "min": 0, "max": 100, "step": 1,
             "default": 50, "unit": " %"},
            {"key": "inverse", "label": "Inverser", "type": "bool", "default": False},
            {"key": "mode", "label": "Mode", "type": "choice", "choices": ["Doux", "Fort"], "default": "Doux"},
        ],
    }

    def process(audio, sr, params, ctx):
        # audio : numpy float32 de forme (échantillons, 2), valeurs entre -1 et 1, sr = 44100
        # params : dict {clé: valeur} des réglages
        # ctx : outils (ctx.bpm, ctx.progress(0..1, "texte"), ctx.limit(x), ctx.dsp, ctx.estimate_bpm(x))
        return audio  # le son transformé, même format (la longueur peut changer)

Les plugins intégrés sont dans fourtafy/plugins_builtin/, ceux de l'utilisateur dans ~/4tafy/plugins/.
"""
import importlib.util
import re
import shutil
import traceback
from pathlib import Path

import numpy as np

from . import studio_dsp as dsp
from .config import DATA_DIR

BUILTIN_DIR = Path(__file__).resolve().parent / "plugins_builtin"
USER_DIR = DATA_DIR / "plugins"
PARAM_TYPES = {"slider", "bool", "choice"}


class Plugin:
    def __init__(self, path, builtin):
        self.path = Path(path)
        self.builtin = builtin
        self.id = self.path.stem
        self.name = self.path.stem
        self.version = ""
        self.author = ""
        self.description = ""
        self.suffix = self.path.stem
        self.params = []
        self.process = None
        self.error = ""

    @property
    def ok(self):
        return self.process is not None and not self.error

    def defaults(self):
        return {p["key"]: p.get("default") for p in self.params}


def _load(path, builtin):
    pl = Plugin(path, builtin)
    try:
        modname = "fourtafy_plugin_" + re.sub(r"\W", "_", pl.id)
        spec = importlib.util.spec_from_file_location(modname, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        meta = getattr(mod, "PLUGIN", None)
        fn = getattr(mod, "process", None)
        if not isinstance(meta, dict) or not callable(fn):
            raise ValueError("le fichier doit définir PLUGIN = {...} et une fonction process(audio, sr, params, ctx)")
        pl.id = str(meta.get("id") or pl.id)
        pl.name = str(meta.get("name") or pl.id)
        pl.version = str(meta.get("version", ""))
        pl.author = str(meta.get("author", ""))
        pl.description = str(meta.get("description", ""))
        pl.suffix = str(meta.get("suffix") or pl.name)
        params = []
        for p in meta.get("params", []):
            if p.get("type") not in PARAM_TYPES or "key" not in p:
                raise ValueError(f"réglage invalide : {p}")
            params.append(dict(p, label=p.get("label", p["key"])))
        pl.params = params
        pl.process = fn
    except Exception as e:
        pl.error = f"{type(e).__name__} : {e}"
        traceback.print_exc()
    return pl


def discover():
    """Tous les plugins (intégrés puis utilisateur). Un plugin utilisateur peut remplacer un intégré."""
    USER_DIR.mkdir(parents=True, exist_ok=True)
    found = {}
    for folder, builtin in ((BUILTIN_DIR, True), (USER_DIR, False)):
        for f in sorted(folder.glob("*.py")):
            if f.name.startswith("_"):
                continue
            pl = _load(f, builtin)
            found[pl.id] = pl
    return list(found.values())


def install(src):
    """Copie un fichier .py dans le dossier des plugins et vérifie qu'il se charge."""
    USER_DIR.mkdir(parents=True, exist_ok=True)
    src = Path(src)
    dest = USER_DIR / src.name
    shutil.copy2(src, dest)
    pl = _load(dest, False)
    if not pl.ok:
        dest.unlink(missing_ok=True)
        raise ValueError(pl.error or "plugin invalide")
    return pl


def uninstall(plugin):
    if plugin.builtin:
        raise ValueError("les plugins intégrés ne peuvent pas être supprimés (désactive-les)")
    plugin.path.unlink(missing_ok=True)


TEMPLATE = '''"""Modèle de plugin 4tafy — modifie-moi !

Copie ce fichier, change PLUGIN et la fonction process, puis clique sur « Recharger » dans 4tafy.
"""
import numpy as np

PLUGIN = {
    "id": "echo_exemple",
    "name": "Écho (exemple)",
    "version": "1.0",
    "author": "Toi",
    "description": "Ajoute un écho rythmique. Sers-toi de ce fichier comme point de départ.",
    "suffix": "Écho",
    "params": [
        {"key": "delay", "label": "Délai", "type": "slider", "min": 50, "max": 1000, "step": 10,
         "default": 350, "unit": " ms"},
        {"key": "feedback", "label": "Répétitions", "type": "slider", "min": 0, "max": 90, "step": 1,
         "default": 45, "unit": " %"},
        {"key": "sync", "label": "Caler le délai sur le tempo", "type": "bool", "default": True},
    ],
}


def process(audio, sr, params, ctx):
    delay_s = params["delay"] / 1000
    if params["sync"] and ctx.bpm:
        delay_s = 60 / ctx.bpm * 0.75          # croche pointée
    d = int(delay_s * sr)
    out = audio.copy()
    fb = params["feedback"] / 100
    gain = fb
    k = 1
    while gain > 0.02 and k * d < len(audio):
        out[k * d:] += audio[: len(audio) - k * d] * gain
        gain *= fb
        k += 1
        ctx.progress(min(0.9, k / 20), "Écho…")
    return ctx.limit(out)
'''


def write_template():
    USER_DIR.mkdir(parents=True, exist_ok=True)
    dest = USER_DIR / "mon_plugin_exemple.py"
    i = 2
    while dest.exists():
        dest = USER_DIR / f"mon_plugin_exemple_{i}.py"
        i += 1
    dest.write_text(TEMPLATE, encoding="utf-8")
    return dest


# --------------------------------------------------------------------------- exécution
class Context:
    """Outils mis à disposition des plugins."""

    def __init__(self, sr, bpm=0, progress=None):
        self.sr = sr
        self.bpm = bpm
        self.dsp = dsp
        self._progress = progress

    def progress(self, frac, text=""):
        if self._progress:
            self._progress(max(0.0, min(1.0, float(frac))), text)

    def estimate_bpm(self, audio):
        return dsp.estimate_bpm(audio)

    def limit(self, x, ceiling=0.97):
        """Limiteur sans saturation (le même que celui du Studio)."""
        from .studio_live import Limiter
        lim = Limiter(ceiling=ceiling)
        L = 2 * Limiter.LOOK
        y = lim.process(np.concatenate([x, np.zeros((L, 2), np.float32)]).astype(np.float32))
        return y[L:]


def run(plugin, audio, params, bpm=0, progress=None):
    """Exécute un plugin et vérifie son résultat."""
    if not plugin.ok:
        raise RuntimeError(plugin.error or "plugin indisponible")
    full = dict(plugin.defaults(), **(params or {}))
    ctx = Context(dsp.SR, bpm, progress)
    out = plugin.process(audio.astype(np.float32, copy=True), dsp.SR, full, ctx)
    out = np.asarray(out, dtype=np.float32)
    if out.ndim == 1:
        out = np.stack([out, out], axis=1)
    if out.ndim != 2 or out.shape[1] != 2 or len(out) < dsp.SR // 10:
        raise RuntimeError(f"le plugin a renvoyé un son invalide (forme {out.shape})")
    out = np.nan_to_num(out, nan=0.0, posinf=0.0, neginf=0.0)
    return np.clip(out, -1, 1)
