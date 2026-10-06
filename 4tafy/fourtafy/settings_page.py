"""Page « Personnaliser » : thèmes, couleurs, fond d'écran, police, export/import de thèmes."""
import json
import shutil
import sys
import time
from pathlib import Path

from PySide6.QtCore import QProcess, QRectF, QSize, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QColorDialog, QFileDialog, QFontComboBox, QGridLayout,
                               QHBoxLayout, QLabel, QMessageBox, QPushButton, QScrollArea, QSlider, QSpinBox,
                               QVBoxLayout, QWidget)

from .config import APP_NAME, DATA_DIR, IMAGE_FILTER, THEMES_DIR, VERSION, WALLPAPER_DIR
from .themes import COLOR_LABELS, PRESETS
from .widgets import hline

LOOK_KEYS = ("colors", "wallpaper_dim", "wallpaper_blur", "panel_opacity", "radius",
             "font_family", "font_size", "accent_glow")


def preset_icon(colors, size=44):
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(colors["bg"]))
    p.drawRoundedRect(QRectF(0, 0, size, size), 8, 8)
    p.setBrush(QColor(colors["panel"]))
    p.drawRoundedRect(QRectF(4, 4, size * 0.35, size - 8), 4, 4)
    p.setBrush(QColor(colors["accent"]))
    p.drawEllipse(QRectF(size * 0.5, size * 0.5, size * 0.38, size * 0.38))
    p.setBrush(QColor(colors["text"]))
    p.drawRoundedRect(QRectF(size * 0.48, size * 0.18, size * 0.42, 4), 2, 2)
    p.end()
    return QIcon(pm)


def color_icon(hex_color, w=40, h=26):
    pm = QPixmap(w, h)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(hex_color))
    p.drawRoundedRect(QRectF(0, 0, w, h), 6, 6)
    p.end()
    return QIcon(pm)


