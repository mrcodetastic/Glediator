from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from glediator.core.config import EngineConfig
from glediator.core.engine import RenderEngine
from glediator.core.project import AUTOSAVE_PATH, acquire_session_lock, release_session_lock
from glediator.effects import load_effects
from glediator.ui.main_window import MainWindow


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Glediator")
    app.setOrganizationName("Glediator")
    load_effects()
    dirty_prev = acquire_session_lock()
    config = EngineConfig.load()
    engine = RenderEngine(config)
    window = MainWindow(engine, config)
    window.show()
    if dirty_prev and AUTOSAVE_PATH.is_file():
        reply = QMessageBox.question(
            window,
            "Recover Session",
            "Glediator did not shut down cleanly last time. Recover the autosaved session?",
        )
        if reply == QMessageBox.StandardButton.Yes:
            window.load_project_file(AUTOSAVE_PATH)
    engine.start()

    def _cleanup() -> None:
        engine.stop()
        release_session_lock()

    app.aboutToQuit.connect(_cleanup)
    sys.exit(app.exec())
