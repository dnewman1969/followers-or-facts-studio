"""Episode: the pipeline for one video. Pick a stage, run it, look at what it made, approve it."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox,
                               QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QPlainTextEdit, QScrollArea, QSplitter, QStackedWidget, QTabWidget,
                               QTextBrowser, QVBoxLayout, QWidget)

from ... import db, jobs, pipeline
from ...config import Paths, settings
from ...episode import Episode, list_episodes
from ...stages.storyboard import CAMERA_MOVES, STYLES
from ...util import StageError, read_json
from ..common import (GOLD, GREEN, MUTED, RED, STATUS_COLORS, STATUS_WORDS, button, error, info,
                      label, open_path, row)

CHECK_COLORS = {"block": RED, "warn": GOLD, "ok": GREEN}


class ShotEditor(QWidget):
    """The storyboard as a grid of pictures, with an editor for the selected shot."""

    def __init__(self, page: "EpisodePage"):
        super().__init__()
        self.page = page
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        split = QSplitter(Qt.Horizontal)
        self.grid = QListWidget()
        self.grid.setViewMode(QListWidget.IconMode)
        self.grid.setIconSize(QSize(192, 108))
        self.grid.setResizeMode(QListWidget.Adjust)
        self.grid.setSpacing(6)
        self.grid.setSelectionMode(QListWidget.ExtendedSelection)
        self.grid.itemSelectionChanged.connect(self._select)
        split.addWidget(self.grid)
        side = QWidget()
        form = QFormLayout(side)
        self.shot_label = label("", "h2")
        self.preview = QLabel()
        self.preview.setMinimumHeight(180)
        self.preview.setAlignment(Qt.AlignCenter)
        self.type = QLabel()
        self.prompt = QPlainTextEdit()
        self.prompt.setMaximumHeight(110)
        self.text = QLineEdit()
        self.camera = QComboBox()
        self.camera.addItems(CAMERA_MOVES)
        self.weight = QDoubleSpinBox()
        self.weight.setRange(0.5, 3.0)
        self.weight.setSingleStep(0.5)
        self.animate = QCheckBox("Animate this shot (Wan 2.2)")
        self.provenance = label("", "muted")
        form.addRow(self.shot_label)
        form.addRow(self.preview)
        form.addRow("Type", self.type)
        form.addRow("Picture prompt", self.prompt)
        form.addRow("Text", self.text)
        form.addRow("Camera", self.camera)
        form.addRow("Screen time", self.weight)
        form.addRow(self.animate)
        form.addRow(self.provenance)
        form.addRow(row(button("Save shot", self._save),
                        button("Remake selected images", self._redo_images),
                        button("Re-animate selected", self._redo_video)))
        scroll = QScrollArea()
        scroll.setWidget(side)
        scroll.setWidgetResizable(True)
        split.addWidget(scroll)
        split.setSizes([700, 380])
        lay.addWidget(split)
        self._shots: list[dict[str, Any]] = []

    def load(self, ep: Episode) -> None:
        self.ep = ep
        self._shots = ep.storyboard().get("shots", [])
        self.grid.clear()
        for s in self._shots:
            item = QListWidgetItem(f"{s['shot_id']}\n{s['type']}" + ("  [anim]" if s.get("animate") else ""))
            img = s.get("image")
            if img and ep.abs(img["path"]).exists():
                item.setIcon(QIcon(QPixmap(str(ep.abs(img["path"]))).scaled(
                    192, 108, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
            self.grid.addItem(item)

    def _current(self) -> dict[str, Any] | None:
        r = self.grid.currentRow()
        return self._shots[r] if 0 <= r < len(self._shots) else None

    def _select(self) -> None:
        s = self._current()
        if not s:
            return
        self.shot_label.setText(s["shot_id"])
        self.type.setText(s["type"])
        self.prompt.setPlainText(s.get("prompt", ""))
        self.text.setText(s.get("text", ""))
        self.camera.setCurrentText(s.get("camera", "zoom_in"))
        self.weight.setValue(float(s.get("weight", 1)))
        self.animate.setChecked(bool(s.get("animate")))
        self.animate.setEnabled(s["type"] == "ai_image")
        img = s.get("image")
        if img and self.ep.abs(img["path"]).exists():
            self.preview.setPixmap(QPixmap(str(self.ep.abs(img["path"]))).scaled(
                360, 203, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            bits = [f"{k}: {v}" for k, v in img.items() if k in ("model", "seed", "workflow")]
            if s.get("clip"):
                bits.append(f"clip: {s['clip']['path']}")
            self.provenance.setText(" · ".join(bits))
        else:
            self.preview.setText("(no picture yet)")
            self.provenance.setText("")

    def _save(self) -> None:
        s = self._current()
        if not s:
            return
        changed = s.get("prompt") != self.prompt.toPlainText().strip() or s.get("text") != self.text.text().strip()
        s["prompt"] = self.prompt.toPlainText().strip()
        s["text"] = self.text.text().strip()
        s["camera"] = self.camera.currentText()
        s["weight"] = self.weight.value()
        s["animate"] = self.animate.isChecked()
        if s["type"] == "ai_image":
            style = STYLES.get(self.ep.storyboard().get("style", "documentary"), STYLES["documentary"])
            from ...stages.storyboard import GUARD
            s["full_prompt"] = f"{s['prompt']}. {style}. {GUARD}"
        if changed:
            s.pop("image", None)
            s.pop("clip", None)
        board = self.ep.storyboard()
        board["shots"] = self._shots
        self.ep.save_storyboard(board)
        self.page.after_edit("storyboard" if changed else None)

    def _selected_ids(self) -> list[str]:
        rows = sorted({i.row() for i in self.grid.selectedIndexes()})
        return [self._shots[r]["shot_id"] for r in rows]

    def _redo_images(self) -> None:
        ids = self._selected_ids()
        if ids:
            self.page.queue("images", {"redo": ids})

    def _redo_video(self) -> None:
        ids = self._selected_ids()
        if ids:
            self.page.queue("video", {"redo": ids})


class EpisodePage(QWidget):
    def __init__(self):
        super().__init__()
        self.ep: Episode | None = None
        lay = QVBoxLayout(self)
        self.picker = QComboBox()
        self.picker.currentIndexChanged.connect(self._pick)
        self.title = label("", "h1")
        lay.addWidget(row(self.title, QLabel("Episode:"), self.picker,
                          button("Open folder", lambda: self.ep and open_path(self.ep.folder))))
        split = QSplitter(Qt.Horizontal)
        self.stages = QListWidget()
        self.stages.setMaximumWidth(240)
        self.stages.currentRowChanged.connect(lambda r: self._show_stage())
        split.addWidget(self.stages)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(6, 0, 0, 0)
        self.stage_title = label("", "h2")
        self.stage_desc = label("", "muted")
        self.stage_state = label("")
        rl.addWidget(self.stage_title)
        rl.addWidget(self.stage_desc)
        rl.addWidget(self.stage_state)
        self.options_box = QGroupBox("Options")
        self.options_form = QFormLayout(self.options_box)
        rl.addWidget(self.options_box)
        self.run_btn = button("Run", self._run, "primary")
        self.approve_btn = button("Approve", self._approve)
        self.skip_btn = button("Skip", self._skip)
        self.reject_btn = button("Reject", self._reject, "danger")
        self.recheck_btn = button("Re-check", self._show_stage)
        rl.addWidget(row(self.run_btn, self.approve_btn, self.skip_btn, self.reject_btn, self.recheck_btn))
        self.checks = QListWidget()
        self.checks.setMaximumHeight(110)
        self.checks.setWordWrap(True)
        rl.addWidget(self.checks)
        self.tabs = QTabWidget()
        self.view = QStackedWidget()
        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        self.browser.document().setDefaultStyleSheet("a { color: #d4a017; }")
        self.editor = QPlainTextEdit()
        self.shots = ShotEditor(self)
        editor_box = QWidget()
        el = QVBoxLayout(editor_box)
        el.setContentsMargins(0, 0, 0, 0)
        el.addWidget(self.editor)
        el.addWidget(row(button("Save script.md", self._save_script),
                         label("Edit freely; keep the SCENE headings and SOURCES lines.", "muted")))
        self.view.addWidget(self.browser)     # 0
        self.view.addWidget(editor_box)       # 1
        self.view.addWidget(self.shots)       # 2
        self.tabs.addTab(self.view, "What this stage made")
        self.history = QTextBrowser()
        self.tabs.addTab(self.history, "History")
        rl.addWidget(self.tabs, 1)
        split.addWidget(right)
        split.setSizes([220, 900])
        lay.addWidget(split, 1)
        self._opts: dict[str, Any] = {}

    # ------------------------------------------------------------ loading
    def refresh(self) -> None:
        current = self.ep.project_id if self.ep else None
        self.picker.blockSignals(True)
        self.picker.clear()
        for p in list_episodes():
            self.picker.addItem(f"{p['project_id']}  {p['title']}", p["project_id"])
        if current:
            self.picker.setCurrentIndex(max(0, self.picker.findData(current)))
        self.picker.blockSignals(False)
        if not self.ep and self.picker.count():
            self._pick()
        elif self.ep:
            self.title.setText(self.ep.title)
        self._refresh_stages()

    def open(self, project_id: str) -> None:
        self.ep = Episode.load(project_id)
        self.refresh()
        self.picker.blockSignals(True)
        self.picker.setCurrentIndex(max(0, self.picker.findData(project_id)))
        self.picker.blockSignals(False)
        self.title.setText(self.ep.title)
        self._refresh_stages()
        nxt = pipeline.next_stage(self.ep)
        names = [s.name for s in pipeline.STAGES]
        self.stages.setCurrentRow(names.index(nxt) if nxt else 0)

    def _pick(self) -> None:
        pid = self.picker.currentData()
        if pid:
            self.ep = Episode.load(pid)
            self.title.setText(self.ep.title)
            self._refresh_stages()
            self._show_stage()

    def _refresh_stages(self) -> None:
        if not self.ep:
            return
        r = self.stages.currentRow()
        self.stages.blockSignals(True)
        self.stages.clear()
        for s in pipeline.overview(self.ep):
            word = "Skipped" if s["skipped"] else STATUS_WORDS.get(s["status"], s["status"])
            item = QListWidgetItem(f"{s['label']}\n   {word}")
            if s["status"] == "not_started":
                color = "#ffffff" if not s["missing"] else MUTED
            else:
                color = STATUS_COLORS.get(s["status"], MUTED)
            item.setForeground(QColor(color))
            self.stages.addItem(item)
        self.stages.setCurrentRow(max(0, r))
        self.stages.blockSignals(False)

    def current_stage(self) -> str | None:
        r = self.stages.currentRow()
        return pipeline.STAGES[r].name if 0 <= r < len(pipeline.STAGES) else None

    # ------------------------------------------------------------ stage panel
    def _show_stage(self) -> None:
        name = self.current_stage()
        if not self.ep or not name:
            return
        st = pipeline.stage(name)
        status = self.ep.stage_status(name)
        missing = pipeline.missing_requirements(self.ep, name)
        self.stage_title.setText(st.label)
        self.stage_desc.setText(st.description + ("  (optional)" if st.optional else ""))
        word = STATUS_WORDS.get(status["status"], status["status"])
        extra = f" - {status['note']}" if status.get("note") else ""
        wait = f"   Needs first: {', '.join(pipeline.stage(m).label for m in missing)}" if missing else ""
        self.stage_state.setText(f"Status: {word}{extra}{wait}")
        busy = status["status"] in ("queued", "running")
        self.run_btn.setEnabled(not missing and not busy)
        self.approve_btn.setEnabled(not missing and status["status"] not in ("approved", "queued", "running", "not_started"))
        self.skip_btn.setVisible(st.optional)
        self.skip_btn.setEnabled(not busy)
        self.reject_btn.setEnabled(status["status"] == "awaiting_approval")
        self._build_options(name)
        self.checks.clear()
        if status["status"] != "not_started":
            for c in pipeline.checks(self.ep, name):
                item = QListWidgetItem(f"{'✖' if c.level == 'block' else '!' if c.level == 'warn' else '✔'}  {c.message}")
                item.setForeground(QColor(CHECK_COLORS[c.level]))
                self.checks.addItem(item)
        self._show_output(name)
        self.history.setHtml("<br>".join(
            f"<span style='color:{MUTED}'>{e['at']}</span> <b>{e['stage']}</b> "
            f"{STATUS_WORDS.get(e['status'], e['status'])} {e['note'] or ''}"
            for e in reversed(self.ep.history())))

    def _clear_options(self) -> None:
        while self.options_form.rowCount():
            self.options_form.removeRow(0)
        self._opts = {}

    def _build_options(self, name: str) -> None:
        self._clear_options()
        f = self.options_form
        if name == "research":
            self._opts["fetch_sources"] = QCheckBox("Save copies of the primary sources from the web")
            self._opts["fetch_sources"].setChecked(True)
            self._opts["find_quotes"] = QCheckBox("Find quotes in them (kept only if word-for-word)")
            self._opts["find_quotes"].setChecked(True)
            self._opts["refresh"] = QCheckBox("Download sources again even if already saved")
            for w in self._opts.values():
                f.addRow(w)
            claims = QListWidget()
            claims.setMaximumHeight(130)
            chosen = set(self.ep.claim_ids)
            arc = self.ep.info.get("arc_id")
            marks = ",".join("?" * len(chosen)) or "''"
            for c in db.rows("SELECT * FROM claim_readiness WHERE arc_id=? OR claim_id IN (%s) "
                             "ORDER BY primary_sources DESC" % marks, (arc, *chosen)):
                item = QListWidgetItem(f"{c['claim_id']}  ({c['primary_sources']} primary)  {c['short_title']}")
                item.setData(Qt.UserRole, c["claim_id"])
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked if c["claim_id"] in chosen else Qt.Unchecked)
                claims.addItem(item)
            claims.itemChanged.connect(lambda _i, w=claims: self._save_claims(w))
            f.addRow("Claims in this episode", claims)
        elif name == "script":
            spin = QDoubleSpinBox()
            spin.setRange(2, 20)
            spin.setValue(8)
            spin.setSuffix(" min")
            self._opts["minutes"] = spin
            self._opts["direction"] = QLineEdit()
            self._opts["direction"].setPlaceholderText("Optional direction, e.g. 'open on the radio show'")
            f.addRow("Length", spin)
            f.addRow("Direction", self._opts["direction"])
        elif name == "storyboard":
            style = QComboBox()
            style.addItems(list(STYLES))
            mode = QComboBox()
            mode.addItems(["llm", "simple"])
            mode.setCurrentText(settings()["storyboard"]["mode"])
            self._opts["style"], self._opts["mode"] = style, mode
            f.addRow("Picture style", style)
            f.addRow("Shot planning", mode)
        elif name == "narration":
            from ...engines.tts import get_engine
            voice = QComboBox()
            voice.setEditable(True)
            try:
                voice.addItems(get_engine().voices())
            except Exception:  # noqa: BLE001
                pass
            voice.setCurrentText(settings()["voice"]["voice"])
            speed = QDoubleSpinBox()
            speed.setRange(0.7, 1.3)
            speed.setSingleStep(0.05)
            speed.setValue(float(settings()["voice"]["speed"]))
            self._opts["voice"], self._opts["speed"] = voice, speed
            f.addRow("Voice", voice)
            f.addRow("Speed", speed)
        elif name == "music":
            tags = QLineEdit()
            tags.setPlaceholderText("instrumental, documentary underscore, calm, soft piano...")
            lib = QComboBox()
            lib.addItem("(generate with ACE-Step)", "")
            for p in sorted(Paths().music_library.glob("*")):
                if p.suffix.lower() in (".wav", ".mp3", ".flac", ".ogg"):
                    lib.addItem(p.name, p.name)
            self._opts["tags"], self._opts["library_file"] = tags, lib
            f.addRow("Music style", tags)
            f.addRow("Or use", lib)
        elif name == "render":
            self._opts["draft"] = QCheckBox("Quick 720p draft first")
            f.addRow(self._opts["draft"])
        elif name == "package":
            self._opts["title"] = QLineEdit()
            self._opts["title"].setPlaceholderText("(script title)")
            self._opts["thumbnail_text"] = QLineEdit()
            self._opts["thumbnail_text"].setPlaceholderText("Up to 4 words")
            verdict = QComboBox()
            verdict.addItems(["FALSE", "MISLEADING", "UNPROVEN", "TRUE", ""])
            self._opts["verdict"] = verdict
            f.addRow("YouTube title", self._opts["title"])
            f.addRow("Thumbnail words", self._opts["thumbnail_text"])
            f.addRow("Verdict stamp", verdict)
        self.options_box.setVisible(self.options_form.rowCount() > 0)

    def _option_values(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, w in self._opts.items():
            if isinstance(w, QCheckBox):
                out[key] = w.isChecked()
            elif isinstance(w, QDoubleSpinBox):
                out[key] = w.value()
            elif isinstance(w, QComboBox):
                out[key] = w.currentData() if w.currentData() is not None else w.currentText()
            elif isinstance(w, QLineEdit):
                if w.text().strip():
                    out[key] = w.text().strip()
        return out

    def _save_claims(self, widget: QListWidget) -> None:
        ids = [widget.item(i).data(Qt.UserRole) for i in range(widget.count())
               if widget.item(i).checkState() == Qt.Checked]
        self.ep.set_claims(ids)

    def _show_output(self, name: str) -> None:
        ep = self.ep
        if name == "script":
            path = ep.path("script.md")
            self.editor.setPlainText(path.read_text(encoding="utf-8") if path.exists() else "")
            self.view.setCurrentIndex(1)
            return
        if name in ("storyboard", "images", "video"):
            self.shots.load(ep)
            self.view.setCurrentIndex(2)
            return
        self.view.setCurrentIndex(0)
        html = ""
        if name == "research" and ep.path("research.md").exists():
            import html as h
            html = "<pre style='white-space: pre-wrap'>" + h.escape(ep.path("research.md").read_text(encoding="utf-8")) + "</pre>"
        elif name == "narration":
            manifest = read_json(ep.path("audio", "narration.json"), {}) or {}
            html = "".join(f"<p><a href='{ep.abs(m['path']).as_uri()}'>{sid}</a> - {m['seconds']:.1f}s "
                           f"({m['engine']}/{m['voice']})</p>" for sid, m in manifest.items())
        elif name == "captions" and ep.path("captions", "words.json").exists():
            t = read_json(ep.path("captions", "words.json"))
            html = "".join(f"<p><b>{sid}</b>: " + " ".join(w["word"] for w in s["words"][:40]) + " ...</p>"
                           for sid, s in t["scenes"].items())
        elif name == "music":
            meta = read_json(ep.path("audio", "music", "music.json"))
            if meta:
                html = f"<p><a href='{ep.abs(meta['path']).as_uri()}'>Play music bed</a> - {meta.get('model')}</p>"
        elif name == "render":
            t = read_json(ep.path("render", "timeline.json"))
            if t:
                html = (f"<p><a href='{ep.abs(t['output']).as_uri()}'>Play {Path(t['output']).name}</a>"
                        f" - {t['seconds'] / 60:.1f} min, {t['encoder']}{' (draft)' if t['draft'] else ''}</p>"
                        "<p>Chapters: " + ", ".join(f"{c['scene_id']} @ {c['start']:.0f}s" for c in t["chapters"]) + "</p>")
        elif name == "package" and ep.path("publish", "metadata.json").exists():
            import html as h
            meta = read_json(ep.path("publish", "metadata.json"))
            html = (f"<p><img src='{ep.path('publish', 'thumbnail.png').as_uri()}' width='480'></p>"
                    f"<h3>{h.escape(meta['title'])}</h3><pre style='white-space: pre-wrap'>"
                    f"{h.escape(meta['description'])}</pre>")
        elif name == "upload":
            u = read_json(ep.path("publish", "upload.json"))
            if u:
                html = f"<p><a href='https://youtu.be/{u['youtube_id']}'>https://youtu.be/{u['youtube_id']}</a> ({u['privacy']})</p>"
        self.browser.setHtml(html or "<p style='color:#8a8fa3'>Nothing here yet.</p>")

    # ------------------------------------------------------------ actions
    def queue(self, name: str, options: dict[str, Any]) -> None:
        try:
            jobs.enqueue(self.ep.project_id, name, options)
            jobs.start_worker()
        except StageError as exc:
            error(self, str(exc))
        self._refresh_stages()
        self._show_stage()

    def _run(self) -> None:
        name = self.current_stage()
        if name == "upload":
            meta = read_json(self.ep.path("publish", "metadata.json")) or {}
            from PySide6.QtWidgets import QMessageBox
            if QMessageBox.question(self, "Upload to YouTube",
                                    f"Upload \"{meta.get('title')}\" as {settings()['youtube']['privacy']}?") \
                    != QMessageBox.Yes:
                return
        self.queue(name, self._option_values())

    def _approve(self) -> None:
        try:
            pipeline.approve(self.ep, self.current_stage())
        except StageError as exc:
            error(self, str(exc))
        self._advance()

    def _skip(self) -> None:
        try:
            pipeline.skip(self.ep, self.current_stage())
        except StageError as exc:
            error(self, str(exc))
        self._advance()

    def _reject(self) -> None:
        note, ok = QInputDialog.getText(self, "Reject", "What's wrong? (kept in the history)")
        if ok:
            pipeline.reject(self.ep, self.current_stage(), note)
            self._show_stage()

    def _advance(self) -> None:
        self._refresh_stages()
        nxt = pipeline.next_stage(self.ep)
        if nxt:
            self.stages.setCurrentRow([s.name for s in pipeline.STAGES].index(nxt))
        self._show_stage()

    def _save_script(self) -> None:
        from ...util import write_text
        write_text(self.ep.path("script.md"), self.editor.toPlainText())
        self.after_edit("script")

    def after_edit(self, stage: str | None) -> None:
        """You changed a file by hand: the stage needs a fresh look, and later ones are stale."""
        if stage:
            st = self.ep.stage_status(stage)["status"]
            if st == "approved":
                self.ep.record(stage, "awaiting_approval", "edited by hand")
            pipeline.invalidate_after(self.ep, stage)
        self._refresh_stages()
        self._show_stage()

    def poll(self) -> None:
        """Called every few seconds: update statuses while the worker runs."""
        if not self.ep:
            return
        name = self.current_stage()
        before = self.ep.stage_status(name)["status"] if name else None
        self._refresh_stages()
        if name and self.ep.stage_status(name)["status"] != before:
            self._show_stage()
