"""Thèmes prédéfinis + génération de la feuille de style Qt (QSS).

Pour ajouter ton propre thème intégré, ajoute simplement une entrée dans PRESETS.
"""
from PySide6.QtGui import QColor

COLOR_LABELS = {
    "bg": "Fond",
    "panel": "Panneaux",
    "card": "Cartes / champs",
    "hover": "Survol",
    "accent": "Accent",
    "text": "Texte",
    "subtext": "Texte secondaire",
    "border": "Bordures",
}

PRESETS = {
    "macOS Sombre": dict(bg="#1c1c1e", panel="#28282b", card="#2c2c2e", hover="#3a3a3c",
                         accent="#fa2d48", text="#f5f5f7", subtext="#98989d", border="#3a3a3c"),
    "macOS Clair": dict(bg="#ffffff", panel="#f2f2f5", card="#f5f5f7", hover="#e8e8ed",
                        accent="#fa2d48", text="#1d1d1f", subtext="#86868b", border="#d2d2d7"),
    "macOS Bleu": dict(bg="#1e1e20", panel="#2a2a2d", card="#2c2c2e", hover="#3a3a3c",
                       accent="#0a84ff", text="#f5f5f7", subtext="#98989d", border="#3a3a3c"),
    "4tafy": dict(bg="#0b0b10", panel="#15151d", card="#1f1f2b", hover="#2a2a3a",
                  accent="#a855f7", text="#ffffff", subtext="#a7a7b3", border="#2e2e3e"),
    "Spotify Classic": dict(bg="#000000", panel="#121212", card="#1f1f1f", hover="#2a2a2a",
                            accent="#1db954", text="#ffffff", subtext="#b3b3b3", border="#2a2a2a"),
    "Minuit": dict(bg="#070b14", panel="#0f1626", card="#18223a", hover="#22304f",
                   accent="#3b82f6", text="#e6edf7", subtext="#8fa0bd", border="#22304f"),
    "Océan": dict(bg="#031a1f", panel="#062a31", card="#0b3a43", hover="#0f4b57",
                  accent="#22d3ee", text="#e0fbff", subtext="#8cc4cc", border="#11505c"),
    "Coucher de soleil": dict(bg="#1a0b0b", panel="#241010", card="#331716", hover="#42201d",
                              accent="#fb923c", text="#fff4ec", subtext="#d0a594", border="#4a2622"),
    "Dracula": dict(bg="#1e1f29", panel="#282a36", card="#343746", hover="#44475a",
                    accent="#ff79c6", text="#f8f8f2", subtext="#a4a8c7", border="#44475a"),
    "Matrix": dict(bg="#000000", panel="#050f05", card="#0a1a0a", hover="#0f2a0f",
                   accent="#00ff66", text="#c8ffd8", subtext="#5fae78", border="#0f3a1a"),
    "Or & Noir": dict(bg="#0a0906", panel="#14120c", card="#1f1b12", hover="#2b2618",
                      accent="#eab308", text="#fff8e1", subtext="#b9ab83", border="#3a321c"),
    "Sakura": dict(bg="#fff1f5", panel="#ffffff", card="#ffe4ec", hover="#ffd6e3",
                   accent="#e8457a", text="#3a1f2b", subtext="#8a6574", border="#f6c6d6"),
}


def rgba(hex_color, alpha=1.0):
    c = QColor(hex_color)
    return f"rgba({c.red()},{c.green()},{c.blue()},{max(0, min(255, int(alpha * 255)))})"


def qcolor(hex_color, alpha=1.0):
    c = QColor(hex_color)
    c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


def on_color(hex_color):
    """Noir ou blanc selon ce qui est le plus lisible sur la couleur donnée."""
    c = QColor(hex_color)
    lum = 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()
    return "#000000" if lum > 160 else "#ffffff"


def lighten(hex_color, factor=115):
    return QColor(hex_color).lighter(factor).name()


