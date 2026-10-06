"""« Chrome » de fenêtre façon macOS : fenêtre sans bordure, coins arrondis, ombre portée,
boutons rouge / jaune / vert, zones de déplacement et redimensionnement par les bords."""
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QMovie, QPainter, QPainterPath, QPen, QPixmap, QLinearGradient
from PySide6.QtWidgets import QFrame, QWidget

from . import graphics as gfx

SHADOW = 14  # taille de l'ombre autour de la fenêtre (px)


def _edges_at(widget, pos, margin):
    """Bords de fenêtre sous la souris (zone d'ombre + 4 px à l'intérieur)."""
    grab = margin + 4
    e = Qt.Edge(0)
    if pos.x() <= grab:
        e |= Qt.LeftEdge
    elif pos.x() >= widget.width() - grab:
        e |= Qt.RightEdge
    if pos.y() <= grab:
        e |= Qt.TopEdge
    elif pos.y() >= widget.height() - grab:
        e |= Qt.BottomEdge
    return e


def _v(edges):
    return getattr(edges, "value", edges)


_CURSORS = {
    _v(Qt.LeftEdge): Qt.SizeHorCursor, _v(Qt.RightEdge): Qt.SizeHorCursor,
    _v(Qt.TopEdge): Qt.SizeVerCursor, _v(Qt.BottomEdge): Qt.SizeVerCursor,
    _v(Qt.LeftEdge | Qt.TopEdge): Qt.SizeFDiagCursor, _v(Qt.RightEdge | Qt.BottomEdge): Qt.SizeFDiagCursor,
    _v(Qt.RightEdge | Qt.TopEdge): Qt.SizeBDiagCursor, _v(Qt.LeftEdge | Qt.BottomEdge): Qt.SizeBDiagCursor,
}


