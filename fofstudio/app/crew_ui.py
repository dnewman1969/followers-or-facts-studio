"""The "Crew & sets..." window on the Storyboard page (Dave, 2026-11-02: "think of it like the way a movie is
made"): who on the film crew did what and why, the sets the production designer dressed (editable), and each
shot's card from the narration it covers to what the camera sees (crew.py)."""

from __future__ import annotations

from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QListWidget, QPlainTextEdit, QPushButton, QSplitter,
                               QTabWidget, QTextBrowser, QVBoxLayout, QWidget)

from .. import bible as biblemod
from .. import crew
from ..util import write_json
from .common import GOLD, MUTED


def _esc(t: str) -> str:
    return (t or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class CrewDialog(QDialog):
    def __init__(self, parent, ep) -> None:
        super().__init__(parent)
        self.ep = ep
        self.setWindowTitle("The film crew")
        self.resize(980, 700)
        lay = QVBoxLayout(self)
        intro = QLabel("A line of script passes through the crew before anything is painted, the way a film is "
                       "made: each one adds one kind of decision, and the script supervisor checks them all. "
                       "You're the showrunner: approve each step on its page, or change anything here.")
        intro.setWordWrap(True)
        intro.setObjectName("muted")
        lay.addWidget(intro)
        tabs = QTabWidget()
        tabs.addTab(self._crew_tab(), "The crew")
        tabs.addTab(self._sets_tab(), "Sets")
        tabs.addTab(self._shots_tab(), "Shot cards")
        lay.addWidget(tabs, 1)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(close)
        lay.addLayout(row)

    # ------------------------------------------------------------- who did what
    def _crew_tab(self) -> QWidget:
        log = crew.entries(self.ep)
        html = []
        for i, r in enumerate(crew.ROLES, 1):
            mine = [e for e in log if e["role"] == r["key"]]
            html.append(f"<h3 style='color:{GOLD};margin-bottom:0'>{i}. {_esc(r['title'])} "
                        f"<span style='color:{MUTED};font-weight:normal'>({_esc(r['real'])})</span></h3>"
                        f"<p style='margin-top:2px'>{_esc(r['job'])}</p>")
            if mine:
                rows = "".join(f"<li>{('<b>' + _esc(e['shot']) + '</b>: ') if e.get('shot') else ''}"
                               f"{_esc(e['what'])}</li>" for e in mine[-6:])
                more = f"<p style='color:{MUTED}'>(and {len(mine) - 6} more)</p>" if len(mine) > 6 else ""
                html.append(f"<ul>{rows}</ul>{more}")
            elif r["key"] not in ("dave", "director", "layout", "animation"):
                html.append(f"<p style='color:{MUTED}'>Nothing yet: press Make pictures.</p>")
        view = QTextBrowser()
        view.setHtml("".join(html))
        return view

    # ------------------------------------------------------------- the production designer's sets
    def _sets_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.bible = biblemod.load(self.ep)
        self.locs = list((self.bible.get("locations") or {}).values())
        if not self.locs:
            lay.addWidget(QLabel("No places yet: press Make pictures once (the breakdown clerk lists them)."))
            return w
        split = QSplitter()
        self.loc_list = QListWidget()
        for loc in self.locs:
            self.loc_list.addItem(loc.get("name") or loc["id"])
        split.addWidget(self.loc_list)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.addWidget(QLabel("Set pieces, one per line (what the camera sees in this place, with materials and "
                            "wear). Changes are used the next time pictures are made:"))
        self.dressing = QPlainTextEdit()
        rl.addWidget(self.dressing, 1)
        self.loc_info = QLabel("")
        self.loc_info.setWordWrap(True)
        self.loc_info.setObjectName("muted")
        rl.addWidget(self.loc_info)
        save = QPushButton("Save this set")
        save.clicked.connect(self._save_set)
        self.saved = QLabel("")
        r2 = QHBoxLayout()
        r2.addWidget(save)
        r2.addWidget(self.saved, 1)
        rl.addLayout(r2)
        split.addWidget(right)
        split.setSizes([260, 700])
        lay.addWidget(split, 1)
        self.loc_list.currentRowChanged.connect(self._show_set)
        self.loc_list.setCurrentRow(0)
        return w

    def _show_set(self, i: int) -> None:
        if not 0 <= i < len(self.locs):
            return
        loc = self.locs[i]
        self.dressing.setPlainText("\n".join(loc.get("dressing") or []))
        self.loc_info.setText(" · ".join(x for x in (
            loc.get("era") and f"Era: {loc['era']}", loc.get("palette") and f"Palette: {loc['palette']}",
            (loc.get("light") or loc.get("lighting")) and f"Light: {loc.get('light') or loc.get('lighting')}",
            loc.get("architecture") and f"Architecture: {loc['architecture']}") if x))
        self.saved.setText("")

    def _save_set(self) -> None:
        i = self.loc_list.currentRow()
        if not 0 <= i < len(self.locs):
            return
        items = [crew.painter_safe(x) for x in self.dressing.toPlainText().splitlines()]
        self.locs[i]["dressing"] = [x for x in items if x][:12]
        self.locs[i]["edited_by_hand"] = True
        write_json(biblemod.path(self.ep), self.bible)
        # shots in this place are drawn up again the next time pictures are made
        board = self.ep.storyboard() or {}
        lid = self.locs[i]["id"]
        scenes = {sid for sid, sc in (self.bible.get("scenes") or {}).items() if sc.get("location") == lid}
        for s in board.get("scenes", []):
            if s["scene_id"] in scenes:
                for sh in s.get("shots", []):
                    sh.pop("camera_sees_from", None)
        if board:
            self.ep.save_storyboard(board)
        crew.log(self.ep, "dave", f"changed the set of {self.locs[i].get('name') or lid}")
        self.dressing.setPlainText("\n".join(self.locs[i]["dressing"]))
        self.saved.setText(f"Saved. {len(scenes)} scene(s) in this place are drawn up again next time you press "
                           "Make pictures (use Remake on a shot to repaint it).")

    # ------------------------------------------------------------- each shot's card
    def _shots_tab(self) -> QWidget:
        view = QTextBrowser()
        board = self.ep.storyboard() or {}
        html = []
        for s in board.get("scenes", []):
            html.append(f"<h3 style='color:{GOLD}'>{_esc(s['scene_id'])}</h3>")
            for sh in s.get("shots", []):
                look = sh.get("look") or {}
                cam = ", ".join(x for x in (look.get("shot_type"), look.get("angle"), look.get("movement")) if x)
                cont = sh.get("continuity") or {}
                html.append(
                    f"<p><b>{_esc(sh['shot_id'])}</b> <span style='color:{MUTED}'>{_esc(sh['kind'])}"
                    f"{' · ' + _esc(sh.get('shows')) if sh.get('shows') else ''}</span><br>"
                    + (f"<i>Covers:</i> “{_esc(sh.get('covers'))}”<br>" if sh.get("covers") else "")
                    + f"<i>Director:</i> {_esc(sh.get('idea'))}"
                    + (f" <span style='color:{MUTED}'>(why: {_esc(sh.get('why'))})</span>" if sh.get("why") else "")
                    + (f"<br><i>Layout:</i> {_esc(cam)}" if cam else "")
                    + (f"<br><i>Camera sees (painted):</i> {_esc(sh['camera_sees'])}" if sh.get("camera_sees") else "")
                    + (f"<br><i>Continuity:</i> place {_esc(cont.get('place') or '-')}, "
                       f"Owlbert {_esc(cont.get('owlbert') or '-')}" if cont else "")
                    + "</p>")
        view.setHtml("".join(html) or "<p>No shots yet: press Make pictures.</p>")
        return view
