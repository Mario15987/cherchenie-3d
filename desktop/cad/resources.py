"""Пути к файлам программы (иконка и прочее из assets) — и при запуске из исходников, и внутри сборки PyInstaller."""
from __future__ import annotations

import sys
from pathlib import Path

APP_NAME = "Черчение 3D"                       # название программы в окнах, справке и панели задач
APP_USER_MODEL_ID = "kompascad.desktop.app.1.0"   # внутренний идентификатор группы на панели задач — не менять


def resource_path(relative: str) -> Path:
    """В собранном .exe ресурсы лежат в sys._MEIPASS (папка _internal), иначе — рядом с main.py."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / relative


def icon_path() -> Path:
    return resource_path("assets/icon.ico")


def set_windows_app_id() -> None:
    """Своя группа на панели задач Windows: иначе там значок python.exe, а не программы. Вызывать до QApplication."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except (AttributeError, OSError):
        pass  # старая Windows без этой функции — значок просто будет общий
