"""Shared look and small widgets for the window."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPushButton,
                               QTableWidget, QTableWidgetItem, QWidget)

NAVY = "#2c3e6b"
STUDIO = "#12141c"
PANEL = "#1b1e2a"
CREAM = "#f5f0e6"
GOLD = "#d4a017"
RED = "#c0392b"
GREEN = "#27ae60"
MUTED = "#8a8fa3"

CHECK_ICON = (Path(__file__).parent / "check.svg").as_posix()

STYLE = f"""
QWidget {{ background: {STUDIO}; color: {CREAM}; font-size: 10pt; }}
QLabel#h1 {{ font-size: 18pt; font-weight: 600; color: {CREAM}; }}
QLabel#h2 {{ font-size: 12pt; font-weight: 600; color: {GOLD}; }}
QLabel#muted {{ color: {MUTED}; }}
QListWidget#nav {{ background: {PANEL}; border: none; padding-top: 8px; font-size: 11pt; }}
QListWidget#nav::item {{ padding: 10px 14px; border-left: 3px solid transparent; }}
QListWidget#nav::item:selected {{ background: {NAVY}; border-left: 3px solid {GOLD}; color: white; }}
QPushButton {{ background: {NAVY}; border: 1px solid #3c4f85; border-radius: 4px; padding: 6px 12px; }}
QPushButton:hover {{ background: #364c84; }}
QPushButton:disabled {{ background: #22263a; color: #5c6075; border-color: #2a2e44; }}
QPushButton:pressed {{ background: #0f1a33; border-color: {GOLD}; padding-top: 8px; padding-bottom: 4px; }}
QPushButton#primary {{ background: {GOLD}; color: #111; font-weight: 600; border-color: {GOLD}; }}
QPushButton#primary:hover {{ background: #e6b325; }}
QPushButton#primary:pressed {{ background: #a87d0f; color: white; }}
QPushButton#primary:disabled {{ background: #3a3420; color: #7d7458; border-color: #3a3420; }}
QPushButton#tab {{ background: {PANEL}; border: 1px solid #2c3046; font-size: 11pt; padding: 6px 18px; }}
QPushButton#tab:checked {{ background: {NAVY}; border-bottom: 3px solid {GOLD}; color: white; font-weight: 600; }}
QPushButton:focus {{ outline: none; border-color: {GOLD}; }}
QPushButton#danger {{ background: #5a1f1a; border-color: {RED}; }}
QTableWidget, QListWidget, QPlainTextEdit, QTextBrowser, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background: {PANEL}; border: 1px solid #2c3046; border-radius: 4px; selection-background-color: {NAVY}; }}
QTableView::indicator, QListView::indicator, QCheckBox::indicator {{ width: 17px; height: 17px;
    border: 2px solid #9aa0b8; border-radius: 4px; background: #1b1e2b; }}
QTableView::indicator:checked, QListView::indicator:checked, QCheckBox::indicator:checked {{
    background: {GOLD}; border-color: {GOLD}; image: url({CHECK_ICON}); }}
QHeaderView::section {{ background: #222639; color: {MUTED}; border: none; padding: 5px; }}
QTabWidget::pane {{ border: 1px solid #2c3046; }}
QTabBar::tab {{ background: {PANEL}; padding: 6px 14px; color: {MUTED}; }}
QTabBar::tab:selected {{ color: {CREAM}; border-bottom: 2px solid {GOLD}; }}
QGroupBox {{ border: 1px solid #2c3046; border-radius: 6px; margin-top: 14px; padding-top: 8px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; color: {GOLD}; }}
QStatusBar {{ background: {PANEL}; color: {MUTED}; }}
"""

STATUS_COLORS = {
    "approved": GREEN, "awaiting_approval": GOLD, "running": "#4aa3df", "queued": "#4aa3df",
    "failed": RED, "rejected": RED, "interrupted": RED, "cancelled": MUTED, "reset": "#e67e22",
    "not_started": MUTED, "done": GREEN,
}
STATUS_WORDS = {
    "approved": "Approved", "awaiting_approval": "Needs your OK", "running": "Running",
    "queued": "Queued", "failed": "Failed", "rejected": "Rejected", "interrupted": "Interrupted",
    "cancelled": "Cancelled", "reset": "Look again", "not_started": "Not started", "done": "Done",
}


def label(text: str, name: str = "") -> QLabel:
    lab = QLabel(text)
    if name:
        lab.setObjectName(name)
    lab.setWordWrap(True)
    return lab


def button(text: str, slot=None, kind: str = "") -> QPushButton:
    b = QPushButton(text)
    if kind:
        b.setObjectName(kind)
    if slot:
        b.clicked.connect(slot)
    return b


def row(*widgets, stretch: bool = True) -> QWidget:
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    for x in widgets:
        lay.addWidget(x)
    if stretch:
        lay.addStretch(1)
    return w


def table(headers: list[str]) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.verticalHeader().setVisible(False)
    t.setSelectionBehavior(QTableWidget.SelectRows)
    t.setSelectionMode(QTableWidget.SingleSelection)
    t.setEditTriggers(QTableWidget.NoEditTriggers)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
    t.horizontalHeader().setStretchLastSection(True)
    t.setAlternatingRowColors(False)
    return t


def fill(t: QTableWidget, rows: list[list], colors: dict[int, str] | None = None) -> None:
    t.setRowCount(len(rows))
    for r, values in enumerate(rows):
        for c, v in enumerate(values):
            item = QTableWidgetItem("" if v is None else str(v))
            if colors and c in colors and str(v) in STATUS_WORDS.values():
                pass
            t.setItem(r, c, item)


def color_item(t: QTableWidget, r: int, c: int, color: str) -> None:
    item = t.item(r, c)
    if item:
        item.setForeground(QColor(color))


def open_path(path: Path) -> None:
    path = Path(path)
    if sys.platform.startswith("win"):
        os.startfile(str(path))  # noqa: S606 - opening the user's own file
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def error(parent: QWidget, text: str) -> None:
    QMessageBox.warning(parent, "Followers or Facts Studio", text)


def info(parent: QWidget, text: str) -> None:
    QMessageBox.information(parent, "Followers or Facts Studio", text)


ALIGN_TOP = Qt.AlignTop
