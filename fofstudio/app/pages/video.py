"""Video: written instructions for how each picture plays out, then the clips themselves."""

from __future__ import annotations

from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QPlainTextEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget)

from ... import pipeline
from ...stages import video as vs
from ..common import GOLD, GREEN, MUTED, PANEL, cached_pixmap
from ..player import PlayerDialog
from ..widgets import StagePage, click_feedback

METHODS = {"animate": "Animate the picture (Wan 2.2, ~6 min)",
           "text_to_video": "Make from words (Wan 2.2 5B, ~8 min, b-roll only)",
           "camera_move": "Smooth camera move (seconds)"}


class ShotRow(QFrame):
    def __init__(self, page: "VideoPage", shot: dict):
        super().__init__()
        self.page, self.shot = page, shot
        self.setStyleSheet(f"QFrame {{ background:{PANEL}; border-radius:8px; }}")
        g = QGridLayout(self)
        ep = page.ep
        pic = QLabel()
        pic.setFixedSize(240, 135)
        if ep.abs(shot["image"]).exists():
            pic.setPixmap(cached_pixmap(ep.abs(shot["image"]), 240, 135))
        g.addWidget(pic, 0, 0, 4, 1)
        g.addWidget(QLabel(f"<b style='color:{GOLD}'>{shot['shot_id']}</b>  {shot['type'].replace('_', ' ')}"), 0, 1, 1, 3)
        self.plays = QPlainTextEdit(shot["how_it_plays"])
        self.plays.setFixedHeight(48)
        self.plays.setToolTip("How the shot plays out, in plain words")
        g.addWidget(self.plays, 1, 1, 1, 3)
        self.motion = QPlainTextEdit(shot["motion_prompt"])
        self.motion.setFixedHeight(48)
        self.motion.setPlaceholderText("Motion prompt for the animation model")
        self.motion.setEnabled(shot["type"] == "ai_image")
        g.addWidget(self.motion, 2, 1, 1, 3)
        self.method = QComboBox()
        for k, v in METHODS.items():
            self.method.addItem(v, k)
        self.method.setCurrentIndex(max(0, self.method.findData(shot["method"])))
        if shot.get("kind") in ("owl", "caricature"):   # characters must start from their picture to stay on model
            self.method.model().item(self.method.findData("text_to_video")).setEnabled(False)
        self.method.setEnabled(shot["type"] == "ai_image")
        self.camera = QComboBox()
        self.camera.addItems(vs.CAMERA_MOVES)
        self.camera.setCurrentText(shot["camera"])
        self.seconds = QDoubleSpinBox()
        self.seconds.setRange(2, 12)
        self.seconds.setSuffix(" s")
        self.seconds.setValue(float(shot["seconds"]))
        g.addWidget(self.method, 3, 1)
        g.addWidget(self.camera, 3, 2)
        g.addWidget(self.seconds, 3, 3)
        side = QVBoxLayout()
        clip = shot.get("clip")
        made = clip and ep.abs(clip["path"]).exists() and clip.get("digest") == vs._digest(shot)
        status = (f"<span style='color:{GREEN}'>✔ Approved</span>" if made and shot.get("approved") else
                  f"<span style='color:{GOLD}'>Ready to watch</span>" if made else
                  f"<span style='color:{MUTED}'>Not made yet</span>")
        side.addWidget(QLabel(status))
        save = QPushButton("Save changes")
        save.clicked.connect(self._save)
        watch = QPushButton("▶ Watch")
        watch.setEnabled(bool(made))
        watch.clicked.connect(lambda: PlayerDialog(ep.abs(clip["path"]), shot["shot_id"], page).exec())
        ok = QPushButton("Approve clip")
        ok.setEnabled(bool(made) and not shot.get("approved"))
        ok.clicked.connect(lambda: (vs.update_shot(ep, shot["shot_id"], approved=True), page.refresh()))
        redo = QPushButton("Make again")
        redo.setEnabled(bool(made) and not page.busy("video"))
        redo.clicked.connect(lambda: page.run_stage("video", {"redo": [shot["shot_id"]]}, f"Remaking {shot['shot_id']}"))
        for b in (save, watch, ok, redo):
            side.addWidget(b)
        side.addStretch(1)
        g.addLayout(side, 0, 4, 4, 1)
        g.setColumnStretch(1, 1)

    def _save(self) -> None:
        vs.update_shot(self.page.ep, self.shot["shot_id"], how_it_plays=self.plays.toPlainText().strip(),
                       motion_prompt=self.motion.toPlainText().strip(), method=self.method.currentData(),
                       camera=self.camera.currentText(), seconds=self.seconds.value())
        self.page.toast(f"{self.shot['shot_id']} saved. Press Make the clips to apply it.")
        self.page.refresh()


