"""Page « Studio » : modifier un son (égaliseur, basses, tempo, tonalité, effets, découpe…)
avec rendu EN DIRECT pendant la lecture, puis l'enregistrer comme nouveau titre ou l'exporter.
Les réglages sont mémorisés pour chaque son, et peuvent être appliqués à tous les sons d'une playlist."""
import copy
import threading
import uuid
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QPointF, QRectF, QSize, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtMultimedia import QAudioDecoder, QAudioFormat
from PySide6.QtWidgets import (QCheckBox, QComboBox, QCompleter, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
                               QMessageBox,
                               QLabel, QLineEdit, QPushButton, QScrollArea, QSlider, QVBoxLayout,
                               QWidget)

from . import graphics as gfx
from . import studio_dsp as dsp
from .config import COVERS_DIR, MUSIC_DIR
from .studio_live import LivePlayer, render_offline
from .widgets import ClickSlider, fmt_time



# =========================================================================== chargement / rendu
class AudioLoader(QObject):
    """Décode n'importe quel fichier audio en PCM float32 stéréo 44,1 kHz (via QtMultimedia)."""
    loaded = Signal(object)
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.dec = None
        self.chunks = []

    def load(self, path):
        old, self.dec = self.dec, None
        if old:
            # on coupe ses signaux AVANT de l'arrêter : stop() peut émettre « finished »
            for sig in (old.bufferReady, old.finished, old.error):
                try:
                    sig.disconnect()
                except (RuntimeError, TypeError):
                    pass
            old.stop()
            old.deleteLater()
        self.chunks = []
        self.dec = QAudioDecoder(self)
        fmt = QAudioFormat()
        fmt.setSampleRate(dsp.SR)
        fmt.setChannelCount(2)
        fmt.setSampleFormat(QAudioFormat.Float)
        self.dec.setAudioFormat(fmt)
        self.dec.setSource(QUrl.fromLocalFile(str(path)))
        dec = self.dec
        dec.bufferReady.connect(lambda: self.chunks.append(bytes(dec.read().constData())))
        dec.finished.connect(lambda: self._done(dec))
        dec.error.connect(lambda _e: self.failed.emit(dec.errorString()) if dec is self.dec else None)
        dec.start()

    def _done(self, dec):
        if dec is not self.dec:
            return
        data = np.frombuffer(b"".join(self.chunks), dtype=np.float32)
        self.chunks = []
        if data.size < 2 * dsp.SR // 2:
            self.failed.emit("son trop court ou illisible")
            return
        self.loaded.emit(data[: data.size // 2 * 2].reshape(-1, 2).copy())


class RenderWorker(QThread):
    """Calcule le son complet en arrière-plan (pour l'enregistrement, l'export et la normalisation).
    La pré-écoute, elle, est calculée en direct par studio_live."""
    done = Signal(object, object)   # infos, paramètres utilisés
    failed = Signal(str)

    def __init__(self):
        super().__init__()
        self.audio = None
        self.cache = {}
        self._req = None
        self._ev = threading.Event()
        self._stop = False
        self.last = None          # (son, paramètres) du dernier rendu
        self.pitch_cache = {}
        self.busy = False

    def set_audio(self, audio):
        self.audio = audio
        self.cache = {}
        self.last = None

    def request(self, params):
        self._req = copy.deepcopy(params)
        self._ev.set()

    def stop(self):
        self._stop = True
        self._ev.set()

    def run(self):
        while not self._stop:
            self._ev.wait()
            self._ev.clear()
            if self._stop:
                break
            params, self._req = self._req, None
            if params is None or self.audio is None:
                continue
            self.busy = True
            try:
                pitched = self.pitch_cache.get(int(params["pitch"])) if params["pitch"] else None
                y, info = render_offline(self.audio, params, pitched)
                if self._req is not None:  # un réglage plus récent attend déjà
                    continue
                self.last = (y, params)
                self.done.emit(info, params)
            except Exception as e:  # pragma: no cover - affiché à l'utilisateur
                self.failed.emit(str(e))
            finally:
                self.busy = self._req is not None


# =========================================================================== widgets graphiques
class WaveformView(QWidget):
    """Forme d'onde du son d'origine + poignées de découpe + tête de lecture."""
    trim_changed = Signal(float, float)
    seek_requested = Signal(float)   # secondes (temps du son d'origine)

    def __init__(self, colors_fn):
        super().__init__()
        self.colors = colors_fn
        self.peaks = None
        self.duration = 0.0
        self.start = 0.0
        self.end = 0.0
        self.playhead = None
        self._drag = None
        self.setMinimumHeight(130)
        self.setMouseTracking(True)

    def set_audio(self, peaks, duration):
        self.peaks = peaks / max(1e-6, float(peaks.max()))
        self.duration = duration
        self.start, self.end = 0.0, duration
        self.update()

    def set_trim(self, start, end):
        self.start, self.end = start, end
        self.update()

    def _x(self, t):
        return 10 + (self.width() - 20) * (t / max(1e-6, self.duration))

    def _t(self, x):
        return max(0.0, min(self.duration, (x - 10) / max(1, self.width() - 20) * self.duration))

    def paintEvent(self, _):
        c = self.colors()
        key = (self.width(), self.height(), round(self.start, 2), round(self.end, 2), id(self.peaks),
               c["accent"], c["subtext"], c["text"], self.devicePixelRatioF())
        if key != getattr(self, "_cache_key", None):
            dpr = self.devicePixelRatioF()
            pm = QPixmap(int(self.width() * dpr), int(self.height() * dpr))
            pm.setDevicePixelRatio(dpr)
            pm.fill(Qt.transparent)
            sp = QPainter(pm)
            self._paint_static(sp, c)
            sp.end()
            self._cache, self._cache_key = pm, key
        p = QPainter(self)
        p.drawPixmap(0, 0, self._cache)
        if self.peaks is not None and self.playhead is not None and self.start <= self.playhead <= self.end:
            p.setRenderHint(QPainter.Antialiasing)
            px = self._x(self.playhead)
            p.setPen(QPen(QColor(c["text"]), 1.5))
            p.drawLine(QPointF(px, 4), QPointF(px, self.height() - 4))
        p.end()

    def _paint_static(self, p, c):
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        bg = QColor(c["text"])
        bg.setAlphaF(0.04)
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(r, 10, 10)
        if self.peaks is None:
            p.setPen(QColor(c["subtext"]))
            p.drawText(r, Qt.AlignCenter, "Choisis un son pour afficher sa forme d'onde")
            return
        w = self.width() - 20
        n = len(self.peaks)
        mid = r.height() / 2
        x0, x1 = self._x(self.start), self._x(self.end)
        acc = QColor(c["accent"])
        dim = QColor(c["subtext"])
        dim.setAlphaF(0.35)
        # barres groupées en deux chemins (bien plus rapide que des milliers de drawRect)
        bar_w = max(1.0, w / n) * 0.8
        inside, outside = QPainterPath(), QPainterPath()
        for i, v in enumerate(self.peaks):
            x = 10 + i * w / n
            h = max(1.0, float(v) * (mid - 10))
            (inside if x0 <= x <= x1 else outside).addRect(QRectF(x, mid - h, bar_w, 2 * h))
        p.fillPath(outside, dim)
        p.fillPath(inside, acc)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 90))
        p.drawRect(QRectF(0, 0, x0, r.height()))
        p.drawRect(QRectF(x1, 0, r.width() - x1, r.height()))
        for x in (x0, x1):
            p.setBrush(QColor(c["text"]))
            p.drawRoundedRect(QRectF(x - 2, 6, 4, r.height() - 12), 2, 2)
            p.drawEllipse(QPointF(x, 10), 5, 5)
        return

    def mousePressEvent(self, e):
        if self.peaks is None:
            return
        x = e.position().x()
        if abs(x - self._x(self.start)) < 9:
            self._drag = "start"
        elif abs(x - self._x(self.end)) < 9:
            self._drag = "end"
        else:
            self.seek_requested.emit(self._t(x))

    def mouseMoveEvent(self, e):
        x = e.position().x()
        if self._drag:
            t = self._t(x)
            if self._drag == "start":
                self.start = min(t, self.end - 1.0)
            else:
                self.end = max(t, self.start + 1.0)
            self.update()
        elif self.peaks is not None:
            near = min(abs(x - self._x(self.start)), abs(x - self._x(self.end))) < 9
            self.setCursor(Qt.SizeHorCursor if near else Qt.PointingHandCursor)

    def mouseReleaseEvent(self, e):
        if self._drag:
            self._drag = None
            self.trim_changed.emit(self.start, self.end)


