"""Pages principales : Accueil, Liste de titres (bibliothèque / likés / playlist / recherche),
Import et File d'attente."""
import time

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QProgressBar,
                               QPushButton, QScrollArea, QSizePolicy, QTextEdit, QVBoxLayout, QWidget)

from . import graphics as gfx
from .widgets import Card, FlowLayout, Tile, TrackTable, clear_layout, fmt_total


def _label(text, name=None, wrap=False):
    lb = QLabel(text)
    if name:
        lb.setObjectName(name)
    lb.setWordWrap(wrap)
    return lb


# =========================================================================== Accueil
class HomePage(QScrollArea):
    def __init__(self, main):
        super().__init__()
        self.m = main
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.body = QWidget()
        self.lay = QVBoxLayout(self.body)
        self.lay.setContentsMargins(28, 6, 28, 28)
        self.lay.setSpacing(14)
        self.setWidget(self.body)

    def _flow(self, widgets):
        holder = QWidget()
        fl = FlowLayout(holder, spacing=14)
        for w in widgets:
            fl.addWidget(w)
        return holder

    def rebuild(self):
        clear_layout(self.lay)
        lib, m = self.m.lib, self.m
        h = time.localtime().tm_hour
        greet = "Bonjour" if 5 <= h < 18 else "Bonsoir"
        self.lay.addWidget(_label(greet, "h1"))

        tracks = lib.all_tracks()
        if not tracks:
            box = QWidget()
            bl = QVBoxLayout(box)
            bl.setContentsMargins(0, 30, 0, 0)
            bl.setSpacing(10)
            bl.addWidget(_label("Ta bibliothèque est vide", "h2"))
            bl.addWidget(_label("Importe des sons depuis YouTube, Spotify, TikTok, SoundCloud ou tes fichiers MP3 "
                                "(tu peux aussi glisser-déposer des fichiers ou des liens sur la fenêtre).",
                                "sub", wrap=True))
            btn = QPushButton("  Importer de la musique")
            btn.setObjectName("accent")
            btn.setIcon(gfx.icon("download", "#ffffff"))
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(m.show_import)
            row = QHBoxLayout()
            row.addWidget(btn)
            row.addStretch()
            bl.addLayout(row)
            self.lay.addWidget(box)
            self.lay.addStretch()
            return

        # raccourcis
        tiles = []
        liked = lib.liked_tracks()
        t = Tile(gfx.cover("", 64, 6, kind="liked"), f"Titres likés ({len(liked)})")
        t.clicked.connect(m.show_liked)
        tiles.append(t)
        t = Tile(gfx.track_cover(tracks[0], 64, 6), "Toute la bibliothèque")
        t.clicked.connect(m.show_library)
        tiles.append(t)
        for pl in lib.playlists[:6]:
            t = Tile(m.playlist_cover(pl, 64, 6), pl["name"])
            t.clicked.connect(lambda pid=pl["id"]: m.open_playlist(pid))
            tiles.append(t)
        self.lay.addWidget(self._flow(tiles))

        # récemment ajoutés
        self.lay.addSpacing(10)
        self.lay.addWidget(_label("Ajoutés récemment", "h2"))
        cards = []
        recent = tracks[:12]
        for i, tr in enumerate(recent):
            c = Card(gfx.track_cover(tr, 150, 10), tr["title"], tr["artist"] or "Artiste inconnu",
                     play_icon=m.card_play_icon())
            c.clicked.connect(lambda i=i, ids=[x["id"] for x in recent]: m.play_ids(ids, i))
            c.play_clicked.connect(lambda i=i, ids=[x["id"] for x in recent]: m.play_ids(ids, i))
            c.right_clicked.connect(lambda pos, tid=tr["id"]: m.track_menu([tid], pos))
            cards.append(c)
        self.lay.addWidget(self._flow(cards))

        if lib.playlists:
            self.lay.addSpacing(10)
            self.lay.addWidget(_label("Tes playlists", "h2"))
            cards = []
            for pl in lib.playlists:
                n = len(pl["tracks"])
                c = Card(m.playlist_cover(pl, 150, 10), pl["name"], f"Playlist • {n} titre{'s' * (n > 1)}",
                         play_icon=m.card_play_icon())
                c.clicked.connect(lambda pid=pl["id"]: m.open_playlist(pid))
                c.play_clicked.connect(lambda pid=pl["id"]: m.play_playlist(pid))
                c.right_clicked.connect(lambda pos, pid=pl["id"]: m.playlist_menu(pid, pos))
                cards.append(c)
            self.lay.addWidget(self._flow(cards))

        top = sorted([t for t in tracks if t.get("plays")], key=lambda t: t["plays"], reverse=True)[:6]
        if top:
            self.lay.addSpacing(10)
            self.lay.addWidget(_label("Tes plus écoutés", "h2"))
            cards = []
            for i, tr in enumerate(top):
                c = Card(gfx.track_cover(tr, 150, 75), tr["title"], f"{tr['plays']} écoute(s)",
                         play_icon=m.card_play_icon())
                c.clicked.connect(lambda i=i, ids=[x["id"] for x in top]: m.play_ids(ids, i))
                c.play_clicked.connect(lambda i=i, ids=[x["id"] for x in top]: m.play_ids(ids, i))
                cards.append(c)
            self.lay.addWidget(self._flow(cards))
        self.lay.addStretch()


