"""Fresh looks: what you haven't used lately, and the style mixer (Script page → Fresh looks...)."""

from __future__ import annotations

from PySide6.QtWidgets import (QComboBox, QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton,
                               QVBoxLayout)

from .. import styleengine, styles
from ..util import StageError
from .common import GOLD, GREEN, MUTED, RED


class StyleIdeasDialog(QDialog):
    def __init__(self, ep, parent=None):
        super().__init__(parent)
        self.ep, self.chosen = ep, ""
        self.careful = bool(ep.creative().get("careful"))
        self.setWindowTitle("Fresh looks")
        self.resize(780, 620)
        v = QVBoxLayout(self)
        recent = styleengine.history(ep.project_id)
        now = styles.get(ep.creative()["style"])
        f = styleengine.fatigue(now.key, recent)
        v.addWidget(QLabel(
            f"<b>This video:</b> {now.name} · fatigue <b style='color:{GOLD if f >= styleengine.FATIGUE_LIMIT else GREEN}'>"
            f"{f:.2f}</b> <span style='color:{MUTED}'>(0 = fresh, 1 = the same as your last videos; it counts the "
            f"medium, colours, light and kind of look of your last {len(recent)} videos, newest most)</span>"))
        due = styleengine.due(recent)
        if due:
            v.addWidget(QLabel(f"<b>Not used in your last {styleengine.HISTORY_N} videos:</b> {', '.join(due)}"))
        v.addWidget(QLabel("<b>Suggested next</b> (double-click to use)"))
        self.ideas = QListWidget()
        for key, fat, why in styleengine.recommend(recent, self.careful, n=8):
            s = styles.get(key)
            it = QListWidgetItem(f"{s.name}  ·  fatigue {fat:.2f}  ·  {why}")
            it.setData(256, key)
            it.setToolTip(styles.describe(s) or s.blurb)
            self.ideas.addItem(it)
        self.ideas.itemDoubleClicked.connect(lambda it: self._use(it.data(256)))
        v.addWidget(self.ideas, 1)
        v.addWidget(QLabel("<b>Mix two looks</b>: how it's made from the first, where it lives (colours, light, "
                           "setting) from the second."))
        h = QHBoxLayout()
        self.body, self.world = QComboBox(), QComboBox()
        for box in (self.body, self.world):
            for key, name in styles.choices(self.careful):
                if not key.startswith("mix:"):
                    box.addItem(name, key)
        h.addWidget(QLabel("Made like"))
        h.addWidget(self.body, 1)
        h.addWidget(QLabel("Set in"))
        h.addWidget(self.world, 1)
        mix = QPushButton("Mix")
        mix.clicked.connect(self._mix)
        h.addWidget(mix)
        v.addLayout(h)
        self.preview = QLabel("")
        self.preview.setWordWrap(True)
        v.addWidget(self.preview)
        h2 = QHBoxLayout()
        self.use_btn = QPushButton("Use this mix")
        self.use_btn.setObjectName("primary")
        self.use_btn.setEnabled(False)
        self.use_btn.clicked.connect(lambda: self._use(self._mixed))
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        h2.addStretch(1)
        h2.addWidget(close)
        h2.addWidget(self.use_btn)
        v.addLayout(h2)
        self._mixed = ""

    def _mix(self) -> None:
        a, b = self.body.currentData(), self.world.currentData()
        try:
            m = styleengine.mix(a, b, self.careful)
        except StageError as exc:
            self.preview.setText(f"<span style='color:{RED}'>{exc}</span>")
            self.use_btn.setEnabled(False)
            return
        f = styleengine.fatigue(m.key, styleengine.history(self.ep.project_id))
        self._mixed = m.key
        self.preview.setText(f"<b>{m.name}</b> · fatigue {f:.2f}<br><span style='color:{MUTED}'>Picture recipe: "
                             f"{m.look}</span><br>Untested: Storyboard → Test styles can paint it first.")
        self.use_btn.setEnabled(True)

    def _use(self, key: str) -> None:
        if key:
            self.chosen = key
            self.accept()