class EqCurve(QWidget):
    """Courbe de réponse de l'égaliseur (20 Hz → 20 kHz, ±15 dB)."""

    def __init__(self, colors_fn):
        super().__init__()
        self.colors = colors_fn
        self.gains = [0.0] * len(dsp.EQ_BANDS)
        self.freqs = np.geomspace(20, 20000, 220)
        self.resp = np.zeros_like(self.freqs)
        self.setMinimumHeight(130)

    def set_gains(self, gains):
        self.gains = list(gains)
        self.resp = dsp.eq_response(self.gains, self.freqs)
        self.dots = dsp.eq_response(self.gains, np.array([b[0] for b in dsp.EQ_BANDS], dtype=float))
        self.update()

    def paintEvent(self, _):
        c = self.colors()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0, 0, 0, -16)
        bg = QColor(c["text"])
        bg.setAlphaF(0.04)
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(QRectF(self.rect()), 10, 10)
        lx = lambda f: r.left() + 8 + (r.width() - 16) * (np.log10(f / 20) / 3)
        ly = lambda db: r.top() + r.height() / 2 - db / 15 * (r.height() / 2 - 8)
        grid = QColor(c["text"])
        grid.setAlphaF(0.08)
        p.setPen(QPen(grid, 1))
        small = QFont(self.font())
        small.setPointSizeF(max(6.5, small.pointSizeF() - 2))
        p.setFont(small)
        for f, lab in ((50, "50"), (100, "100"), (500, "500"), (1000, "1k"), (5000, "5k"), (10000, "10k")):
            x = lx(f)
            p.setPen(QPen(grid, 1))
            p.drawLine(QPointF(x, r.top() + 6), QPointF(x, r.bottom()))
            p.setPen(QColor(c["subtext"]))
            p.drawText(QRectF(x - 20, r.bottom() + 1, 40, 14), Qt.AlignCenter, lab)
        p.setPen(QPen(grid, 1))
        for db in (-12, -6, 6, 12):
            p.drawLine(QPointF(r.left() + 8, ly(db)), QPointF(r.right() - 8, ly(db)))
        zero = QColor(c["text"])
        zero.setAlphaF(0.2)
        p.setPen(QPen(zero, 1, Qt.DashLine))
        p.drawLine(QPointF(r.left() + 8, ly(0)), QPointF(r.right() - 8, ly(0)))
        path = QPainterPath()
        for i, (f, db) in enumerate(zip(self.freqs, np.clip(self.resp, -15, 15))):
            pt = QPointF(lx(f), ly(db))
            path.moveTo(pt) if i == 0 else path.lineTo(pt)
        fill = QPainterPath(path)
        fill.lineTo(QPointF(lx(20000), ly(0)))
        fill.lineTo(QPointF(lx(20), ly(0)))
        fill.closeSubpath()
        acc = QColor(c["accent"])
        g = QLinearGradient(0, r.top(), 0, r.bottom())
        a1, a2 = QColor(acc), QColor(acc)
        a1.setAlphaF(0.35)
        a2.setAlphaF(0.05)
        g.setColorAt(0, a1)
        g.setColorAt(1, a2)
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawPath(fill)
        p.setPen(QPen(acc, 2.2))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        p.setPen(Qt.NoPen)
        p.setBrush(acc)
        for (f, *_), db in zip(dsp.EQ_BANDS, getattr(self, "dots", np.zeros(len(dsp.EQ_BANDS)))):
            p.drawEllipse(QPointF(lx(f), ly(float(np.clip(db, -15, 15)))), 4, 4)
        p.end()


