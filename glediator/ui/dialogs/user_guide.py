from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

REPO_URL = "https://github.com/mrcodetastic/Glediator"
ONLINE_GUIDE_URL = "https://github.com/mrcodetastic/Glediator/blob/master/docs/user-guide.md"


def load_user_guide_markdown() -> str:
    candidates = [
        Path(__file__).resolve().parents[3] / "docs" / "user-guide.md",
        Path(__file__).resolve().parents[2] / "assets" / "user-guide.md",
    ]
    for path in candidates:
        if path.is_file():
            return path.read_text(encoding="utf-8")
    return f"# Glediator User Guide\n\nView online at [{ONLINE_GUIDE_URL}]({ONLINE_GUIDE_URL}).\n"


class UserGuideDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Glediator User Guide")
        self.resize(780, 620)

        layout = QVBoxLayout(self)
        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        self.browser.setMarkdown(load_user_guide_markdown())
        layout.addWidget(self.browser, 1)

        buttons = QHBoxLayout()
        github_btn = QPushButton("Open on GitHub…")
        github_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(ONLINE_GUIDE_URL)))
        repo_btn = QPushButton("Main Repository…")
        repo_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(REPO_URL)))
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        buttons.addWidget(github_btn)
        buttons.addWidget(repo_btn)
        buttons.addStretch(1)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)
