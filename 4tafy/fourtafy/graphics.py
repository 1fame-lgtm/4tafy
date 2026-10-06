"""Icônes vectorielles dessinées à la main + pochettes générées.

Aucune image externe : tout est dessiné avec QPainter, donc les icônes prennent
automatiquement les couleurs du thème.
"""
import math
import zlib
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QIcon, QImage, QLinearGradient, QPainter,
                           QPainterPath, QPen, QPixmap, QPolygonF)
from PySide6.QtWidgets import QGraphicsBlurEffect, QGraphicsPixmapItem, QGraphicsScene


# --------------------------------------------------------------------------- icônes
def _pen(c, w=2.0):
    return QPen(c, w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)


def _poly(*pts):
    return QPolygonF([QPointF(x, y) for x, y in pts])


def _heart_path():
    path = QPainterPath()
    path.moveTo(12, 20.5)
    path.cubicTo(-1.5, 12, 4, 0.5, 12, 6.8)
    path.cubicTo(20, 0.5, 25.5, 12, 12, 20.5)
    return path


def _draw(name, p, c):
    p.setBrush(Qt.NoBrush)
    p.setPen(_pen(c))
    if name == "play":
        p.setPen(_pen(c, 1.5)); p.setBrush(c)
        p.drawPolygon(_poly((7.5, 4.5), (19.5, 12), (7.5, 19.5)))
    elif name == "pause":
        p.setPen(Qt.NoPen); p.setBrush(c)
        p.drawRoundedRect(QRectF(6, 4.5, 4.2, 15), 1.2, 1.2)
        p.drawRoundedRect(QRectF(13.8, 4.5, 4.2, 15), 1.2, 1.2)
    elif name == "next":
        p.setPen(_pen(c, 1.2)); p.setBrush(c)
        p.drawPolygon(_poly((5, 5), (15.5, 12), (5, 19)))
        p.drawRoundedRect(QRectF(16.5, 5, 2.6, 14), 1, 1)
    elif name == "prev":
        p.setPen(_pen(c, 1.2)); p.setBrush(c)
        p.drawPolygon(_poly((19, 5), (8.5, 12), (19, 19)))
        p.drawRoundedRect(QRectF(4.9, 5, 2.6, 14), 1, 1)
    elif name == "shuffle":
        a = QPainterPath(); a.moveTo(3, 7); a.lineTo(7, 7); a.cubicTo(13, 7, 11, 17, 17, 17); a.lineTo(20, 17)
        b = QPainterPath(); b.moveTo(3, 17); b.lineTo(7, 17); b.cubicTo(13, 17, 11, 7, 17, 7); b.lineTo(20, 7)
        p.drawPath(a); p.drawPath(b)
        p.drawPolyline(_poly((17, 4), (20, 7), (17, 10)))
        p.drawPolyline(_poly((17, 14), (20, 17), (17, 20)))
    elif name in ("repeat", "repeat_one"):
        path = QPainterPath()
        path.moveTo(17, 6.5); path.lineTo(7, 6.5); path.arcTo(QRectF(3, 6.5, 8, 9), 90, 90); path.lineTo(3, 12)
        path.moveTo(7, 17.5); path.lineTo(17, 17.5); path.arcTo(QRectF(13, 8.5, 8, 9), 270, 90); path.lineTo(21, 12)
        p.drawPath(path)
        p.drawPolyline(_poly((14.5, 3.5), (17.5, 6.5), (14.5, 9.5)))
        p.drawPolyline(_poly((9.5, 14.5), (6.5, 17.5), (9.5, 20.5)))
        if name == "repeat_one":
            f = QFont("Segoe UI", 7); f.setBold(True); p.setFont(f)
            p.drawText(QRectF(8, 7, 8, 10), Qt.AlignCenter, "1")
    elif name == "heart":
        p.drawPath(_heart_path())
    elif name == "heart_full":
        p.setBrush(c); p.drawPath(_heart_path())
    elif name in ("volume", "volume_low", "volume_mute"):
        p.setPen(_pen(c, 1.2)); p.setBrush(c)
        p.drawPolygon(_poly((3, 9), (7, 9), (12, 4.5), (12, 19.5), (7, 15), (3, 15)))
        p.setBrush(Qt.NoBrush); p.setPen(_pen(c))
        if name == "volume_mute":
            p.drawLine(QPointF(15.5, 9), QPointF(21, 15)); p.drawLine(QPointF(21, 9), QPointF(15.5, 15))
        else:
            p.drawArc(QRectF(10, 8, 7, 8), -60 * 16, 120 * 16)
            if name == "volume":
                p.drawArc(QRectF(9, 4.5, 12, 15), -60 * 16, 120 * 16)
    elif name == "queue":
        for y in (6, 11):
            p.drawLine(QPointF(3, y), QPointF(15, y))
        p.drawLine(QPointF(3, 16), QPointF(10, 16))
        p.setBrush(c); p.setPen(_pen(c, 1))
        p.drawPolygon(_poly((14, 13), (21, 17), (14, 21)))
    elif name == "home":
        p.drawPolyline(_poly((3.5, 11), (12, 3.5), (20.5, 11)))
        p.drawPolyline(_poly((6, 9), (6, 20), (18, 20), (18, 9)))
        p.drawPolyline(_poly((10, 20), (10, 14), (14, 14), (14, 20)))
    elif name == "search":
        p.drawEllipse(QRectF(3.5, 3.5, 12, 12)); p.setPen(_pen(c, 2.4))
        p.drawLine(QPointF(14, 14), QPointF(20.5, 20.5))
    elif name == "library":
        p.drawLine(QPointF(5, 4), QPointF(5, 20)); p.drawLine(QPointF(10, 4), QPointF(10, 20))
        p.drawLine(QPointF(14.5, 5), QPointF(19.5, 19.5))
    elif name == "plus":
        p.setPen(_pen(c, 2.2))
        p.drawLine(QPointF(12, 4), QPointF(12, 20)); p.drawLine(QPointF(4, 12), QPointF(20, 12))
    elif name == "download":
        p.drawLine(QPointF(12, 3), QPointF(12, 15))
        p.drawPolyline(_poly((7, 10.5), (12, 15.5), (17, 10.5)))
        p.drawPolyline(_poly((4, 15), (4, 20), (20, 20), (20, 15)))
    elif name == "brush":
        path = QPainterPath(); path.moveTo(20, 3.5); path.lineTo(10.5, 13); path.lineTo(12.5, 15); path.lineTo(21, 5); path.closeSubpath()
        p.setBrush(c); p.drawPath(path)
        tip = QPainterPath(); tip.moveTo(9.5, 14); tip.cubicTo(5, 13.5, 6, 19, 3, 20.5); tip.cubicTo(8, 21, 12, 19.5, 11.5, 16)
        p.drawPath(tip)
    elif name == "dots":
        p.setPen(Qt.NoPen); p.setBrush(c)
        for x in (5, 12, 19):
            p.drawEllipse(QPointF(x, 12), 2, 2)
    elif name == "note":
        p.setBrush(c)
        p.drawEllipse(QRectF(4.5, 15, 6, 5)); p.drawEllipse(QRectF(13.5, 13, 6, 5))
        p.setBrush(Qt.NoBrush)
        p.drawPolyline(_poly((10.5, 17.5), (10.5, 5), (19.5, 3), (19.5, 15.5)))
    elif name == "puzzle":
        path = QPainterPath()
        path.moveTo(4, 8); path.lineTo(9, 8)
        path.arcTo(QRectF(9, 4.5, 4, 4), 200, -220)
        path.lineTo(17, 8); path.lineTo(17, 12)
        path.arcTo(QRectF(17.5, 12, 4, 4), 110, -220)
        path.lineTo(17, 20); path.lineTo(4, 20); path.closeSubpath()
        p.drawPath(path)
    elif name == "sliders":
        for x, y in ((6, 15), (12, 8), (18, 13)):
            p.drawLine(QPointF(x, 4), QPointF(x, 20))
            p.setBrush(c)
            p.drawEllipse(QPointF(x, y), 2.4, 2.4)
    elif name == "chevron_left":
        p.setPen(_pen(c, 2.4))
        p.drawPolyline(_poly((15, 5), (8, 12), (15, 19)))
    elif name == "chevron_right":
        p.setPen(_pen(c, 2.4))
        p.drawPolyline(_poly((9, 5), (16, 12), (9, 19)))
    elif name == "close":
        p.drawLine(QPointF(6, 6), QPointF(18, 18)); p.drawLine(QPointF(18, 6), QPointF(6, 18))
    elif name == "folder":
        p.drawPolyline(_poly((3, 19), (3, 5), (9, 5), (11, 7.5), (21, 7.5), (21, 19), (3, 19)))
    elif name == "link":
        p.drawRoundedRect(QRectF(2.5, 8.5, 10, 7), 3.5, 3.5)
        p.drawRoundedRect(QRectF(11.5, 8.5, 10, 7), 3.5, 3.5)