class SettingsPage(QScrollArea):
    def __init__(self, main):
        super().__init__()
        self.m = main
        self.s = main.settings
        self._loading = False
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(28, 24, 28, 40)
        lay.setSpacing(12)
        self.setWidget(body)

        def title(text, sub=None):
            lay.addSpacing(10)
            lb = QLabel(text)
            lb.setObjectName("h2")
            lay.addWidget(lb)
            if sub:
                s = QLabel(sub)
                s.setObjectName("sub")
                s.setWordWrap(True)
                lay.addWidget(s)

        h1 = QLabel("Personnaliser 4tafy")
        h1.setObjectName("h1")
        lay.addWidget(h1)
        sub = QLabel("Tout est modifiable : les changements s'appliquent en direct et sont sauvegardés.")
        sub.setObjectName("sub")
        lay.addWidget(sub)

        # ------------------------------------------------ thèmes
        title("Thèmes", "Choisis un thème de départ, puis ajuste chaque couleur si tu veux.")
        grid = QGridLayout()
        grid.setSpacing(10)
        self.preset_group = QButtonGroup(self)
        self.preset_btns = {}
        for i, (name, colors) in enumerate(PRESETS.items()):
            b = QPushButton(f"  {name}".replace("&", "&&"))
            b.setObjectName("preset")
            b.setCheckable(True)
            b.setIcon(preset_icon(colors))
            b.setIconSize(QSize(36, 36))
            b.setCursor(Qt.PointingHandCursor)
            b.setMinimumHeight(56)
            b.clicked.connect(lambda _=False, n=name: self.apply_preset(n))
            self.preset_group.addButton(b)
            self.preset_btns[name] = b
            grid.addWidget(b, i // 4, i % 4)
        lay.addLayout(grid)

        # ------------------------------------------------ couleurs
        title("Couleurs")
        cgrid = QGridLayout()
        cgrid.setHorizontalSpacing(18)
        cgrid.setVerticalSpacing(8)
        self.color_btns = {}
        for i, (key, label) in enumerate(COLOR_LABELS.items()):
            b = QPushButton()
            b.setObjectName("swatch")
            b.setFixedSize(52, 34)
            b.setIconSize(QSize(40, 24))
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self.pick_color(k))
            self.color_btns[key] = b
            row, col = divmod(i, 4)
            cell = QHBoxLayout()
            cell.addWidget(b)
            cell.addWidget(QLabel(label))
            cell.addStretch()
            cgrid.addLayout(cell, row, col)
        lay.addLayout(cgrid)

        # ------------------------------------------------ fond d'écran
        title("Fond d'écran", "Une image (PNG, JPG, WEBP) ou même un GIF animé derrière toute l'application.")
        wrow = QHBoxLayout()
        wrow.setSpacing(18)
        self.wall_preview = QLabel()
        self.wall_preview.setFixedSize(256, 144)
        self.wall_preview.setAlignment(Qt.AlignCenter)
        self.wall_preview.setObjectName("chip")
        wrow.addWidget(self.wall_preview)
        wcol = QVBoxLayout()
        wcol.setSpacing(8)
        btns = QHBoxLayout()
        choose = QPushButton("Choisir une image…")
        choose.setObjectName("accent")
        choose.setCursor(Qt.PointingHandCursor)
        choose.clicked.connect(self.choose_wallpaper)
        remove = QPushButton("Retirer")
        remove.setObjectName("ghost")
        remove.setCursor(Qt.PointingHandCursor)
        remove.clicked.connect(self.remove_wallpaper)
        btns.addWidget(choose)
        btns.addWidget(remove)
        btns.addStretch()
        wcol.addLayout(btns)
        self.dim = self._slider(wcol, "Assombrissement du fond", 0, 95, "wallpaper_dim", "%")
        self.blur = self._slider(wcol, "Flou du fond", 0, 40, "wallpaper_blur", " px", live=False)
        wcol.addStretch()
        wrow.addLayout(wcol, 1)
        lay.addLayout(wrow)

        # ------------------------------------------------ apparence
        title("Apparence")
        app = QVBoxLayout()
        app.setSpacing(8)
        self.opacity = self._slider(app, "Opacité des panneaux", 0, 100, "panel_opacity", "%")
        self.radius = self._slider(app, "Coins arrondis", 0, 28, "radius", " px")
        frow = QHBoxLayout()
        frow.addWidget(QLabel("Police"))
        self.font_box = QFontComboBox()
        self.font_box.setMinimumWidth(240)
        self.font_box.currentFontChanged.connect(lambda f: self._set("font_family", f.family()))
        frow.addWidget(self.font_box)
        frow.addSpacing(20)
        frow.addWidget(QLabel("Taille"))
        self.font_size = QSpinBox()
        self.font_size.setRange(8, 16)
        self.font_size.setSuffix(" pt")
        self.font_size.valueChanged.connect(lambda v: self._set("font_size", v))
        frow.addWidget(self.font_size)
        frow.addStretch()
        app.addLayout(frow)
        self.glow = QCheckBox("Dégradé de couleur d'accent en haut de l'écran (sans fond d'écran)")
        self.glow.toggled.connect(lambda v: self._set("accent_glow", v))
        app.addWidget(self.glow)
        self.shadow = QCheckBox("Ombre douce autour de la fenêtre (style macOS)")
        self.shadow.toggled.connect(lambda v: self._set("window_shadow", v))
        app.addWidget(self.shadow)
        self.clean = QCheckBox("Nettoyer les titres importés (retire « Official Video », « Lyrics »…)")
        self.clean.toggled.connect(lambda v: self._set("clean_titles", v, restyle=False))
        app.addWidget(self.clean)
        lay.addLayout(app)

        # ------------------------------------------------ icône de l'application
        title("Icône de l'application", "Choisis n'importe quelle image (PNG, JPG, WEBP, ICO…) : elle devient "
              "l'icône de la fenêtre, de la barre des tâches et du logo. Aucune compilation nécessaire.")
        irow = QHBoxLayout()
        irow.setSpacing(18)
        self.icon_preview = QLabel()
        self.icon_preview.setFixedSize(96, 96)
        irow.addWidget(self.icon_preview)
        icol = QVBoxLayout()
        icol.setSpacing(8)
        ib = QHBoxLayout()
        pick_icon = QPushButton("Choisir une image…")
        pick_icon.setObjectName("accent")
        pick_icon.setCursor(Qt.PointingHandCursor)
        pick_icon.clicked.connect(self.choose_icon)
        default_icon = QPushButton("Icône 4tafy par défaut")
        default_icon.setObjectName("ghost")
        default_icon.clicked.connect(self.reset_icon)
        ib.addWidget(pick_icon)
        ib.addWidget(default_icon)
        ib.addStretch()
        icol.addLayout(ib)
        self.icon_round = QCheckBox("Arrondir l'icône façon macOS")
        self.icon_round.toggled.connect(self._toggle_icon_round)
        icol.addWidget(self.icon_round)
        sc = QHBoxLayout()
        self.shortcut_btn = QPushButton("Créer un raccourci sur le Bureau avec cette icône")
        self.shortcut_btn.setObjectName("ghost")
        self.shortcut_btn.clicked.connect(self.create_shortcut)
        self.shortcut_btn.setVisible(sys.platform == "win32")
        sc.addWidget(self.shortcut_btn)
        sc.addStretch()
        icol.addLayout(sc)
        icol.addStretch()
        irow.addLayout(icol, 1)
        lay.addLayout(irow)

        # ------------------------------------------------ partage
        title("Partager mes thèmes", "Exporte ton thème en fichier .json pour le partager, ou importe celui d'un ami.")
        srow = QHBoxLayout()
        for text, fn in (("Exporter mon thème…", self.export_theme), ("Importer un thème…", self.import_theme),
                         ("Réinitialiser l'apparence", self.reset)):
            b = QPushButton(text)
            b.setObjectName("ghost")
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(fn)
            srow.addWidget(b)
        srow.addStretch()
        lay.addLayout(srow)

        # ------------------------------------------------ stockage / à propos
        title("Stockage")
        st = QHBoxLayout()
        lb = QLabel(f"Musique, pochettes et réglages : {DATA_DIR}")
        lb.setObjectName("sub")
        lb.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lb.setWordWrap(True)
        st.addWidget(lb, 1)
        ob = QPushButton("Ouvrir le dossier")
        ob.setObjectName("ghost")
        ob.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(DATA_DIR))))
        st.addWidget(ob)
        lay.addLayout(st)
        up = QHBoxLayout()
        lb = QLabel("YouTube / TikTok changent souvent : si un import échoue, mets à jour le moteur de "
                    "téléchargement (yt-dlp).")
        lb.setObjectName("sub")
        lb.setWordWrap(True)
        up.addWidget(lb, 1)
        self.update_btn = QPushButton("Mettre à jour yt-dlp")
        self.update_btn.setObjectName("ghost")
        self.update_btn.clicked.connect(self.update_ytdlp)
        up.addWidget(self.update_btn)
        lay.addLayout(up)
        lay.addWidget(hline())
        about = QLabel(f"{APP_NAME} v{VERSION} — lecteur de musique libre et open source (licence MIT). "
                       "Fait avec Python, PySide6, yt-dlp et mutagen. Modifie le code comme tu veux !")
        about.setObjectName("small")
        about.setWordWrap(True)
        lay.addWidget(about)
        lay.addStretch()
        self.load()

    # ---------------------------------------------------------------- helpers
    def _slider(self, layout, label, lo, hi, key, suffix, live=True):
        row = QHBoxLayout()
        lb = QLabel(label)
        lb.setMinimumWidth(200)
        sl = QSlider(Qt.Horizontal)
        sl.setRange(lo, hi)
        sl.setMaximumWidth(380)
        val = QLabel()
        val.setObjectName("sub")
        val.setMinimumWidth(50)
        sl.valueChanged.connect(lambda v: val.setText(f"{v}{suffix}"))
        if live:
            sl.valueChanged.connect(lambda v: self._set(key, v))
        else:  # le flou est coûteux : on l'applique au relâchement
            sl.sliderReleased.connect(lambda: self._set(key, sl.value()))
            sl.valueChanged.connect(lambda v: None if sl.isSliderDown() else self._set(key, v))
        row.addWidget(lb)
        row.addWidget(sl, 1)
        row.addWidget(val)
        row.addStretch()
        layout.addLayout(row)
        sl._val = val
        sl._suffix = suffix
        return sl

    def _set(self, key, value, restyle=True):
        if self._loading:
            return
        self.s[key] = value
        if restyle:
            self.m.schedule_theme()
        else:
            self.s.save()

    def load(self):
        """Synchronise les contrôles avec les réglages."""
        self._loading = True
        s = self.s
        for name, b in self.preset_btns.items():
            b.setChecked(name == s["preset"])
        if s["preset"] not in self.preset_btns:
            self.preset_group.setExclusive(False)
            for b in self.preset_btns.values():
                b.setChecked(False)
            self.preset_group.setExclusive(True)
        for k, b in self.color_btns.items():
            b.setIcon(color_icon(s.colors[k]))
            b.setToolTip(s.colors[k])
        for sl, key in ((self.dim, "wallpaper_dim"), (self.blur, "wallpaper_blur"),
                        (self.opacity, "panel_opacity"), (self.radius, "radius")):
            sl.setValue(s[key])
            sl._val.setText(f"{s[key]}{sl._suffix}")
        self.font_box.setCurrentFont(QFont(s["font_family"]))
        self.font_size.setValue(s["font_size"])
        self.glow.setChecked(s["accent_glow"])
        self.icon_round.setChecked(s["icon_round"])
        self._update_icon_preview()
        self.shadow.setChecked(s["window_shadow"])
        self.clean.setChecked(s["clean_titles"])
        self._update_wall_preview()
        self._loading = False

    def _update_wall_preview(self):
        path = self.s["wallpaper"]
        pm = QPixmap(path) if path else QPixmap()
        if pm.isNull():
            self.wall_preview.setPixmap(QPixmap())
            self.wall_preview.setText("Aucun fond d'écran")
        else:
            self.wall_preview.setPixmap(pm.scaled(256, 144, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                                        .copy(0, 0, 256, 144))

    # ---------------------------------------------------------------- actions
    def apply_preset(self, name):
        self.s["preset"] = name
        self.s.colors.update(PRESETS[name])
        self.load()
        self.m.schedule_theme()

    def pick_color(self, key):
        c = QColorDialog.getColor(QColor(self.s.colors[key]), self, f"Couleur : {COLOR_LABELS[key]}")
        if c.isValid():
            self.s.colors[key] = c.name()
            self.s["preset"] = "Personnalisé"
            self.load()
            self.m.schedule_theme()

    def choose_wallpaper(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choisir un fond d'écran", str(Path.home() / "Pictures"),
                                              IMAGE_FILTER)
        if not path:
            return
        WALLPAPER_DIR.mkdir(parents=True, exist_ok=True)
        dest = WALLPAPER_DIR / f"{int(time.time())}_{Path(path).name}"
        try:
            shutil.copy2(path, dest)
        except OSError:
            dest = Path(path)
        self.s["wallpaper"] = str(dest)
        self._update_wall_preview()
        self.m.schedule_theme()

    def remove_wallpaper(self):
        self.s["wallpaper"] = ""
        self._update_wall_preview()
        self.m.schedule_theme()

    def export_theme(self):
        THEMES_DIR.mkdir(parents=True, exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(self, "Exporter le thème", str(THEMES_DIR / "mon_theme.4tafy.json"),
                                              "Thème 4tafy (*.json)")
        if not path:
            return
        data = {"app": "4tafy", "name": Path(path).stem.replace(".4tafy", "")}
        data.update({k: self.s[k] for k in LOOK_KEYS})
        Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        self.m.toast("Thème exporté !")

    def import_theme(self):
        path, _ = QFileDialog.getOpenFileName(self, "Importer un thème", str(THEMES_DIR), "Thème 4tafy (*.json)")
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            for k in LOOK_KEYS:
                if k == "colors":
                    self.s.colors.update({ck: v for ck, v in data.get("colors", {}).items()
                                          if ck in COLOR_LABELS and QColor(v).isValid()})
                elif k in data:
                    self.s[k] = data[k]
            self.s["preset"] = data.get("name", "Importé")
        except (OSError, ValueError, AttributeError) as e:
            QMessageBox.warning(self, "4tafy", f"Thème invalide : {e}")
            return
        self.load()
        self.m.schedule_theme()
        self.m.toast("Thème importé !")

    def update_ytdlp(self):
        self.update_btn.setEnabled(False)
        self.update_btn.setText("Mise à jour…")
        proc = QProcess(self)
        proc.finished.connect(lambda code, _st: self._update_done(proc, code))
        proc.start(sys.executable, ["-m", "pip", "install", "-U", "yt-dlp"])

    def _update_done(self, proc, code):
        self.update_btn.setEnabled(True)
        self.update_btn.setText("Mettre à jour yt-dlp")
        if code == 0:
            self.m.toast("yt-dlp est à jour ! Redémarre 4tafy pour l'utiliser.")
        else:
            err = bytes(proc.readAllStandardError()).decode(errors="replace")[-200:]
            self.m.toast(f"Échec de la mise à jour : {err}")

    # ---------------------------------------------------------------- icône
    def _update_icon_preview(self):
        self.icon_preview.setPixmap(self.m.current_icon().pixmap(QSize(96, 96), self.devicePixelRatioF()))

    def choose_icon(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choisir l'icône de 4tafy", str(Path.home() / "Pictures"),
            "Images (*.png *.jpg *.jpeg *.webp *.bmp *.gif *.ico *.svg)")
        if not path:
            return
        from .config import ICON_DIR
        ICON_DIR.mkdir(parents=True, exist_ok=True)
        for old in ICON_DIR.glob("custom_*"):  # on ne garde que la dernière icône choisie
            try:
                old.unlink()
            except OSError:
                pass
        dest = ICON_DIR / f"custom_{int(time.time())}{Path(path).suffix.lower()}"
        try:
            shutil.copy2(path, dest)
        except OSError:
            dest = Path(path)
        from . import graphics as gfx
        if gfx.custom_app_icon(str(dest)) is None:
            QMessageBox.warning(self, "4tafy", "Cette image ne peut pas être lue.")
            return
        self.s["custom_icon"] = str(dest)
        self._apply_icon()
        self.m.toast("Nouvelle icône appliquée !")

    def reset_icon(self):
        self.s["custom_icon"] = ""
        self._apply_icon()

    def _toggle_icon_round(self, on):
        if self._loading:
            return
        self.s["icon_round"] = on
        self._apply_icon()

    def _apply_icon(self):
        self.s.save()
        self.m.apply_theme()
        self._update_icon_preview()

    def create_shortcut(self):
        """Raccourci « 4tafy » sur le Bureau, qui lance l'appli sans console, avec l'icône choisie."""
        from .config import ICON_ICO
        import subprocess
        self.m.current_icon()  # (ré)écrit le fichier .ico
        exe = Path(sys.executable)
        pythonw = exe.with_name("pythonw.exe")
        target = pythonw if pythonw.exists() else exe
        script = Path(__file__).resolve().parents[1] / "main.py"
        import base64
        q = lambda v: str(v).replace("'", "''")  # échappement d'une chaîne PowerShell entre apostrophes
        ps = "\n".join([
            "$ErrorActionPreference = 'Stop'",
            "$d = [Environment]::GetFolderPath('Desktop')",
            "$s = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d '4tafy.lnk'))",
            f"$s.TargetPath = '{q(target)}'",
            f"$s.Arguments = '\"' + '{q(script)}' + '\"'",
            f"$s.WorkingDirectory = '{q(script.parent)}'",
            f"$s.IconLocation = '{q(ICON_ICO)},0'",
            "$s.Description = '4tafy - lecteur de musique'",
            "$s.Save()",
        ])
        # script encodé en base64 (UTF-16) : aucun souci de guillemets ni d'accents dans les chemins
        encoded = base64.b64encode(ps.encode("utf-16-le")).decode("ascii")
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                                "-EncodedCommand", encoded],
                               capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            ok = r.returncode == 0
        except Exception as e:
            ok, r = False, type("R", (), {"stderr": str(e)})
        if ok:
            self.m.toast("Raccourci « 4tafy » créé sur le Bureau !")
        else:
            QMessageBox.warning(self, "4tafy", "Impossible de créer le raccourci :\n" + (r.stderr or "")[-300:])

    def reset(self):
        self.s.reset_look()
        self.load()
        self.m.schedule_theme()
