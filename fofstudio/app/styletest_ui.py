"""Storyboard → Test styles: paint each look's showcase and the channel's everyday jobs, then Keep, Maybe or
Drop each one (Dave, 2026-10-30: reset and rerun the test, and show what each style can do)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFrame, QGridLayout, QHBoxLayout, QInputDialog, QLabel,
                               QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget)

from .. import styleengine, styles
from ..stages import styletest
from ..util import reveal
from .common import GOLD, GREEN, MUTED, PANEL, RED, cached_pixmap

GROUPS = {"all": "Every look", "untested": "Untested looks", "maybe": "Maybes (round 2)",
          "animation": "Animation, film and TV", "puppet": "Puppets and stop motion", "print": "Print and posters",
          "fine_art": "Fine art", "storybook": "Storybook", "international": "From around the world", "mix": "Mixes",
          "house": "House styles"}
VERDICT_COLOUR = {"kept": GREEN, "maybe": GOLD, "dropped": RED, "live": GOLD}
TAGS = {"showcase": "Showcase", "showcase2": "Showcase (2nd)", "crowd": "Crowd", "evidence": "Evidence",
        "owlbert": "Owlbert", "salesman": "Caricature"}


class StyleTestDialog(QDialog):
    def __init__(self, page, parent=None):
        super().__init__(parent)
        self.page = page
        self.setWindowTitle("Test styles")
        self.resize(1250, 820)
        v = QVBoxLayout(self)
        v.addWidget(QLabel(
            "<b>Each look paints what it's best at, plus the channel's everyday jobs:</b> its own showcase scene "
            "(twice), a crowd watching a salesman, an evidence close-up and Owlbert's set with the real Owlbert "
            "(caricature looks also paint an invented salesman). Then press <b>Keep</b>, <b>Maybe</b> or "
            f"<b>Drop</b>.<br><span style='color:{MUTED}'>Ask: does it suit a fact-check, does it read on a phone, "
            "is it clean (no fake writing or bad hands), is it really that style, and is it different from the ones "
            "you've kept? About 15-60 seconds a picture on your PC, so test a group at a time or leave the whole lot "
            "overnight. Dropped looks leave the pickers; Maybes get a second look.</span>"))
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
        over = QPushButton("Start the test over")
        over.setToolTip("Clear every test picture and every Keep / Maybe / Drop, so all the looks are judged again "
                        "from scratch. Showcase scenes you edited are kept.")
        over.clicked.connect(self._reset)
        h.addWidget(over)
        self.go = QPushButton("Paint the test")
        self.go.setObjectName("primary")
        self.go.clicked.connect(self._go)
        h.addWidget(self.go)
        sheet = QPushButton("Open the contact sheets")
        sheet.clicked.connect(lambda: reveal(styletest.folder()))
        h.addWidget(sheet)
        v.addLayout(h)
        self.counts = QLabel("")
        v.addWidget(self.counts)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        v.addWidget(self.scroll, 1)
        self.boxes: list[tuple[QCheckBox, str]] = []
        self._fill()
        old = [k for k, r in styletest.results().items() if r.get("round", 1) < styletest.ROUND]
        if old and QMessageBox.question(
                self, "Start the test over", f"{len(old)} look(s) were tested with the old two-picture test. Start "
                "the test over now (clear the old pictures and every Keep / Drop) so every look is judged on its "
                "showcase?") == QMessageBox.Yes:
            styletest.reset()
            self._fill()

    def _status(self, key: str) -> str:
        s = styles.get(key)
        if key.startswith("mix:"):
            return styles.ratings().get(key, "draft")
        return styles.status_of(s)

    def _keys(self) -> list[str]:
        g = self.group.currentData()
        keys = [s.key for s in styles.STYLES.values()]
        keys += [f"mix:{h['key']}" for h in styleengine.recipes()]
        out = []
        for k in keys:
            s = styles.get(k)
            st = self._status(k)
            group = "mix" if k.startswith("mix:") else s.group
            if g == "all" or (g == "untested" and st == "draft") or (g == "maybe" and st == "maybe") or group == g:
                out.append(k)
        return out

    def _fill(self) -> None:
        res = styletest.results()
        holder = QWidget()
        grid = QGridLayout(holder)
        self.boxes = []
        all_st = [self._status(s.key) for s in styles.STYLES.values()]
        self.counts.setText(f"<span style='color:{MUTED}'>{all_st.count('kept')} kept · {all_st.count('maybe')} "
                            f"maybe · {all_st.count('dropped')} dropped · {all_st.count('draft')} untested · "
                            f"{all_st.count('live')} house looks</span>")
        for i, key in enumerate(self._keys()):
            s = styles.get(key)
            box = QFrame()
            box.setStyleSheet(f"QFrame {{ background:{PANEL}; border-radius:6px; }}")
            bl = QVBoxLayout(box)
            st = self._status(key)
            cb = QCheckBox(s.name)
            cb.setToolTip(styles.describe(s) or s.look)
            bl.addWidget(cb)
            done = res.get(key) or {}
            old = done and done.get("round", 1) < styletest.ROUND
            bl.addWidget(QLabel(f"<span style='color:{VERDICT_COLOUR.get(st, MUTED)}'>{st}</span> · {s.group} · "
                                f"tier {s.tier}" + (f" · <span style='color:{MUTED}'>old test: paint again</span>"
                                                    if old else "")))
            pics = QHBoxLayout()
            for pic in (done.get("pictures") or [])[:6]:
                lab = QLabel()
                lab.setPixmap(cached_pixmap(pic["path"], 132, 74))
                lab.setToolTip(f"{TAGS.get(pic.get('tag', ''), pic.get('tag', ''))}\n\n{pic['prompt']}")
                pics.addWidget(lab)
            if not done:
                pics.addWidget(QLabel(f"<span style='color:{MUTED}'>not painted yet</span>"))
            pics.addStretch(1)
            bl.addLayout(pics)
            row = QHBoxLayout()
            for text, verdict in (("Keep", "kept"), ("Maybe", "maybe"), ("Drop", "dropped")):
                b = QPushButton(text)
                b.clicked.connect(lambda _=False, k=key, vv=verdict: self._rate(k, vv))
                b.setEnabled(key != styles.DEFAULT and st != verdict)
                row.addWidget(b)
            if not key.startswith("mix:"):
                edit = QPushButton("Showcase scene...")
                edit.setToolTip("What this look paints as its showcase (the scene it's known for). Change it, then "
                                "paint again.\n\nNow: " + (styletest.showcase(key) or "written by the local AI on "
                                                            "the first test"))
                edit.clicked.connect(lambda _=False, k=key: self._edit(k))
                row.addWidget(edit)
            row.addStretch(1)
            bl.addLayout(row)
            grid.addWidget(box, i // 2, i % 2, Qt.AlignTop)
            self.boxes.append((cb, key))
        self.scroll.setWidget(holder)

    def _rate(self, key: str, verdict: str) -> None:
        styles.rate(key, verdict)
        self._fill()

    def _edit(self, key: str) -> None:
        text, ok = QInputDialog.getMultiLineText(
            self, "Showcase scene", f"The scene {styles.get(key).name} paints to show what it can do. One subject "
            "doing one thing, the setting, the camera and the light. No names, signs or words to read.",
            styletest.showcase(key))
        if ok:
            styletest.save_showcase(key, text)
            self._fill()

    def _reset(self) -> None:
        if QMessageBox.question(self, "Start the test over", "Clear every test picture and every Keep / Maybe / "
                                "Drop, so all the looks are judged again from scratch?") != QMessageBox.Yes:
            return
        n = styletest.reset()
        self.group.setCurrentIndex(max(0, self.group.findData("untested")))
        self._fill()
        self.counts.setText(self.counts.text() + f" <span style='color:{GREEN}'>· Cleared {n} verdict(s). Tick "
                                                 "the looks and press Paint the test.</span>")

    def _go(self) -> None:
        keys = [k for b, k in self.boxes if b.isChecked()]
        if not keys:
            return
        self.page.run_stage("styletest", {"styles": keys}, f"Testing {len(keys)} look(s)")
        self.accept()
