"""Research: browse arcs and claims, see how well each is sourced, re-import from truth-vlog."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QFileDialog, QLineEdit, QSplitter, QTextBrowser, QVBoxLayout,
                               QWidget)
from PySide6.QtCore import Qt

from ... import db
from ...db import importer
from ...db.validate import validate
from ..common import GOLD, GREEN, MUTED, RED, button, color_item, error, fill, info, label, row, table


class ResearchPage(QWidget):
    make_episode = Signal(str)

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.addWidget(label("Research database", "h1"))
        self.summary = label("", "muted")
        lay.addWidget(self.summary)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search arcs and claims...")
        self.search.textChanged.connect(self.refresh)
        lay.addWidget(row(self.search, button("Make episode from arc", self._make),
                          button("Re-import from truth-vlog", self._import),
                          button("Check database", self._validate), stretch=False))
        split = QSplitter(Qt.Vertical)
        self.arcs = table(["Arc", "Title", "Claims", "Sourced", "3+ sources", "Careful", "Status"])
        self.arcs.itemSelectionChanged.connect(self._load_claims)
        self.claims = table(["Claim", "Title", "Verdict", "Primary sources", "Status"])
        self.claims.itemSelectionChanged.connect(self._load_detail)
        self.detail = QTextBrowser()
        self.detail.setOpenExternalLinks(True)
        self.detail.document().setDefaultStyleSheet("a { color: #d4a017; }")
        split.addWidget(self.arcs)
        split.addWidget(self.claims)
        split.addWidget(self.detail)
        split.setSizes([300, 250, 250])
        lay.addWidget(split, 1)
        self._arc_ids: list[str] = []
        self._claim_ids: list[str] = []

    def refresh(self) -> None:
        q = f"%{self.search.text().strip()}%"
        arcs = db.rows("""SELECT a.* FROM arc_strength a WHERE a.title LIKE ? OR a.arc_id LIKE ?
                          OR EXISTS (SELECT 1 FROM claim c WHERE c.arc_id=a.arc_id AND
                          (c.short_title LIKE ? OR c.claim_summary LIKE ?))
                          ORDER BY sourced_claims DESC, claims DESC""", (q, q, q, q))
        self._arc_ids = [a["arc_id"] for a in arcs]
        fill(self.arcs, [[a["arc_id"], a["title"], a["claims"], a["sourced_claims"],
                          a["well_sourced_claims"], "yes" if a["careful"] else "", a["status"]]
                         for a in arcs])
        for r, a in enumerate(arcs):
            color_item(self.arcs, r, 3, GREEN if a["claims"] and a["sourced_claims"] == a["claims"]
                       else GOLD if a["sourced_claims"] else RED)
        self.arcs.resizeColumnsToContents()
        meta = {r["key"]: r["value"] for r in db.rows("SELECT * FROM meta")}
        n = db.one("SELECT COUNT(*) c, SUM(primary_sources>0) s FROM claim_readiness")
        self.summary.setText(f"{n['c']} claims, {n['s']} with a primary source. Imported "
                             f"{meta.get('research_imported_at', 'never')} from "
                             f"{meta.get('research_source', '-')}")

    def _load_claims(self) -> None:
        r = self.arcs.currentRow()
        if not 0 <= r < len(self._arc_ids):
            return
        claims = db.rows("SELECT * FROM claim_readiness WHERE arc_id=? ORDER BY primary_sources DESC",
                         (self._arc_ids[r],))
        self._claim_ids = [c["claim_id"] for c in claims]
        fill(self.claims, [[c["claim_id"], c["short_title"], c["falsity_status"],
                            c["primary_sources"], c["status"]] for c in claims])
        for i, c in enumerate(claims):
            color_item(self.claims, i, 3, GREEN if c["primary_sources"] else RED)
        self.claims.resizeColumnsToContents()

    def _load_detail(self) -> None:
        r = self.claims.currentRow()
        if not 0 <= r < len(self._claim_ids):
            return
        cid = self._claim_ids[r]
        c = db.one("SELECT * FROM claim WHERE claim_id=?", (cid,))
        srcs = db.rows("""SELECT s.* FROM claim_source cs JOIN source s USING(source_id)
                          WHERE cs.claim_id=? ORDER BY s.is_primary DESC""", (cid,))
        people = db.rows("""SELECT p.name, ce.link_role FROM claim_entity ce JOIN person p
                            ON p.person_id=ce.entity_id WHERE ce.claim_id=? AND ce.entity_type='person'""", (cid,))
        html = [f"<h3>{c['short_title']}</h3><p>{c['claim_summary'] or ''}</p>",
                f"<p><b>Verdict:</b> {c['falsity_status']} &nbsp; <b>Harm:</b> {c['harm_summary'] or ''}"
                f"<br><b>Who benefited:</b> {c['who_benefited'] or ''}</p>"]
        if people:
            html.append("<p><b>People:</b> " + ", ".join(f"{p['name']} ({p['link_role']})" for p in people) + "</p>")
        html.append("<p><b>Sources</b></p><ul>")
        for s in srcs:
            tag = "primary" if s["is_primary"] else s["source_type"]
            link = f" <a href='{s['url']}'>link</a>" if s["url"] else ""
            saved = " · saved copy" if s["text_path"] else ""
            html.append(f"<li>[{tag}] {s['source_id']}: {s['title']} ({s['publisher'] or ''} "
                        f"{s['date'] or ''}){link}{saved}</li>")
        html.append("</ul>")
        self.detail.setHtml("".join(html))

    def _make(self) -> None:
        r = self.arcs.currentRow()
        if 0 <= r < len(self._arc_ids):
            self.make_episode.emit(self._arc_ids[r])

    def _import(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "truth-vlog research folder",
                                                  str(importer.research_dir()))
        if not folder:
            return
        try:
            report = importer.import_research(folder)
        except Exception as exc:  # noqa: BLE001
            error(self, str(exc))
            return
        info(self, f"Imported {report['counts']['claims']} claims, {report['counts']['sources']} "
                   f"sources.\n\nFixed on the way in:\n" + "\n".join(report["fixes"][:15]) +
             (f"\n\nWarnings: {len(report['warnings'])}" if report["warnings"] else ""))
        self.refresh()

    def _validate(self) -> None:
        result = validate()
        text = (f"{len(result['errors'])} errors, {len(result['warnings'])} warnings.\n\n" +
                "\n".join(result["errors"][:20] + result["warnings"][:20]))
        info(self, text)