class LevelMeter(QWidget):
    """Vumètre stéréo (crête en dB) façon console de mixage."""

    def __init__(self, colors_fn):
        super().__init__()
        self.colors = colors_fn
        self.levels = (0.0, 0.0)
        self.setFixedSize(110, 22)
        self.setToolTip("Niveau de sortie (gauche / droite)")

    def set_levels(self, left, right):
        if (left, right) != self.levels:
            self.levels = (left, right)
            self.update()

    def paintEvent(self, _):
        c = self.colors()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        w = self.width()
        for i, v in enumerate(self.levels):
            y = 3 + i * 10
            bg = QColor(c["text"])
            bg.setAlphaF(0.10)
            p.setBrush(bg)
            p.drawRoundedRect(QRectF(0, y, w, 6), 3, 3)
            db = 20 * np.log10(max(float(v), 1e-5))
            frac = max(0.0, min(1.0, (db + 48) / 48))
            g = QLinearGradient(0, 0, w, 0)
            g.setColorAt(0, QColor("#30d158"))
            g.setColorAt(0.75, QColor("#ffd60a"))
            g.setColorAt(1, QColor("#ff453a"))
            p.setBrush(g)
            p.drawRoundedRect(QRectF(0, y, w * frac, 6), 3, 3)
        p.end()


class ParamSlider(QWidget):
    """Curseur avec titre et valeur affichée ; travaille en nombres décimaux."""
    changed = Signal(float)

    def __init__(self, label, lo, hi, step, fmt, vertical=False, tip=""):
        super().__init__()
        self.step = step
        self.fmt = fmt
        self.slider = QSlider(Qt.Vertical if vertical else Qt.Horizontal)
        self.slider.setRange(int(round(lo / step)), int(round(hi / step)))
        self.slider.setCursor(Qt.PointingHandCursor)
        self.value_lbl = QLabel()
        self.value_lbl.setObjectName("small")
        self.title = QLabel(label)
        self.setToolTip(tip)
        if vertical:
            lay = QVBoxLayout(self)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(4)
            self.slider.setMinimumHeight(120)
            self.value_lbl.setAlignment(Qt.AlignCenter)
            self.title.setAlignment(Qt.AlignCenter)
            self.title.setObjectName("small")
            lay.addWidget(self.value_lbl)
            lay.addWidget(self.slider, 1, Qt.AlignHCenter)
            lay.addWidget(self.title)
        else:
            lay = QVBoxLayout(self)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(2)
            top = QHBoxLayout()
            top.addWidget(self.title)
            top.addStretch()
            top.addWidget(self.value_lbl)
            lay.addLayout(top)
            lay.addWidget(self.slider)
        self.slider.valueChanged.connect(self._emit)
        self.slider.mouseDoubleClickEvent = lambda e: self.changed.emit(self.reset_value()) if self.default is not None else None
        self.default = None
        self._emit(self.slider.value(), silent=True)

    def reset_value(self):
        self.set_value(self.default)
        return self.default

    def value(self):
        return self.slider.value() * self.step

    def set_value(self, v):
        self.slider.blockSignals(True)
        self.slider.setValue(int(round(v / self.step)))
        self.slider.blockSignals(False)
        self.value_lbl.setText(self.fmt(self.value()))

    def _emit(self, _v, silent=False):
        self.value_lbl.setText(self.fmt(self.value()))
        if not silent:
            self.changed.emit(self.value())


def _card(title, subtitle=None):
    f = QFrame()
    f.setObjectName("studiocard")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(18, 14, 18, 16)
    lay.setSpacing(10)
    t = QLabel(title)
    t.setObjectName("h3")
    lay.addWidget(t)
    if subtitle:
        s = QLabel(subtitle)
        s.setObjectName("small")
        s.setWordWrap(True)
        lay.addWidget(s)
    return f, lay


def _db(v):
    return f"{v:+.1f} dB" if abs(v) >= 0.05 else "0 dB"