class VideoPage(StagePage):
    TITLE = "Video"
    HELP = ("Step 6. First the AI writes how each picture plays out and how it will be made (an animation "
            "with Wan 2.2, or a slow camera move). Change anything, then press Make the clips. Watch each "
            "clip and approve it or make it again.")
    APPROVE_STAGE = "video"
    CLEAR_STAGE = "video_plan"

    def __init__(self, window):
        super().__init__(window)
        row = QHBoxLayout()
        self.plan_btn = QPushButton("1. Write scene instructions")
        click_feedback(self.plan_btn, lambda: self.run_stage("video_plan", {}, "Writing scene instructions"))
        self.make_btn = QPushButton("2. Make the clips")
        self.make_btn.setObjectName("primary")
        click_feedback(self.make_btn, self._make)
        self.all_btn = QPushButton("Approve all clips")
        click_feedback(self.all_btn, self._approve_all, "Approving...")
        self.summary = QLabel("")
        self.summary.setObjectName("muted")
        for w in (self.plan_btn, self.make_btn, self.all_btn, self.summary):
            row.addWidget(w)
        row.addStretch(1)
        self.body.addLayout(row)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.body.addWidget(self.scroll, 1)
        self._sig = None

    def _make(self) -> None:
        st = self.stage_status("video_plan")["status"]
        if st != "approved":
            pipeline.approve(self.ep, "video_plan")
        self.run_stage("video", {}, "Making the clips")

    def _approve_all(self) -> None:
        plan = vs.load_plan(self.ep)
        for s in plan["shots"]:
            if s.get("clip") and self.ep.abs(s["clip"]["path"]).exists():
                s["approved"] = True
        vs.save_plan(self.ep, plan)
        self.refresh()

    def refresh(self) -> None:
        super().refresh()
        if not self.ep:
            return
        busy = self.busy("video") or self.busy("video_plan")
        board_ok = self.stage_status("storyboard")["status"] == "approved"
        plan = vs.load_plan(self.ep)
        self.plan_btn.setEnabled(board_ok and not busy)
        self.make_btn.setEnabled(bool(plan["shots"]) and not busy)
        self.all_btn.setEnabled(bool(plan["shots"]) and not busy)
        n_anim = sum(1 for s in plan["shots"] if s["method"] == "animate")
        n_t2v = sum(1 for s in plan["shots"] if s["method"] == "text_to_video")
        self.summary.setText(f"{len(plan['shots'])} shots · {n_anim} animated, {n_t2v} made from words (about "
                             f"{n_anim * 6 + n_t2v * 8} min of GPU time), the rest smooth camera moves"
                             if plan["shots"] else "")
        sig = (busy, str(plan))
        if sig == self._sig:
            return
        self._sig = sig
        holder = QWidget()
        v = QVBoxLayout(holder)
        for s in plan["shots"]:
            v.addWidget(ShotRow(self, s))
        if not plan["shots"]:
            msg = QLabel("Working... see the bar at the top." if busy else
                         "Press 1. Write scene instructions to start.")
            msg.setObjectName("muted")
            v.addWidget(msg)
        v.addStretch(1)
        pos = self.scroll.verticalScrollBar().value()
        self.scroll.setWidget(holder)
        self.scroll.verticalScrollBar().setValue(pos)

    def poll(self) -> None:
        super().poll()
        if self.ep and (self.busy("video") or self.busy("video_plan")):
            import time
            if time.time() - getattr(self, "_last_live", 0) > 3:   # show clips as they come in
                self._last_live = time.time()
                self.refresh()

    def watched(self) -> list[str]:
        return ["video", "video_plan", "storyboard"]
