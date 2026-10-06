"""Fenêtre « Corriger le son » : quand l'import a pris la mauvaise musique, on choisit la bonne
version parmi les meilleurs résultats YouTube (classés par ressemblance + durée), ou on colle un lien."""
import threading

from PySide6.QtCore import QSize, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
                               QVBoxLayout)

from . import matcher
from .widgets import fmt_time


class FixMatchDialog(QDialog):
    results = Signal(object)

    def __init__(self, main, track):
        super().__init__(main)
        self.m = main
        self.t = track
        q = track.get("query") or {}
        self.q_title = q.get("title") or track["title"]
        self.q_artist = q.get("artist") or track["artist"]
        self.q_dur = q.get("duration") or track["duration"]
        self.setWindowTitle("Corriger le son")
        self.resize(760, 560)
        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        h = QLabel(f"Corriger : {self.q_artist + ' — ' if self.q_artist else ''}{self.q_title}")
        h.setObjectName("h2")
        h.setWordWrap(True)
        lay.addWidget(h)
        info = QLabel(f"Durée attendue : {fmt_time(self.q_dur)}   •   Version actuelle : "
                      f"{track.get('yt_title') or track.get('url') or 'inconnue'}")
        info.setObjectName("sub")
        info.setWordWrap(True)
        lay.addWidget(info)

        row = QHBoxLayout()
        self.query = QLineEdit(f"{self.q_artist} - {self.q_title}" if self.q_artist else self.q_title)
        self.query.returnPressed.connect(self.search)
        go = QPushButton("Rechercher")
        go.setObjectName("dlg")
        go.clicked.connect(self.search)
        row.addWidget(self.query, 1)
        row.addWidget(go)
        lay.addLayout(row)

        self.status = QLabel("")
        self.status.setObjectName("small")
        lay.addWidget(self.status)
        self.list = QListWidget()
        self.list.setIconSize(QSize(1, 1))
        self.list.setSpacing(2)
        self.list.itemDoubleClicked.connect(lambda _it: self.accept_choice())
        lay.addWidget(self.list, 1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("ou colle un lien :"))
        self.link = QLineEdit()
        self.link.setPlaceholderText("https://www.youtube.com/watch?v=…  (ou SoundCloud, etc.)")
        row2.addWidget(self.link, 1)
        lay.addLayout(row2)

        btns = QHBoxLayout()
        open_btn = QPushButton("Voir sur YouTube")
        open_btn.setObjectName("dlg")
        open_btn.clicked.connect(self._open)
        btns.addWidget(open_btn)
        btns.addStretch()
        cancel = QPushButton("Annuler")
        cancel.setObjectName("dlg")
        cancel.clicked.connect(self.reject)
        ok = QPushButton("Remplacer par cette version")
        ok.setObjectName("accent")
        ok.clicked.connect(self.accept_choice)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        lay.addLayout(btns)

        self.results.connect(self._show)
        self.search()

    def search(self):
        text = self.query.text().strip()
        if not text:
            return
        self.status.setText("Recherche des meilleures versions…")
        self.list.clear()
        title, artist, dur = self.q_title, self.q_artist, self.q_dur
        custom = text != (f"{artist} - {title}" if artist else title)

        def job():
            try:
                if custom:  # recherche libre : on garde le titre/la durée attendus pour le classement
                    cands = matcher._flat(f"ytsearch12:{text}", 12)
                    for c in cands:
                        c["score"], c["diff"] = matcher.score(c, title, artist, dur)
                    cands.sort(key=lambda c: c["score"], reverse=True)
                else:
                    cands = matcher.find_candidates(title, artist, dur, deep=True, n=12)
                self.results.emit(cands)
            except Exception as e:
                self.results.emit(str(e))

        threading.Thread(target=job, daemon=True).start()

    def _show(self, cands):
        if isinstance(cands, str):
            self.status.setText(f"Erreur : {cands}")
            return
        current = (self.t.get("url") or "").split("v=")[-1][:11]
        self.list.clear()
        for i, c in enumerate(cands[:15]):
            d = f"{fmt_time(c['duration'])}" if c.get("duration") else "?:??"
            diff = f"  (écart {c['diff']:.0f} s)" if c.get("diff") is not None else ""
            tag = "  ★ recommandé" if i == 0 else ""
            cur = "  ← actuel" if c["id"] == current else ""
            it = QListWidgetItem(f"{c['title']}\n{c.get('channel') or '?'}  •  {d}{diff}{tag}{cur}")
            it.setData(Qt.UserRole, c["url"])
            it.setSizeHint(QSize(0, 48))
            self.list.addItem(it)
        if self.list.count():
            self.list.setCurrentRow(0)
        self.status.setText(f"{len(cands)} versions trouvées, classées de la plus probable à la moins probable. "
                            "Double-clic pour choisir.")

    def _url(self):
        link = self.link.text().strip()
        if link.startswith("http"):
            return link
        it = self.list.currentItem()
        return it.data(Qt.UserRole) if it else None

    def _open(self):
        url = self._url()
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def accept_choice(self):
        url = self._url()
        if not url:
            return
        self.m.worker.add_replace(self.t["id"], url)
        self.m.toast("Remplacement en cours… (suivi dans Importer)")
        self.accept()
