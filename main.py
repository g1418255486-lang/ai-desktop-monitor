import sys
import os
import ctypes
import traceback
from datetime import datetime

from PySide6.QtGui import QIcon, QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from app.tray import TrayApp

ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ai.desktop-monitor")

APP_DIR_NAME = "ai-desktop-monitor"
MUTEX_NAME = "Global\\AIDesktopMonitor_SingleInstance"


def _crash_log(exc_type, exc_value, exc_tb):
    try:
        log_dir = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP_DIR_NAME)
        os.makedirs(log_dir, exist_ok=True)
        with open(os.path.join(log_dir, "crash.log"), "w", encoding="utf-8") as f:
            traceback.print_exception(exc_type, exc_value, exc_tb, file=f)
    except Exception:
        pass
    sys.__excepthook__(exc_type, exc_value, exc_tb)


sys.excepthook = _crash_log


def is_already_running():
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW(None, False, MUTEX_NAME)
        return ctypes.GetLastError() == 183
    except Exception:
        return False


def _icon_path():
    if getattr(sys, 'frozen', False):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "icons", "app.ico")


def main():
    log_dir = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP_DIR_NAME)
    log_path = os.path.join(log_dir, "startup.log")
    try:
        os.makedirs(log_dir, exist_ok=True)
    except Exception:
        pass

    def log(msg):
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(msg + "\n")
        except Exception:
            pass

    log(f"=== startup {datetime.now()} ===")
    log(f"frozen={getattr(sys, 'frozen', False)}")

    if is_already_running():
        log("EXIT: already running")
        sys.exit(0)
    log("single instance check passed")

    try:
        app = QApplication(sys.argv)
        log("QApplication created")
        app.setQuitOnLastWindowClosed(False)
        app.setApplicationName("AI 桌面监控")
        app.setWindowIcon(QIcon(_icon_path()))
        log("icon set")

        app.setStyle("Fusion")

        from app.theme import FONT_FAMILY
        font_families = QFontDatabase.families()
        picked = next(
            (n for n in FONT_FAMILY.split(",") if n in font_families),
            "Microsoft YaHei UI",
        )
        app.setFont(QFont(picked, 9, QFont.Weight.Medium))
        log(f"font set: {picked}")

        if not QSystemTrayIcon.isSystemTrayAvailable():
            log("EXIT: no system tray")
            sys.exit(1)
        log("tray available")

        tray_app = TrayApp(app)
        log("TrayApp created, entering event loop")
        sys.exit(app.exec())
    except Exception:
        log("FATAL:")
        log(traceback.format_exc())
        raise


if __name__ == "__main__":
    main()
