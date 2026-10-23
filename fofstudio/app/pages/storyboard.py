"""Storyboard: three pictures per scene. Tick the ones to use; remake any you don't like."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QInputDialog,
                               QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget)

from ...stages import storyboard as sb
from ..common import GOLD, MUTED, PANEL
from ..widgets import StagePage, click_feedback

THUMB_W, THUMB_H = 300, 169


class SceneRow(QFrame):
    def __init__(self, page: "StoryboardPage", scene: dict):
        super().__init__()
        self.page, self.scene = page, scene
        self.setStyleSheet(f"QFrame {{ background:{PANEL}; border-radius:8px; }}")
        lay = QVBoxLayout(self)
        head = QLabel(f"<b style='color:{GOLD}'>{scene['scene_id']}</b>  "
                      f"<span style='color:{MUTED}'>{scene['narration'][:220]}...</span>")
        head.setWordWrap(True)
        lay.addWidget(head)
        grid = QGridLayout()
        ep = page.ep
        for k in range(3):
            c = scene["candidates"][k] if k < len(scene["candidates"]) else None
            pic = QLabel()
            pic.setFixedSize(THUMB_W, THUMB_H)
            pic.setAlignment(Qt.AlignCenter)
            picked = k in scene.get("picked", [])
            border = GOLD if picked else "#2c3046"
            pic.setStyleSheet(f"border:3px solid {border}; border-radius:6px; background:#0d0f15;")
            if c and ep.abs(c["path"]).exists():
                pic.setPixmap(QPixmap(str(ep.abs(c["path"]))).scaled(THUMB_W - 6, THUMB_H - 6, Qt.KeepAspectRatio,
                                                                     Qt.SmoothTransformation))
                pic.setToolTip(c["prompt"])
            else:
                pic.setText("being painted..." if page.busy("storyboard") else "not made yet")
            box = QCheckBox("Use this picture")
            box.setChecked(picked)
            box.setEnabled(bool(c))
            box.toggled.connect(lambda on, kk=k: self._pick(kk, on))
            remake = QPushButton("Remake")
            remake.setEnabled(bool(c) and not page.busy("storyboard"))
            remake.clicked.connect(lambda _=False, kk=k: self._remake(kk))
            idea = QLabel((scene.get("ideas") or [""] * 3)[k][:140])
            idea.setWordWrap(True)
            idea.setObjectName("muted")
            idea.setFixedWidth(THUMB_W)
            grid.addWidget(pic, 0, k)
            grid.addWidget(idea, 1, k)
            grid.addWidget(row_of(box, remake), 2, k)
        lay.addLayout(grid)
        if scene.get("cards"):
            lay.addWidget(QLabel("<span style='color:%s'>Also shown automatically: %s</span>" % (
                MUTED, ", ".join(f"{c['type'].replace('_', ' ')} “{c['text'][:50]}”" for c in scene["cards"]))))

    def _pick(self, k: int, on: bool) -> None:
        picked = set(self.scene.get("picked", []))
        picked.add(k) if on else picked.discard(k)
        sb.set_picks(self.page.ep, self.scene["scene_id"], sorted(picked))
        self.scene["picked"] = sorted(picked)
        st = self.page.ep.stage_status("storyboard")["status"]
        if st == "approved":
            self.page.ep.record("storyboard", "awaiting_approval", "picks changed")
        self.page.refresh_checks_only()

    def _remake(self, k: int) -> None:
        idea, ok = QInputDialog.getMultiLineText(self, "Remake picture",
                                                 "Change the idea if you like, then OK to paint it again:",
                                                 (self.scene.get("ideas") or [""] * 3)[k])
        if not ok:
            return
        sb.set_idea(self.page.ep, self.scene["scene_id"], k, idea.strip())
        self.page.run_stage("storyboard", {"remake": [f"{self.scene['scene_id']}:{k}"]},
                            f"Repainting {self.scene['scene_id']} picture {k + 1}")


def row_of(*widgets) -> QWidget:
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    for x in widgets:
        h.addWidget(x)
    return w


class StoryboardPage(StagePage):
    TITLE = "Storyboard"
    HELP = ("Step 5. For every scene the AI paints three different pictures. Tick the ones you want "
            "(one or more per scene). Remake lets you change the idea and paint it again.")
    APPROVE_STAGE = "storyboard"

    def __init__(self, window):
        super().__init__(window)
        row = QHBoxLayout()
        self.style = QComboBox()
        self.style.addItems(list(sb.STYLES))
        self.make_btn = QPushButton("Make pictures")
        self.make_btn.setObjectName("primary")
        click_feedback(self.make_btn, lambda: self.run_stage("storyboard", {"style": self.style.currentText()},
                                                             "Painting 3 pictures per scene"))
        row.addWidget(QLabel("Picture style"))
        row.addWidget(self.style)
        row.addWidget(self.make_btn)
        row.addStretch(1)
        self.body.addLayout(row)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.body.addWidget(self.scroll, 1)
        self._sig = None

    def refresh_checks_only(self) -> None:
        super().refresh()

    def refresh(self) -> None:
        super().refresh()
        busy = self.busy("storyboard")
        self.make_btn.setEnabled(bool(self.ep) and not busy and self.stage_status("script")["status"] == "approved")
        board = self.ep.storyboard() if self.ep else {}
        sig = (busy, str(board))
        if sig == self._sig:
            return
        self._sig = sig
        holder = QWidget()
        v = QVBoxLayout(holder)
        for scene in board.get("scenes", []):
            v.addWidget(SceneRow(self, scene))
        if not board.get("scenes"):
            msg = QLabel("Painting... the pictures appear here as they finish." if busy else
                         "Press Make pictures to paint three pictures for every scene.")
            msg.setObjectName("muted")
            v.addWidget(msg)
        v.addStretch(1)
        pos = self.scroll.verticalScrollBar().value()
        self.scroll.setWidget(holder)
        self.scroll.verticalScrollBar().setValue(pos)

    def poll(self) -> None:
        super().poll()
        if self.ep and self.busy("storyboard"):
            self.refresh()  # show pictures as they come in

    def watched(self) -> list[str]:
        return ["storyboard", "script"]