def icon(name, color="#ffffff", size=48):
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(size / 24.0, size / 24.0)
    _draw(name, p, QColor(color))
    p.end()
    return QIcon(pm)


def _squircle(rect, n=5.0, steps=160):
    """Forme « squircle » des icônes macOS (super-ellipse)."""
    path = QPainterPath()
    cx, cy = rect.center().x(), rect.center().y()
    a, b = rect.width() / 2, rect.height() / 2
    for i in range(steps + 1):
        t = 2 * math.pi * i / steps
        c, s_ = math.cos(t), math.sin(t)
        x = cx + a * math.copysign(abs(c) ** (2 / n), c)
        y = cy + b * math.copysign(abs(s_) ** (2 / n), s_)
        path.moveTo(x, y) if i == 0 else path.lineTo(x, y)
    path.closeSubpath()
    return path


def _shift(color, hue_delta, light=100):
    h, s_, v, a = color.getHsv()
    c = QColor.fromHsv((max(h, 0) + hue_delta) % 360, s_, v, a)
    return c.lighter(light) if light >= 100 else c.darker(int(10000 / light))


_icon_cache = {}


def app_icon(accent="#fa2d48"):
    """Icône 4tafy : squircle dégradé, reflet, « 4 » épais et ondes sonores."""
    if accent in _icon_cache:
        return _icon_cache[accent]
    S = 512
    pm = QPixmap(S, S)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    body = QRectF(S * 0.06, S * 0.06, S * 0.88, S * 0.88)
    shape = _squircle(body)
    acc = QColor(accent)

    # ombre portée de l'icône
    p.setPen(Qt.NoPen)
    for i in range(10, 0, -1):
        p.setBrush(QColor(0, 0, 0, 5))
        p.drawPath(_squircle(body.adjusted(-i * 0.6, -i * 0.2 + 6, i * 0.6, i + 6)))

    # fond dégradé
    g = QLinearGradient(body.topLeft(), body.bottomRight())
    g.setColorAt(0, _shift(acc, 16, 135))
    g.setColorAt(0.55, acc)
    g.setColorAt(1, _shift(acc, -24, 60))
    p.setBrush(g)
    p.drawPath(shape)
    p.save()
    p.setClipPath(shape)
    # halo lumineux en haut à gauche + reflet
    from PySide6.QtGui import QRadialGradient
    rg = QRadialGradient(body.left() + body.width() * 0.25, body.top() + body.height() * 0.15, body.width() * 0.75)
    rg.setColorAt(0, QColor(255, 255, 255, 90))
    rg.setColorAt(1, QColor(255, 255, 255, 0))
    p.setBrush(rg)
    p.drawRect(body)
    gloss = QLinearGradient(0, body.top(), 0, body.top() + body.height() * 0.5)
    gloss.setColorAt(0, QColor(255, 255, 255, 55))
    gloss.setColorAt(1, QColor(255, 255, 255, 0))
    p.setBrush(gloss)
    p.drawRect(body)
    p.restore()

    # « 4 » avec ombre douce
    f = QFont("Inter", 1)
    if not QFont(f).exactMatch():
        f = QFont("Segoe UI", 1)
    f.setPixelSize(int(S * 0.56))
    f.setWeight(QFont.Black)
    p.setFont(f)
    txt_rect = QRectF(body.left() + body.width() * 0.02, body.top() - body.height() * 0.02,
                      body.width() * 0.62, body.height())
    for dy, alpha in ((14, 35), (9, 45), (5, 55)):
        p.setPen(QColor(0, 0, 0, alpha))
        p.drawText(txt_rect.translated(0, dy), Qt.AlignCenter, "4")
    p.setPen(QColor(255, 255, 255))
    p.drawText(txt_rect, Qt.AlignCenter, "4")

    # ondes sonores
    cx = body.left() + body.width() * 0.60
    cy = body.center().y() + body.height() * 0.02
    for i, (r, alpha) in enumerate(((0.16, 245), (0.27, 175))):
        rad = body.width() * r
        pen = QPen(QColor(255, 255, 255, alpha), S * 0.045, Qt.SolidLine, Qt.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawArc(QRectF(cx - rad, cy - rad, 2 * rad, 2 * rad), -45 * 16, 90 * 16)

    # liseré intérieur
    p.setPen(QPen(QColor(255, 255, 255, 45), S * 0.006))
    p.setBrush(Qt.NoBrush)
    p.drawPath(_squircle(body.adjusted(2, 2, -2, -2)))
    p.end()
    ic = QIcon(pm)
    _icon_cache[accent] = ic
    return ic


def custom_app_icon(path, rounded=True):
    """Icône perso à partir de n'importe quelle image : recadrage carré, lissage, arrondi optionnel."""
    p = Path(path)
    if not path or not p.exists():
        return None
    key = (str(p), rounded, p.stat().st_mtime)
    if key in _icon_cache:
        return _icon_cache[key]
    sq = load_square(str(p), 512)
    if sq is None:
        return None
    if rounded:
        out = QPixmap(512, 512)
        out.fill(Qt.transparent)
        painter = QPainter(out)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        body = QRectF(512 * 0.06, 512 * 0.06, 512 * 0.88, 512 * 0.88)
        painter.setClipPath(_squircle(body))
        painter.drawPixmap(body.toRect(), sq)
        painter.setClipping(False)
        painter.setPen(QPen(QColor(255, 255, 255, 40), 3))
        painter.drawPath(_squircle(body.adjusted(1.5, 1.5, -1.5, -1.5)))
        painter.end()
        sq = out
    ic = QIcon(sq)
    _icon_cache[key] = ic
    return ic


def save_ico(icon, dest):
    """Enregistre une icône au format .ico (pour les raccourcis Windows)."""
    img = icon.pixmap(256, 256).toImage()
    return img.save(str(dest), "ICO")


# --------------------------------------------------------------------------- pochettes
_cover_cache = {}


def _seed_colors(seed):
    h = zlib.crc32(seed.encode("utf-8")) & 0xFFFFFFFF
    hue = h % 360
    hue2 = (hue + 40 + (h >> 9) % 80) % 360
    return QColor.fromHsv(hue, 170, 210), QColor.fromHsv(hue2, 200, 90)


def generated_cover(seed, size, kind="note"):
    if kind == "liked":
        c1, c2 = QColor("#4f46e5"), QColor("#c4b5fd")
    else:
        c1, c2 = _seed_colors(seed or "4tafy")
    pm = QPixmap(size, size)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    g = QLinearGradient(0, 0, size, size)
    g.setColorAt(0, c1); g.setColorAt(1, c2)
    p.fillRect(0, 0, size, size, QBrush(g))
    s = size * 0.42
    p.translate((size - s) / 2, (size - s) / 2)
    p.scale(s / 24, s / 24)
    _draw("heart_full" if kind == "liked" else "note", p, QColor(255, 255, 255, 220))
    p.end()
    return pm


def _rounded(pm, radius):
    if radius <= 0:
        return pm
    out = QPixmap(pm.size())
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, pm.width(), pm.height()), radius, radius)
    p.setClipPath(path)
    p.drawPixmap(0, 0, pm)
    p.end()
    return out