class WindowBackground(QWidget):
    """Widget central : dessine l'ombre, le fond arrondi et le fond d'écran perso."""

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.margin = SHADOW
        self.maximized = False
        self._key = None
        self._src = None
        self._movie = None
        self._scaled = None
        self._scaled_size = QSize()
        self.setMouseTracking(True)

    # -- géométrie
    def set_maximized(self, maxi):
        self.maximized = maxi
        self.margin = 0 if maxi or not self.settings["window_shadow"] else SHADOW
        if self.layout():
            self.layout().setContentsMargins(self.margin, self.margin, self.margin, self.margin)
        self._scaled = None
        self.update()

    def body_rect(self):
        m = self.margin
        return QRectF(m, m, self.width() - 2 * m, self.height() - 2 * m)

    def radius(self):
        return 0 if self.maximized else self.settings["radius"]

    # -- fond d'écran
    def reload(self):
        s = self.settings
        key = (s["wallpaper"], s["wallpaper_blur"])
        if key != self._key:
            self._key = key
            self._src = None
            self._scaled = None
            if self._movie:
                self._movie.stop()
                self._movie.deleteLater()
                self._movie = None
            path = s["wallpaper"]
            if path and Path(path).exists():
                if path.lower().endswith(".gif"):
                    self._movie = QMovie(path)
                    self._movie.frameChanged.connect(self.update)
                    self._movie.start()
                else:
                    pm = QPixmap(path)
                    if not pm.isNull():
                        if max(pm.width(), pm.height()) > 2200:
                            pm = pm.scaled(2200, 2200, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                        self._src = gfx.blurred(pm, s["wallpaper_blur"])
        self.set_maximized(self.maximized)

    def _cover_rect(self, size, area):
        scale = max(area.width() / max(1, size.width()), area.height() / max(1, size.height()))
        sw, sh = size.width() * scale, size.height() * scale
        return QRectF(area.x() + (area.width() - sw) / 2, area.y() + (area.height() - sh) / 2, sw, sh)

    def paintEvent(self, _):
        c = self.settings.colors
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        body = self.body_rect()
        rad = self.radius()

        # ombre portée douce (anneaux de plus en plus transparents)
        m = self.margin
        if m:
            p.setPen(Qt.NoPen)
            for i in range(m, 0, -1):
                a = int(70 * (1 - i / m) ** 2.2) + 1
                p.setBrush(QColor(0, 0, 0, a))
                p.drawRoundedRect(body.adjusted(-i, -i + 3, i, i + 3), rad + i, rad + i)

        path = QPainterPath()
        path.addRoundedRect(body, rad, rad)
        p.setClipPath(path)
        p.fillRect(body, QColor(c["bg"]))
        pm = None
        if self._movie:
            pm = self._movie.currentPixmap()
            if not pm.isNull():
                p.drawPixmap(self._cover_rect(pm.size(), body), pm, QRectF(pm.rect()))
        elif self._src is not None:
            r = self._cover_rect(self._src.size(), body)
            if self._scaled is None or self._scaled_size != self.size():
                self._scaled = self._src.scaled(int(r.width()) + 1, int(r.height()) + 1,
                                                Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
                self._scaled_size = self.size()
            p.drawPixmap(int(r.x()), int(r.y()), self._scaled)
            pm = self._src
        if pm is not None:
            dim = QColor(c["bg"])
            dim.setAlpha(int(255 * self.settings["wallpaper_dim"] / 100))
            p.fillRect(body, dim)
        elif self.settings["accent_glow"]:
            g = QLinearGradient(0, body.top(), 0, body.top() + body.height() * 0.55)
            a = QColor(c["accent"])
            a.setAlpha(45)
            g.setColorAt(0, a)
            a.setAlpha(0)
            g.setColorAt(1, a)
            p.fillRect(body, g)
        p.end()

    # -- redimensionnement par les bords
    def mouseMoveEvent(self, e):
        if self.maximized:
            self.unsetCursor()
            return
        edges = _edges_at(self, e.position().toPoint(), self.margin)
        cur = _CURSORS.get(_v(edges))
        if cur is None:
            self.unsetCursor()
        else:
            self.setCursor(cur)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and not self.maximized:
            edges = _edges_at(self, e.position().toPoint(), self.margin)
            if _v(edges):
                self.window().windowHandle().startSystemResize(edges)
                return
        super().mousePressEvent(e)


class WindowOutline(QWidget):
    """Fin liseré clair autour de la fenêtre, dessiné par-dessus tout (comme sur macOS)."""

    def __init__(self, bg):
        super().__init__(bg)
        self.bg = bg
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def paintEvent(self, _):
        if self.bg.maximized:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.bg.body_rect().adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor(255, 255, 255, 30), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(r, self.bg.radius(), self.bg.radius())
        p.end()


class DragArea(QWidget):
    """Zone vide qui sert de barre de titre : glisser = déplacer, double-clic = agrandir."""

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.window().windowHandle().startSystemMove()
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        w = self.window()
        w.showNormal() if w.isMaximized() else w.showMaximized()


class TrafficLights(QWidget):
    """Les trois boutons ronds de macOS : fermer, réduire, agrandir."""
    COLORS = ("#ff5f57", "#febc2e", "#28c840")
    D = 12
    GAP = 8

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(3 * self.D + 2 * self.GAP + 4, self.D + 8)
        self.setMouseTracking(True)
        self.setCursor(Qt.ArrowCursor)
        self._hover = False
        self._pressed = -1

    def _circle(self, i):
        return QRectF(2 + i * (self.D + self.GAP), 4, self.D, self.D)

    def _index(self, pos):
        for i in range(3):
            if self._circle(i).adjusted(-3, -3, 3, 3).contains(QPointF(pos)):
                return i
        return -1

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def mousePressEvent(self, e):
        self._pressed = self._index(e.position().toPoint())

    def mouseReleaseEvent(self, e):
        i = self._index(e.position().toPoint())
        if i == self._pressed and i >= 0:
            w = self.window()
            if i == 0:
                w.close()
            elif i == 1:
                w.showMinimized()
            else:
                w.showNormal() if w.isMaximized() else w.showMaximized()
        self._pressed = -1

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        active = self.window().isActiveWindow() or self._hover
        for i, col in enumerate(self.COLORS):
            r = self._circle(i)
            base = QColor(col) if active else QColor(128, 128, 128, 110)
            p.setPen(QPen(base.darker(125), 0.8))
            p.setBrush(base)
            p.drawEllipse(r)
            if self._hover:
                p.setPen(QPen(QColor(0, 0, 0, 150), 1.3, Qt.SolidLine, Qt.RoundCap))
                cx, cy = r.center().x(), r.center().y()
                k = 2.6
                if i == 0:
                    p.drawLine(QPointF(cx - k, cy - k), QPointF(cx + k, cy + k))
                    p.drawLine(QPointF(cx + k, cy - k), QPointF(cx - k, cy + k))
                elif i == 1:
                    p.drawLine(QPointF(cx - k - 0.6, cy), QPointF(cx + k + 0.6, cy))
                else:
                    p.setPen(Qt.NoPen)
                    p.setBrush(QColor(0, 0, 0, 150))
                    path = QPainterPath()
                    path.moveTo(cx - 3, cy + 1.2); path.lineTo(cx - 3, cy - 3); path.lineTo(cx + 1.2, cy - 3)
                    path.closeSubpath()
                    path.moveTo(cx + 3, cy - 1.2); path.lineTo(cx + 3, cy + 3); path.lineTo(cx - 1.2, cy + 3)
                    path.closeSubpath()
                    p.drawPath(path)
        p.end()



class ContentFrame(QFrame):
    """Zone de contenu ; peut afficher un dégradé de la couleur de la pochette en haut."""

    def __init__(self, bg, parent=None):
        super().__init__(parent)
        self.bg = bg
        self.tint = None

    def set_tint(self, color):
        self.tint = color
        self.update()

    def paintEvent(self, e):
        super().paintEvent(e)
        if self.tint is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        R = self.bg.radius()
        path = QPainterPath()
        path.addRoundedRect(QRectF(-R, 0, self.width() + R, self.height() + R), R, R)
        p.setClipPath(path)
        h = 400
        g = QLinearGradient(0, 0, 0, h)
        c = QColor(self.tint)
        c.setAlpha(120)
        g.setColorAt(0, c)
        c.setAlpha(0)
        g.setColorAt(1, c)
        p.fillRect(0, 0, self.width(), h, g)
        p.end()
