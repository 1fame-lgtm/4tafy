"""Fenêtre principale de 4tafy : barre latérale, pages, barre de lecture."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPushButton, QStackedWidget,
                               QVBoxLayout, QWidget)

from . import graphics as gfx
from .config import AUDIO_EXTENSIONS, COVERS_DIR, IMAGE_FILTER, Settings, ensure_dirs
from .importer import ImportWorker
from .library import Library
from .pages import HomePage, ImportPage, QueuePage, TrackListPage
from .player import REPEAT_OFF, REPEAT_ONE, Player
from .settings_page import SettingsPage
from .studio_page import StudioPage
from .plugins_page import PluginsPage
from .themes import build_qss, on_color
from .chrome import ContentFrame, DragArea, TrafficLights, WindowBackground, WindowOutline
from .widgets import ClickSlider, fmt_time

AUDIO_FILTER = "Audio (" + " ".join(f"*{e}" for e in sorted(AUDIO_EXTENSIONS)) + " *.m3u *.m3u8)"


class EditTrackDialog(QDialog):
    def __init__(self, parent, track):
        super().__init__(parent)
        self.setWindowTitle("Modifier les infos")
        self.track = track
        self.new_cover = None
        lay = QHBoxLayout(self)
        lay.setSpacing(18)
        left = QVBoxLayout()
        self.cover = QLabel()
        self.cover.setFixedSize(180, 180)
        self.cover.setPixmap(gfx.track_cover(track, 180, 8))
        left.addWidget(self.cover)
        b = QPushButton("Changer la pochette…")
        b.setObjectName("dlg")
        b.clicked.connect(self._pick)
        left.addWidget(b)
        left.addStretch()
        lay.addLayout(left)
        form = QFormLayout()
        self.title = QLineEdit(track["title"])
        self.artist = QLineEdit(track["artist"])
        self.album = QLineEdit(track["album"])
        form.addRow("Titre", self.title)
        form.addRow("Artiste", self.artist)
        form.addRow("Album", self.album)
        right = QVBoxLayout()
        right.addLayout(form)
        right.addStretch()
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Save).setText("Enregistrer")
        bb.button(QDialogButtonBox.Cancel).setText("Annuler")
        for btn in bb.buttons():
            btn.setObjectName("dlg")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        right.addWidget(bb)
        lay.addLayout(right, 1)
        self.resize(560, 240)

    def _pick(self):
        path, _ = QFileDialog.getOpenFileName(self, "Pochette", str(Path.home() / "Pictures"), IMAGE_FILTER)
        if path:
            self.new_cover = path
            pm = gfx.load_square(path, 180)
            if pm:
                self.cover.setPixmap(pm)


class MainWindow(QMainWindow):
    NAV = [
        ("4tafy", [("home", "Accueil", "home"), ("library", "Bibliothèque", "library"),
                   ("liked", "Titres likés", "heart_full")]),
        ("Outils", [("studio", "Studio", "sliders"), ("plugins", "Plugins", "puzzle"),
                    ("import", "Importer", "download"),
                    ("queue", "File d'attente", "queue"),
                    ("settings", "Personnaliser", "brush")]),
    ]

    def __init__(self):
        super().__init__()
        ensure_dirs()
        self.settings = Settings()
        self.lib = Library()
        self.player = Player(self.lib)
        self.worker = ImportWorker(self.lib, self.settings)
        self._icon_bindings = []
        self._seeking = False
        self.view = ("home", None)
        self._back, self._fwd = [], []
        self._navigating = False

        # fenêtre sans bordure Windows (on dessine nous-mêmes coins arrondis + ombre)
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle("4tafy")
        self.resize(1360, 860)
        self.setMinimumSize(1000, 660)
        self.setAcceptDrops(True)

        self.bg = WindowBackground(self.settings)
        self.setCentralWidget(self.bg)
        root = QVBoxLayout(self.bg)
        root.setSpacing(0)
        top = QHBoxLayout()
        top.setSpacing(0)
        top.addWidget(self._build_sidebar())
        self.main_panel = ContentFrame(self.bg)
        self.main_panel.setObjectName("content")
        ml = QVBoxLayout(self.main_panel)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(0)
        ml.addWidget(self._build_toolbar())
        self.stack = QStackedWidget()
        ml.addWidget(self.stack, 1)
        top.addWidget(self.main_panel, 1)
        root.addLayout(top, 1)
        root.addWidget(self._build_player_bar())
        self.outline = WindowOutline(self.bg)

        self.home = HomePage(self)
        self.tracks_page = TrackListPage(self)
        self.import_page = ImportPage(self)
        self.queue_page = QueuePage(self)
        self.settings_page = SettingsPage(self)
        self.studio_page = StudioPage(self)
        self.plugins_page = PluginsPage(self)
        for p in (self.home, self.tracks_page, self.import_page, self.queue_page, self.settings_page,
                  self.studio_page, self.plugins_page):
            self.stack.addWidget(p)

        self.toast_lbl = QLabel(self.bg)
        self.toast_lbl.hide()
        self._toast_timer = QTimer(self, singleShot=True, interval=2800, timeout=self.toast_lbl.hide)

        self._theme_timer = QTimer(self, singleShot=True, interval=60, timeout=self.apply_theme)
        self._refresh_timer = QTimer(self, singleShot=True, interval=500, timeout=self.refresh_all)
        self._anim = QTimer(self, interval=110, timeout=self._animate)
        self._anim.start()

        # signaux
        p = self.player
        p.track_changed.connect(self._on_track)
        p.playing_changed.connect(self._on_playing)
        p.playing_changed.connect(lambda on: self.studio_page.pause() if on else None)
        p.playing_changed.connect(lambda on: self.plugins_page.pause() if on else None)
        p.position_changed.connect(self._on_position)
        p.duration_changed.connect(lambda d: self.seek.setRange(0, max(0, d)))
        p.queue_changed.connect(lambda: self.queue_page.refresh() if self.view[0] == "queue" else None)
        p.error.connect(self.toast)
        self.worker.library_changed.connect(self.schedule_refresh)
        self.worker.log.connect(lambda msg, lvl: self.toast(msg) if lvl == "err" else None)

        # réglages de lecture restaurés
        self.vol.setValue(self.settings["volume"])
        self.player.set_volume(self.settings["volume"])
        self.player.shuffle = self.settings["shuffle"]
        self.player.repeat = self.settings["repeat"]

        self._shortcuts()
        self.worker.start()
        self.apply_theme()
        self.show_home()

    # ================================================================ construction
    def bind_icon(self, button, name, color_key="subtext", size=None):
        self._icon_bindings.append((button, name, color_key))
        if size:
            button.setIconSize(QSize(size, size))

    def _color(self, key):
        c = self.settings.colors
        return on_color(c["accent"]) if key == "on_accent" else c[key]

    def _icon_btn(self, name, tip, size=20, color_key="subtext", slot=None):
        b = QPushButton()
        b.setObjectName("icon")
        b.setToolTip(tip)
        b.setCursor(Qt.PointingHandCursor)
        b.setIconSize(QSize(size, size))
        self.bind_icon(b, name, color_key)
        if slot:
            b.clicked.connect(slot)
        return b

    def _build_sidebar(self):
        side = QFrame()
        side.setObjectName("side")
        side.setFixedWidth(250)
        v = QVBoxLayout(side)
        v.setContentsMargins(10, 0, 10, 10)
        v.setSpacing(1)

        # rangée du haut : boutons de fenêtre (zone de déplacement)
        head = DragArea()
        head.setFixedHeight(52)
        hl = QHBoxLayout(head)
        hl.setContentsMargins(8, 0, 4, 0)
        self.lights = TrafficLights()
        hl.addWidget(self.lights)
        hl.addStretch()
        self.logo_icon = QLabel()
        self.logo_icon.setFixedSize(28, 28)
        hl.addWidget(self.logo_icon)
        self.logo_text = QLabel("4tafy")
        self.logo_text.setObjectName("logo")
        self.logo_text.setTextFormat(Qt.RichText)
        hl.addWidget(self.logo_text)
        v.addWidget(head)

        # recherche (comme dans Musique sur Mac)
        self.search_box = QLineEdit()
        self.search_box.setObjectName("search")
        self.search_box.setPlaceholderText("Rechercher")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.setFocusPolicy(Qt.ClickFocus)
        self._search_action = self.search_box.addAction(gfx.icon("search", "#888888"), QLineEdit.LeadingPosition)
        self.search_box.textChanged.connect(self._on_search)
        self.search_box.returnPressed.connect(lambda: self._on_search(self.search_box.text(), force=True))
        v.addWidget(self.search_box)
        v.addSpacing(14)

        self.nav_group = QButtonGroup(self)
        self.nav_btns = {}
        actions = {"home": self.show_home, "library": self.show_library, "liked": self.show_liked,
                   "import": self.show_import, "queue": self.show_queue, "settings": self.show_settings,
                   "studio": self.show_studio, "plugins": self.show_plugins}
        for section, keys in self.NAV:
            t = QLabel(section)
            t.setObjectName("section")
            t.setContentsMargins(10, 6, 0, 4)
            v.addWidget(t)
            for key, text, ic in keys:
                b = QPushButton(f"  {text}")
                b.setObjectName("nav")
                b.setCheckable(True)
                b.setIconSize(QSize(18, 18))
                b.clicked.connect(actions[key])
                self.bind_icon(b, ic, "accent")
                self.nav_group.addButton(b)
                self.nav_btns[key] = b
                v.addWidget(b)
            v.addSpacing(12)

        ph = QHBoxLayout()
        ph.setContentsMargins(10, 0, 0, 0)
        t = QLabel("Playlists")
        t.setObjectName("section")
        ph.addWidget(t)
        ph.addStretch()
        ph.addWidget(self._icon_btn("plus", "Nouvelle playlist", 14, slot=lambda: self.new_playlist()))
        v.addLayout(ph)
        self.pl_list = QListWidget()
        self.pl_list.setIconSize(QSize(34, 34))
        self.pl_list.setSpacing(0)
        self.pl_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.pl_list.itemClicked.connect(lambda it: self.open_playlist(it.data(Qt.UserRole)))
        self.pl_list.itemDoubleClicked.connect(lambda it: self.play_playlist(it.data(Qt.UserRole)))
        self.pl_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.pl_list.customContextMenuRequested.connect(self._pl_list_menu)
        v.addWidget(self.pl_list, 1)
        return side

    def _build_toolbar(self):
        """Barre du haut du contenu : précédent / suivant + titre ; sert aussi à déplacer la fenêtre."""
        bar = DragArea()
        bar.setFixedHeight(52)
        h = QHBoxLayout(bar)
        h.setContentsMargins(18, 0, 14, 0)
        h.setSpacing(4)
        self.back_btn = self._icon_btn("chevron_left", "Précédent (Alt+←)", 18, "text", self.go_back)
        self.fwd_btn = self._icon_btn("chevron_right", "Suivant (Alt+→)", 18, "text", self.go_forward)
        h.addWidget(self.back_btn)
        h.addWidget(self.fwd_btn)
        h.addSpacing(10)
        self.toolbar_title = QLabel("")
        self.toolbar_title.setObjectName("toolbartitle")
        h.addWidget(self.toolbar_title)
        h.addStretch()
        imp = self._icon_btn("plus", "Importer de la musique (Ctrl+I)", 18, "text", self.show_import)
        h.addWidget(imp)
        return bar

    def _build_player_bar(self):
        bar = QFrame()
        bar.setObjectName("bar")
        bar.setFixedHeight(84)
        h = QHBoxLayout(bar)
        h.setContentsMargins(16, 8, 20, 8)

        left = QWidget()
        left.setFixedWidth(330)
        ll = QHBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(12)
        self.now_cover = QLabel()
        self.now_cover.setFixedSize(54, 54)
        self.now_cover.setCursor(Qt.PointingHandCursor)
        self.now_cover.mousePressEvent = lambda e: self.show_queue()
        ll.addWidget(self.now_cover)
        txt = QVBoxLayout()
        txt.setSpacing(0)
        txt.addStretch()
        self.now_title = QLabel("Rien en lecture")
        self.now_title.setObjectName("nowtitle")
        self.now_artist = QLabel("Choisis un son pour commencer")
        self.now_artist.setObjectName("nowartist")
        txt.addWidget(self.now_title)
        txt.addWidget(self.now_artist)
        txt.addStretch()
        ll.addLayout(txt, 1)
        self.like_btn = self._icon_btn("heart", "J'aime", 20, slot=self._like_current)
        ll.addWidget(self.like_btn)
        h.addWidget(left)

        center = QVBoxLayout()
        center.setSpacing(2)
        ctr = QHBoxLayout()
        ctr.setSpacing(12)
        ctr.addStretch()
        self.shuffle_btn = self._icon_btn("shuffle", "Aléatoire", 20, slot=self._toggle_shuffle)
        self.prev_btn = self._icon_btn("prev", "Précédent (Ctrl+←)", 20, "text", self.player.prev)
        self.play_btn = QPushButton()
        self.play_btn.setObjectName("playmain")
        self.play_btn.setFixedSize(34, 34)
        self.play_btn.setIconSize(QSize(16, 16))
        self.play_btn.setCursor(Qt.PointingHandCursor)
        self.play_btn.setToolTip("Lecture / Pause (Espace)")
        self.play_btn.clicked.connect(self.toggle_play)
        self.next_btn = self._icon_btn("next", "Suivant (Ctrl+→)", 20, "text", lambda: self.player.next())
        self.repeat_btn = self._icon_btn("repeat", "Répéter", 20, slot=self._cycle_repeat)
        for b in (self.shuffle_btn, self.prev_btn, self.play_btn, self.next_btn, self.repeat_btn):
            ctr.addWidget(b)
        ctr.addStretch()
        center.addLayout(ctr)
        seek_row = QHBoxLayout()
        self.t_cur = QLabel("0:00")
        self.t_cur.setObjectName("small")
        self.t_tot = QLabel("0:00")
        self.t_tot.setObjectName("small")
        self.seek = ClickSlider()
        self.seek.sliderPressed.connect(lambda: setattr(self, "_seeking", True))
        self.seek.sliderReleased.connect(self._seek_release)
        self.seek.sliderMoved.connect(lambda v: self.t_cur.setText(fmt_time(v / 1000)))
        seek_row.addWidget(self.t_cur)
        seek_row.addWidget(self.seek, 1)
        seek_row.addWidget(self.t_tot)
        center.addLayout(seek_row)
        h.addLayout(center, 1)

        right = QWidget()
        right.setFixedWidth(330)
        rl = QHBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addStretch()
        rl.addWidget(self._icon_btn("queue", "File d'attente", 20, slot=self.show_queue))
        self.vol_btn = self._icon_btn("volume", "Couper le son", 20, slot=self._toggle_mute)
        rl.addWidget(self.vol_btn)
        self.vol = ClickSlider()
        self.vol.setRange(0, 100)
        self.vol.setFixedWidth(120)
        self.vol.valueChanged.connect(self._on_volume)
        rl.addWidget(self.vol)
        h.addWidget(right)
        return bar

    def _shortcuts(self):
        def sc(keys, fn):
            for k in keys if isinstance(keys, (list, tuple)) else [keys]:
                s = QShortcut(QKeySequence(k), self)
                s.activated.connect(fn)
        sc(["Space", Qt.Key_MediaPlay, Qt.Key_MediaTogglePlayPause, Qt.Key_MediaPause], self.toggle_play)
        sc(["Ctrl+Right", Qt.Key_MediaNext], lambda: self.player.next())
        sc(["Ctrl+Left", Qt.Key_MediaPrevious], self.player.prev)
        sc("Ctrl+Up", lambda: self.vol.setValue(self.vol.value() + 5))
        sc("Ctrl+Down", lambda: self.vol.setValue(self.vol.value() - 5))
        sc(["Ctrl+F", "Ctrl+K"], lambda: (self.search_box.setFocus(), self.search_box.selectAll()))
        sc("Alt+Left", self.go_back)
        sc("Alt+Right", self.go_forward)
        sc("Ctrl+I", self.show_import)
        sc("Ctrl+L", self._like_current)
        sc("Ctrl+S", self._toggle_shuffle)
        sc("Ctrl+R", self._cycle_repeat)

    # ================================================================ thème
    def schedule_theme(self):
        self._theme_timer.start()

    def apply_theme(self):
        s = self.settings
        app = QApplication.instance()
        app.setFont(QFont(s["font_family"], s["font_size"]))
        app.setStyleSheet(build_qss(s, self.isMaximized()))
        for btn, name, key in self._icon_bindings:
            btn.setIcon(gfx.icon(name, self._color(key)))
        icon = self.current_icon()
        self.setWindowIcon(icon)
        app.setWindowIcon(icon)
        self.logo_icon.setPixmap(icon.pixmap(QSize(28, 28), self.devicePixelRatioF()))
        self.logo_text.setText(f'<span style="color:{s.colors["accent"]}">4</span>tafy')
        self.studio_page.apply_theme()
        self.plugins_page.apply_theme()
        self._search_action.setIcon(gfx.icon("search", s.colors["subtext"]))
        self._card_icon = gfx.icon("play", on_color(s.colors["accent"]))
        c = s.colors
        self.toast_lbl.setStyleSheet(
            f"background:{c['text']}; color:{c['bg']}; border-radius:10px; padding:10px 18px; font-weight:700;")
        self.bg.reload()
        self.bg.set_maximized(self.isMaximized())
        self._place_outline()
        self.sync_player_buttons()
        self._on_track(self.player.current)
        s.save()
        self.refresh_all()

    def sync_player_buttons(self):
        c = self.settings.colors
        p = self.player
        self.play_btn.setIcon(gfx.icon("pause" if p.is_playing() else "play", c["bg"]))
        self.shuffle_btn.setIcon(gfx.icon("shuffle", c["accent"] if p.shuffle else c["subtext"]))
        self.repeat_btn.setIcon(gfx.icon("repeat_one" if p.repeat == REPEAT_ONE else "repeat",
                                         c["subtext"] if p.repeat == REPEAT_OFF else c["accent"]))
        self.repeat_btn.setToolTip(["Répéter : désactivé", "Répéter : tout", "Répéter : ce titre"][p.repeat])
        t = p.current
        liked = bool(t and t["liked"])
        self.like_btn.setIcon(gfx.icon("heart_full" if liked else "heart", c["accent"] if liked else c["subtext"]))
        v = self.vol.value()
        muted = p.out.isMuted() or v == 0
        self.vol_btn.setIcon(gfx.icon("volume_mute" if muted else ("volume_low" if v < 50 else "volume"),
                                      c["subtext"]))

    # ================================================================ navigation
    TITLES = {"home": "Accueil", "library": "Bibliothèque", "liked": "Titres likés", "search": "Recherche",
              "import": "Importer", "queue": "File d'attente", "settings": "Personnaliser", "studio": "Studio",
              "plugins": "Plugins"}

    def _set_nav(self, key):
        if key in self.nav_btns:
            self.nav_btns[key].setChecked(True)
        else:
            self.nav_group.setExclusive(False)
            for b in self.nav_btns.values():
                b.setChecked(False)
            self.nav_group.setExclusive(True)
        if key != "playlist":
            self.pl_list.clearSelection()
        if key != "search" and self.search_box.text():
            self.search_box.blockSignals(True)
            self.search_box.clear()
            self.search_box.blockSignals(False)

    def _remember(self, view):
        """Mémorise la page actuelle pour les boutons précédent / suivant."""
        if view[0] != "studio":
            self.studio_page.pause()
        if view[0] != "plugins":
            self.plugins_page.pause()
        if view != self.view and not self._navigating:
            self._back.append(self.view)
            self._back = self._back[-50:]
            self._fwd.clear()
        self.view = view
        if view[0] not in ("library", "liked", "playlist"):
            self.set_tint(None)
        if view[0] == "playlist":
            pl = self.lib.get_playlist(view[1])
            self.toolbar_title.setText(pl["name"] if pl else "")
        else:
            self.toolbar_title.setText(self.TITLES.get(view[0], ""))
        self.back_btn.setEnabled(bool(self._back))
        self.fwd_btn.setEnabled(bool(self._fwd))

    def _open_view(self, view):
        self._navigating = True
        try:
            kind, pid = view
            if kind == "playlist" and self.lib.get_playlist(pid):
                self.open_playlist(pid)
            elif kind == "search":
                self._show_tracks("search")
            else:
                {"library": self.show_library, "liked": self.show_liked, "import": self.show_import,
                 "queue": self.show_queue, "settings": self.show_settings,
                 "studio": self.show_studio, "plugins": self.show_plugins}.get(kind, self.show_home)()
        finally:
            self._navigating = False

    def go_back(self):
        if self._back:
            self._fwd.append(self.view)
            self._open_view(self._back.pop())
            self.back_btn.setEnabled(bool(self._back))
            self.fwd_btn.setEnabled(bool(self._fwd))

    def go_forward(self):
        if self._fwd:
            self._back.append(self.view)
            self._open_view(self._fwd.pop())
            self.back_btn.setEnabled(bool(self._back))
            self.fwd_btn.setEnabled(bool(self._fwd))

    def _on_search(self, text, force=False):
        if text.strip() or force:
            if self.view[0] != "search":
                self._show_tracks("search")
            self.tracks_page.set_filter(text)
        elif self.view[0] == "search":
            self.tracks_page.set_filter("")

    def show_home(self):
        self._remember(("home", None))
        self._set_nav("home")
        self.home.rebuild()
        self.stack.setCurrentWidget(self.home)

    def _show_tracks(self, mode, pid=None):
        self._remember((mode, pid))
        self._set_nav(mode)
        self.tracks_page.show_mode(mode, pid)
        self.stack.setCurrentWidget(self.tracks_page)

    def show_library(self):
        self._show_tracks("library")

    def show_liked(self):
        self._show_tracks("liked")

    def show_search(self):
        self.search_box.setFocus()

    def open_playlist(self, pid):
        self._show_tracks("playlist", pid)
        for i in range(self.pl_list.count()):
            it = self.pl_list.item(i)
            if it.data(Qt.UserRole) == pid:
                self.pl_list.setCurrentItem(it)

    def show_import(self):
        self._remember(("import", None))
        self._set_nav("import")
        self.import_page.refresh_targets()
        self.stack.setCurrentWidget(self.import_page)
        self.import_page.links.setFocus()

    def show_queue(self):
        self._remember(("queue", None))
        self._set_nav("queue")
        self.queue_page.refresh()
        self.stack.setCurrentWidget(self.queue_page)

    def show_settings(self):
        self._remember(("settings", None))
        self._set_nav("settings")
        self.settings_page.load()
        self.stack.setCurrentWidget(self.settings_page)

    def show_studio(self):
        self._remember(("studio", None))
        self._set_nav("studio")
        self.studio_page.refresh_sources()
        self.stack.setCurrentWidget(self.studio_page)

    def show_plugins(self):
        self._remember(("plugins", None))
        self._set_nav("plugins")
        self.plugins_page.refresh_sources()
        self.stack.setCurrentWidget(self.plugins_page)

    def open_plugin(self, pid, tid):
        self.show_plugins()
        self.plugins_page.open_with(pid, tid)

    def open_studio(self, tid):
        self.show_studio()
        self.studio_page.load_track(tid)

    def current_icon(self):
        """Icône perso (Personnaliser → Icône de l'application) ou l'icône 4tafy aux couleurs du thème."""
        s = self.settings
        icon = gfx.custom_app_icon(s["custom_icon"], s["icon_round"]) if s["custom_icon"] else None
        icon = icon or gfx.app_icon(s.colors["accent"])
        try:  # copie .ico, toujours à jour, pour le raccourci du Bureau
            from .config import ICON_ICO
            ICON_ICO.parent.mkdir(parents=True, exist_ok=True)
            gfx.save_ico(icon, ICON_ICO)
        except Exception:
            pass
        return icon

    def set_tint(self, color):
        self.main_panel.set_tint(color)

    def card_play_icon(self):
        return self._card_icon

    def schedule_refresh(self):
        if not self._refresh_timer.isActive():
            self._refresh_timer.start()

    def refresh_all(self):
        self._refresh_playlists()
        self.import_page.refresh_targets()
        kind = self.view[0]
        if kind == "home":
            self.home.rebuild()
        elif kind in ("library", "liked", "playlist", "search"):
            self.tracks_page.refresh()
        elif kind == "queue":
            self.queue_page.refresh()

    def _refresh_playlists(self):
        cur = self.view[1] if self.view[0] == "playlist" else None
        self.pl_list.clear()
        for pl in self.lib.playlists:
            n = len(pl["tracks"])
            it = QListWidgetItem(self.playlist_cover(pl, 34, 5), pl["name"])
            it.setToolTip(f"{pl['name']} • {n} titre{'s' * (n > 1)}")
            it.setData(Qt.UserRole, pl["id"])
            it.setSizeHint(QSize(0, 44))
            self.pl_list.addItem(it)
            if pl["id"] == cur:
                it.setSelected(True)

    # ================================================================ lecture
    def play_ids(self, ids, start=0):
        self.player.play_list(ids, start)

    def play_playlist(self, pid, shuffle=False):
        ids = [t["id"] for t in self.lib.playlist_tracks(pid)]
        if not ids:
            return self.toast("Cette playlist est vide.")
        if shuffle:
            self.player.play_shuffled(ids)
            self.sync_player_buttons()
        else:
            self.player.play_list(ids, 0)

    def toggle_play(self):
        if self.view[0] == "studio" and self.studio_page.audio is not None:
            self.studio_page.toggle_play()  # Espace dans le Studio = pré-écoute en direct
            return
        if not self.player.toggle():
            ids = self.tracks_page.table.visible_ids() if self.view[0] in ("library", "liked", "playlist", "search") \
                else [t["id"] for t in self.lib.all_tracks()]
            if ids:
                self.player.play_list(ids, 0)

    def _on_track(self, t):
        if t:
            self.now_title.setText(self._elide(t["title"], self.now_title, 210))
            self.now_artist.setText(self._elide(t["artist"] or "Artiste inconnu", self.now_artist, 210))
            self.now_title.setToolTip(t["title"])
            self.setWindowTitle(f"{t['title']} • {t['artist']} — 4tafy" if t["artist"] else f"{t['title']} — 4tafy")
            self.t_tot.setText(fmt_time(t["duration"]))
        else:
            self.now_title.setText("Rien en lecture")
            self.now_artist.setText("Choisis un son pour commencer")
            self.setWindowTitle("4tafy")
        self.now_cover.setPixmap(gfx.track_cover(t, 54, 6))
        for tbl in (self.tracks_page.table, self.queue_page.now, self.queue_page.next):
            tbl.playing_id = self.player.current_id
            tbl.viewport().update()
        self.sync_player_buttons()

    @staticmethod
    def _elide(text, label, width):
        return label.fontMetrics().elidedText(text, Qt.ElideRight, width)

    def _on_playing(self, playing):
        for tbl in (self.tracks_page.table, self.queue_page.now, self.queue_page.next):
            tbl.is_playing = playing
            tbl.viewport().update()
        self.sync_player_buttons()

    def _on_position(self, ms):
        if not self._seeking:
            self.seek.setValue(ms)
            self.t_cur.setText(fmt_time(ms / 1000))
        d = self.player.mp.duration()
        if d > 0:
            self.t_tot.setText(fmt_time(d / 1000))

    def _seek_release(self):
        self._seeking = False
        self.player.seek(self.seek.value())

    def _on_volume(self, v):
        self.player.set_volume(v)
        if v > 0 and self.player.out.isMuted():
            self.player.set_muted(False)
        self.settings["volume"] = v
        self.sync_player_buttons()

    def _toggle_mute(self):
        self.player.set_muted(not self.player.out.isMuted())
        self.sync_player_buttons()

    def _toggle_shuffle(self):
        self.player.set_shuffle(not self.player.shuffle)
        self.settings["shuffle"] = self.player.shuffle
        self.sync_player_buttons()
        self.toast("Lecture aléatoire activée" if self.player.shuffle else "Lecture aléatoire désactivée")

    def _cycle_repeat(self):
        self.settings["repeat"] = self.player.cycle_repeat()
        self.sync_player_buttons()

    def _like_current(self):
        if self.player.current_id:
            self.toggle_like(self.player.current_id)

    def toggle_like(self, tid):
        liked = self.lib.toggle_like(tid)
        self.toast("Ajouté aux titres likés ♥" if liked else "Retiré des titres likés")
        self.sync_player_buttons()
        if self.view[0] == "liked":
            self.tracks_page.refresh()
        else:
            self.tracks_page.table.viewport().update()

    def _animate(self):
        if self.player.is_playing():
            for tbl in (self.tracks_page.table, self.queue_page.now, self.queue_page.next):
                if tbl.isVisible():
                    tbl.phase += 0.55
                    tbl.viewport().update()

    # ================================================================ menus
    def track_menu(self, tids, pos, pid=None, queue_positions=None):
        tids = [t for t in tids if self.lib.get(t)]
        if not tids:
            return
        n = len(tids)
        menu = self._new_menu()
        menu.addAction("Lire", lambda: self.play_ids(tids, 0))
        menu.addAction("Lire ensuite", lambda: (self.player.enqueue(tids, play_next=True),
                                                 self.toast(f"{n} titre(s) joué(s) ensuite")))
        menu.addAction("Ajouter à la file d'attente", lambda: (self.player.enqueue(tids),
                                                                self.toast(f"{n} titre(s) ajouté(s) à la file")))
        sub = self._new_menu("Ajouter à la playlist")
        menu.addMenu(sub)
        sub.addAction("+ Nouvelle playlist…", lambda: self.new_playlist(tids))
        if self.lib.playlists:
            sub.addSeparator()
        for pl in self.lib.playlists:
            sub.addAction(pl["name"], lambda p=pl["id"], name=pl["name"]: self._add_to_pl(p, name, tids))
        all_liked = all(self.lib.get(t)["liked"] for t in tids)
        menu.addAction("Retirer des titres likés" if all_liked else "Ajouter aux titres likés",
                       lambda: self._set_liked(tids, not all_liked))
        menu.addSeparator()
        if pid:
            menu.addAction("Retirer de cette playlist", lambda: (self.lib.remove_from_playlist(pid, tids),
                                                                  self.refresh_all()))
            if n == 1:
                menu.addAction("Monter", lambda: (self.lib.move_in_playlist(pid, tids[0], -1), self.refresh_all()))
                menu.addAction("Descendre", lambda: (self.lib.move_in_playlist(pid, tids[0], 1), self.refresh_all()))
        if queue_positions:
            menu.addAction("Retirer de la file d'attente", lambda: self.player.remove_from_queue(queue_positions))
        if n == 1:
            t = self.lib.get(tids[0])
            menu.addAction("Ouvrir dans le Studio…", lambda: self.open_studio(tids[0]))
            usable = self.plugins_page.enabled_plugins()
            if usable:
                pm = self._new_menu("Plugins")
                for pl in usable:
                    pm.addAction(f"{pl.name}…", lambda pid=pl.id, tid=tids[0]: self.open_plugin(pid, tid))
                menu.addMenu(pm)
            if t["source"] not in ("local", "studio"):
                warn = "⚠ " if t.get("match") == "uncertain" else ""
                menu.addAction(f"{warn}Corriger le son (mauvaise musique)…", lambda: self.fix_match(tids[0]))
            menu.addAction("Modifier les infos…", lambda: self.edit_track(tids[0]))
            menu.addAction("Afficher le fichier", lambda: self._reveal(t["path"]))
            if t["url"].startswith("http"):
                menu.addAction("Ouvrir la page d'origine", lambda: QDesktopServices.openUrl(QUrl(t["url"])))
        menu.addSeparator()
        menu.addAction(f"Supprimer de la bibliothèque{' (' + str(n) + ')' if n > 1 else ''}…",
                       lambda: self.delete_tracks(tids))
        menu.exec(pos)

    def _set_liked(self, tids, value):
        for t in tids:
            self.lib.tracks[t]["liked"] = value
        self.lib.save()
        self.sync_player_buttons()
        self.refresh_all()

    def _add_to_pl(self, pid, name, tids):
        added = self.lib.add_to_playlist(pid, tids)
        self.toast(f"{added} titre(s) ajouté(s) à « {name} »" if added else f"Déjà dans « {name} »")
        self.refresh_all()

    def _pl_list_menu(self, pos):
        it = self.pl_list.itemAt(pos)
        if it:
            self.playlist_menu(it.data(Qt.UserRole), self.pl_list.viewport().mapToGlobal(pos))
        else:
            menu = self._new_menu()
            menu.addAction("Nouvelle playlist…", lambda: self.new_playlist())
            menu.exec(self.pl_list.viewport().mapToGlobal(pos))

    def playlist_menu(self, pid, pos):
        pl = self.lib.get_playlist(pid)
        if not pl:
            return
        menu = self._new_menu()
        menu.addAction("Lire", lambda: self.play_playlist(pid))
        menu.addAction("Lecture aléatoire", lambda: self.play_playlist(pid, shuffle=True))
        menu.addAction("Ajouter à la file d'attente",
                       lambda: self.player.enqueue([t["id"] for t in self.lib.playlist_tracks(pid)]))
        menu.addSeparator()
        menu.addAction("Renommer…", lambda: self.rename_playlist(pid))
        menu.addAction("Modifier la description…", lambda: self.describe_playlist(pid))
        menu.addAction("Changer la pochette…", lambda: self.change_playlist_cover(pid))
        if pl.get("cover"):
            menu.addAction("Pochette automatique", lambda: (self.lib.update_playlist(pid, cover=""),
                                                            self.refresh_all()))
        menu.addAction("Exporter en .m3u…", lambda: self.export_playlist(pid))
        menu.addSeparator()
        menu.addAction("Mettre toute la playlist en 8D…", lambda: self.playlist_8d(pid))
        menu.addSeparator()
        menu.addAction("Supprimer la playlist…", lambda: self.delete_playlist(pid))
        menu.exec(pos)

    def playlist_8d(self, pid):
        from .playlist_fx import Playlist8DDialog
        if not self.lib.playlist_tracks(pid):
            return self.toast("Cette playlist est vide.")
        Playlist8DDialog(self, pid).exec()

    # ================================================================ playlists
    def playlist_cover(self, pl, size, radius):
        if pl.get("cover") and Path(pl["cover"]).exists():
            return gfx.cover(pl["cover"], size, radius, pl["name"])
        t = self.lib.playlist_cover_track(pl["id"])
        if t:
            return gfx.cover(t["cover"], size, radius, pl["name"])
        return gfx.cover("", size, radius, pl["name"])

    def new_playlist(self, tids=None):
        name, ok = QInputDialog.getText(self, "Nouvelle playlist", "Nom de la playlist :",
                                        text=f"Ma playlist n°{len(self.lib.playlists) + 1}")
        if not ok or not name.strip():
            return
        pl = self.lib.create_playlist(name.strip())
        if tids:
            self.lib.add_to_playlist(pl["id"], tids)
            self.toast(f"Playlist « {pl['name']} » créée")
            self.refresh_all()
        else:
            self._refresh_playlists()
            self.open_playlist(pl["id"])

    def rename_playlist(self, pid):
        pl = self.lib.get_playlist(pid)
        name, ok = QInputDialog.getText(self, "Renommer", "Nouveau nom :", text=pl["name"])
        if ok and name.strip():
            self.lib.update_playlist(pid, name=name.strip())
            self.refresh_all()

    def describe_playlist(self, pid):
        pl = self.lib.get_playlist(pid)
        text, ok = QInputDialog.getText(self, "Description", "Description :", text=pl.get("description", ""))
        if ok:
            self.lib.update_playlist(pid, description=text.strip())
            self.refresh_all()

    def change_playlist_cover(self, pid):
        path, _ = QFileDialog.getOpenFileName(self, "Pochette de la playlist", str(Path.home() / "Pictures"),
                                              IMAGE_FILTER)
        if not path:
            return
        dest = COVERS_DIR / f"pl_{pid}{Path(path).suffix.lower()}"
        shutil.copy2(path, dest)
        gfx.forget_cover(str(dest))
        self.lib.update_playlist(pid, cover=str(dest))
        self.refresh_all()

    def export_playlist(self, pid):
        pl = self.lib.get_playlist(pid)
        path, _ = QFileDialog.getSaveFileName(self, "Exporter la playlist", str(Path.home() / f"{pl['name']}.m3u"),
                                              "Playlist (*.m3u)")
        if path:
            self.lib.export_m3u(pid, path)
            self.toast("Playlist exportée !")

    def delete_playlist(self, pid):
        pl = self.lib.get_playlist(pid)
        if QMessageBox.question(self, "Supprimer", f"Supprimer la playlist « {pl['name']} » ?\n"
                                "(les titres restent dans ta bibliothèque)") == QMessageBox.Yes:
            self.lib.delete_playlist(pid)
            if self.view == ("playlist", pid):
                self.show_home()
            self.refresh_all()

    # ================================================================ titres
    def edit_track(self, tid):
        t = self.lib.get(tid)
        dlg = EditTrackDialog(self, t)
        if dlg.exec() != QDialog.Accepted:
            return
        fields = {"title": dlg.title.text().strip() or t["title"], "artist": dlg.artist.text().strip(),
                  "album": dlg.album.text().strip()}
        if dlg.new_cover:
            dest = COVERS_DIR / f"{tid}{Path(dlg.new_cover).suffix.lower()}"
            try:
                shutil.copy2(dlg.new_cover, dest)
                gfx.forget_cover(str(dest))
                fields["cover"] = str(dest)
            except OSError as e:
                self.toast(f"Pochette non copiée : {e}")
        self.lib.update_track(tid, **fields)
        if tid == self.player.current_id:
            self._on_track(self.lib.get(tid))
        self.refresh_all()

    def fix_match(self, tid):
        from .fix_dialog import FixMatchDialog
        t = self.lib.get(tid)
        if t:
            FixMatchDialog(self, t).exec()

    def delete_tracks(self, tids):
        box = QMessageBox(self)
        box.setWindowTitle("Supprimer")
        box.setText(f"Supprimer {len(tids)} titre(s) de ta bibliothèque ?")
        cb = QCheckBox("Supprimer aussi les fichiers téléchargés par 4tafy")
        cb.setChecked(True)
        box.setCheckBox(cb)
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.Cancel)
        if box.exec() != QMessageBox.Yes:
            return
        self.player.forget(set(tids))
        self.lib.remove_tracks(tids, delete_files=cb.isChecked())
        self.refresh_all()

    def _reveal(self, path):
        if not path or not Path(path).exists():
            return self.toast("Fichier introuvable")
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))

    # ================================================================ import
    def import_files_dialog(self, target="none"):
        files, _ = QFileDialog.getOpenFileNames(self, "Importer des fichiers audio", str(Path.home() / "Music"),
                                                AUDIO_FILTER)
        if files:
            self.worker.add_files(files, target)
            self.toast(f"{len(files)} fichier(s) en cours d'import")

    def import_folder_dialog(self, target="none"):
        folder = QFileDialog.getExistingDirectory(self, "Importer un dossier", str(Path.home() / "Music"))
        if folder:
            self.worker.add_files([folder], target)
            self.toast("Import du dossier en cours…")

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() or e.mimeData().hasText():
            e.acceptProposedAction()

    def dropEvent(self, e):
        md = e.mimeData()
        files, links = [], []
        for u in md.urls():
            if u.isLocalFile():
                files.append(u.toLocalFile())
            elif u.scheme() in ("http", "https"):
                links.append(u.toString())
        if not md.hasUrls() and md.hasText():
            links = [w for w in md.text().split() if w.startswith(("http", "spotify:"))]
        if files:
            self.worker.add_files(files, "none")
        if links:
            self.worker.add_urls(links, "auto")
        if files or links:
            self.toast(f"Import lancé : {len(files)} fichier(s), {len(links)} lien(s)")

    # ================================================================ divers
    def toast(self, msg):
        self.toast_lbl.setText(msg if len(msg) < 140 else msg[:137] + "…")
        self.toast_lbl.adjustSize()
        w = min(self.toast_lbl.width(), self.bg.width() - 40)
        self.toast_lbl.resize(w, self.toast_lbl.height())
        self.toast_lbl.move((self.bg.width() - w) // 2,
                            self.bg.height() - self.bg.margin - 84 - 24 - self.toast_lbl.height())
        self.toast_lbl.show()
        self.toast_lbl.raise_()
        self._toast_timer.start()

    def _new_menu(self, title=""):
        """Menu contextuel aux coins arrondis (fond transparent autour)."""
        m = QMenu(title, self)
        m.setWindowFlags(m.windowFlags() | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        m.setAttribute(Qt.WA_TranslucentBackground)
        return m

    def _place_outline(self):
        self.outline.setGeometry(self.bg.rect())
        self.outline.raise_()
        self.toast_lbl.raise_()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place_outline()

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == QEvent.WindowStateChange:
            self.bg.set_maximized(self.isMaximized())
            QApplication.instance().setStyleSheet(build_qss(self.settings, self.isMaximized()))
            self._place_outline()
        elif e.type() == QEvent.ActivationChange:
            self.lights.update()

    def showEvent(self, e):
        super().showEvent(e)
        if sys.platform == "win32" and not getattr(self, "_styled", False):
            self._styled = True
            try:  # permet de réduire / restaurer la fenêtre en cliquant sur la barre des tâches
                import ctypes
                hwnd = int(self.winId())
                GWL_STYLE, WS_MINIMIZEBOX = -16, 0x00020000
                style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_STYLE)
                ctypes.windll.user32.SetWindowLongW(hwnd, GWL_STYLE, style | WS_MINIMIZEBOX)
            except Exception:
                pass

    def closeEvent(self, e):
        self.settings.save()
        self.lib.save()
        self.studio_page.shutdown()
        self.plugins_page.shutdown()
        self.worker.stop()
        if not self.worker.wait(2000):
            os._exit(0)  # un téléchargement bloqué ne doit pas empêcher de quitter
        super().closeEvent(e)