# =========================================================================== page
class StudioPage(QScrollArea):
    saved = Signal(str)            # message (depuis un thread d'enregistrement)
    pitch_ready = Signal(int, object)
    batch_step = Signal(str)

    def __init__(self, main):
        super().__init__()
        self.m = main
        self.track = None
        self.audio = None
        self.bpm = 0
        self.params = dsp.params_with()
        self._mode = "edit"          # « edit » = modifié, « orig » = original
        self._save_after_render = None
        self._pitch_cache = {}
        self._pitch_job = None
        self._batch = None
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        root = QVBoxLayout(body)
        root.setContentsMargins(28, 6, 28, 28)
        root.setSpacing(14)
        self.setWidget(body)

        self.loader = AudioLoader(self)
        self.loader.loaded.connect(self._on_loaded)
        self.loader.failed.connect(lambda msg: self._status(f"Impossible de lire ce son : {msg}", err=True))
        self.worker = RenderWorker()
        self.worker.done.connect(self._on_rendered)
        self.worker.failed.connect(lambda msg: self._status(f"Erreur de calcul : {msg}", err=True))
        self.worker.start()
        self._render_timer = QTimer(self, singleShot=True, interval=900, timeout=self._request_render)
        self._remember_timer = QTimer(self, singleShot=True, interval=800, timeout=self._remember_settings)
        self.saved.connect(self._on_saved)
        self.pitch_ready.connect(self._on_pitch_ready)
        self.batch_step.connect(self._batch_done_one)

        # lecture en direct : chaque réglage s'entend immédiatement
        self.live = LivePlayer(self)
        self.engine = self.live.engine
        self.live.state_changed.connect(lambda _p: self._sync_play_icon())
        self.live.finished.connect(self._sync_play_icon)
        self._ui_timer = QTimer(self, interval=40, timeout=self._tick)
        self._ui_timer.start()

        # ---------------------------------------------------------------- en-tête + choix du son
        h1 = QLabel("Studio")
        h1.setObjectName("h1")
        root.addWidget(h1)
        sub = QLabel("Modifie n'importe quel son de ta bibliothèque : basses, égaliseur, volume, tempo, "
                     "tonalité, effets, découpe… Lance la lecture et bouge les curseurs : tu entends le "
                     "résultat en direct. Tes réglages sont mémorisés pour chaque son.")
        sub.setObjectName("sub")
        sub.setWordWrap(True)
        root.addWidget(sub)

        pick = QHBoxLayout()
        pick.setSpacing(10)
        self.source_box = QComboBox()
        self.source_box.setMinimumWidth(200)
        self.source_box.currentIndexChanged.connect(self._fill_tracks)
        self.track_box = QComboBox()
        self.track_box.setEditable(True)
        self.track_box.setInsertPolicy(QComboBox.NoInsert)
        self.track_box.setMinimumWidth(380)
        self.track_box.lineEdit().setPlaceholderText("Choisis ou tape le nom d'un son…")
        for box in (self.source_box, self.track_box):
            box.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            box.setMinimumContentsLength(18)
        comp = self.track_box.completer()
        comp.setFilterMode(Qt.MatchContains)
        comp.setCompletionMode(QCompleter.PopupCompletion)
        self.track_box.activated.connect(self._on_pick)
        pick.addWidget(QLabel("Source"))
        pick.addWidget(self.source_box)
        pick.addSpacing(8)
        pick.addWidget(QLabel("Son"))
        pick.addWidget(self.track_box, 1)
        root.addLayout(pick)

        # ---------------------------------------------------------------- titre chargé + forme d'onde
        info = QHBoxLayout()
        info.setSpacing(14)
        self.cover = QLabel()
        self.cover.setFixedSize(64, 64)
        info.addWidget(self.cover)
        tcol = QVBoxLayout()
        tcol.setSpacing(2)
        self.t_title = QLabel("Aucun son chargé")
        self.t_title.setObjectName("h2")
        self.t_meta = QLabel("")
        self.t_meta.setObjectName("sub")
        tcol.addStretch()
        tcol.addWidget(self.t_title)
        tcol.addWidget(self.t_meta)
        tcol.addStretch()
        info.addLayout(tcol, 1)
        self.status = QLabel("")
        self.status.setObjectName("chip")
        info.addWidget(self.status, 0, Qt.AlignVCenter)
        root.addLayout(info)

        self.wave = WaveformView(lambda: self.m.settings.colors)
        self.wave.trim_changed.connect(self._on_trim)
        self.wave.seek_requested.connect(self._seek_orig)
        root.addWidget(self.wave)

        tr = QHBoxLayout()
        tr.setSpacing(10)
        self.play_btn = QPushButton()
        self.play_btn.setObjectName("playmain")
        self.play_btn.setFixedSize(34, 34)
        self.play_btn.setIconSize(QSize(16, 16))
        self.play_btn.setCursor(Qt.PointingHandCursor)
        self.play_btn.clicked.connect(self.toggle_play)
        self.time_lbl = QLabel("0:00 / 0:00")
        self.time_lbl.setObjectName("small")
        self.seek = ClickSlider()
        self.seek.sliderMoved.connect(self._seek_out)
        self.meter = LevelMeter(lambda: self.m.settings.colors)
        self.seg_edit = QPushButton("Modifié")
        self.seg_orig = QPushButton("Original")
        self.seg_edit.setObjectName("segL")
        self.seg_orig.setObjectName("segR")
        for b in (self.seg_edit, self.seg_orig):
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
        self.seg_edit.setChecked(True)
        self.seg_edit.clicked.connect(lambda: self._set_mode("edit"))
        self.seg_orig.clicked.connect(lambda: self._set_mode("orig"))
        self.trim_lbl = QLabel("")
        self.trim_lbl.setObjectName("small")
        reset_trim = QPushButton("Annuler la découpe")
        reset_trim.setObjectName("ghost")
        reset_trim.clicked.connect(lambda: self._on_trim(0.0, self.wave.duration))
        tr.addWidget(self.play_btn)
        tr.addWidget(self.time_lbl)
        tr.addWidget(self.seek, 1)
        tr.addWidget(self.meter)
        tr.addSpacing(6)
        seg = QHBoxLayout()
        seg.setSpacing(0)
        seg.addWidget(self.seg_edit)
        seg.addWidget(self.seg_orig)
        tr.addLayout(seg)
        tr.addSpacing(6)
        tr.addWidget(self.trim_lbl)
        tr.addWidget(reset_trim)
        root.addLayout(tr)
        hint = QLabel("Astuce : tire les poignées blanches de la forme d'onde pour couper le début ou la fin, "
                      "clique dessus pour te déplacer. Double-clic sur un curseur = remise à zéro. "
                      "Espace = lecture / pause.")
        hint.setObjectName("small")
        root.addWidget(hint)

        # ---------------------------------------------------------------- préréglages
        pr = QHBoxLayout()
        pr.setSpacing(8)
        lab = QLabel("Préréglages")
        lab.setObjectName("section")
        pr.addWidget(lab)
        for name in list(dsp.PRESETS) + ["Réinitialiser"]:
            b = QPushButton(name)
            b.setObjectName("ghost")
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, n=name: self.apply_preset(n))
            pr.addWidget(b)
        pr.addStretch()
        root.addLayout(pr)

        # ---------------------------------------------------------------- réglages
        self.controls = QWidget()
        grid = QGridLayout(self.controls)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(14)
        self.sliders = {}

        eq_card, eq = _card("Égaliseur", "Monte les basses pour plus de puissance, les aigus pour plus de clarté.")
        self.curve = EqCurve(lambda: self.m.settings.colors)
        eq.addWidget(self.curve)
        bands = QHBoxLayout()
        self.eq_sliders = []
        for i, (f, name, *_r) in enumerate(dsp.EQ_BANDS):
            label = f"{name}\n{f if f < 1000 else str(f // 1000) + 'k'} Hz"
            s = ParamSlider(label, -12, 12, 0.5, _db, vertical=True)
            s.default = 0.0
            s.changed.connect(lambda v, i=i: self._set_eq(i, v))
            self.eq_sliders.append(s)
            bands.addWidget(s)
        eq.addLayout(bands)
        grid.addWidget(eq_card, 0, 0, 2, 1)

        dyn_card, dyn = _card("Volume & dynamique")
        self._add(dyn, "gain", "Volume", -12, 12, 0.5, _db, "Gain général en décibels")
        self._add(dyn, "beats", "Impact des beats", 0, 100, 1, lambda v: f"{v:.0f} %",
                  "Fait ressortir les kicks et les snares")
        self._add(dyn, "punch", "Compression", 0, 100, 1, lambda v: f"{v:.0f} %",
                  "Rend le son plus dense et plus fort")
        self.normalize = QCheckBox("Normaliser (volume max sans saturer)")
        self.normalize.toggled.connect(lambda v: self._set("normalize", v))
        dyn.addWidget(self.normalize)
        self.levels = QLabel("")
        self.levels.setObjectName("small")
        dyn.addWidget(self.levels)
        dyn.addStretch()
        grid.addWidget(dyn_card, 0, 1)

        tempo_card, tempo = _card("Tempo & tonalité")
        self._add(tempo, "speed", "Vitesse (vinyle)", 0.5, 1.5, 0.01, lambda v: f"{v * 100:.0f} %",
                  "Change le tempo ET la tonalité (slowed / nightcore)")
        self._add(tempo, "pitch", "Tonalité", -12, 12, 1, lambda v: f"{v:+.0f} demi-ton{'s' if abs(v) > 1 else ''}",
                  "Change la hauteur sans changer le tempo")
        self.bpm_lbl = QLabel("")
        self.bpm_lbl.setObjectName("small")
        tempo.addWidget(self.bpm_lbl)
        tempo.addStretch()
        grid.addWidget(tempo_card, 1, 1)

        fx_card, fx = _card("Effets")
        self._add(fx, "reverb", "Réverbération", 0, 100, 1, lambda v: f"{v:.0f} %")
        self._add(fx, "pan8d", "Audio 8D", 0, 100, 1, lambda v: f"{v:.0f} %", "Le son tourne autour de toi (casque !)")
        self._add(fx, "width", "Largeur stéréo", 0, 200, 1, lambda v: "Mono" if v == 0 else f"{v:.0f} %")
        self._add(fx, "lofi", "Lo-fi", 0, 100, 1, lambda v: f"{v:.0f} %", "Son vintage, filtré, avec craquements")
        grid.addWidget(fx_card, 2, 0)

        edit_card, ed = _card("Montage")
        self._add(ed, "fade_in", "Fondu d'entrée", 0, 10, 0.5, lambda v: f"{v:.1f} s")
        self._add(ed, "fade_out", "Fondu de sortie", 0, 10, 0.5, lambda v: f"{v:.1f} s")
        ed.addStretch()
        grid.addWidget(edit_card, 2, 1)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 2)
        root.addWidget(self.controls)

        # ---------------------------------------------------------------- enregistrement
        save_card, sv = _card("Enregistrer")
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(QLabel("Nom"))
        self.name_edit = QLineEdit()
        row.addWidget(self.name_edit, 1)
        sv.addLayout(row)
        self.same_pl = QCheckBox("Ajouter aux mêmes playlists que l'original")
        self.same_pl.setChecked(True)
        sv.addWidget(self.same_pl)
        brow = QHBoxLayout()
        self.batch_btn = QPushButton("Enregistrer tous les sons de la source…")
        self.batch_btn.setObjectName("ghost")
        self.batch_btn.setToolTip("Applique ces réglages (sans la découpe) à tous les sons de la bibliothèque "
                                  "ou de la playlist choisie en haut, et les enregistre comme nouveaux titres")
        self.batch_btn.clicked.connect(self.save_all)
        brow.addWidget(self.batch_btn)
        brow.addStretch()
        self.export_btn = QPushButton("Exporter un fichier…")
        self.export_btn.setObjectName("ghost")
        self.export_btn.clicked.connect(self.export_file)
        self.save_btn = QPushButton("Enregistrer dans 4tafy")
        self.save_btn.setObjectName("accent")
        self.save_btn.setCursor(Qt.PointingHandCursor)
        self.save_btn.clicked.connect(self.save_to_library)
        brow.addWidget(self.export_btn)
        brow.addWidget(self.save_btn)
        sv.addLayout(brow)
        root.addWidget(save_card)
        root.addStretch()

        self._set_enabled(False)
        self._sync_all()

    # ------------------------------------------------------------------ construction
    def _add(self, layout, key, label, lo, hi, step, fmt, tip=""):
        s = ParamSlider(label, lo, hi, step, fmt, tip=tip)
        s.default = dsp.DEFAULT_PARAMS[key]
        s.changed.connect(lambda v, k=key: self._set(k, v))
        self.sliders[key] = s
        layout.addWidget(s)

    def _set_enabled(self, on):
        for w in (self.controls, self.save_btn, self.export_btn, self.play_btn, self.seek,
                  self.seg_edit, self.seg_orig, self.name_edit, self.batch_btn):
            w.setEnabled(on)

    def refresh_sources(self):
        cur = self.source_box.currentData()
        self.source_box.blockSignals(True)
        self.source_box.clear()
        self.source_box.addItem("Toute la bibliothèque", None)
        for pl in self.m.lib.playlists:
            self.source_box.addItem(f"Playlist : {pl['name']}", pl["id"])
        i = self.source_box.findData(cur)
        self.source_box.setCurrentIndex(max(0, i))
        self.source_box.blockSignals(False)
        self._fill_tracks()

    def _fill_tracks(self):
        pid = self.source_box.currentData()
        tracks = self.m.lib.playlist_tracks(pid) if pid else self.m.lib.all_tracks()
        self.track_box.blockSignals(True)
        self.track_box.clear()
        for t in tracks:
            label = f"{t['artist']} — {t['title']}" if t["artist"] else t["title"]
            if t.get("studio"):
                label += "   ✎ modifié"
            self.track_box.addItem(gfx.track_cover(t, 32, 4), label, t["id"])
        if self.track:
            i = self.track_box.findData(self.track["id"])
            self.track_box.setCurrentIndex(i)
        else:
            self.track_box.setCurrentIndex(-1)
        self.track_box.blockSignals(False)

    # ------------------------------------------------------------------ chargement
    def _on_pick(self, index):
        tid = self.track_box.itemData(index)
        if tid:
            self.load_track(tid)

    def load_track(self, tid):
        t = self.m.lib.get(tid)
        if not t:
            return
        if not t.get("path") or not Path(t["path"]).exists():
            self._status("Fichier introuvable pour ce son", err=True)
            return
        self.live.pause()
        self.track = t
        self.audio = None
        self._set_enabled(False)
        self.t_title.setText(t["title"])
        self.t_meta.setText(t["artist"] or "Artiste inconnu")
        self.cover.setPixmap(gfx.track_cover(t, 64, 8))
        self.name_edit.setText(f"{t['title']} (Studio)")
        i = self.track_box.findData(tid)
        if i < 0:
            self.source_box.setCurrentIndex(0)
            i = self.track_box.findData(tid)
        self.track_box.setCurrentIndex(i)
        self._status("Chargement du son…")
        self.loader.load(t["path"])

    def _on_loaded(self, audio):
        self.audio = audio
        self.worker.set_audio(audio)
        self.live.set_audio(audio)
        self.worker.pitch_cache = self._pitch_cache
        self._pitch_cache = {}
        self._pitch_job = None
        dur = len(audio) / dsp.SR
        self.wave.set_audio(dsp.peaks(audio), dur)
        saved = self.track.get("studio") or {}
        self.params = dsp.params_with({k: v for k, v in saved.items() if k in dsp.DEFAULT_PARAMS})
        self.bpm = dsp.estimate_bpm(audio)
        self._sync_all()
        self._set_enabled(True)
        self.live.seek(self.params["start"])
        self.t_meta.setText(f"{self.track['artist'] or 'Artiste inconnu'}  •  {fmt_time(dur)}"
                            + (f"  •  ≈ {self.bpm} BPM" if self.bpm else ""))
        self._status("Réglages mémorisés restaurés" if saved else "Prêt")
        self._changed(remember=False)

    # ------------------------------------------------------------------ réglages
    def _set(self, key, value):
        self.params[key] = value
        self._sync_labels()
        self._changed()

    def _set_eq(self, i, value):
        self.params["eq"][i] = value
        self.curve.set_gains(self.params["eq"])
        self._changed()

    def _on_trim(self, start, end):
        self.params["start"] = round(start, 2)
        self.params["end"] = None if end >= self.wave.duration - 0.05 else round(end, 2)
        self.wave.set_trim(start, end)
        self._sync_labels()
        if not self.engine.bypass and not (start <= self.live.position() < end):
            self.live.seek(start)
        self._changed()

    def apply_preset(self, name):
        keep = {"start": self.params["start"], "end": self.params["end"]}
        self.params = dsp.params_with(dsp.PRESETS.get(name, {}))
        self.params.update(keep)
        self._sync_all()
        self._changed()
        self.live.resync()
        if name != "Réinitialiser":
            self.m.toast(f"Préréglage « {name} » appliqué")

    def _sync_all(self):
        p = self.params
        for k, s in self.sliders.items():
            s.set_value(p[k])
        for s, g in zip(self.eq_sliders, p["eq"]):
            s.set_value(g)
        self.curve.set_gains(p["eq"])
        self.normalize.blockSignals(True)
        self.normalize.setChecked(p["normalize"])
        self.normalize.blockSignals(False)
        end = p["end"] if p["end"] else self.wave.duration
        self.wave.set_trim(p["start"], end)
        self._sync_labels()

    def _sync_labels(self):
        p = self.params
        if self.bpm:
            new = self.bpm * p["speed"]
            self.bpm_lbl.setText(f"Tempo d'origine ≈ {self.bpm} BPM" +
                                 (f"  →  {new:.0f} BPM" if abs(p["speed"] - 1) > 0.005 else ""))
        else:
            self.bpm_lbl.setText("")
        end = p["end"] if p["end"] else self.wave.duration
        cut = p["start"] > 0.05 or p["end"]
        self.trim_lbl.setText(f"Découpe : {fmt_time(p['start'])} → {fmt_time(end)}" if cut else "")

    # ------------------------------------------------------------------ rendu en direct
    def _changed(self, remember=True):
        """Un réglage a bougé : le moteur direct l'applique au prochain bloc (~23 ms)."""
        if self.audio is None:
            return
        self.engine.set_params(self.params)
        self._ensure_pitch()
        if self.params["normalize"]:
            self._render_timer.start()  # la normalisation a besoin de mesurer tout le morceau
        if remember:
            self._remember_timer.start()

    def _remember_settings(self):
        """Mémorise les réglages Studio de ce son (retrouvés à la prochaine ouverture)."""
        if not self.track:
            return
        default = dsp.params_with()
        keep = None if self.params == default else copy.deepcopy(self.params)
        if self.track.get("studio") != keep:
            self.m.lib.update_track(self.track["id"], studio=keep)
            i = self.track_box.findData(self.track["id"])
            if i >= 0:
                t = self.track
                label = f"{t['artist']} — {t['title']}" if t["artist"] else t["title"]
                self.track_box.setItemText(i, label + ("   ✎ modifié" if keep else ""))

    def _ensure_pitch(self):
        """La tonalité (sans changer le tempo) se pré-calcule une fois, en arrière-plan."""
        k = int(self.params["pitch"])
        if k == 0:
            self.live.set_source(None)
            return
        if k in self._pitch_cache:
            self.live.set_source(self._pitch_cache[k])
            return
        if self._pitch_job is not None:
            return
        self._pitch_job = k
        self._status(f"Calcul de la tonalité {k:+d}…")
        audio = self.audio

        def job():
            try:
                data = dsp.pitch_shift(audio, k)
                n = len(audio)
                data = data[:n] if len(data) >= n else np.pad(data, ((0, n - len(data)), (0, 0)))
            except Exception:
                data = None
            self.pitch_ready.emit(k, (audio, data))

        threading.Thread(target=job, daemon=True).start()

    def _on_pitch_ready(self, k, payload):
        audio, data = payload
        self._pitch_job = None
        if audio is not self.audio:
            return
        if data is not None:
            if len(self._pitch_cache) >= 2:
                self._pitch_cache.pop(next(iter(self._pitch_cache)))
            self._pitch_cache[k] = data
        self._status("Prêt")
        self._ensure_pitch()

    def _request_render(self):
        if self.audio is not None:
            self.worker.request(self.params)

    def _on_rendered(self, info, params):
        if self.audio is None:
            return
        self.engine.norm_gain = info["norm_gain"]
        lim = "  •  limiteur actif" if info["limited"] else ""
        self.levels.setText(f"Morceau complet : crête {info['peak_db']:.1f} dB  •  "
                            f"niveau moyen {info['rms_db']:.1f} dB{lim}")
        if self._save_after_render:
            action, self._save_after_render = self._save_after_render, None
            action()

    def _set_mode(self, mode):
        """Modifié / Original : on bascule instantanément, au même endroit du morceau."""
        self.seg_edit.setChecked(mode == "edit")
        self.seg_orig.setChecked(mode == "orig")
        self._mode = mode
        self.live.set_bypass(mode == "orig")
        if mode == "edit":
            p = self.params
            end = p["end"] or self.wave.duration
            if not (p["start"] <= self.live.position() < end):
                self.live.seek(p["start"])

    def toggle_play(self):
        if self.audio is None:
            return
        if self.live.playing:
            self.live.pause()
        else:
            if self.m.player.is_playing():
                self.m.player.toggle()
            self.live.set_volume(self.m.player.out.volume())
            self.live.play()

    def pause(self):
        if self.live.playing:
            self.live.pause()

    def _seek_orig(self, orig_s):
        if self.audio is not None:
            self.live.seek(orig_s)

    def _seek_out(self, ms):
        p = self.params
        t = ms / 1000 if self.engine.bypass else p["start"] + ms / 1000 * p["speed"]
        self.live.seek(t)

    def _tick(self):
        if self.audio is None or not self.isVisible():
            return
        pos, dur = self.live.output_time()
        if not self.seek.isSliderDown():
            self.seek.setRange(0, int(dur * 1000))
            self.seek.setValue(int(pos * 1000))
        self.time_lbl.setText(f"{fmt_time(pos)} / {fmt_time(dur)}")
        now = self.live.position()
        if self.wave.playhead != now:
            self.wave.playhead = now
            self.wave.update()
        if not self.live.playing:
            self.live.peak = self.live.peak * 0.6
        self.meter.set_levels(*[float(v) for v in self.live.peak])

    def _sync_play_icon(self):
        c = self.m.settings.colors
        self.play_btn.setIcon(gfx.icon("pause" if self.live.playing else "play", c["bg"]))

    def apply_theme(self):
        self._sync_play_icon()
        self.wave.update()
        self.curve.update()
        self.meter.update()

    def _status(self, text, err=False):
        self.status.setText(text)
        self.status.setVisible(bool(text))
        if err:
            self.m.toast(text)

    # ------------------------------------------------------------------ enregistrement
    def _ready_audio(self, action):
        """Renvoie le son correspondant aux réglages actuels (ou relance un calcul puis `action`)."""
        last = self.worker.last
        if last and last[1] == self.params and not self.worker.busy:
            return last[0]
        self._save_after_render = action
        self._request_render()
        self._status("Calcul avant enregistrement…")
        return None

    def save_to_library(self):
        y = self._ready_audio(self.save_to_library)
        if y is None:
            return
        t = self.track
        name = self.name_edit.text().strip() or f"{t['title']} (Studio)"
        same_pl = self.same_pl.isChecked()
        self.save_btn.setEnabled(False)
        self._status("Enregistrement…")

        def job():
            try:
                n_pl = self._store(y, t, name, same_pl)
                self.saved.emit(f"« {name} » ajouté à ta bibliothèque" +
                                (f" et à {n_pl} playlist(s)" if n_pl else ""))
            except Exception as e:
                self.saved.emit(f"Échec de l'enregistrement : {e}")

        threading.Thread(target=job, daemon=True).start()

    def _store(self, y, t, name, same_pl):
        """Écrit le son modifié (MP3, sinon WAV) et l'ajoute à la bibliothèque. Renvoie le nb de playlists."""
        ext = ".mp3" if dsp.mp3_available() else ".wav"
        dest = MUSIC_DIR / f"Studio_{uuid.uuid4().hex[:10]}{ext}"
        (dsp.write_mp3 if ext == ".mp3" else dsp.write_wav)(dest, y)
        cover = ""
        if t.get("cover") and Path(t["cover"]).exists():
            cover = str(COVERS_DIR / f"studio_{dest.stem}{Path(t['cover']).suffix}")
            Path(cover).write_bytes(Path(t["cover"]).read_bytes())
        new = self.m.lib.add_track(title=name, artist=t["artist"], album=t["album"],
                                   duration=len(y) / dsp.SR, path=str(dest), cover=cover,
                                   source="studio", source_id="", url="")
        pls = [pl["id"] for pl in self.m.lib.playlists if t["id"] in pl["tracks"]] if same_pl else []
        for pid in pls:
            self.m.lib.add_to_playlist(pid, [new["id"]])
        return len(pls)

    # ------------------------------------------------------------------ enregistrer tous les sons
    def save_all(self):
        if self._batch:
            self._batch["queue"].clear()
            self._status("Arrêt après le son en cours…")
            return
        pid = self.source_box.currentData()
        lib = self.m.lib
        tracks = lib.playlist_tracks(pid) if pid else lib.all_tracks()
        tracks = [t for t in tracks if t["source"] != "studio" and t.get("path") and Path(t["path"]).exists()]
        if not tracks:
            self.m.toast("Aucun son à traiter dans cette source")
            return
        src = self.source_box.currentText()
        if QMessageBox.question(
                self, "Enregistrer tous les sons",
                f"Appliquer les réglages actuels à {len(tracks)} son(s) de « {src} » et les enregistrer "
                "comme nouveaux titres ?\n\nLa découpe n'est pas appliquée (chaque son garde sa durée) et "
                "les originaux ne sont pas modifiés.") != QMessageBox.Yes:
            return
        params = copy.deepcopy(self.params)
        params["start"], params["end"] = 0.0, None
        self._batch = {"queue": [t["id"] for t in tracks], "params": params, "done": 0, "ok": 0,
                       "total": len(tracks), "same_pl": self.same_pl.isChecked(), "cur": None}
        self.batch_btn.setText("Arrêter l'enregistrement en lot")
        self._batch_loader = AudioLoader(self)
        self._batch_loader.loaded.connect(self._batch_loaded)
        self._batch_loader.failed.connect(lambda msg: self.batch_step.emit(f"illisible : {msg}"))
        self._batch_next()

    def _batch_next(self):
        b = self._batch
        if not b["queue"]:
            self.m.toast(f"Enregistrement terminé : {b['ok']} son(s) ajouté(s) à ta bibliothèque")
            self._status("Prêt")
            self.batch_btn.setText("Enregistrer tous les sons de la source…")
            self._batch = None
            self.m.schedule_refresh()
            return
        b["cur"] = b["queue"].pop(0)
        t = self.m.lib.get(b["cur"])
        self._status(f"Tous les sons : {b['done'] + 1}/{b['total']} — {t['title'][:40]}")
        self._batch_loader.load(t["path"])

    def _batch_loaded(self, audio):
        b = self._batch
        t = self.m.lib.get(b["cur"])

        def job():
            try:
                y, _info = render_offline(audio, b["params"])
                self._store(y, t, f"{t['title']} (Studio)", b["same_pl"])
                self.batch_step.emit("")
            except Exception as e:
                self.batch_step.emit(str(e))

        threading.Thread(target=job, daemon=True).start()

    def _batch_done_one(self, error):
        b = self._batch
        if not b:
            return
        b["done"] += 1
        if error:
            self.m.toast(f"Son ignoré : {error[:80]}")
        else:
            b["ok"] += 1
        self.m.schedule_refresh()
        self._batch_next()

    def export_file(self):
        y = self._ready_audio(self.export_file)
        if y is None:
            return
        name = (self.name_edit.text().strip() or "4tafy studio").replace("/", "-").replace("\\", "-")
        filters = ("MP3 (*.mp3);;WAV (*.wav)" if dsp.mp3_available() else "WAV (*.wav)")
        path, chosen = QFileDialog.getSaveFileName(self, "Exporter le son", str(Path.home() / "Music" / name),
                                                   filters)
        if not path:
            return
        if not Path(path).suffix:
            path += ".mp3" if "mp3" in chosen.lower() else ".wav"
        self._status("Export…")

        def job():
            try:
                (dsp.write_mp3 if path.lower().endswith(".mp3") else dsp.write_wav)(path, y)
                self.saved.emit(f"Exporté : {Path(path).name}")
            except Exception as e:
                self.saved.emit(f"Échec de l'export : {e}")

        threading.Thread(target=job, daemon=True).start()

    def _on_saved(self, msg):
        self.save_btn.setEnabled(self.audio is not None)
        self._status("Prêt")
        self.m.toast(msg)
        self.m.schedule_refresh()

    def shutdown(self):
        self._remember_settings()
        self.live.stop()
        self.worker.stop()
        self.worker.wait(3000)
