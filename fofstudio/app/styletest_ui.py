"""Storyboard → Test styles: paint the test pictures for the looks you pick, then Keep or Drop each one."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QPushButton, QScrollArea, QVBoxLayout, QWidget)

from .. import styleengine, styles
from ..stages import styletest
from ..util import reveal
from .common import GOLD, GREEN, MUTED, PANEL, RED, cached_pixmap

GROUPS = {"all": "Every look", "untested": "Untested looks", "animation": "Animation, film and TV",
          "puppet": "Puppets and stop motion", "print": "Print and posters", "fine_art": "Fine art",
          "storybook": "Storybook", "international": "From around the world", "mix": "Mixes", "house": "House styles"}


class StyleTestDialog(QDialog):
    def __init__(self, page, parent=None):
        super().__init__(parent)
        self.page = page
        self.setWindowTitle("Test styles")
        self.resize(1100, 760)
        v = QVBoxLayout(self)
        v.addWidget(QLabel(
            "<b>Paint the same two test pictures in each look</b> (a street at dusk, a desk with documents; "
            "caricature looks also get an invented cartoon salesman), then press <b>Keep</b> or <b>Drop</b>. "
            f"<span style='color:{MUTED}'>About 10-20 seconds a picture on your PC. Dropped looks leave the pickers; "
            "kept ones lose their '(untested)' mark.</span>"))
        h = QHBoxLayout()
        self.group = QComboBox()
        for k, name in GROUPS.items():
            self.group.addItem(name, k)
        self.group.setCurrentIndex(1)
        self.group.currentIndexChanged.connect(self._fill)
        h.addWidget(QLabel("Show"))
        h.addWidget(self.group)
        tick = QPushButton("Tick all shown")
        tick.clicked.connect(lambda: [b.setChecked(True) for b, _ in self.boxes])
        h.addWidget(tick)
        h.addStretch(1)
        self.go = QPushButton("Paint the test")
        self.go.setObjectName("primary")
        self.go.clicked.connect(self._go)
        h.addWidget(self.go)
        sheet = QPushButton("Open the contact sheets")
        sheet.clicked.connect(lambda: reveal(styletest.folder()))
        h.addWidget(sheet)
        v.addLayout(h)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        v.addWidget(self.scroll, 1)
        self.boxes: list[tuple[QCheckBox, str]] = []
        self._fill()

    def _keys(self) -> list[str]:
        g = self.group.currentData()
        keys = [k for k, _ in styles.choices(include_drafts=True)]
        keys += [f"mix:{h['key']}" for h in styleengine.recipes() if f"mix:{h['key']}" not in keys]
        out = []
        for k in keys:
            s = styles.get(k)
            st = styles.status_of(s) if not k.startswith("mix:") else styles.ratings().get(k, "draft")
            if g == "all" or (g == "untested" and st == "draft") or s.group == g:
                out.append(k)
        return out

    def _fill(self) -> None:
        res = styletest.results()
        holder = QWidget()
        grid = QGridLayout(holder)
        self.boxes = []
        for i, key in enumerate(self._keys()):
            s = styles.get(key)
            box = QFrame()
            box.setStyleSheet(f"QFrame {{ background:{PANEL}; border-radius:6px; }}")
            bl = QVBoxLayout(box)
            st = styles.ratings().get(key) or (styles.status_of(s) if not key.startswith("mix:") else "draft")
            colour = {"kept": GREEN, "dropped": RED, "live": GOLD}.get(st, MUTED)
            cb = QCheckBox(s.name)
            cb.setToolTip(styles.describe(s) or s.look)
            bl.addWidget(cb)
            bl.addWidget(QLabel(f"<span style='color:{colour}'>{st}</span> · {s.group} · tier {s.tier}"))
            pics = QHBoxLayout()
            for pic in (res.get(key) or {}).get("pictures", [])[:3]:
                lab = QLabel()
                lab.setPixmap(cached_pixmap(pic["path"], 150, 86))
                lab.setToolTip(pic["prompt"])
                pics.addWidget(lab)
            if not res.get(key):
                pics.addWidget(QLabel(f"<span style='color:{MUTED}'>not painted yet</span>"))
            bl.addLayout(pics)
            row = QHBoxLayout()
            keep, drop = QPushButton("Keep"), QPushButton("Drop")
            keep.clicked.connect(lambda _=False, k=key: self._rate(k, "kept"))
            drop.clicked.connect(lambda _=False, k=key: self._rate(k, "dropped"))
            keep.setEnabled(s.status != "live")
            drop.setEnabled(s.status != "live")
            row.addWidget(keep)
            row.addWidget(drop)
            bl.addLayout(row)
            grid.addWidget(box, i // 4, i % 4, Qt.AlignTop)
            self.boxes.append((cb, key))
        self.scroll.setWidget(holder)

    def _rate(self, key: str, verdict: str) -> None:
        styles.rate(key, verdict)
        self._fill()

    def _go(self) -> None:
        keys = [k for b, k in self.boxes if b.isChecked()]
        if not keys:
            return
        self.page.run_stage("styletest", {"styles": keys}, f"Testing {len(keys)} look(s)")
        self.accept()