# =========================================================================== Liste de titres
class TrackListPage(QWidget):
    KINDS = {"library": "BIBLIOTHÈQUE", "liked": "PLAYLIST", "playlist": "PLAYLIST", "search": "RECHERCHE"}
    def _set_tint(self, pixmap):
        """Couleur dominante de la pochette → dégradé en haut de la page."""
        tint = None
        if pixmap is not None and self.mode != "search":
            img = pixmap.toImage().scaled(1, 1, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            h, sat, v, _ = QColor(img.pixel(0, 0)).getHsv()
            tint = QColor.fromHsv(max(0, h), min(255, sat + 40), max(110, min(200, v + 30)))
        self.m.set_tint(tint)

    def __init__(self, main):
        super().__init__()
        self.m = main
        self.mode = "library"
        self.pid = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 6, 28, 8)
        lay.setSpacing(14)

        # en-tête
        self.header = QWidget()
        hl = QHBoxLayout(self.header)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(24)
        self.cover = QLabel()
        self.cover.setFixedSize(190, 190)
        self.cover.setCursor(Qt.PointingHandCursor)
        self.cover.mousePressEvent = lambda e: self._cover_clicked()
        hl.addWidget(self.cover, 0, Qt.AlignBottom)
        info = QVBoxLayout()
        info.setSpacing(4)
        info.addStretch()
        self.kind = _label("", "section")
        self.title = _label("", "h1")
        self.title.setWordWrap(True)
        self.desc = _label("", "sub", wrap=True)
        self.meta = _label("", "small")
        for w in (self.kind, self.title, self.desc, self.meta):
            info.addWidget(w)
        hl.addLayout(info, 1)
        lay.addWidget(self.header)

        # barre d'actions
        bar = QHBoxLayout()
        bar.setSpacing(10)
        self.play_btn = QPushButton()
        self.play_btn.setObjectName("playbig")
        self.play_btn.setFixedSize(56, 56)
        self.play_btn.setIconSize(QSize(26, 26))
        self.play_btn.setCursor(Qt.PointingHandCursor)
        self.play_btn.setToolTip("Lire")
        self.play_btn.clicked.connect(self._play_all)
        self.shuffle_btn = QPushButton()
        self.shuffle_btn.setObjectName("icon")
        self.shuffle_btn.setIconSize(QSize(30, 30))
        self.shuffle_btn.setToolTip("Lecture aléatoire")
        self.shuffle_btn.setCursor(Qt.PointingHandCursor)
        self.shuffle_btn.clicked.connect(lambda: self.m.player.play_shuffled(self.table.visible_ids())
                                         or self.m.sync_player_buttons())
        self.more_btn = QPushButton()
        self.more_btn.setObjectName("icon")
        self.more_btn.setIconSize(QSize(28, 28))
        self.more_btn.setToolTip("Options de la playlist")
        self.more_btn.setCursor(Qt.PointingHandCursor)
        self.more_btn.clicked.connect(lambda: self.m.playlist_menu(
            self.pid, self.more_btn.mapToGlobal(self.more_btn.rect().bottomLeft())))
        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText("Filtrer…")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(220)
        self.search.textChanged.connect(lambda s: self.table.apply_filter(s))
        bar.addWidget(self.play_btn)
        bar.addWidget(self.shuffle_btn)
        bar.addWidget(self.more_btn)
        bar.addStretch()
        bar.addWidget(self.search)
        lay.addLayout(bar)

        self.table = TrackTable(main.lib, main.settings.colors)
        self.table.play_row.connect(self._play_row)
        self.table.like_toggled.connect(self.m.toggle_like)
        self.table.menu_requested.connect(
            lambda ids, pos: self.m.track_menu(ids, pos, pid=self.pid if self.mode == "playlist" else None))
        lay.addWidget(self.table, 1)
        self.empty = _label("", "sub", wrap=True)
        self.empty.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.empty, 1)

        main.bind_icon(self.play_btn, "play", "on_accent")
        main.bind_icon(self.shuffle_btn, "shuffle", "subtext")
        main.bind_icon(self.more_btn, "dots", "subtext")

    def show_mode(self, mode, pid=None):
        if (mode, pid) != (self.mode, self.pid):
            self.search.clear()
        self.mode, self.pid = mode, pid
        self.search.setVisible(mode != "search")
        self.refresh()

    def set_filter(self, text):
        """Utilisé par le champ de recherche de la barre d'outils."""
        if self.search.text() != text:
            self.search.setText(text)
        if self.mode == "search":
            q = text.strip()
            self.title.setText(f"Résultats pour « {q} »" if q else "Rechercher")
            n = len(self.table.visible_ids())
            self.meta.setText(f"{n} résultat{'s' * (n > 1)}")

    def tracks(self):
        lib = self.m.lib
        if self.mode == "liked":
            return lib.liked_tracks()
        if self.mode == "playlist":
            return lib.playlist_tracks(self.pid)
        return lib.all_tracks()

    def refresh(self):
        lib, m = self.m.lib, self.m
        tracks = self.tracks()
        total = sum(t["duration"] for t in tracks)
        n = len(tracks)
        meta = f"{n} titre{'s' * (n > 1)} • {fmt_total(total)}"
        self.kind.setText(self.KINDS[self.mode])
        self.more_btn.setVisible(self.mode == "playlist")
        self.cover.setVisible(self.mode != "search")
        self.desc.setText("")
        if self.mode == "liked":
            self.title.setText("Titres likés")
            self.cover.setPixmap(gfx.cover("", 190, 10, kind="liked"))
        elif self.mode == "playlist":
            pl = lib.get_playlist(self.pid)
            if not pl:
                return m.show_home()
            self.title.setText(pl["name"])
            self.desc.setText(pl.get("description", ""))
            self.cover.setPixmap(m.playlist_cover(pl, 190, 10))
            self.cover.setToolTip("Cliquer pour changer la pochette")
        elif self.mode == "search":
            q = self.search.text().strip()
            self.title.setText(f"Résultats pour « {q} »" if q else "Rechercher")
        else:
            self.title.setText("Ta bibliothèque")
            self.cover.setPixmap(gfx.track_cover(tracks[0] if tracks else None, 190, 10))
            self.cover.setToolTip("")
        self.desc.setVisible(bool(self.desc.text()))
        self.meta.setText(meta)
        self._set_tint(self.cover.pixmap() if self.mode != "search" else None)
        self.table.colors = m.settings.colors
        scroll = self.table.verticalScrollBar().value()
        self.table.set_tracks(tracks, sortable=self.mode != "playlist")
        self.table.apply_filter(self.search.text())
        self.table.verticalScrollBar().setValue(scroll)
        self.table.playing_id = m.player.current_id
        empty = not tracks
        self.table.setVisible(not empty)
        self.empty.setVisible(empty)
        self.empty.setText({
            "liked": "Les titres que tu likes (♥) apparaîtront ici.",
            "playlist": "Cette playlist est vide.\nClic droit sur un titre → « Ajouter à la playlist ».",
        }.get(self.mode, "Aucun titre pour l'instant. Va dans « Importer » pour ajouter de la musique."))

    def _cover_clicked(self):
        if self.mode == "playlist":
            self.m.change_playlist_cover(self.pid)

    def _play_all(self):
        ids = self.table.visible_ids()
        cur = self.m.player.current_id
        if cur in ids and self.m.player.original[:len(ids)] == ids:
            self.m.player.toggle()
        else:
            self.m.play_ids(ids, 0)

    def _play_row(self, row):
        self.m.play_ids(self.table.visible_ids(), self.table.visible_index_of_row(row))