def build_qss(settings, maximized=False):
    c = settings.colors
    op = settings["panel_opacity"] / 100
    R = 0 if maximized else settings["radius"]
    r = max(4, min(settings["radius"], 10))
    fs = settings["font_size"]
    font = settings["font_family"]
    t = c["text"]
    hair = rgba(t, 0.09)
    soft = rgba(t, 0.06)
    soft2 = rgba(t, 0.10)
    on_acc = on_color(c["accent"])
    return f"""
* {{ outline: 0; }}
QWidget {{ color: {t}; font-family: "{font}"; font-size: {fs}pt; }}
QMainWindow {{ background: transparent; }}

/* ---- structure de la fenêtre (style macOS) ---- */
QFrame#side {{ background: {rgba(c['panel'], op)}; border-top-left-radius: {R}px; border-right: 1px solid {hair}; }}
QFrame#content {{ background: {rgba(c['bg'], op)}; border-top-right-radius: {R}px; }}
QFrame#bar {{ background: {rgba(c['panel'], min(1, op + 0.04))}; border-top: 1px solid {hair};
             border-bottom-left-radius: {R}px; border-bottom-right-radius: {R}px; }}
QFrame#card {{ background: transparent; border-radius: {r + 2}px; }}
QFrame#card:hover {{ background: {soft}; }}
QFrame#tile {{ background: {soft}; border-radius: {r}px; }}
QFrame#tile:hover {{ background: {soft2}; }}
QFrame#studiocard {{ background: {soft}; border-radius: {r + 4}px; }}
QPushButton#segL, QPushButton#segR {{ background: {soft2}; color: {c['subtext']}; padding: 6px 14px; font-weight: 600;
    border-radius: 0; }}
QPushButton#segL {{ border-top-left-radius: 7px; border-bottom-left-radius: 7px; }}
QPushButton#segR {{ border-top-right-radius: 7px; border-bottom-right-radius: 7px; }}
QPushButton#segL:checked, QPushButton#segR:checked {{ background: {c['accent']}; color: {on_acc}; }}
QFrame#pcard {{ background: {soft}; border: 2px solid transparent; border-radius: {r + 4}px; }}
QFrame#pcard:hover {{ background: {soft2}; }}
QFrame#pcard[selected="true"] {{ border-color: {c['accent']}; }}
QFrame#sep {{ background: {hair}; max-height: 1px; min-height: 1px; }}
QStackedWidget, QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}

QLabel {{ background: transparent; }}
QLabel#logo {{ color: {t}; font-size: {fs + 4}pt; font-weight: 800; }}
QLabel#h1 {{ font-size: {fs + 18}pt; font-weight: 800; }}
QLabel#h2 {{ font-size: {fs + 5}pt; font-weight: 700; }}
QLabel#h3 {{ font-size: {fs + 1}pt; font-weight: 600; }}
QLabel#toolbartitle {{ font-size: {fs + 2}pt; font-weight: 700; }}
QLabel#sub, QLabel#small {{ color: {c['subtext']}; }}
QLabel#small {{ font-size: {max(7, fs - 1)}pt; }}
QLabel#section {{ color: {c['subtext']}; font-weight: 700; font-size: {max(7, fs - 1)}pt; }}
QLabel#chip {{ background: {soft}; border-radius: 11px; padding: 4px 12px; color: {c['subtext']}; }}
QLabel#nowtitle {{ font-weight: 600; }}
QLabel#nowartist {{ color: {c['subtext']}; font-size: {max(7, fs - 1)}pt; }}

/* ---- boutons ---- */
QPushButton {{ background: transparent; border: none; color: {c['subtext']}; padding: 6px 10px; border-radius: 6px; }}
QPushButton:hover {{ color: {t}; background: {soft}; }}
QPushButton:disabled {{ color: {rgba(c['subtext'], 0.4)}; }}
QPushButton#nav {{ text-align: left; padding: 6px 10px; color: {t}; font-weight: 500; border-radius: 6px; }}
QPushButton#nav:hover {{ background: {soft}; }}
QPushButton#nav:checked {{ background: {soft2}; font-weight: 600; }}
QPushButton#accent {{ background: {c['accent']}; color: {on_acc}; border-radius: 8px; padding: 7px 18px; font-weight: 600; }}
QPushButton#accent:hover {{ background: {lighten(c['accent'])}; color: {on_acc}; }}
QPushButton#ghost {{ background: {soft2}; color: {t}; border-radius: 8px; padding: 7px 16px; font-weight: 500; }}
QPushButton#ghost:hover {{ background: {rgba(t, 0.16)}; }}
QPushButton#icon {{ padding: 4px; border-radius: 6px; }}
QPushButton#icon:hover {{ background: {soft}; }}
QPushButton#icon:disabled {{ background: transparent; }}
QPushButton#playmain {{ background: {t}; border-radius: 17px; padding: 0; }}
QPushButton#playmain:hover {{ background: {t}; }}
QPushButton#playbig {{ background: {c['accent']}; border-radius: 26px; padding: 0; }}
QPushButton#cardplay {{ background: {c['accent']}; border-radius: 20px; padding: 0; }}
QPushButton#playbig:hover, QPushButton#cardplay:hover {{ background: {lighten(c['accent'])}; }}
QPushButton#swatch {{ border: 1px solid {hair}; border-radius: 8px; padding: 0; background: transparent; }}
QPushButton#swatch:hover {{ border-color: {t}; }}
QPushButton#preset {{ background: {soft}; border: 2px solid transparent; border-radius: 10px; padding: 8px;
                     color: {t}; font-weight: 600; }}
QPushButton#preset:hover {{ background: {soft2}; }}
QPushButton#preset:checked {{ border-color: {c['accent']}; }}

/* ---- champs ---- */
QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox, QFontComboBox {{
    background: {soft}; border: 1px solid {hair}; border-radius: 7px; padding: 6px 9px;
    selection-background-color: {c['accent']}; selection-color: {on_acc}; }}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus {{ border: 1px solid {c['accent']}; }}
QLineEdit#search {{ padding: 5px 8px; border-radius: 7px; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {c['panel']}; border: 1px solid {hair};
    selection-background-color: {c['accent']}; selection-color: {on_acc}; padding: 4px; outline: 0; }}

QListWidget {{ background: transparent; border: none; }}
QListWidget::item {{ padding: 4px 6px; border-radius: 6px; color: {t}; }}
QListWidget::item:hover {{ background: {soft}; }}
QListWidget::item:selected {{ background: {soft2}; color: {t}; }}

QTableWidget {{ background: transparent; border: none; gridline-color: transparent; }}
QTableWidget::item {{ background: transparent; border: none; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{ background: transparent; color: {c['subtext']}; border: none;
    border-bottom: 1px solid {hair}; padding: 5px 8px; font-weight: 600; font-size: {max(7, fs - 1)}pt; }}
QTableCornerButton::section {{ background: transparent; border: none; }}

QScrollBar:vertical {{ background: transparent; width: 9px; margin: 2px 1px; }}
QScrollBar::handle:vertical {{ background: {rgba(t, 0.22)}; border-radius: 3px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {rgba(t, 0.4)}; }}
QScrollBar:horizontal {{ background: transparent; height: 9px; margin: 1px 2px; }}
QScrollBar::handle:horizontal {{ background: {rgba(t, 0.22)}; border-radius: 3px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

QSlider {{ min-height: 16px; }}
QSlider::groove:horizontal {{ height: 4px; background: {rgba(t, 0.16)}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {rgba(t, 0.75)}; border-radius: 2px; }}
QSlider::sub-page:horizontal:hover {{ background: {c['accent']}; }}
QSlider::groove:vertical {{ width: 4px; background: {rgba(t, 0.16)}; border-radius: 2px; }}
QSlider::add-page:vertical, QSlider::sub-page:vertical {{ background: {rgba(t, 0.16)}; border-radius: 2px; }}
QSlider::handle:vertical {{ background: #ffffff; width: 14px; height: 14px; margin: 0 -5px; border-radius: 7px;
                            border: 1px solid rgba(0,0,0,40); }}
QSlider::handle:horizontal {{ background: #ffffff; width: 12px; height: 12px; margin: -4px 0; border-radius: 6px;
                              border: 1px solid rgba(0,0,0,40); }}

QProgressBar {{ background: {soft2}; border: none; border-radius: 3px; max-height: 6px; color: transparent; }}
QProgressBar::chunk {{ background: {c['accent']}; border-radius: 3px; }}

QCheckBox {{ spacing: 8px; }}
QRadioButton {{ spacing: 8px; }}
QRadioButton::indicator {{ width: 14px; height: 14px; border-radius: 8px; border: 1px solid {rgba(t, 0.35)};
                           background: {soft}; }}
QRadioButton::indicator:checked {{ border: 4px solid {c['accent']}; background: #ffffff; width: 8px; height: 8px; }}
QCheckBox::indicator {{ width: 15px; height: 15px; border-radius: 4px; border: 1px solid {rgba(t, 0.3)}; background: {soft}; }}
QCheckBox::indicator:checked {{ background: {c['accent']}; border-color: {c['accent']}; }}

/* ---- menus (popups arrondis, surbrillance accent comme sur Mac) ---- */
QMenu {{ background: {rgba(c['panel'], 0.97)}; border: 1px solid {rgba(t, 0.13)}; border-radius: 10px; padding: 5px; }}
QMenu::item {{ padding: 5px 22px 5px 12px; border-radius: 5px; color: {t}; }}
QMenu::item:selected {{ background: {c['accent']}; color: {on_acc}; }}
QMenu::item:disabled {{ color: {c['subtext']}; }}
QMenu::separator {{ height: 1px; background: {hair}; margin: 4px 8px; }}
QToolTip {{ background: {c['panel']}; color: {t}; border: 1px solid {hair}; padding: 4px 8px; border-radius: 6px; }}
QDialog, QMessageBox, QInputDialog, QColorDialog {{ background: {c['panel']}; }}
QMessageBox QPushButton, QInputDialog QPushButton, QDialog QPushButton#dlg {{
    background: {soft2}; color: {t}; padding: 6px 18px; min-width: 70px; border-radius: 7px; }}
"""
