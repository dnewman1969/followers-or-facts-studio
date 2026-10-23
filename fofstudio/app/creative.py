"""How the video is told: style, length, humor and caricatures (shown on the Stories and Script pages),
plus the Cast window where you approve how each caricatured public figure is drawn."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFrame, QHBoxLayout,
                               QLabel, QPlainTextEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget)

from .. import cast, styles
from .common import GOLD, MUTED, PANEL, error

HUMOR = ["No jokes", "A light touch", "Some gentle humor", "Full satire (punching up only)"]


class CreativePanel(QFrame):
    """Style · length · humor · caricatures, saved to the episode as soon as you change them."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.ep = None
        self.setObjectName("creative")
        self.setStyleSheet(f"QFrame#creative {{ background:{PANEL}; border-radius:8px; }}")
        v = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(QLabel("<b>Video style</b>"))
        self.style = QComboBox()
        for key, name in styles.choices():
            self.style.addItem(name, key)
        self.style.setMinimumWidth(240)
        row.addWidget(self.style)
        row.addWidget(QLabel("Length"))
        self.minutes = QDoubleSpinBox()
        self.minutes.setRange(1, 30)
        self.minutes.setDecimals(1)
        self.minutes.setSuffix(" min")
        row.addWidget(self.minutes)
        row.addWidget(QLabel("Humor"))
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
        self.blurb = QLabel("")
        self.blurb.setWordWrap(True)
        self.blurb.setObjectName("muted")
        v.addWidget(self.blurb)
        self._loading = False
        self.style.currentIndexChanged.connect(self._style_changed)
        self.minutes.valueChanged.connect(self._save)
        self.humor.currentIndexChanged.connect(self._save)
        self.caric.toggled.connect(self._save)

    def set_episode(self, ep) -> None:
        self.ep = ep
        self.setEnabled(bool(ep))
        if not ep:
            return
        self._loading = True
        c = ep.creative()
        self.style.setCurrentIndex(max(0, self.style.findData(c["style"])))
        self.minutes.setValue(float(c.get("minutes", 8)))
        self.humor.setCurrentIndex(c["humor"])
        self.caric.setChecked(c["caricatures"])
        self._loading = False
        self._show()

    def _style_changed(self) -> None:
        if self._loading or not self.ep:
            return
        st = styles.get(self.style.currentData())
        # a new style brings its own humor level and caricature default
        self.ep.set_creative(style=st.key, humor=st.humor, caricatures=st.caricature)
        self.set_episode(self.ep)
        self.changed.emit()

    def _save(self) -> None:
        if self._loading or not self.ep:
            return
        self.ep.set_creative(style=self.style.currentData(), minutes=self.minutes.value(),
                             humor=self.humor.currentData(), caricatures=self.caric.isChecked())
        self._show()
        self.changed.emit()

    def _show(self) -> None:
        c = self.ep.creative()
        st = styles.get(c["style"])
        allowed = st.caricature and not c["careful"]
        self.caric.setEnabled(allowed)
        self.cast_btn.setEnabled(allowed and c["caricatures"])
        self.humor.setEnabled(not c["careful"])
        notes = [f"<b>{st.name}:</b> {st.blurb} About {st.shot_seconds:g} s per picture, so a "
                 f"{c['minutes']:g}-minute video needs about {round(c['minutes'] * 60 / st.shot_seconds)} pictures."]
        if c["careful"]:
            notes.append(f"<span style='color:{GOLD}'>Careful topic (victims: courts and documents only): no humor and "
                         "no caricatures.</span>")
        elif not st.caricature:
            notes.append("Caricatures are only offered in cartoon satire styles.")
        elif c["caricatures"]:
            n_ok = len(cast.approved(self.ep))
            notes.append(f"Caricatures on: {n_ok} approved in the Cast." if n_ok else
                         f"<span style='color:{GOLD}'>Caricatures on, but nobody is approved yet: press Cast...</span>")
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
        self.rows = []
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
            design = QPlainTextEdit(p["design"])
            design.setPlaceholderText("e.g. a stocky man with a shaved head and a goatee, shouting into a huge "
                                      "radio microphone, sleeves rolled up")
            design.setFixedHeight(64)
            bl.addWidget(design)
            r = QHBoxLayout()
            suggest = QPushButton("Suggest a design")
            ok = QCheckBox("Approved: OK to draw this person in this style")
            ok.setChecked(p["approved"])
            suggest.clicked.connect(lambda _=False, pp=p, d=design: self._suggest(pp, d))
            r.addWidget(suggest)
            r.addWidget(ok)
            r.addStretch(1)
            bl.addLayout(r)
            hl.addWidget(box)
            self.rows.append((p, design, ok))
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

    def _suggest(self, person, edit) -> None:
        edit.setPlainText("Thinking...")
        QApplication.processEvents()
        try:
            edit.setPlainText(cast.propose(person))
        except Exception as exc:  # noqa: BLE001 - Ollama not running, etc.
            edit.setPlainText("")
            error(self, f"Couldn't suggest a design: {exc}")

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
        self.accept()