def load_square(path, size):
    """Charge une image et la recadre au centre en carré."""
    if not path or not Path(path).exists():
        return None
    img = QImage(str(path))
    if img.isNull():
        return None
    side = min(img.width(), img.height())
    img = img.copy((img.width() - side) // 2, (img.height() - side) // 2, side, side)
    return QPixmap.fromImage(img.scaled(size, size, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))


def cover(path, size, radius=6, seed="", kind="note"):
    key = (path or "", size, radius, seed, kind)
    pm = _cover_cache.get(key)
    if pm is None:
        pm = load_square(path, size) or generated_cover(seed, size, kind)
        pm = _rounded(pm, radius)
        if len(_cover_cache) > 2500:
            _cover_cache.clear()
        _cover_cache[key] = pm
    return pm


def forget_cover(path):
    for k in [k for k in _cover_cache if k[0] == path]:
        _cover_cache.pop(k, None)


def track_cover(track, size, radius=6):
    if not track:
        return cover("", size, radius, "4tafy")
    return cover(track.get("cover", ""), size, radius, track.get("title", "") + track.get("artist", ""))


# --------------------------------------------------------------------------- fond d'écran
def blurred(pm, radius):
    if radius <= 0 or pm.isNull():
        return pm
    scene = QGraphicsScene()
    item = QGraphicsPixmapItem(pm)
    eff = QGraphicsBlurEffect()
    eff.setBlurRadius(radius)
    eff.setBlurHints(QGraphicsBlurEffect.QualityHint)
    item.setGraphicsEffect(eff)
    scene.addItem(item)
    img = QImage(pm.size(), QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    scene.render(p, QRectF(0, 0, pm.width(), pm.height()), QRectF(0, 0, pm.width(), pm.height()))
    p.end()
    return QPixmap.fromImage(img)


def equalizer_bars(p, rect, color, phase=0.0):
    """Petit égaliseur animé dessiné pour le titre en cours de lecture."""
    p.save()
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    w = 3
    gap = 2
    total = 3 * w + 2 * gap
    x0 = rect.center().x() - total / 2
    base = rect.center().y() + 7
    for i in range(3):
        h = 5 + 8 * abs(math.sin(phase + i * 1.3))
        p.drawRoundedRect(QRectF(x0 + i * (w + gap), base - h, w, h), 1, 1)
    p.restore()
