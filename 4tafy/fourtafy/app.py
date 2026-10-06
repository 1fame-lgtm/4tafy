"""Point d'entrée de l'application."""
import os
import sys

# Qt Multimedia / FFmpeg sont très bavards dans la console (version d'FFmpeg, infos des fichiers…).
# On coupe ces messages d'information ; mettre FOURTAFY_DEBUG=1 pour les revoir.
if not os.environ.get("FOURTAFY_DEBUG"):
    os.environ.setdefault("QT_LOGGING_RULES", "qt.multimedia*=false")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from .config import APP_NAME, DATA_DIR, ensure_dirs  # noqa: E402


def _quiet_native_logs():
    """Envoie les messages techniques de FFmpeg (écrits en C sur la sortie d'erreur) dans
    ~/4tafy/4tafy.log, tout en gardant les erreurs Python visibles dans la console."""
    if os.environ.get("FOURTAFY_DEBUG") or sys.stderr is None:
        return
    try:
        ensure_dirs()
        sys.stderr.flush()
        console = os.dup(2)
        log = open(DATA_DIR / "4tafy.log", "w", encoding="utf-8", errors="replace")
        os.dup2(log.fileno(), 2)
        sys.stderr = os.fdopen(console, "w", encoding="utf-8", errors="replace", buffering=1)
    except OSError:
        pass


def run():
    _quiet_native_logs()
    if sys.platform == "win32":
        try:  # icône propre dans la barre des tâches Windows
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("4tafy.player")
        except Exception:
            pass
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")

    from .main_window import MainWindow
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