# =========================================================================== Import
class ImportPage(QScrollArea):
    def __init__(self, main):
        super().__init__()
        self.m = main
        self.setWidgetResizable(True)
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(28, 6, 28, 28)
        lay.setSpacing(12)
        self.setWidget(body)

        lay.addWidget(_label("Importer de la musique", "h1"))
        lay.addWidget(_label("Colle un ou plusieurs liens (un par ligne). Titres seuls, playlists, albums, "
                             "profils TikTok… tout est téléchargé dans ta bibliothèque pour écouter hors-ligne.",
                             "sub", wrap=True))
        chips = QHBoxLayout()
        chips.setSpacing(8)
        for s in ("YouTube", "YouTube Music", "Spotify", "TikTok", "SoundCloud", "Bandcamp", "MP3 / FLAC / WAV…",
                  "+ 1000 sites"):
            chips.addWidget(_label(s, "chip"))
        chips.addStretch()
        lay.addLayout(chips)

        self.links = QPlainTextEdit()
        self.links.setPlaceholderText(
            "https://www.youtube.com/watch?v=…\n"
            "https://open.spotify.com/playlist/…\n"
            "https://www.tiktok.com/@artiste/video/…\n"
            "https://soundcloud.com/…")
        self.links.setFixedHeight(150)
        lay.addWidget(self.links)

        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(_label("Ajouter à :", "sub"))
        self.target = QComboBox()
        self.target.setMinimumWidth(280)
        row.addWidget(self.target)
        row.addStretch()
        self.go = QPushButton("  Importer")
        self.go.setObjectName("accent")
        self.go.setCursor(Qt.PointingHandCursor)
        self.go.clicked.connect(self._import_links)
        row.addWidget(self.go)
        lay.addLayout(row)

        row2 = QHBoxLayout()
        row2.setSpacing(10)
        self.files_btn = QPushButton("  Fichiers audio…")
        self.folder_btn = QPushButton("  Dossier entier…")
        for b in (self.files_btn, self.folder_btn):
            b.setObjectName("ghost")
            b.setCursor(Qt.PointingHandCursor)
            row2.addWidget(b)
        self.files_btn.clicked.connect(lambda: self.m.import_files_dialog(self.current_target()))
        self.folder_btn.clicked.connect(lambda: self.m.import_folder_dialog(self.current_target()))
        row2.addWidget(_label("Astuce : glisse-dépose des fichiers, des dossiers ou des liens n'importe où "
                              "sur la fenêtre.", "small", wrap=True), 1)
        lay.addLayout(row2)

        lay.addSpacing(12)
        lay.addWidget(_label("Progression", "h2"))
        self.status = _label("Aucun import en cours.", "sub")
        lay.addWidget(self.status)
        prow = QHBoxLayout()
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.overall = _label("", "small")
        self.cancel = QPushButton("Annuler")
        self.cancel.setObjectName("ghost")
        self.cancel.setEnabled(False)
        self.cancel.clicked.connect(self.m.worker.cancel)
        prow.addWidget(self.bar, 1)
        prow.addWidget(self.overall)
        prow.addWidget(self.cancel)
        lay.addLayout(prow)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(220)
        self.log.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        lay.addWidget(self.log, 1)

        main.bind_icon(self.go, "download", "on_accent")
        main.bind_icon(self.files_btn, "note", "text")
        main.bind_icon(self.folder_btn, "folder", "text")

        w = main.worker
        w.status.connect(lambda s: self.status.setText(s or "Terminé."))
        w.progress.connect(lambda v: self.bar.setValue(int(v * 10)))
        w.overall.connect(lambda d, t: self.overall.setText(f"{d}/{t}" if t else ""))
        w.busy.connect(self.cancel.setEnabled)
        w.log.connect(self.add_log)

    def refresh_targets(self):
        cur = self.target.currentData()
        self.target.clear()
        self.target.addItem("Automatique (les playlists deviennent des playlists 4tafy)", "auto")
        self.target.addItem("Bibliothèque uniquement", "none")
        for pl in self.m.lib.playlists:
            self.target.addItem(f"Playlist : {pl['name']}", pl["id"])
        i = self.target.findData(cur)
        self.target.setCurrentIndex(max(0, i))

    def current_target(self):
        return self.target.currentData() or "auto"

    def _import_links(self):
        urls = [u.strip() for u in self.links.toPlainText().split() if u.strip().startswith(("http", "spotify:"))]
        if not urls:
            self.m.toast("Colle au moins un lien valide.")
            return
        self.m.worker.add_urls(urls, self.current_target())
        self.links.clear()
        self.m.toast(f"{len(urls)} lien(s) ajouté(s) à la file d'import")

    def add_log(self, msg, level):
        c = self.m.settings.colors
        color = {"ok": c["accent"], "err": "#ef4444"}.get(level, c["subtext"])
        stamp = time.strftime("%H:%M:%S")
        safe = msg.replace("&", "&amp;").replace("<", "&lt;")
        self.log.append(f'<span style="color:{c["subtext"]}">{stamp}</span>&nbsp; '
                        f'<span style="color:{color}">{safe}</span>')


