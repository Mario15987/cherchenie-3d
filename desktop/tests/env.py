"""Общая подготовка автотестов интерфейса: окна без показа, временные config.json и user_library.json, сбор исключений
из обработчиков Qt. Импортируется всеми модулями тестов — пути подменяются один раз на весь прогон."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from cad import ai, library  # noqa: E402

APP = QApplication.instance() or QApplication(sys.argv)
TMP = Path(tempfile.mkdtemp(prefix="recad_ui_"))
ai.config_path = lambda: TMP / "config.json"             # не трогать настоящий config.json
library.user_path = lambda: TMP / "user_library.json"    # и настоящие «Мои элементы»
library.reload_user()
ERRORS: list[str] = []


def _hook(t, v, tb):
    import traceback
    ERRORS.append("".join(traceback.format_exception(t, v, tb)))


sys.excepthook = _hook
