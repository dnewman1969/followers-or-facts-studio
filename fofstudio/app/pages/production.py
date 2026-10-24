"""Production: a video/audio editor. Owlbert's speech track, music, the timeline, a preview player."""

from __future__ import annotations

import json

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QFormLayout, QFrame, QHBoxLayout, QLabel, QPushButton,
                               QSlider, QSplitter, QVBoxLayout)

from ... import bits, musicbook, pipeline
from ...stages import production as prod
from ...util import read_json
from ..common import PANEL
from ..player import Player
from ..timeline import TimelineEditor
from ..widgets import Chip, StagePage, click_feedback


class ProductionPage(StagePage):
    TITLE = "Production"
    HELP = ("Step 7. Owlbert reads the script into a speech track, then everything is lined up on the timeline: "
            "intro bumper, your clips, Owlbert in the corner, his voice, music, outro bumper. Drag and trim to "
            "adjust, press Make preview to watch it, then Render the final video.")
    APPROVE_STAGE = "render"
    CLEAR_STAGE = "narration"

    def __init__(self, window):
        super().__init__(window)
        steps = QHBoxLayout()
        self.b_speech = QPushButton("1. Make speech track")
        click_feedback(self.b_speech, lambda: self._chain(["narration", "captions"], "Owlbert reading the script"))
        self.b_music = QPushButton("2. Make music")
        self.genre = QComboBox()
        self.genre.addItem("Music: to suit the style", "")
        for key, g in musicbook.GENRES.items():
            self.genre.addItem(f"Music: {g.name}", key)
        self.genre.addItem("Music: from my library folder (picked by mood)", "library")
        self.genre.setToolTip("The kind of music. The script's MUSIC lines choose the mood of each scene "
                              "(curious, tense, somber...) and the program makes a matching piece for each change.")
        click_feedback(self.b_music, lambda: self.run_stage("music", {"genre": self.genre.currentData()},
                                                            "Making the music, one piece for each mood"))
        self.b_nomusic = QPushButton("No music")
        click_feedback(self.b_nomusic, self._skip_music, "Skipping...")
        self.b_assemble = QPushButton("3. Assemble timeline")
        self.b_assemble.setObjectName("primary")
        click_feedback(self.b_assemble, self._assemble)
        self.b_rebuild = QPushButton("Rebuild from scratch")
        click_feedback(self.b_rebuild, lambda: self.run_stage("production", {"rebuild": True}, "Rebuilding the timeline"))
        self.b_preview = QPushButton("▶  Make preview")
        click_feedback(self.b_preview, lambda: self.run_stage("preview", {}, "Making a quick preview"))
        self.b_render = QPushButton("4. Render final video")
        self.b_render.setObjectName("primary")
        click_feedback(self.b_render, self._render)
        for b in (self.b_speech, self.genre, self.b_music, self.b_nomusic, self.b_assemble, self.b_rebuild,
                  self.b_preview, self.b_render):
            steps.addWidget(b)
        steps.addStretch(1)
        self.body.addLayout(steps)
        self.state = QLabel("")
        self.state.setObjectName("muted")
        self.body.addWidget(self.state)

        split = QSplitter(Qt.Vertical)
        top = QSplitter(Qt.Horizontal)
        pv = QFrame()
        pv.setStyleSheet(f"QFrame {{ background:{PANEL}; border-radius:8px; }}")
        pl = QVBoxLayout(pv)
        head = QHBoxLayout()
        head.addWidget(QLabel("<b>Preview</b>"))
        self.preview_chip = Chip()
        head.addWidget(self.preview_chip)
        head.addStretch(1)
        self.which = QPushButton("Show final render")
        self.which.setCheckable(True)
        self.which.toggled.connect(lambda _: self._load_player(force=True))
        head.addWidget(self.which)
        pl.addLayout(head)
        self.player = Player()
        self.player.position_changed.connect(self._player_moved)
        pl.addWidget(self.player, 1)
        pl.addWidget(self._mixer())
        top.addWidget(pv)
        insp = QFrame()
        insp.setStyleSheet(f"QFrame {{ background:{PANEL}; border-radius:8px; }}")
        il = QVBoxLayout(insp)
        il.addWidget(QLabel("<b>Selected clip</b>"))
        form = QFormLayout()
        self.i_name = QLabel("Click a clip on the timeline")
        self.i_name.setWordWrap(True)
        self.i_start = QDoubleSpinBox()
        self.i_dur = QDoubleSpinBox()
        self.i_in = QDoubleSpinBox()
        self.i_vol = QDoubleSpinBox()
        for w, suf in ((self.i_start, " s"), (self.i_dur, " s"), (self.i_in, " s")):
            w.setRange(0, 7200)
            w.setDecimals(2)
            w.setSingleStep(0.1)
            w.setSuffix(suf)
        self.i_vol.setRange(0, 2)
        self.i_vol.setSingleStep(0.05)
        self.i_vol.setToolTip("1.00 = the Music level on the mixer below; 0.5 = half as loud")
        form.addRow(self.i_name)
        form.addRow("Starts at", self.i_start)
        form.addRow("Length", self.i_dur)
        form.addRow("Start inside clip", self.i_in)
        form.addRow("Music clip level", self.i_vol)
        il.addLayout(form)
        btns = QHBoxLayout()
        self.i_apply = QPushButton("Apply")
        self.i_apply.clicked.connect(self._apply)
        self.i_delete = QPushButton("Remove")
        self.i_delete.setObjectName("danger")
        self.i_delete.clicked.connect(self._delete)
        btns.addWidget(self.i_apply)
        btns.addWidget(self.i_delete)
        il.addLayout(btns)
        undo = QHBoxLayout()
        self.b_undo = QPushButton("↶ Undo")
        self.b_undo.clicked.connect(self._undo)
        self.b_redo = QPushButton("↷ Redo")
        self.b_redo.clicked.connect(self._redo)
        self.b_owl = QPushButton("Add Owlbert at playhead")
        self.b_owl.clicked.connect(self._add_owl)
        undo.addWidget(self.b_undo)
        undo.addWidget(self.b_redo)
        il.addLayout(undo)
        il.addWidget(self.b_owl)
        moves = QHBoxLayout()
        self.move_kind = QComboBox()
        for key, name in bits.KINDS.items():
            self.move_kind.addItem(name, key)
        self.move_kind.setToolTip("Owlbert's moves: he flies in or off, points at the evidence, gives a wing "
                                  "flourish, or takes off his cap and pulls out the trick of the day")
        self.b_move = QPushButton("Add move")
        self.b_move.clicked.connect(self._add_move)
        moves.addWidget(self.move_kind, 1)
        moves.addWidget(self.b_move)
        il.addLayout(moves)
        tip = QLabel("Keys: Space play/pause · Ctrl+Z undo · Ctrl+Y redo · Delete removes the selected "
                     "Owlbert piece, move or music piece. Moves show in the preview and the final video.")
        tip.setObjectName("muted")
        tip.setWordWrap(True)
        il.addWidget(tip)
        il.addStretch(1)
        top.addWidget(insp)
        top.setSizes([900, 320])
        split.addWidget(top)
        self.editor = TimelineEditor()
        self.editor.changed.connect(self._edited)
        self.editor.seek.connect(lambda s: self.player.seek(s))
        self.editor.selected.connect(self._select)
        split.addWidget(self.editor)
        split.setSizes([420, 300])
        self.body.addWidget(split, 1)
        QShortcut(QKeySequence(Qt.Key_Space), self, activated=self.player.toggle)
        QShortcut(QKeySequence.Undo, self, activated=self._undo)
        QShortcut(QKeySequence.Redo, self, activated=self._redo)
        QShortcut(QKeySequence(Qt.Key_Delete), self, activated=self._delete)
        self._tl: dict = {}
        self._undo_stack: list[str] = []
        self._redo_stack: list[str] = []
        self._sel = None
        self._loaded_media = None
        self._tl_sig = None
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._save)

    # ------------------------------------------------------------ actions
    def _chain(self, stages: list[str], label: str) -> None:
        """Speech track = Owlbert reads every scene, then the words are timed for captions.
        The second step starts by itself when the first one finishes."""
        self._auto_captions = True
        narr = self.stage_status("narration")["status"]
        if narr not in ("approved", "awaiting_approval"):
            self.run_stage("narration", {}, label)
            return
        self._continue_speech()

    def _continue_speech(self) -> None:
        if self.stage_status("narration")["status"] == "awaiting_approval":
            pipeline.approve(self.ep, "narration")
        cap = self.stage_status("captions")["status"]
        if cap == "awaiting_approval":
            pipeline.approve(self.ep, "captions")
            self._auto_captions = False
            self.toast("Speech track and captions are ready. Next: music or No music, then Assemble.")
        elif cap not in ("approved", "queued", "running"):
            self.run_stage("captions", {}, "Timing the words for captions")
        else:
            self._auto_captions = False
        self.refresh()

    def _skip_music(self) -> None:
        pipeline.skip(self.ep, "music", "no music")
        self.toast("No music for this episode.")
        self.refresh()

    def _assemble(self) -> None:
        for st in ("narration", "captions"):
            if self.stage_status(st)["status"] == "awaiting_approval":
                pipeline.approve(self.ep, st)
        if self.stage_status("music")["status"] == "awaiting_approval":
            pipeline.approve(self.ep, "music")
        self.run_stage("production", {}, "Assembling the timeline")

    def _render(self) -> None:
        if self.stage_status("production")["status"] != "approved":
            pipeline.approve(self.ep, "production")
        self.run_stage("render", {}, "Rendering the final video")

    # ------------------------------------------------------------ editing
    def _snapshot(self) -> None:
        self._undo_stack.append(json.dumps(self._tl))
        self._undo_stack = self._undo_stack[-50:]
        self._redo_stack.clear()

    # ------------------------------------------------------------ mixer
    MIX = [("speech_db", "Speech", -24, 12), ("music_db", "Music", -40, 6), ("master_db", "Master", -24, 12)]

    def _mixer(self) -> QFrame:
        """One row under the player: Speech, Music and Master levels, baked into the video."""
        self._mix_loading = True   # ignore slider signals until the page is built
        box = QFrame()
        box.setStyleSheet("QFrame { background:#1d2133; border-radius:6px; }")
        row = QHBoxLayout(box)
        row.setContentsMargins(10, 6, 10, 6)
        mix_label = QLabel("<b>Sound mix</b>")
        mix_label.setToolTip("Baked into the video. Speech and Music balance the voice against the music; Master "
                             "makes the whole video louder or quieter. Press Make preview to hear a change.")
        row.addWidget(mix_label)
        self.mix_sliders: dict[str, tuple[QSlider, QLabel]] = {}
        for key, name, lo, hi in self.MIX:
            val = QLabel("0 dB")
            val.setMinimumWidth(58)
            sl = QSlider(Qt.Horizontal)
            sl.setRange(lo * 2, hi * 2)  # half-dB steps
            sl.setMinimumWidth(110)
            sl.valueChanged.connect(lambda x, lab=val: lab.setText(f"{x / 2:+.1f} dB"))
            sl.sliderReleased.connect(self._mix_changed)
            sl.valueChanged.connect(lambda _x, s_=sl: None if s_.isSliderDown() else self._mix_changed())
            row.addWidget(QLabel(name))
            row.addWidget(sl, 1)
            row.addWidget(val)
            self.mix_sliders[key] = (sl, val)
        reset = QPushButton("Reset")
        reset.setToolTip("Back to the default mix from Settings → Sound")
        reset.clicked.connect(self._mix_reset)
        row.addWidget(reset)
        self._mix_loading = False
        return box

    def _show_mix(self) -> None:
        self._mix_loading = True
        m = prod.mix(self._tl or {})
        for key, (sl, val) in self.mix_sliders.items():
            sl.setValue(int(round(m[key] * 2)))
            val.setText(f"{m[key]:+.1f} dB")
        self._mix_loading = False

    def _mix_changed(self) -> None:
        if self._mix_loading or not getattr(self, "_tl", None):
            return
        new = {k: sl.value() / 2 for k, (sl, _) in self.mix_sliders.items()}
        if new == prod.mix(self._tl):
            return
        self._snapshot_after_edit()
        self._tl["mix"] = new
        self._save_timer.start(400)
        self.state.setText("Sound mix changed. Press ▶ Make preview to hear it.")

    def _mix_reset(self) -> None:
        if self._tl:
            self._snapshot_after_edit()
            self._tl.pop("mix", None)
            self._show_mix()
            self._save_timer.start(400)

    def _edited(self) -> None:
        self._snapshot_after_edit()
        self._save_timer.start(400)

    def _snapshot_after_edit(self) -> None:
        # the editor already changed self._tl in place; record the state before it
        if self._last_saved is not None:
            self._undo_stack.append(self._last_saved)
            self._redo_stack.clear()

    def _save(self) -> None:
        prod.save(self.ep, self._tl, edited=True)
        self._last_saved = json.dumps(self._tl)
        self._tl_sig = self._last_saved
        st = self.stage_status("production")["status"]
        if st == "approved":
            self.ep.record("production", "awaiting_approval", "timeline edited")
            pipeline.invalidate_after(self.ep, "production")
        self._status_line()

    def _undo(self) -> None:
        if not self._undo_stack:
            return
        self._redo_stack.append(json.dumps(self._tl))
        self._tl = json.loads(self._undo_stack.pop())
        self.editor.load(self._tl, self.ep.abs)
        self._show_mix()
        self._save()

    def _redo(self) -> None:
        if not self._redo_stack:
            return
        self._undo_stack.append(json.dumps(self._tl))
        self._tl = json.loads(self._redo_stack.pop())
        self.editor.load(self._tl, self.ep.abs)
        self._show_mix()
        self._save()

    def _select(self, sel) -> None:
        self._sel = sel
        on = sel is not None
        for w in (self.i_start, self.i_dur, self.i_apply):
            w.setEnabled(on)
        if not on:
            self.i_name.setText("Click a clip on the timeline")
            return
        track, c = sel
        self.i_name.setText(f"<b>{track}</b>: {c.get('label') or c.get('scene_id') or c['id']}")
        self.i_start.setValue(c["start"])
        self.i_dur.setValue(c["duration"])
        self.i_dur.setEnabled(track not in ("speech", "moves"))
        self.i_in.setEnabled(track == "video")
        self.i_in.setValue(c.get("inpoint", 0.0))
        self.i_vol.setEnabled(track == "music")
        vol = float(c.get("volume", 1.0))
        self.i_vol.setValue(1.0 if abs(vol - 0.18) < 1e-6 else vol)  # 0.18 was the old fixed music level
        self.i_delete.setEnabled(track in ("owl", "music", "moves", "sfx"))

    def _apply(self) -> None:
        if not self._sel:
            return
        self._undo_stack.append(json.dumps(self._tl))
        track, c = self._sel
        c["start"] = round(self.i_start.value(), 3)
        if track not in ("speech", "moves"):
            c["duration"] = round(max(0.2, self.i_dur.value()), 3)
        if track == "video":
            c["inpoint"] = round(self.i_in.value(), 3)
        if track == "music":
            c["volume"] = round(self.i_vol.value(), 3)
        self.editor.load(self._tl, self.ep.abs)
        self._save()

    def _delete(self) -> None:
        if not self._sel or self._sel[0] not in ("owl", "music", "moves", "sfx"):
            return
        self._undo_stack.append(json.dumps(self._tl))
        track, c = self._sel
        self._tl[track] = [x for x in self._tl[track] if x is not c]
        self._sel = None
        self.editor.load(self._tl, self.ep.abs)
        self._save()

    def _add_owl(self) -> None:
        if not self._tl:
            return
        self._undo_stack.append(json.dumps(self._tl))
        t = self.editor.scene.playhead_s
        n = len(self._tl.setdefault("owl", []))
        self._tl["owl"].append({"id": f"owl-extra-{n}", "start": round(t, 3), "duration": 6.0})
        self.editor.load(self._tl, self.ep.abs)
        self._save()

    def _add_move(self) -> None:
        """Add one of Owlbert's moves at the playhead (the hat trick pulls out the story's trick)."""
        if not self._tl:
            return
        self._undo_stack.append(json.dumps(self._tl))
        kind = self.move_kind.currentData()
        t = self.editor.scene.playhead_s
        mv = {"id": f"{kind}-extra-{len(self._tl.setdefault('moves', [])) + 1}", "kind": kind,
              "start": round(t, 3), "duration": bits.LENGTH[kind], "label": bits.KINDS[kind], "variant": 0}
        if kind == "hat_trick":
            from ... import techniques
            from ...stages.stories import chosen
            try:
                keys = (chosen(self.ep) or {}).get("techniques", [])
            except Exception:  # noqa: BLE001 - no story chosen: a plain card
                keys = []
            tech = techniques.get(keys[0]) if keys else None
            mv["prop"] = {"kind": "card", "text": tech.name if tech else "The Trick"}
        self._tl["moves"].append(mv)
        self._tl["moves"].sort(key=lambda m: m["start"])
        self.editor.load(self._tl, self.ep.abs)
        self._save()

    def _player_moved(self, seconds: float) -> None:
        if not self.which.isChecked():
            self.editor.set_playhead(seconds)

    # ------------------------------------------------------------ refresh
    def _status_line(self) -> None:
        if not self.ep:
            return
        names = [("narration", "speech"), ("captions", "captions"), ("music", "music"),
                 ("production", "timeline"), ("render", "final video")]
        bits = []
        for st, word in names:
            s = self.stage_status(st)
            mark = ("✔" if s["status"] == "approved" else "…" if s["status"] in ("queued", "running")
                    else "!" if s["status"] in ("failed", "rejected") else "○")
            if st == "music" and (s.get("note") or "").startswith("SKIPPED"):
                word = "no music"
            bits.append(f"{mark} {word}")
        self.state.setText("   ".join(bits))
        prev = read_json(self.ep.path("render", "preview.json"))
        tl = prod.load(self.ep)
        if not prev:
            self.preview_chip.set_status("not_started", "No preview yet")
        elif prev.get("timeline_saved_at") != tl.get("saved_at"):
            self.preview_chip.set_status("reset", "Out of date — press Make preview")
        else:
            self.preview_chip.set_status("approved", "Up to date")

    def _load_player(self, force: bool = False) -> None:
        info = read_json(self.ep.path("render", "timeline.json" if self.which.isChecked() else "preview.json"))
        path = self.ep.abs(info["output"]) if info else None
        key = (str(path), info.get("made_at") if info else None)
        if force or key != self._loaded_media:
            self._loaded_media = key
            self.player.load(path)

    _auto_captions = False

    def refresh(self) -> None:
        super().refresh()
        if not self.ep:
            return
        if self._auto_captions and not self.busy("narration") and not self.busy("captions"):
            try:
                self._continue_speech()
            except Exception as exc:  # noqa: BLE001 - show it rather than loop
                self._auto_captions = False
                self.toast(str(exc), "error")
        busy = any(self.busy(s) for s in ("narration", "captions", "music", "production", "preview", "render"))
        video_ok = self.stage_status("video")["status"] == "approved"
        narr = self.stage_status("narration")["status"]
        self.b_speech.setEnabled(not busy and self.stage_status("script")["status"] == "approved")
        self.b_speech.setText("1. Speech track ✔" if narr == "approved" and
                              self.stage_status("captions")["status"] == "approved" else "1. Make speech track")
        self.b_music.setEnabled(not busy)
        if self.ep and getattr(self, "_genre_for", None) != self.ep.project_id:   # show this video's choice
            self._genre_for = self.ep.project_id
            self.genre.setCurrentIndex(max(0, self.genre.findData(self.ep.creative().get("music_genre", ""))))
        self.b_nomusic.setEnabled(not busy)
        self.b_assemble.setEnabled(not busy and video_ok and narr in ("approved", "awaiting_approval"))
        self.b_rebuild.setEnabled(not busy and bool(prod.load(self.ep)))
        self.b_preview.setEnabled(not busy and bool(prod.load(self.ep)))
        self.b_render.setEnabled(not busy and bool(prod.load(self.ep)))
        tl = prod.load(self.ep)
        sig = json.dumps(tl, sort_keys=True)
        if sig != self._tl_sig:
            self._tl_sig = sig
            self._tl = tl
            self._last_saved = json.dumps(tl) if tl else None
            self.editor.load(self._tl, self.ep.abs)
            self._show_mix()
        self._status_line()
        self._load_player()

    _last_saved = None

    def watched(self) -> list[str]:
        return ["narration", "captions", "music", "production", "preview", "render", "video"]
