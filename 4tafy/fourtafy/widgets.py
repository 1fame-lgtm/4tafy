"""Widgets réutilisables de l'interface."""
import time

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import (QAbstractItemView, QFrame, QHBoxLayout, QHeaderView, QLabel, QLayout, QPushButton,
                               QSizePolicy, QSlider, QStyle, QStyledItemDelegate, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)

from . import graphics as gfx
from .importer import SOURCE_LABELS
from .themes import on_color, qcolor


def fmt_time(seconds):
    seconds = int(seconds or 0)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_total(seconds):
    seconds = int(seconds or 0)
    h, rem = divmod(seconds, 3600)
    m = rem // 60
    return f"{h} h {m} min" if h else f"{m} min"


# --------------------------------------------------------------------------- slider cliquable
class ClickSlider(QSlider):
    """Slider qui saute directement à l'endroit cliqué."""
    def __init__(self, *a):
        super().__init__(Qt.Horizontal, *a)
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            val = QStyle.sliderValueFromPosition(self.minimum(), self.maximum(),
                                                 int(e.position().x()), self.width())
            self.setValue(val)
            self.sliderMoved.emit(val)
        super().mousePressEvent(e)


# --------------------------------------------------------------------------- flow layout
class FlowLayout(QLayout):
    """Layout qui passe à la ligne automatiquement (grille de cartes)."""
    def __init__(self, parent=None, spacing=16):
        super().__init__(parent)
        self._items = []
        self._sp = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientations(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self._do(QRect(0, 0, w, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        s = QSize()
        for it in self._items:
            s = s.expandedTo(it.minimumSize())
        return s

    def _do(self, rect, test):
        x, y, line_h = rect.x(), rect.y(), 0
        for it in self._items:
            hint = it.sizeHint()
            nx = x + hint.width() + self._sp
            if nx - self._sp > rect.right() and line_h > 0:
                x = rect.x()
                y += line_h + self._sp
                nx = x + hint.width() + self._sp
                line_h = 0
            if not test:
                it.setGeometry(QRect(QPoint(x, y), hint))
            x = nx
            line_h = max(line_h, hint.height())
        return y + line_h - rect.y()


def clear_layout(layout):
    while layout.count():
        it = layout.takeAt(0)
        w = it.widget()
        if w:
            w.hide()
            w.setParent(None)
            w.deleteLater()
        elif it.layout():
            clear_layout(it.layout())


# --------------------------------------------------------------------------- cartes
class Clickable(QFrame):
    clicked = Signal()
    right_clicked = Signal(QPoint)

    def __init__(self, name="card", parent=None):
        super().__init__(parent)
        self.setObjectName(name)
        self.setAttribute(Qt.WA_Hover)
        self.setCursor(Qt.PointingHandCursor)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()
        elif e.button() == Qt.RightButton:
            self.right_clicked.emit(e.globalPosition().toPoint())


class Card(Clickable):
    """Grande carte : pochette + titre + sous-titre ; un bouton lecture apparaît au survol."""
    play_clicked = Signal()

    def __init__(self, pixmap, title, subtitle, size=150, play_icon=None, parent=None):
        super().__init__("card", parent)
        self.setFixedWidth(size + 20)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 12)
        lay.setSpacing(2)
        img = QLabel()
        img.setPixmap(pixmap)
        img.setFixedSize(size, size)
        lay.addWidget(img)
        lay.addSpacing(8)
        fm = QFontMetrics(self.font())
        t = QLabel(fm.elidedText(title, Qt.ElideRight, size))
        t.setObjectName("h3")
        t.setToolTip(title)
        s = QLabel(fm.elidedText(subtitle, Qt.ElideRight, size))
        s.setObjectName("small")
        lay.addWidget(t)
        lay.addWidget(s)
        self.play = None
        if play_icon is not None:
            self.play = QPushButton(img)
            self.play.setObjectName("cardplay")
            self.play.setIcon(play_icon)
            self.play.setIconSize(QSize(18, 18))
            self.play.setFixedSize(40, 40)
            self.play.setCursor(Qt.PointingHandCursor)
            self.play.move(size - 48, size - 48)
            self.play.clicked.connect(self.play_clicked)
            self.play.hide()

    def enterEvent(self, e):
        if self.play:
            self.play.show()
        super().enterEvent(e)

    def leaveEvent(self, e):
        if self.play:
            self.play.hide()
        super().leaveEvent(e)


class Tile(Clickable):
    """Raccourci horizontal (pochette + nom), comme en haut de l'accueil Spotify."""
    def __init__(self, pixmap, title, parent=None):
        super().__init__("tile", parent)
        self.setFixedSize(300, 64)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 12, 0)
        lay.setSpacing(14)
        img = QLabel()
        img.setPixmap(pixmap)
        img.setFixedSize(64, 64)
        lay.addWidget(img)
        t = QLabel(QFontMetrics(self.font()).elidedText(title, Qt.ElideRight, 200))
        t.setObjectName("h3")
        lay.addWidget(t, 1)


# --------------------------------------------------------------------------- table des titres
SORT_ROLE = Qt.UserRole + 1
COL_NUM, COL_TITLE, COL_ALBUM, COL_SOURCE, COL_ADDED, COL_LIKE, COL_DUR = range(7)


class SortItem(QTableWidgetItem):
    def __lt__(self, other):
        a, b = self.data(SORT_ROLE), other.data(SORT_ROLE)
        try:
            return a < b
        except TypeError:
            return str(a) < str(b)


class RowDelegate(QStyledItemDelegate):
    def __init__(self, table):
        super().__init__(table)
        self.t = table

    def paint(self, p, opt, idx):
        t = self.t
        c = t.colors
        row, col = idx.row(), idx.column()
        tid = t.row_id(row)
        track = t.lib.get(tid)
        r = opt.rect
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        selected = bool(opt.state & QStyle.State_Selected)
        row_rect = QRect(0, r.y(), t.viewport().width(), r.height()).adjusted(4, 1, -4, -1)
        p.setClipRect(r)
        p.setPen(Qt.NoPen)
        if selected:
            p.setBrush(QColor(c["accent"]))
        elif row == t.hover_row:
            p.setBrush(qcolor(c["text"], 0.08))
        elif row % 2 == 1:
            p.setBrush(qcolor(c["text"], 0.025))
        else:
            p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(row_rect, 6, 6)
        p.setClipping(False)
        playing = tid is not None and tid == t.playing_id
        if selected:
            txt = QColor(on_color(c["accent"]))
            sub = qcolor(on_color(c["accent"]), 0.78)
            acc = txt
        else:
            sub = QColor(c["subtext"])
            txt = QColor(c["text"])
            acc = QColor(c["accent"])
        if not track:
            p.restore()
            return
        if col == COL_NUM:
            if playing and t.is_playing:
                gfx.equalizer_bars(p, r, acc, t.phase)
            elif row == t.hover_row:
                gfx.icon("play", txt.name(), 32).paint(p, QRect(r.center().x() - 8, r.center().y() - 8, 16, 16))
            else:
                p.setPen(acc if playing else sub)
                p.drawText(r, Qt.AlignCenter, str(idx.data(Qt.DisplayRole)))
        elif col == COL_TITLE:
            pm = gfx.track_cover(track, 40, 5)
            p.drawPixmap(r.x() + 4, r.y() + (r.height() - 40) // 2, pm)
            x = r.x() + 56
            w = r.width() - 60
            f = QFont(opt.font)
            f.setWeight(QFont.DemiBold)
            p.setFont(f)
            p.setPen(acc if playing else txt)
            fm = QFontMetrics(f)
            p.drawText(QRect(x, r.y() + 7, w, r.height() // 2 - 4), Qt.AlignLeft | Qt.AlignBottom,
                       fm.elidedText(track["title"], Qt.ElideRight, w))
            p.setFont(opt.font)
            p.setPen(sub)
            p.drawText(QRect(x, r.y() + r.height() // 2 + 2, w, r.height() // 2 - 6), Qt.AlignLeft | Qt.AlignTop,
                       QFontMetrics(opt.font).elidedText(track["artist"] or "Artiste inconnu", Qt.ElideRight, w))
        elif col == COL_LIKE:
            if track["liked"] or row == t.hover_row or selected:
                name = "heart_full" if track["liked"] else "heart"
                color = (acc.name() if track["liked"] else sub.name()) if selected else \
                    (c["accent"] if track["liked"] else c["subtext"])
                gfx.icon(name, color, 36).paint(p, QRect(r.center().x() - 9, r.center().y() - 9, 18, 18))
        else:
            p.setPen(sub)
            align = (Qt.AlignRight if col == COL_DUR else Qt.AlignLeft) | Qt.AlignVCenter
            text = str(idx.data(Qt.DisplayRole) or "")
            rr = r.adjusted(8, 0, -12, 0)
            p.drawText(rr, align, QFontMetrics(opt.font).elidedText(text, Qt.ElideRight, rr.width()))
        p.restore()


class TrackTable(QTableWidget):
    play_row = Signal(int)
    like_toggled = Signal(str)
    menu_requested = Signal(list, QPoint)

    HEADERS = ["#", "Titre", "Album", "Source", "Ajouté le", "", "Durée"]

    def __init__(self, lib, colors, parent=None):
        super().__init__(0, len(self.HEADERS), parent)
        self.lib = lib
        self.colors = colors
        self.hover_row = -1
        self.playing_id = None
        self.is_playing = False
        self.phase = 0.0
        self.setHorizontalHeaderLabels(self.HEADERS)
        self.setItemDelegate(RowDelegate(self))
        self.verticalHeader().hide()
        self.verticalHeader().setDefaultSectionSize(54)
        self.setShowGrid(False)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setMouseTracking(True)
        self.setWordWrap(False)
        self.viewport().setAutoFillBackground(False)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        h = self.horizontalHeader()
        h.setHighlightSections(False)
        h.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        h.setSectionResizeMode(QHeaderView.Interactive)
        h.setSectionResizeMode(COL_TITLE, QHeaderView.Stretch)
        for col, w in ((COL_NUM, 52), (COL_ALBUM, 190), (COL_SOURCE, 110), (COL_ADDED, 110),
                       (COL_LIKE, 40), (COL_DUR, 72)):
            self.setColumnWidth(col, w)
        h.setSectionResizeMode(COL_NUM, QHeaderView.Fixed)
        h.setSectionResizeMode(COL_LIKE, QHeaderView.Fixed)
        h.setSortIndicator(COL_NUM, Qt.AscendingOrder)

    def set_tracks(self, tracks, sortable=True):
        self.setSortingEnabled(False)
        self.clearContents()
        self.setRowCount(len(tracks))
        for i, t in enumerate(tracks):
            vals = [
                (str(i + 1), i),
                (t["title"], t["title"].lower()),
                (t["album"], t["album"].lower()),
                (SOURCE_LABELS.get(t["source"], t["source"].title())
                 + ("  ⚠ à vérifier" if t.get("match") == "uncertain" else ""), t["source"]),
                (time.strftime("%d/%m/%Y", time.localtime(t["added"])), t["added"]),
                ("", int(t["liked"])),
                (fmt_time(t["duration"]), t["duration"]),
            ]
            for col, (text, key) in enumerate(vals):
                it = SortItem(text)
                it.setData(SORT_ROLE, key)
                if col == 0:
                    it.setData(Qt.UserRole, t["id"])
                self.setItem(i, col, it)
        h = self.horizontalHeader()
        if sortable:
            self.setSortingEnabled(True)
            self.sortItems(h.sortIndicatorSection(), h.sortIndicatorOrder())
        else:
            h.setSortIndicator(COL_NUM, Qt.AscendingOrder)
        h.setSortIndicatorShown(sortable)

    def row_id(self, row):
        it = self.item(row, 0)
        return it.data(Qt.UserRole) if it else None

    def visible_ids(self):
        return [self.row_id(r) for r in range(self.rowCount()) if not self.isRowHidden(r)]

    def selected_ids(self):
        rows = sorted({i.row() for i in self.selectedIndexes()})
        return [self.row_id(r) for r in rows]

    def apply_filter(self, text):
        text = text.lower().strip()
        for r in range(self.rowCount()):
            t = self.lib.get(self.row_id(r))
            hay = f"{t['title']} {t['artist']} {t['album']} {t['source']}".lower() if t else ""
            self.setRowHidden(r, bool(text) and text not in hay)

    def visible_index_of_row(self, row):
        ids = self.visible_ids()
        tid = self.row_id(row)
        return ids.index(tid) if tid in ids else 0

    # interactions
    def mouseMoveEvent(self, e):
        row = self.rowAt(int(e.position().y()))
        if row != self.hover_row:
            self.hover_row = row
            self.viewport().update()
        col = self.columnAt(int(e.position().x()))
        self.viewport().setCursor(Qt.PointingHandCursor if col in (COL_NUM, COL_LIKE) and row >= 0
                                  else Qt.ArrowCursor)
        super().mouseMoveEvent(e)

    def leaveEvent(self, e):
        self.hover_row = -1
        self.viewport().update()
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        pos = e.position().toPoint()
        row, col = self.rowAt(pos.y()), self.columnAt(pos.x())
        if e.button() == Qt.LeftButton and row >= 0:
            if col == COL_LIKE:
                self.like_toggled.emit(self.row_id(row))
                self.viewport().update()
                return
            if col == COL_NUM:
                self.play_row.emit(row)
                return
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        row = self.rowAt(int(e.position().y()))
        if row >= 0:
            self.play_row.emit(row)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and self.currentRow() >= 0:
            self.play_row.emit(self.currentRow())
        else:
            super().keyPressEvent(e)

    def _menu(self, pos):
        row = self.rowAt(pos.y())
        if row < 0:
            return
        if row not in {i.row() for i in self.selectedIndexes()}:
            self.selectRow(row)
        self.menu_requested.emit(self.selected_ids(), self.viewport().mapToGlobal(pos))


def hline():
    f = QFrame()
    f.setObjectName("sep")
    f.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    return f
