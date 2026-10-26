"""Stories: two ways to tell it as a short video, each with the AI's length estimate. Pick one, or ask for a
rewrite. Book-sized subjects: write the book, and make it into a long video (the movie)."""

from __future__ import annotations

import html

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QHBoxLayout, QInputDialog, QLabel, QMessageBox, QPushButton, QTextBrowser,
                               QVBoxLayout, QWidget)

from ... import storytypes, techniques
from ...stages import book, stories, storysize
from ...util import read_json
from ..common import GOLD, GREEN, MUTED, tint
from ..creative import CreativePanel
from ..widgets import StagePage, click_feedback

e = html.escape
ROLE_NAMES = {"intro": "Opening", "claim": "The claim", "record": "What the record shows",
              "benefit": "Who cashed in", "harm": "Who got hurt", "tell": "Owlbert names the trick",
              "toolkit": "The question to ask", "verdict": "Verdict", "outro": "Sign-off"}


class StoriesPage(StagePage):
    TITLE = "Stories"
    HELP = ("Step 3. Choose the story type, writer and humor. Then the local AI writes two "
            "ways to tell how the lie was built and take it apart, using only the evidence you ticked, and names the "
            "trick Owlbert will teach, each with how long its short video should be. Pick one (the length follows it), or "
            "Rewrite with notes. Both are kept: to make another later, go "
            "to Database → Researched ★. Before writing, it sizes the story up: a Short, one video, a series, or "
            "big enough for a book. Write the book makes a PDF with references, from the ticked research only.")
    APPROVE_STAGE = "stories"
    CLEAR_STAGE = "stories"

    def __init__(self, window):
        super().__init__(window)
        self.creative = CreativePanel(show=("humor", "story"))
        self.body.addWidget(self.creative)
        top = QHBoxLayout()
        self.make_btn = QPushButton("Create 2 stories")
        self.make_btn.setObjectName("primary")
        click_feedback(self.make_btn, lambda: self.run_stage("stories", {}, "Writing 2 stories"))
        top.addWidget(self.make_btn)
        top.addStretch(1)
        self.body.addLayout(top)
        self.size_text = QLabel("")
        self.size_text.setWordWrap(True)
        self.size_text.setStyleSheet(f"background:{tint(GOLD, 0.10)}; border:1px solid {GOLD}; border-radius:6px; "
                                     "padding:8px;")
        self.body.addWidget(self.size_text)
        shelf = QHBoxLayout()
        self.book_btn = QPushButton("📚 Write the book")
        self.book_btn.setToolTip("The local AI writes the whole story as a book, chapter by chapter, using only the "
                                 "evidence you ticked, with references. Makes a PDF. Takes a while; it carries on "
                                 "where it stopped if you stop it.")
        click_feedback(self.book_btn, lambda: self.run_stage("book", {}, "Writing the book"))
        self.book_again = QPushButton("Write it again from the start")
        click_feedback(self.book_again, self._book_fresh)
        self.book_open = QPushButton("Open the PDF")
        self.book_open.clicked.connect(lambda: self._open("book.pdf"))
        self.book_notes = QPushButton("What to check")
        self.book_notes.setToolTip("Paragraphs that were removed and names to check (book/review.md).")
        self.book_notes.clicked.connect(lambda: self._open("review.md"))
        self.book_ok = QPushButton("Approve the book")
        self.book_ok.setToolTip("You've read every page: make the final PDF without the DRAFT marks.")
        click_feedback(self.book_ok, self._book_approve)
        self.movie_btn = QPushButton("🎬 Make the book into a movie")
        self.movie_btn.setToolTip("A long documentary video that follows the book chapter by chapter. It becomes the "
                                  "chosen story and sets the length; then go to Script.")
        click_feedback(self.movie_btn, self._movie)
        for b in (self.book_btn, self.book_again, self.book_open, self.book_notes, self.book_ok, self.movie_btn):
            shelf.addWidget(b)
        self.book_state = QLabel("")
        self.book_state.setWordWrap(True)
        shelf.addWidget(self.book_state, 1)
        self.body.addLayout(shelf)
        cols = QHBoxLayout()
        self.cards: list[tuple[QTextBrowser, QPushButton, QPushButton]] = []
        for i in range(stories.STORY_COUNT):
            box = QWidget()
            v = QVBoxLayout(box)
            v.setContentsMargins(0, 0, 0, 0)
            view = QTextBrowser()
            view.document().setDefaultStyleSheet(f"h2 {{ color: {GOLD}; }}")
            use = QPushButton("Use this story")
            use.clicked.connect(lambda _=False, k=i: self._use_card(k))
            redo = QPushButton("Rewrite with notes...")
            redo.clicked.connect(lambda _=False, k=i: self._rewrite_card(k))
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
        if self.ep and not self.creative.isAncestorOf(self.focusWidget() or self):
            self.creative.set_episode(self.ep)   # pick up changes made on other pages (e.g. Length on Script)
        busy = self.busy("stories")
        self.make_btn.setEnabled(bool(self.ep) and not busy and
                                 self.stage_status("research")["status"] == "approved")
        data = read_json(self.ep.path("stories.json")) if self.ep else None
        self.make_btn.setText(f"Create {stories.STORY_COUNT} new stories" if data else
                              f"Create {stories.STORY_COUNT} stories")
        used = stories.used_by(self.ep) if data else {}
        self._refresh_book()
        for i, (view, use, redo) in enumerate(self.cards):
            opts = [o for o in (data or {}).get("options", []) if o.get("format") != "movie"]
            opt = opts[i] if i < len(opts) else None
            picked = bool(data and opt is not None and data.get("chosen") is not None
                          and data["options"][data["chosen"]] is opt)
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
        st = storytypes.STORY_TYPES.get(s.get("story_type", ""))
        wr = storytypes.writers().get(s.get("writer", ""))
        if s.get("length_seconds"):
            secs = int(s["length_seconds"])
            kind = "a YouTube Short" if secs <= stories.SHORT_MAX else "a short video"
            mark += (f"<p><b>Video length: about {secs // 60}:{secs % 60:02d}</b> ({kind})"
                     + (f" <span style='color:{MUTED}'>{e(s.get('length_why', ''))}</span>" if s.get("length_why") else "")
                     + "</p>")
        if st or wr:
            mark += (f"<p style='color:{GOLD}'>" + (f"<b>{e(st.name)}</b>" if st else "")
                     + (" · written as " if st and wr else "") + (f"<b>{e(wr.name)}</b>" if wr else "") + "</p>")
        return (f"{mark}<h2>{e(s['title'])}{rev}</h2><p><i>{e(s['logline'])}</i></p>"
                f"<p><b>Angle:</b> {e(s['angle'])}</p><p><b>Opening:</b> {e(s['opening_hook'])}</p>"
                + (f"<p><b>Thumbnail:</b> <span style='background:#c0392b; color:white; padding:2px 6px;'>"
                   f"&nbsp;{e(s['thumbnail_words'])}&nbsp;</span></p>" if s.get("thumbnail_words") else "")
                + teach + f"<p><b>How it goes:</b></p><ol>{beats}</ol>"
                f"<p><b>Where Owlbert appears:</b></p><ul>{owl}</ul>")

    def _refresh_book(self) -> None:
        size = storysize.load(self.ep) if self.ep else {}
        self.size_text.setVisible(bool(size))
        if size:
            self.size_text.setText(storysize.summary_html(size))
        research_ok = bool(self.ep) and self.stage_status("research")["status"] == "approved"
        busy = self.busy("book")
        b = book.load(self.ep) if self.ep else {}
        written = bool(b.get("pdf")) and self.ep.abs(b["pdf"]).exists()
        st = book.stats(b) if b else {}
        partly = bool(b.get("chapters")) and st.get("unwritten")
        self.book_btn.setText("📚 Finish the book" if partly else "📚 Write the book")
        self.book_btn.setObjectName("primary" if size.get("format") == "book" and not written else "")
        self.book_btn.setStyleSheet("")
        self.book_btn.setEnabled(research_ok and not busy)
        self.book_again.setVisible(bool(b.get("chapters")))
        self.movie_btn.setVisible(bool(b.get("chapters")) or size.get("format") == "book")
        self.movie_btn.setEnabled(bool(b.get("chapters")) and not busy)
        if size.get("format") == "book" or b.get("chapters"):
            self.movie_btn.setText(f"🎬 Make the book into a movie (~{stories.movie_minutes(self.ep)} min)")
        self.book_again.setEnabled(research_ok and not busy)
        for w in (self.book_open, self.book_notes, self.book_ok):
            w.setVisible(written)
            w.setEnabled(not busy)
        if busy:
            self.book_state.setText(f"<span style='color:{MUTED}'>Writing the book... (watch the bar at the top)</span>")
        elif written:
            done = (f"<b style='color:{GREEN}'>✔ Approved</b> " if b.get("approved") else
                    f"<b style='color:{GOLD}'>Draft</b> - read it, then Approve. ")
            self.book_state.setText(f"{done}{e(b.get('title', ''))}: {st['chapters']} chapters, about "
                                    f"{st['words']:,} words ({st['pages']} pages). {st['dropped']} paragraph(s) "
                                    f"removed, {st['warnings']} name(s) to check.")
        elif partly:
            self.book_state.setText(f"{st['unwritten']} of {len(b['chapters'])} chapters still to write.")
        else:
            self.book_state.setText("" if research_ok else f"<span style='color:{MUTED}'>Approve Research first.</span>")

    def _open(self, name: str) -> None:
        path = self.ep.path("book", name) if self.ep else None
        if path and path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        else:
            self.toast(f"There's no {name} yet.", "warn")

    def _book_fresh(self) -> None:
        if QMessageBox.question(self, "Write the book again", "Throw away the chapters written so far and write the "
                                "whole book again from the start?") == QMessageBox.StandardButton.Yes:
            self.run_stage("book", {"fresh": True}, "Writing the book from the start")

    def _book_approve(self) -> None:
        book.approve(self.ep)
        self.toast("Book approved: the final PDF (no DRAFT marks) is in the book folder.")
        self.refresh()

    def _index_of_card(self, k: int) -> int:
        data = read_json(self.ep.path("stories.json")) or {}
        cards = [n for n, o in enumerate(data.get("options", [])) if o.get("format") != "movie"]
        return cards[k]

    def _use_card(self, k: int) -> None:
        self._use(self._index_of_card(k))

    def _rewrite_card(self, k: int) -> None:
        self._rewrite(self._index_of_card(k))

    def _movie(self) -> None:
        i = stories.make_movie_story(self.ep)
        self.ep.record("stories", "awaiting_approval", "the movie chosen")
        self.toast(f"The movie is the chosen story (about {stories.movie_minutes(self.ep)} minutes). Approve, then "
                   "go to Script.")
        self.refresh()
        return i

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
        return ["stories", "research", "book"]
