"""Page « Plugins » : installer / activer des plugins et les appliquer à un son."""
import os
import tempfile
import threading
import uuid
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (QCheckBox, QComboBox, QCompleter, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
                               QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton, QScrollArea, QVBoxLayout,
                               QWidget)

from . import graphics as gfx
from . import plugins as plug
from . import studio_dsp as dsp
from .config import COVERS_DIR, MUSIC_DIR
from .studio_page import AudioLoader, ParamSlider
from .widgets import Clickable, FlowLayout, clear_layout, fmt_time

PREVIEW_SECONDS = 30


class PluginCard(Clickable):
    def __init__(self, page, pl, enabled, selected):
        super().__init__("pcard")
        self.setProperty("selected", selected)
        self.setFixedWidth(300)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(4)
        top = QHBoxLayout()
        ic = QLabel()
        ic.setPixmap(gfx.icon("puzzle", page.m.settings.colors["accent"]).pixmap(QSize(26, 26)))
        top.addWidget(ic)
        name = QLabel(pl.name)
        name.setObjectName("h3")
        top.addWidget(name, 1)
        if pl.builtin:
            b = QLabel("intégré")
            b.setObjectName("chip")
            top.addWidget(b)
        lay.addLayout(top)
        meta = QLabel(" • ".join(x for x in (f"v{pl.version}" if pl.version else "",
                                              f"par {pl.author}" if pl.author else "") if x))
        meta.setObjectName("small")
        lay.addWidget(meta)
        desc = QLabel(pl.error if pl.error else pl.description)
        desc.setObjectName("sub")
        desc.setWordWrap(True)
        if pl.error:
            desc.setStyleSheet("color:#ff453a;")
        lay.addWidget(desc)
        row = QHBoxLayout()
        self.enabled = QCheckBox("Activé")
        self.enabled.setChecked(enabled and pl.ok)
        self.enabled.setEnabled(pl.ok)
        self.enabled.toggled.connect(lambda on: page.set_enabled(pl.id, on))
        row.addWidget(self.enabled)
        row.addStretch()
        if not pl.builtin:
            rm = QPushButton("Supprimer")
            rm.setObjectName("ghost")
            rm.clicked.connect(lambda: page.remove(pl))
            row.addWidget(rm)
        lay.addLayout(row)
        self.clicked.connect(lambda: page.select(pl.id))