# =========================================================================== File d'attente
class QueuePage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.m = main
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 6, 28, 8)
        lay.setSpacing(10)
        lay.addWidget(_label("File d'attente", "h1"))
        lay.addWidget(_label("En cours de lecture", "h3"))
        self.now = TrackTable(main.lib, main.settings.colors)
        self.now.horizontalHeader().hide()
        self.now.setFixedHeight(62)
        self.now.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.now.like_toggled.connect(main.toggle_like)
        self.now.play_row.connect(lambda r: main.player.toggle())
        lay.addWidget(self.now)
        lay.addWidget(_label("À suivre", "h3"))
        self.next = TrackTable(main.lib, main.settings.colors)
        self.next.like_toggled.connect(main.toggle_like)
        self.next.play_row.connect(lambda r: main.player.jump_to(main.player.index + 1 + r))
        self.next.menu_requested.connect(self._menu)
        lay.addWidget(self.next, 1)

    def refresh(self):
        p = self.m.player
        for tbl in (self.now, self.next):
            tbl.colors = self.m.settings.colors
            tbl.playing_id = p.current_id
        cur = [p.current] if p.current else []
        self.now.set_tracks(cur, sortable=False)
        self.next.set_tracks([self.m.lib.get(t) for t in p.upcoming() if self.m.lib.get(t)], sortable=False)

    def _menu(self, ids, pos):
        rows = sorted({i.row() for i in self.next.selectedIndexes()})
        positions = [self.m.player.index + 1 + r for r in rows]
        self.m.track_menu(ids, pos, queue_positions=positions)
