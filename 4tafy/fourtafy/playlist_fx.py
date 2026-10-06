"""« Mettre toute la playlist en 8D » : applique l'audio 8D (à un pourcentage choisi) à chaque son
d'une playlist, avec le même moteur que le Studio, puis crée une nouvelle playlist ou remplace les sons."""
import threading
import uuid
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QRadioButton,
                               QVBoxLayout)

from . import studio_dsp as dsp
from .config import COVERS_DIR, MUSIC_DIR
from .studio_live import render_offline
from .studio_page import AudioLoader, ParamSlider


class Playlist8DDialog(QDialog):
    step = Signal(object, str)   # (nouveau titre ou None, message d'erreur)

    def __init__(self, main, pid):
        super().__init__(main)
        self.m = main
        self.pid = pid
        self.pl = main.lib.get_playlist(pid)
        self.tracks = [t for t in main.lib.playlist_tracks(pid) if t.get("path") and Path(t["path"]).exists()]
        self.queue = []
        self.results = {}       # id original -> id du son 8D
        self.running = False
        self.cancelled = False
        self.setWindowTitle("8D sur toute la playlist")
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        lay.setSpacing(12)

        h = QLabel(f"Mettre « {self.pl['name']} » en 8D")
        h.setObjectName("h2")
        lay.addWidget(h)
        sub = QLabel(f"{len(self.tracks)} son(s). Le son tourne autour de ta tête : à écouter au casque. "
                     "Les originaux ne sont jamais modifiés.")
        sub.setObjectName("sub")
        sub.setWordWrap(True)
        lay.addWidget(sub)

        saved = main.settings.data.get("plugin_params", {}).get("_playlist8d", {})
        self.amount = ParamSlider("Intensité 8D", 5, 100, 1, lambda v: f"{v:.0f} %",
                                  tip="Plus c'est haut, plus le son tourne franchement d'une oreille à l'autre")
        self.amount.default = 60
        self.amount.set_value(saved.get("pan8d", 60))
        lay.addWidget(self.amount)
        self.reverb = ParamSlider("Réverbe d'ambiance", 0, 60, 1, lambda v: "Aucune" if v == 0 else f"{v:.0f} %",
                                  tip="Un peu d'espace rend l'effet 8D plus immersif")
        self.reverb.default = 20
        self.reverb.set_value(saved.get("reverb", 20))
        lay.addWidget(self.reverb)

        self.opt_new = QRadioButton("Créer une nouvelle playlist avec les versions 8D")
        self.opt_replace = QRadioButton("Remplacer les sons de cette playlist par leur version 8D")
        (self.opt_replace if saved.get("replace") else self.opt_new).setChecked(True)
        lay.addWidget(self.opt_new)
        lay.addWidget(self.opt_replace)

        self.status = QLabel("")
        self.status.setObjectName("small")
        self.bar = QProgressBar()
        self.bar.setRange(0, max(1, len(self.tracks)))
        self.bar.setTextVisible(False)
        self.bar.hide()
        lay.addWidget(self.status)
        lay.addWidget(self.bar)

        btns = QHBoxLayout()
        btns.addStretch()
        self.cancel_btn = QPushButton("Annuler")
        self.cancel_btn.setObjectName("dlg")
        self.cancel_btn.clicked.connect(self._cancel)
        self.go_btn = QPushButton("Appliquer le 8D")
        self.go_btn.setObjectName("accent")
        self.go_btn.setCursor(Qt.PointingHandCursor)
        self.go_btn.clicked.connect(self.start)
        self.go_btn.setEnabled(bool(self.tracks))
        btns.addWidget(self.cancel_btn)
        btns.addWidget(self.go_btn)
        lay.addLayout(btns)

        self.loader = AudioLoader(self)
        self.loader.loaded.connect(self._on_loaded)
        self.loader.failed.connect(self._on_load_failed)
        self.ready = {}          # sons déjà décodés à l'avance (id -> audio, ou None si illisible)
        self.loading_tid = None
        self.waiting = False
        self.step.connect(self._after_one)

    # ------------------------------------------------------------------ déroulement
    def start(self):
        pct, rev = self.amount.value(), self.reverb.value()
        self.m.settings.data.setdefault("plugin_params", {})["_playlist8d"] = {
            "pan8d": pct, "reverb": rev, "replace": self.opt_replace.isChecked()}
        self.m.settings.save()
        self.params = dsp.params_with({"pan8d": pct, "reverb": rev})
        self.label = f"8D {pct:.0f} %"
        self.queue = list(self.tracks)
        self.running = True
        for w in (self.amount, self.reverb, self.opt_new, self.opt_replace, self.go_btn):
            w.setEnabled(False)
        self.cancel_btn.setText("Arrêter")
        self.bar.show()
        self.bar.setValue(0)
        self._next()

    def _next(self):
        if self.cancelled or not self.queue:
            self._finish()
            return
        self.cur = self.queue.pop(0)
        done = len(self.tracks) - len(self.queue)
        self.status.setText(f"{done}/{len(self.tracks)} — {self.cur['title'][:60]}")
        tid = self.cur["id"]
        if tid in self.ready:
            audio = self.ready.pop(tid)
            if audio is None:
                self.step.emit(None, "son illisible")
            else:
                self._render(audio)
        else:
            self.waiting = True
            if self.loading_tid != tid:
                self._load(self.cur)

    # décodage : le son suivant est préparé pendant le calcul du son en cours
    def _load(self, t):
        self.loading_tid = t["id"]
        self.loader.load(t["path"])

    def _prefetch(self):
        if self.queue and self.loading_tid is None and self.queue[0]["id"] not in self.ready:
            self._load(self.queue[0])

    def _on_loaded(self, audio):
        tid, self.loading_tid = self.loading_tid, None
        if self.waiting and self.cur and tid == self.cur["id"]:
            self.waiting = False
            self._render(audio)
        else:
            self.ready[tid] = audio

    def _on_load_failed(self, msg):
        tid, self.loading_tid = self.loading_tid, None
        if self.waiting and self.cur and tid == self.cur["id"]:
            self.waiting = False
            self.step.emit(None, f"illisible : {msg}")
        else:
            self.ready[tid] = None

    def _render(self, audio):
        t, params, label = self.cur, self.params, self.label

        def job():
            try:
                y, _info = render_offline(audio, params)
                ext = ".mp3" if dsp.mp3_available() else ".wav"
                dest = MUSIC_DIR / f"8D_{uuid.uuid4().hex[:10]}{ext}"
                (dsp.write_mp3 if ext == ".mp3" else dsp.write_wav)(dest, y)
                cover = ""
                if t.get("cover") and Path(t["cover"]).exists():
                    cover = str(COVERS_DIR / f"8d_{dest.stem}{Path(t['cover']).suffix}")
                    Path(cover).write_bytes(Path(t["cover"]).read_bytes())
                new = self.m.lib.add_track(title=f"{t['title']} ({label})", artist=t["artist"], album=t["album"],
                                           duration=len(y) / dsp.SR, path=str(dest), cover=cover,
                                           source="studio", source_id="", url="")
                self.step.emit(new, "")
            except Exception as e:
                self.step.emit(None, str(e))

        threading.Thread(target=job, daemon=True).start()
        self._prefetch()

    def _after_one(self, new, error):
        if new:
            self.results[self.cur["id"]] = new["id"]
        elif error:
            self.m.toast(f"Son ignoré ({self.cur['title'][:30]}) : {error[:60]}")
        self.bar.setValue(len(self.tracks) - len(self.queue))
        self.m.schedule_refresh()
        self._next()

    def _finish(self):
        self.running = False
        lib = self.m.lib
        n = len(self.results)
        if n:
            if self.opt_replace.isChecked():
                # même ordre, mêmes positions : chaque son est remplacé par sa version 8D
                order = [self.results.get(tid, tid) for tid in self.pl["tracks"]]
                lib.update_playlist(self.pid, tracks=order)
                msg = f"« {self.pl['name']} » : {n} son(s) passé(s) en {self.label}"
                target = self.pid
            else:
                new_pl = lib.create_playlist(f"{self.pl['name']} ({self.label})",
                                             description=f"Version {self.label} de « {self.pl['name']} »")
                lib.add_to_playlist(new_pl["id"], [self.results[t["id"]] for t in self.tracks
                                                   if t["id"] in self.results])
                if self.pl.get("cover"):
                    lib.update_playlist(new_pl["id"], cover=self.pl["cover"])
                msg = f"Playlist « {new_pl['name']} » créée ({n} sons)"
                target = new_pl["id"]
            self.m.toast(msg + (" — arrêté en cours de route" if self.cancelled else ""))
            self.m.refresh_all()
            self.m.open_playlist(target)
        else:
            self.m.toast("Aucun son n'a été converti")
        self.accept()

    def _cancel(self):
        if self.running:
            self.cancelled = True
            self.queue.clear()
            self.status.setText("Arrêt après le son en cours…")
            self.cancel_btn.setEnabled(False)
        else:
            self.reject()

    def reject(self):  # touche Échap pendant le calcul = demande d'arrêt
        if self.running:
            self._cancel()
        else:
            super().reject()

    def closeEvent(self, e):
        if self.running:  # on ne ferme pas au milieu d'un calcul : on demande l'arrêt
            self._cancel()
            e.ignore()
        else:
            super().closeEvent(e)