class PluginsPage(QScrollArea):
    progress_sig = Signal(float, str)
    done_sig = Signal(object, object)    # (son, mode) mode = "preview" | "save"
    failed_sig = Signal(str)

    def __init__(self, main):
        super().__init__()
        self.m = main
        self.plugins = []
        self.current = None
        self.track = None
        self.audio = None
        self.audio_tid = None
        self._pending = None
        self._busy = False
        self.widgets = {}
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        root = QVBoxLayout(body)
        root.setContentsMargins(28, 6, 28, 28)
        root.setSpacing(14)
        self.setWidget(body)

        self.loader = AudioLoader(self)
        self.loader.loaded.connect(self._on_loaded)
        self.loader.failed.connect(lambda msg: self._fail(f"Impossible de lire ce son : {msg}"))
        self.progress_sig.connect(self._on_progress)
        self.done_sig.connect(self._on_done)
        self.failed_sig.connect(self._fail)
        self.player = QMediaPlayer(self)
        self.out = QAudioOutput(self)
        self.player.setAudioOutput(self.out)
        self.player.playbackStateChanged.connect(lambda _s: self._sync_preview_btn())
        self._preview_file = Path(tempfile.gettempdir()) / f"4tafy_plugin_{os.getpid()}.wav"

        h1 = QLabel("Plugins")
        h1.setObjectName("h1")
        root.addWidget(h1)
        sub = QLabel("Ajoute des transformations à 4tafy. Un plugin est un simple fichier Python (.py) : "
                     "installe uniquement ceux qui viennent d'une source de confiance.")
        sub.setObjectName("sub")
        sub.setWordWrap(True)
        root.addWidget(sub)

        bar = QHBoxLayout()
        for text, fn, name in (("Installer un plugin…", self.install, "accent"),
                               ("Créer un plugin (modèle)", self.create_template, "ghost"),
                               ("Ouvrir le dossier des plugins", self.open_folder, "ghost"),
                               ("Recharger", self.reload, "ghost")):
            b = QPushButton(text)
            b.setObjectName(name)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch()
        root.addLayout(bar)

        t = QLabel("Installés")
        t.setObjectName("h2")
        root.addWidget(t)
        self.cards_holder = QWidget()
        self.cards = FlowLayout(self.cards_holder, spacing=14)
        root.addWidget(self.cards_holder)

        # ---------------------------------------------------------------- utilisation
        self.panel = QFrame()
        self.panel.setObjectName("studiocard")
        pl = QVBoxLayout(self.panel)
        pl.setContentsMargins(20, 16, 20, 18)
        pl.setSpacing(12)
        self.p_title = QLabel("")
        self.p_title.setObjectName("h2")
        self.p_desc = QLabel("")
        self.p_desc.setObjectName("sub")
        self.p_desc.setWordWrap(True)
        pl.addWidget(self.p_title)
        pl.addWidget(self.p_desc)

        pick = QHBoxLayout()
        self.source_box = QComboBox()
        self.source_box.setMinimumWidth(200)
        self.source_box.currentIndexChanged.connect(self._fill_tracks)
        self.track_box = QComboBox()
        self.track_box.setEditable(True)
        self.track_box.setInsertPolicy(QComboBox.NoInsert)
        self.track_box.lineEdit().setPlaceholderText("Choisis le son à transformer…")
        for box in (self.source_box, self.track_box):  # ne pas s'élargir selon le titre le plus long
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
        pl.addLayout(pick)

        self.params_holder = QWidget()
        self.params_grid = QGridLayout(self.params_holder)
        self.params_grid.setContentsMargins(0, 4, 0, 4)
        self.params_grid.setHorizontalSpacing(28)
        self.params_grid.setVerticalSpacing(10)
        self.params_grid.setColumnStretch(0, 1)
        self.params_grid.setColumnStretch(1, 1)
        pl.addWidget(self.params_holder)

        prog = QHBoxLayout()
        self.preview_btn = QPushButton(f"  Écouter un aperçu ({PREVIEW_SECONDS} s)")
        self.preview_btn.setObjectName("ghost")
        self.preview_btn.setCursor(Qt.PointingHandCursor)
        self.preview_btn.clicked.connect(self.preview)
        self.reset_btn = QPushButton("Réglages par défaut")
        self.reset_btn.setObjectName("ghost")
        self.reset_btn.clicked.connect(self._reset_params)
        self.status = QLabel("")
        self.status.setObjectName("small")
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setFixedWidth(220)
        self.bar.hide()
        prog.addWidget(self.preview_btn)
        prog.addWidget(self.reset_btn)
        prog.addSpacing(10)
        prog.addWidget(self.status, 1)
        prog.addWidget(self.bar)
        pl.addLayout(prog)

        save = QHBoxLayout()
        save.addWidget(QLabel("Nom"))
        self.name_edit = QLineEdit()
        save.addWidget(self.name_edit, 1)
        self.same_pl = QCheckBox("Ajouter aux mêmes playlists")
        self.same_pl.setChecked(True)
        save.addWidget(self.same_pl)
        self.apply_btn = QPushButton("Appliquer et enregistrer")
        self.apply_btn.setObjectName("accent")
        self.apply_btn.setCursor(Qt.PointingHandCursor)
        self.apply_btn.clicked.connect(self.apply)
        save.addWidget(self.apply_btn)
        pl.addLayout(save)
        root.addWidget(self.panel)
        root.addStretch()
        self.reload()

    # ------------------------------------------------------------------ liste des plugins
    def disabled(self):
        return set(self.m.settings.data.get("plugins_disabled", []))

    def enabled_plugins(self):
        off = self.disabled()
        return [p for p in self.plugins if p.ok and p.id not in off]

    def reload(self):
        self.plugins = plug.discover()
        if self.current not in [p.id for p in self.plugins]:
            ok = self.enabled_plugins()
            self.current = ok[0].id if ok else None
        self._render_cards()
        self._build_panel()

    def _render_cards(self):
        clear_layout(self.cards)
        off = self.disabled()
        for p in self.plugins:
            self.cards.addWidget(PluginCard(self, p, p.id not in off, p.id == self.current))

    def set_enabled(self, pid, on):
        off = self.disabled()
        off.discard(pid) if on else off.add(pid)
        self.m.settings.data["plugins_disabled"] = sorted(off)
        self.m.settings.save()
        if pid == self.current:
            self._build_panel()

    def select(self, pid):
        if pid != self.current:
            self.current = pid
            self._render_cards()
            self._build_panel()

    def plugin(self):
        return next((p for p in self.plugins if p.id == self.current), None)

    def install(self):
        path, _ = QFileDialog.getOpenFileName(self, "Installer un plugin 4tafy", str(Path.home() / "Downloads"),
                                              "Plugin 4tafy (*.py)")
        if not path:
            return
        if QMessageBox.question(
                self, "Installer un plugin",
                f"Installer « {Path(path).name} » ?\n\nUn plugin est du code Python qui s'exécute sur ton "
                "ordinateur : installe-le seulement s'il vient d'une source de confiance.") != QMessageBox.Yes:
            return
        try:
            pl = plug.install(path)
        except Exception as e:
            QMessageBox.warning(self, "4tafy", f"Ce plugin ne peut pas être installé :\n{e}")
            return
        self.current = pl.id
        self.reload()
        self.m.toast(f"Plugin « {pl.name} » installé")

    def remove(self, pl):
        if QMessageBox.question(self, "Supprimer", f"Supprimer le plugin « {pl.name} » ?") == QMessageBox.Yes:
            plug.uninstall(pl)
            self.reload()

    def create_template(self):
        dest = plug.write_template()
        self.reload()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(dest.parent)))
        self.m.toast(f"Modèle créé : {dest.name} — modifie-le puis clique sur « Recharger »")

    def open_folder(self):
        plug.USER_DIR.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(plug.USER_DIR)))

    # ------------------------------------------------------------------ panneau d'utilisation
    def _build_panel(self):
        pl = self.plugin()
        usable = pl is not None and pl.ok and pl.id not in self.disabled()
        self.panel.setVisible(pl is not None)
        if pl is None:
            return
        self.p_title.setText(f"Utiliser : {pl.name}")
        self.p_desc.setText(pl.description if usable else "Active ce plugin pour l'utiliser.")
        clear_layout(self.params_grid)
        self.widgets = {}
        for i, prm in enumerate(pl.params):
            w = self._make_param(prm)
            self.params_grid.addWidget(w, i // 2, i % 2)
        for w in (self.params_holder, self.preview_btn, self.apply_btn, self.reset_btn, self.track_box,
                  self.source_box, self.name_edit):
            w.setEnabled(usable)
        self._update_name()

    def _make_param(self, prm):
        key, kind, label = prm["key"], prm["type"], prm["label"]
        saved = self.m.settings.data.get("plugin_params", {}).get(self.current, {})
        value = saved.get(key, prm.get("default"))
        if kind == "slider":
            unit = prm.get("unit", "")
            step = prm.get("step", 1)
            fmt = (lambda v, u=unit: f"{v:.0f}{u}") if float(step).is_integer() else (lambda v, u=unit: f"{v:.2f}{u}")
            w = ParamSlider(label, prm.get("min", 0), prm.get("max", 100), step, fmt)
            w.default = prm.get("default", prm.get("min", 0))
            w.set_value(value)
            w.changed.connect(lambda v, k=key: self._remember(k, v))
            self.widgets[key] = ("slider", w)
        elif kind == "bool":
            w = QCheckBox(label)
            w.setChecked(bool(value))
            w.toggled.connect(lambda v, k=key: self._remember(k, v))
            self.widgets[key] = ("bool", w)
        else:
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(0, 0, 0, 0)
            h.addWidget(QLabel(label))
            box = QComboBox()
            box.addItems([str(c) for c in prm.get("choices", [])])
            box.setCurrentText(str(value))
            box.currentTextChanged.connect(lambda v, k=key: self._remember(k, v))
            h.addWidget(box, 1)
            self.widgets[key] = ("choice", box)
        return w

    def _remember(self, key, value):
        allp = self.m.settings.data.setdefault("plugin_params", {})
        allp.setdefault(self.current, {})[key] = value
        self.m.settings.save()

    def _reset_params(self):
        self.m.settings.data.setdefault("plugin_params", {}).pop(self.current, None)
        self.m.settings.save()
        self._build_panel()

    def values(self):
        out = {}
        for key, (kind, w) in self.widgets.items():
            out[key] = w.value() if kind == "slider" else w.isChecked() if kind == "bool" else w.currentText()
        return out

    # ------------------------------------------------------------------ choix du son
    def refresh_sources(self):
        cur = self.source_box.currentData()
        self.source_box.blockSignals(True)
        self.source_box.clear()
        self.source_box.addItem("Toute la bibliothèque", None)
        for p in self.m.lib.playlists:
            self.source_box.addItem(f"Playlist : {p['name']}", p["id"])
        self.source_box.setCurrentIndex(max(0, self.source_box.findData(cur)))
        self.source_box.blockSignals(False)
        self._fill_tracks()

    def _fill_tracks(self):
        pid = self.source_box.currentData()
        tracks = self.m.lib.playlist_tracks(pid) if pid else self.m.lib.all_tracks()
        self.track_box.blockSignals(True)
        self.track_box.clear()
        for t in tracks:
            label = f"{t['artist']} — {t['title']}" if t["artist"] else t["title"]
            self.track_box.addItem(gfx.track_cover(t, 32, 4), label, t["id"])
        self.track_box.setCurrentIndex(self.track_box.findData(self.track["id"]) if self.track else -1)
        self.track_box.blockSignals(False)

    def _on_pick(self, index):
        tid = self.track_box.itemData(index)
        if tid:
            self.set_track(tid)

    def set_track(self, tid):
        t = self.m.lib.get(tid)
        if not t:
            return
        self.track = t
        i = self.track_box.findData(tid)
        if i < 0:
            self.source_box.setCurrentIndex(0)
            i = self.track_box.findData(tid)
        self.track_box.setCurrentIndex(i)
        self._update_name()
        self.status.setText(f"{t['title']} • {fmt_time(t['duration'])}")

    def _update_name(self):
        pl = self.plugin()
        if self.track and pl:
            self.name_edit.setText(f"{self.track['title']} ({pl.suffix})")

    def open_with(self, pid, tid):
        self.select(pid)
        self.refresh_sources()
        self.set_track(tid)

    # ------------------------------------------------------------------ exécution
    def preview(self):
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.stop()
            return
        self._start("preview")

    def apply(self):
        self._start("save")

    def _start(self, mode):
        if self._busy:
            return
        if not self.track:
            self.m.toast("Choisis d'abord un son")
            return
        if not Path(self.track.get("path", "")).exists():
            self._fail("Fichier introuvable pour ce son")
            return
        self._pending = (mode, self.plugin(), self.values())
        self._busy = True
        self._set_busy(True, "Chargement du son…")
        if self.audio is not None and self.audio_tid == self.track["id"]:
            self._run()
        else:
            self.loader.load(self.track["path"])

    def _on_loaded(self, audio):
        self.audio = audio
        self.audio_tid = self.track["id"] if self.track else None
        if self._pending:
            self._run()

    def _run(self):
        mode, pl, params = self._pending
        audio = self.audio
        if mode == "preview":  # extrait pris vers le premier tiers (souvent le refrain)
            start = int(len(audio) * 0.3)
            audio = audio[start: start + dsp.SR * int(PREVIEW_SECONDS * 1.6)]
        t = self.track

        def job():
            try:
                bpm = dsp.estimate_bpm(self.audio)
                y = plug.run(pl, audio, params, bpm=bpm, progress=lambda f, m: self.progress_sig.emit(f, m))
                if mode == "preview":
                    y = y[: dsp.SR * PREVIEW_SECONDS]
                    dsp.write_wav(self._preview_file, y)
                    self.done_sig.emit(None, "preview")
                else:
                    self.progress_sig.emit(1.0, "Enregistrement du fichier…")
                    self.done_sig.emit(self._store(y, t, pl), "save")
            except Exception as e:
                self.failed_sig.emit(f"Le plugin a échoué : {e}")

        threading.Thread(target=job, daemon=True).start()

    def _store(self, y, t, pl):
        ext = ".mp3" if dsp.mp3_available() else ".wav"
        dest = MUSIC_DIR / f"Plugin_{pl.id}_{uuid.uuid4().hex[:8]}{ext}"
        (dsp.write_mp3 if ext == ".mp3" else dsp.write_wav)(dest, y)
        cover = ""
        if t.get("cover") and Path(t["cover"]).exists():
            cover = str(COVERS_DIR / f"plugin_{dest.stem}{Path(t['cover']).suffix}")
            Path(cover).write_bytes(Path(t["cover"]).read_bytes())
        name = self.name_edit.text().strip() or f"{t['title']} ({pl.suffix})"
        new = self.m.lib.add_track(title=name, artist=t["artist"], album=t["album"], duration=len(y) / dsp.SR,
                                   path=str(dest), cover=cover, source="studio", source_id="", url="")
        n = 0
        if self.same_pl.isChecked():
            for p in self.m.lib.playlists:
                if t["id"] in p["tracks"]:
                    self.m.lib.add_to_playlist(p["id"], [new["id"]])
                    n += 1
        return new, n

    def _on_progress(self, frac, msg):
        self.bar.setValue(int(frac * 1000))
        if msg:
            self.status.setText(msg)

    def _on_done(self, result, mode):
        self._busy = False
        self._set_busy(False)
        if mode == "preview":
            self.status.setText("Aperçu prêt")
            if self.m.player.is_playing():
                self.m.player.toggle()
            self.out.setVolume(self.m.player.out.volume())
            self.player.setSource(QUrl())
            self.player.setSource(QUrl.fromLocalFile(str(self._preview_file)))
            self.player.play()
        else:
            new, n = result
            self.status.setText(f"« {new['title']} » ajouté à ta bibliothèque")
            self.m.toast(f"« {new['title']} » ajouté" + (f" (et à {n} playlist(s))" if n else ""))
            self.m.schedule_refresh()

    def _fail(self, msg):
        self._busy = False
        self._set_busy(False)
        self.status.setText(msg)
        self.m.toast(msg)

    def _set_busy(self, on, text=""):
        self.bar.setVisible(on)
        self.bar.setValue(0)
        for w in (self.preview_btn, self.apply_btn, self.reset_btn):
            w.setEnabled(not on)
        if text:
            self.status.setText(text)

    def _sync_preview_btn(self):
        playing = self.player.playbackState() == QMediaPlayer.PlayingState
        self.preview_btn.setText("  Arrêter l'aperçu" if playing else f"  Écouter un aperçu ({PREVIEW_SECONDS} s)")
        c = self.m.settings.colors
        self.preview_btn.setIcon(gfx.icon("pause" if playing else "play", c["text"]))

    def pause(self):
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()

    def apply_theme(self):
        self._sync_preview_btn()
        self._render_cards()

    def shutdown(self):
        self.player.stop()
        self.player.setSource(QUrl())
        try:
            self._preview_file.unlink(missing_ok=True)
        except OSError:
            pass

