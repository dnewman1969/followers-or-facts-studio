"""Stories: three ways to tell it. Read each breakdown, pick one, or ask for a rewrite."""

from __future__ import annotations

import html

from PySide6.QtWidgets import (QHBoxLayout, QInputDialog, QPushButton, QTextBrowser, QVBoxLayout, QWidget)

from ... import techniques
from ...stages import stories
from ...util import read_json
from ..common import GOLD, GREEN, MUTED
from ..creative import CreativePanel
from ..widgets import StagePage, click_feedback

ROLE_NAMES = {"intro": "Opening", "claim": "The claim", "record": "What the record shows",
              "benefit": "Who cashed in", "harm": "Who got hurt", "tell": "Owlbert names the trick",
              "verdict": "Verdict"}


class StoriesPage(StagePage):
    TITLE = "Stories"
    HELP = ("Step 3. First choose how the video is told: the style, length and humor. Then the local AI writes three "
            "ways to tell how the lie was built and take it apart, using only the evidence you ticked, and names the "
            "trick Owlbert will teach. Pick one, or Rewrite with notes. All three are kept: to make another later, go "
            "to Database → Researched ★.")
    APPROVE_STAGE = "stories"

    def __init__(self, window):
        super().__init__(window)
        self.creative = CreativePanel()
        self.body.addWidget(self.creative)
        top = QHBoxLayout()
        self.make_btn = QPushButton("Create 3 stories")
        self.make_btn.setObjectName("primary")
        click_feedback(self.make_btn, lambda: self.run_stage("stories", {}, "Writing 3 stories"))
        top.addWidget(self.make_btn)
        top.addStretch(1)
        self.body.addLayout(top)
        cols = QHBoxLayout()
        self.cards: list[tuple[QTextBrowser, QPushButton, QPushButton]] = []
        for i in range(3):
            box = QWidget()
            v = QVBoxLayout(box)
            v.setContentsMargins(0, 0, 0, 0)
            view = QTextBrowser()
            view.document().setDefaultStyleSheet(f"h2 {{ color: {GOLD}; }}")
            use = QPushButton("Use this story")
            use.clicked.connect(lambda _=False, k=i: self._use(k))
            redo = QPushButton("Rewrite with notes...")
            redo.clicked.connect(lambda _=False, k=i: self._rewrite(k))
            v.addWidget(view, 1)
            v.addWidget(use)
            v.addWidget(redo)
            cols.addWidget(box)
            self.cards.append((view, use, redo))
        self.body.addLayout(cols, 1)

    def set_episode(self, ep) -> None:
        self.creative.set_episode(ep)
        super().set_episode(ep)

    def refresh(self) -> None:
        super().refresh()
        busy = self.busy("stories")
        self.make_btn.setEnabled(bool(self.ep) and not busy and
                                 self.stage_status("research")["status"] == "approved")
        data = read_json(self.ep.path("stories.json")) if self.ep else None
        self.make_btn.setText("Create 3 new stories" if data else "Create 3 stories")
        used = stories.used_by(self.ep) if data else {}
        for i, (view, use, redo) in enumerate(self.cards):
            opt = (data or {}).get("options", [None] * 3)[i] if data and i < len(data.get("options", [])) else None
            picked = data and data.get("chosen") == i
            if busy:
                view.setHtml(f"<p style='color:{MUTED}'>Writing... (watch the progress line above)</p>")
            elif not opt:
                view.setHtml(f"<p style='color:{MUTED}'>Story {i + 1} will appear here.</p>")
            else:
                view.setHtml(self._html(opt, picked, used.get(i, [])))
            use.setEnabled(bool(opt) and not busy)
            redo.setEnabled(bool(opt) and not busy)
            use.setText("✔ Chosen" if picked else "Use this story")
            use.setObjectName("primary" if picked else "")
            use.setStyleSheet("")  # re-apply the object-name style

    def _html(self, s: dict, picked: bool, used: list[str] | None = None) -> str:
        e = html.escape
        beats = "".join(f"<li><b>{ROLE_NAMES.get(b['role'], b['role'])}:</b> {e(b['beat'])}"
                        f"{' <span style=color:' + MUTED + '>[' + ', '.join(b['evidence_ids']) + ']</span>' if b['evidence_ids'] else ''}</li>"
                        for b in s.get("beats", []))
        owl = "".join(f"<li>{e(o)}</li>" for o in s.get("owl_moments", []))
        tricks = [techniques.get(k) for k in s.get("techniques", []) if techniques.get(k)]
        teach = ("<p><b>Teaches the trick:</b> " + "; ".join(f"<b>{e(t.name)}</b> ({e(t.meaning)})" for t in tricks)
                 + "</p>") if tricks else ""
        mark = f"<p style='color:{GREEN}'><b>✔ This is the chosen story</b></p>" if picked else ""
        if used:
            mark += (f"<p style='color:{GOLD}'><b>Already made as {', '.join(used)}.</b> Pick another one for a "
                     "different video, or use it again if you like.</p>")
        rev = f" <span style='color:{MUTED}'>(rewrite {s['revision'] - 1})</span>" if s.get("revision", 1) > 1 else ""
        return (f"{mark}<h2>{e(s['title'])}{rev}</h2><p><i>{e(s['logline'])}</i></p>"
                f"<p><b>Angle:</b> {e(s['angle'])}</p><p><b>Opening:</b> {e(s['opening_hook'])}</p>"
                + (f"<p><b>Thumbnail:</b> <span style='background:#c0392b; color:white; padding:2px 6px;'>"
                   f"&nbsp;{e(s['thumbnail_words'])}&nbsp;</span></p>" if s.get("thumbnail_words") else "")
                + teach + f"<p><b>How it goes:</b></p><ol>{beats}</ol>"
                f"<p><b>Where Owlbert appears:</b></p><ul>{owl}</ul>")

    def _use(self, i: int) -> None:
        stories.choose(self.ep, i)
        self.ep.record("stories", "awaiting_approval", f"option {i + 1} chosen")
        self.toast(f"Story {i + 1} chosen. Press Approve and continue when you're happy.")
        self.refresh()

    def _rewrite(self, i: int) -> None:
        notes, ok = QInputDialog.getMultiLineText(self, "Rewrite story", f"What should change in story {i + 1}?")
        if ok and notes.strip():
            self.run_stage("stories", {"rewrite": {"index": i, "notes": notes.strip()}}, f"Rewriting story {i + 1}")

    def watched(self) -> list[str]:
        return ["stories", "research"]
