"""How the video is told. The Stories page shows story type, writer and humor; the Script page shows the video
style and caricatures (CreativePanel(show=...)),
plus the Cast window where you approve how each caricatured public figure is drawn."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFrame, QHBoxLayout,
                               QLabel, QLineEdit, QPlainTextEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget)

from .. import cast, storytypes, styles
from .common import GOLD, MUTED, PANEL, error

HUMOR = ["No jokes", "A light touch", "Some gentle humor", "Full satire (punching up only)"]


class CreativePanel(QFrame):
    """Style · length · humor · caricatures, saved to the episode as soon as you change them."""

    changed = Signal()

    ALL = ("style", "minutes", "humor", "caricatures", "story")

    def __init__(self, parent=None, show: tuple[str, ...] = ALL):
        super().__init__(parent)
        self.ep = None
        self.show = set(show)
        self.setObjectName("creative")
        self.setStyleSheet(f"QFrame#creative {{ background:{PANEL}; border-radius:8px; }}")
        v = QVBoxLayout(self)
        row = QHBoxLayout()
        style_label = QLabel("<b>Video style</b>")
        row.addWidget(style_label)
        self.style = QComboBox()
        self._fill_styles(False)
        self.style.setMinimumWidth(240)
        row.addWidget(self.style)
        self.fresh_btn = QPushButton("Fresh looks...")
        self.fresh_btn.setToolTip("Looks you haven't used lately, and the style mixer (how it's made from one look, "
                                  "where it lives from another)")
        self.fresh_btn.clicked.connect(self._fresh)
        row.addWidget(self.fresh_btn)
        style_label.setToolTip("About 85 looks and 38 mixes from the research. '(untested)' ones haven't been "
                               "painted on your PC yet: Storyboard → Test styles.")
        minutes_label = QLabel("Length")
        row.addWidget(minutes_label)
        self.minutes = QDoubleSpinBox()
        self.minutes.setRange(1, 30)
        self.minutes.setDecimals(1)
        self.minutes.setSuffix(" min")
        row.addWidget(self.minutes)
        humor_label = QLabel("Humor")
        row.addWidget(humor_label)
        self.humor = QComboBox()
        for i, h in enumerate(HUMOR):
            self.humor.addItem(h, i)
        row.addWidget(self.humor)
        self.caric = QCheckBox("Caricatures of the people who sold it")
        row.addWidget(self.caric)
        self.cast_btn = QPushButton("Cast...")
        self.cast_btn.setToolTip("Approve how each public figure is drawn as a cartoon")
        self.cast_btn.clicked.connect(self._cast)
        row.addWidget(self.cast_btn)
        row.addStretch(1)
        v.addLayout(row)
        row2 = QHBoxLayout()
        type_label = QLabel("<b>Story type</b>")
        row2.addWidget(type_label)
        self.story_type = QComboBox()
        self.story_type.setMinimumWidth(260)
        row2.addWidget(self.story_type)
        writer_label = QLabel("<b>Writer</b>")
        row2.addWidget(writer_label)
        self.writer = QComboBox()
        self.writer.setMinimumWidth(240)
        row2.addWidget(self.writer)
        row2.addStretch(1)
        v.addLayout(row2)
        parts = {"style": (style_label, self.style, self.fresh_btn), "minutes": (minutes_label, self.minutes),
                 "humor": (humor_label, self.humor), "caricatures": (self.caric, self.cast_btn),
                 "story": (type_label, self.story_type, writer_label, self.writer)}
        for name, widgets in parts.items():
            for w in widgets:
                w.setVisible(name in self.show)
        self.blurb = QLabel("")
        self.blurb.setWordWrap(True)
        self.blurb.setObjectName("muted")
        v.addWidget(self.blurb)
        self._loading = False
        self.style.currentIndexChanged.connect(self._style_changed)
        self.minutes.valueChanged.connect(self._save)
        self.humor.currentIndexChanged.connect(self._save)
        self.caric.toggled.connect(self._caric_toggled)
        self.story_type.currentIndexChanged.connect(self._save)
        self.writer.currentIndexChanged.connect(self._save)

    def set_episode(self, ep) -> None:
        self.ep = ep
        self.setEnabled(bool(ep))
        if not ep:
            return
        self._loading = True
        c = ep.creative()
        self._fill_styles(bool(c.get("careful")), c["style"])
        self.style.setCurrentIndex(max(0, self.style.findData(c["style"])))
        self.minutes.setValue(float(c.get("minutes", 8)))
        self.humor.setCurrentIndex(c["humor"])
        self.caric.setChecked(c["caricatures"])
        self._fill_story_choices(c)
        self._loading = False
        self._show()

    def _fill_story_choices(self, c: dict) -> None:
        """Only the story types and writers that suit this topic (careful topics get the sober ones)."""
        careful, humor = bool(c.get("careful")), int(c.get("humor", 1))
        self.story_type.clear()
        from ..stages.stories import STORY_COUNT
        self.story_type.addItem(f"Let the AI pick ({STORY_COUNT} different)", "auto")
        for t in storytypes.allowed_types(careful):
            self.story_type.addItem(t.name, t.key)
            self.story_type.setItemData(self.story_type.count() - 1, f"{t.blurb}\nSuits: {t.suits}", 3)
        self.story_type.setCurrentIndex(max(0, self.story_type.findData(c.get("story_type", "auto"))))
        self.writer.clear()
        self.writer.addItem("Let the AI pick (one that suits the story)", "auto")
        for w in storytypes.allowed_writers(careful, humor):
            self.writer.addItem(w.name, w.key)
            self.writer.setItemData(self.writer.count() - 1, f"Sounds like {w.sounds_like}", 3)
        self.writer.setCurrentIndex(max(0, self.writer.findData(c.get("writer", "auto"))))

    def _fill_styles(self, careful: bool, current: str = "") -> None:
        """The looks you can pick (careful topics: sober ones only), each with its description as a tooltip."""
        was = self.style.blockSignals(True)
        self.style.clear()
        items = styles.choices(careful)
        if current and current not in {k for k, _ in items}:
            items.insert(0, (current, styles.get(current).name))
        for key, name in items:
            self.style.addItem(name, key)
            self.style.setItemData(self.style.count() - 1, styles.describe(styles.get(key)) or
                                   styles.get(key).blurb, 3)
        self.style.blockSignals(was)

    def _fresh(self) -> None:
        if not self.ep:
            return
        from .styleideas import StyleIdeasDialog
        d = StyleIdeasDialog(self.ep, self)
        if d.exec() and d.chosen:
            st = styles.get(d.chosen)
            self.ep.set_creative(style=d.chosen, humor=st.humor, caricatures=st.caricature)
            self.set_episode(self.ep)
            self.changed.emit()

    def _style_changed(self) -> None:
        if self._loading or not self.ep:
            return
        st = styles.get(self.style.currentData())
        if st.tier == "care" and styles.ratings().get(st.key) != "kept":
            from PySide6.QtWidgets import QMessageBox
            if QMessageBox.question(self, "This look needs your OK", f"{st.name} comes from a living cultural "
                                    f"tradition, so it needs care:\n\n{st.needs_ok}\n\nUse it with that care?") \
                    != QMessageBox.StandardButton.Yes:
                self.set_episode(self.ep)
                return
            styles.rate(st.key, "kept")
        # a new style brings its own humor level and caricature default
        self.ep.set_creative(style=st.key, humor=st.humor, caricatures=st.caricature)
        self.set_episode(self.ep)
        self.changed.emit()

    def _caric_toggled(self, on: bool) -> None:
        """Caricatures are only drawn in the cartoon satire style: ticking the box in another style offers to
        switch to it (it used to just be greyed out, which looked broken)."""
        if self._loading or not self.ep:
            return
        st = styles.get(self.style.currentData())
        if on and not st.caricature:
            satire = styles.STYLES.get("satire") or next((s for s in styles.STYLES.values() if s.caricature), None)
            from PySide6.QtWidgets import QMessageBox
            if satire and QMessageBox.question(
                    self, "Caricatures",
                    f"Caricatures of the people who sold the lie are only drawn in clearly-cartoon styles "
                    f"(so nobody mistakes them for real pictures), such as {satire.name}. This video is {st.name}."
                    f"\n\n"
                    f"Switch this video to {satire.name} and turn caricatures on?") == QMessageBox.StandardButton.Yes:
                self.ep.set_creative(style=satire.key, humor=satire.humor, caricatures=True)
                self.set_episode(self.ep)
                self.changed.emit()
                return
            self._loading = True
            self.caric.setChecked(False)
            self._loading = False
            return
        self._save()

    def _save(self) -> None:
        if self._loading or not self.ep:
            return
        self.ep.set_creative(style=self.style.currentData(), minutes=self.minutes.value(),
                             humor=self.humor.currentData(), caricatures=self.caric.isChecked(),
                             story_type=self.story_type.currentData() or "auto",
                             writer=self.writer.currentData() or "auto")
        self._show()
        self.changed.emit()

    def _show(self) -> None:
        c = self.ep.creative()
        st = styles.get(c["style"])
        allowed = st.caricature and not c["careful"]
        self.caric.setEnabled(not c["careful"])
        self.caric.setToolTip("Never on careful topics (real victims)." if c["careful"] else
                              "Draw the public figures who sold this lie as clearly-cartoon caricatures."
                              + ("" if st.caricature else " Only in a cartoon satire style: ticking it offers to "
                                                           "switch."))
        self.cast_btn.setEnabled(allowed and c["caricatures"])
        self.humor.setEnabled(not c["careful"])
        notes = [f"<b>{st.name}:</b> {st.blurb} About {st.shot_seconds:g} s per picture, so a "
                 f"{c['minutes']:g}-minute video needs about {round(c['minutes'] * 60 / st.shot_seconds)} pictures."] \
            if "style" in self.show else []
        if "style" in self.show:
            from .. import styleengine
            f = styleengine.fatigue(st.key, styleengine.history(self.ep.project_id))
            if f >= styleengine.FATIGUE_LIMIT:
                notes.append(f"<span style='color:{GOLD}'>This look is close to your last videos (fatigue {f:.2f}): "
                             "press Fresh looks... for ones you haven't used lately.</span>")
            if st.status == "draft" and styles.status_of(st) == "draft":
                notes.append("Untested look: Storyboard → Test styles paints it on your PC first.")
            if st.needs_ok:
                notes.append(f"<span style='color:{GOLD}'>Care: {st.needs_ok}</span>")
        if c["careful"]:
            notes.append(f"<span style='color:{GOLD}'>Careful topic (victims: courts and documents only): no humor and "
                         "no caricatures.</span>")
        elif "caricatures" not in self.show:
            pass
        elif not st.caricature:
            notes.append("This look doesn't carry caricatures (only clearly-cartoon drawn looks do): tick the box "
                         "to switch to Political-cartoon satire.")
        elif c["caricatures"]:
            n_ok = len(cast.approved(self.ep))
            notes.append(f"Caricatures on: {n_ok} approved in the Cast." if n_ok else
                         f"<span style='color:{GOLD}'>Caricatures on, but nobody is approved yet: press Cast...</span>")
        t = storytypes.STORY_TYPES.get(c.get("story_type", ""))
        w = storytypes.writers().get(c.get("writer", ""))
        if t and "story" in self.show:
            notes.append(f"<br><b>{t.name}:</b> {t.blurb}")
        if w and "story" in self.show:
            notes.append(f"<br><b>Writer, {w.name}:</b> sounds like {w.sounds_like} (the writing style; Owlbert's "
                         "voice stays his own)")
        self.blurb.setText(" ".join(notes))

    def _cast(self) -> None:
        if self.ep:
            CastDialog(self.ep, self).exec()
            self._show()


class CastDialog(QDialog):
    """Who may be caricatured in this video, and how each one is drawn. Nothing is drawn until you approve it."""

    def __init__(self, ep, parent=None):
        super().__init__(parent)
        self.ep = ep
        self.setWindowTitle("Caricature cast")
        self.resize(860, 640)
        v = QVBoxLayout(self)
        intro = QLabel(
            "<b>The people who sold this lie, drawn as clearly-cartoon caricatures.</b><br>"
            f"<span style='color:{MUTED}'>Only people the database records as saying, spreading, platforming or "
            "profiting from these claims; never victims, families, believers or private people. Write how they're "
            "drawn using public traits only (hair, glasses, build, clothes, props), never their name: the name is "
            "added as a caption, and pictures are labelled AI. They only appear in scenes that cite what they "
            "actually did, and never speak except through verified quote cards. This is research-based caution, "
            "not legal advice.</span>")
        intro.setWordWrap(True)
        v.addWidget(intro)
        trow = QHBoxLayout()
        trow.addWidget(QLabel("<b>Caricature style</b>"))
        self.trad = QComboBox()
        tier_name = {"A": "house style", "B": "with care", "C": "history only"}
        for t in cast.traditions():
            self.trad.addItem(f"{t['name']} ({tier_name.get(t['tier'], t['tier'])})", t["key"])
            self.trad.setItemData(self.trad.count() - 1, f"{t['visual_dna']}\nFaces: {t['face_body']}\n"
                                  f"Best for: {t['best_use']}\nTone risk: {t['tone_risk']}", 3)
        self.trad.setCurrentIndex(max(0, self.trad.findData(cast.tradition(ep)["key"])))
        trow.addWidget(self.trad, 1)
        v.addLayout(trow)
        self.rows = []
        self._research: dict = {}
        self._who: dict = {}
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        holder = QWidget()
        hl = QVBoxLayout(holder)
        people = cast.eligible(ep)
        if not people:
            hl.addWidget(QLabel("Nobody in this video's ticked claims can be caricatured."))
        for p in people:
            box = QFrame()
            box.setStyleSheet(f"QFrame {{ background:{PANEL}; border-radius:6px; }}")
            bl = QVBoxLayout(box)
            head = f"<b>{p['name']}</b> <span style='color:{MUTED}'>{p.get('role_types') or ''} · {p.get('roles')}</span>"
            if p["deceased"]:
                head += (f" <span style='color:{GOLD}'>(deceased: some states protect a dead person's likeness; "
                         "keep it clearly satirical)</span>")
            hl_ = QLabel(head)
            hl_.setWordWrap(True)
            bl.addWidget(hl_)
            who_row = QHBoxLayout()
            who_row.addWidget(QLabel("Who is this (for the photo search)"))
            who = QLineEdit(p.get("search_hint") or "")
            who.setPlaceholderText("e.g. InfoWars conspiracy radio host, Austin Texas")
            who.setToolTip("Words that pick out THIS person, so the photo search doesn't find someone else with the "
                           "same name (Alex Jones the InfoWars host, not the British TV presenter). Only photos "
                           "from pages that mention these words are used.")
            who_row.addWidget(who, 1)
            bl.addLayout(who_row)
            design = QPlainTextEdit(p["design"])
            design.setPlaceholderText("e.g. a stocky man with a shaved head and a goatee, shouting into a huge "
                                      "radio microphone, sleeves rolled up")
            design.setFixedHeight(64)
            bl.addWidget(design)
            r = QHBoxLayout()
            suggest = QPushButton("Research looks from photos")
            suggest.setToolTip("Searches the web for photos of this person (like an image search), has the local "
                               "vision model describe the face in 3-6 of them (multiple choice, majority vote) and "
                               "writes a kind cartoon design that pushes the 1-3 most recognisable features. You "
                               "edit and approve it. The photos are only looked at, then deleted: never used in a "
                               "video or sent to the picture maker.")
            ok = QCheckBox("Approved: OK to draw this person in this style")
            ok.setChecked(p["approved"])
            note = QLabel("")
            note.setWordWrap(True)
            note.setObjectName("muted")
            paint = QPushButton("Paint previews")
            paint.setToolTip("Paint this design in the chosen caricature style and 3 other styles (about a minute "
                             "with ComfyUI), to see it before you approve")
            paint.setEnabled(False)
            pics = QHBoxLayout()
            suggest.clicked.connect(lambda _=False, pp=p, d=design, n=note, b=suggest, pb=paint, w=who:
                                    self._suggest({**pp, "search_hint": w.text().strip()}, d, n, b, pb))
            paint.clicked.connect(lambda _=False, pp=p, d=design, n=note, pb=paint, pl=pics:
                                  self._paint(pp, d, n, pb, pl))
            r.addWidget(suggest)
            r.addWidget(paint)
            r.addWidget(ok)
            r.addStretch(1)
            bl.addLayout(r)
            bl.addWidget(note)
            bl.addLayout(pics)
            hl.addWidget(box)
            self.rows.append((p, design, ok))
            self._who[p["person_id"]] = who
        hl.addStretch(1)
        scroll.setWidget(holder)
        v.addWidget(scroll, 1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        save = QPushButton("Save")
        save.setObjectName("primary")
        save.clicked.connect(self._save)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        v.addLayout(buttons)

    def _background(self, work, note, done) -> None:
        """Run work() in the background, show its progress messages in `note`, then call done(result, error)."""
        import threading

        from PySide6.QtCore import QTimer
        box: dict = {}

        def run() -> None:
            try:
                box["result"] = work(lambda m: box.__setitem__("msg", m))
            except Exception as exc:  # noqa: BLE001 - shown in plain words
                box["error"] = str(exc)

        threading.Thread(target=run, daemon=True).start()
        timer = QTimer(self)

        def poll() -> None:
            if "msg" in box:
                note.setText(box.pop("msg"))
            if "result" in box or "error" in box:
                timer.stop()
                done(box.get("result"), box.get("error"))

        timer.timeout.connect(poll)
        timer.start(400)

    def _suggest(self, person, edit, note, button, paint) -> None:
        """Dave's five steps: research photos, analyse the features, design, art direction, output."""
        button.setEnabled(False)
        if person.get("search_hint"):
            cast.save_hint(person["person_id"], person["search_hint"])
        note.setText(f"Step 1: searching for photos of {person['name']} ({person.get('search_hint') or 'no description'})...")
        tradition = self.trad.currentData()

        def done(res, err) -> None:
            button.setEnabled(True)
            if err:
                note.setText(f"Couldn't research a design: {err}")
                return
            cast.save_research(person["person_id"], res)
            self._research[person["person_id"]] = res
            edit.setPlainText(res["design"])
            paint.setEnabled(True)
            clear = sum(1 for r in res["references"] if r["clear_face"])
            ex = "; ".join(f"{e.get('feature', '')} +{e.get('percent', 35)}%: {e.get('how', '')}"
                           for e in res.get("exaggerations") or [])
            note.setText(
                f"<b>Key features:</b> {', '.join(res.get('key_features') or []) or '-'}<br>"
                f"<b>Exaggerated:</b> {ex or '-'}<br>"
                f"<span style='color:{MUTED}'>Looked at {clear} photo(s) with a clear face (from "
                f"{', '.join(sorted({r['from'] for r in res['references']}))}), then deleted them. Style: "
                f"{res.get('tradition', '')}. Alternates: {', '.join(v['style'] for v in res.get('variations') or [])}."
                + (f" Note: {'; '.join(res['warnings'])}." if res.get("warnings") else "")
                + " Write in the prop tied to what they're documented doing, press Paint previews to see it, then "
                  "approve.</span>")

        self._background(lambda say: cast.research_design(person, tradition, on_progress=say), note, done)

    def _paint(self, person, edit, note, paint, pics) -> None:
        res = dict(self._research.get(person["person_id"]) or {})
        if not res:
            return
        text = edit.toPlainText().strip()      # your edits to the design are what gets painted
        if text and text != res["design"]:
            res["image_prompt"] = res["image_prompt"].replace(res["design"], text)
            res["variations"] = [{**v, "prompt": v["prompt"].replace(res["design"], text)} for v in res["variations"]]
            res["design"] = text
        paint.setEnabled(False)
        note.setText("Painting 4 previews with ComfyUI (about a minute)...")

        def done(out, err) -> None:
            paint.setEnabled(True)
            if err:
                note.setText(f"Couldn't paint the previews: {err}. Is ComfyUI running?")
                return
            while pics.count():
                w = pics.takeAt(0).widget()
                if w:
                    w.deleteLater()
            from .common import cached_pixmap
            for item in out:
                lab = QLabel()
                lab.setPixmap(cached_pixmap(item["path"], 220, 124))
                lab.setToolTip(f"{item['style']}\n\n{item['prompt']}")
                col = QVBoxLayout()
                cap = QLabel(item["style"])
                cap.setObjectName("muted")
                w = QWidget()
                col.addWidget(lab)
                col.addWidget(cap)
                w.setLayout(col)
                pics.addWidget(w)
            note.setText("Previews painted (first one is the chosen style). If the likeness is off, edit the design "
                         "and paint again; approve when it looks right.")

        self._background(lambda say: cast.paint_previews(self.ep, person["person_id"], res), note, done)

    def _save(self) -> None:
        from ..stages.storyboard import names_in, person_names
        names = person_names()
        for p, design, ok in self.rows:
            text = design.toPlainText().strip()
            if ok.isChecked() and not text:
                error(self, f"Write how {p['name']} is drawn before approving.")
                return
            if names_in(text, names):
                error(self, f"{p['name']}: the design mentions a name ({', '.join(names_in(text, names))}). "
                            "Describe looks only; the name is added as a caption.")
                return
            if text or ok.isChecked():
                cast.save(p["person_id"], text, ok.isChecked())
        for pid, who in self._who.items():
            if who.text().strip():
                cast.save_hint(pid, who.text())
        self.ep.set_creative(caricature_style=self.trad.currentData())
        self.accept()
