"""Lay out a book as a PDF (6 x 9 inch trade paperback page) with ReportLab (BSD licence).

Title page, an "About this book" page that says how it was made, contents, chapters with numbered
references after each paragraph, word-for-word quotes set apart, and a reference list with links and
Wayback Machine copies. Until you approve the book every page says DRAFT.

Uses the PDF's built-in Times and Helvetica fonts, so there is no font licence to worry about. Characters
those fonts can't show are swapped for the nearest plain ones.
"""

from __future__ import annotations

import html
import unicodedata
from datetime import date
from pathlib import Path
from typing import Any

from .config import REPO, settings

ART = REPO / "brand" / "owlbert-profile.png"


def clean(text: Any) -> str:
    """Text the built-in fonts can draw (they cover Windows-1252)."""
    out = []
    for ch in str(text or ""):
        try:
            ch.encode("cp1252")
            out.append(ch)
        except UnicodeEncodeError:
            plain = unicodedata.normalize("NFKD", ch).encode("cp1252", "ignore").decode("cp1252")
            out.append(plain or "?")
    return "".join(out)


def _n(k: int, word: str) -> str:
    return f"{k} {word}" + ("" if k == 1 else "s")


def x(text: Any) -> str:
    return html.escape(clean(text), quote=False)


def build(path: Path, book: dict[str, Any], mat, draft: bool = True, kf_episodes: list[str] | None = None) -> Path:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import (BaseDocTemplate, Frame, Image, NextPageTemplate, PageBreak, PageTemplate,
                                    Paragraph, Spacer)
    from reportlab.platypus.tableofcontents import TableOfContents

    from .stages.book import references, stats

    cfg = settings().get("book", {})
    author = cfg.get("author") or "Followers or Facts"
    title = book.get("title") or "Untitled"
    subtitle = book.get("subtitle") or ""

    body = ParagraphStyle("body", fontName="Times-Roman", fontSize=11, leading=15.5, alignment=TA_JUSTIFY,
                          spaceAfter=7, firstLineIndent=14)
    first = ParagraphStyle("first", parent=body, firstLineIndent=0)
    quote = ParagraphStyle("quote", parent=body, fontName="Times-Italic", leftIndent=22, rightIndent=14,
                           firstLineIndent=0, fontSize=10.5, leading=14.5, spaceBefore=2, spaceAfter=3)
    quote_by = ParagraphStyle("quote_by", parent=quote, fontName="Times-Roman", fontSize=9, alignment=TA_LEFT,
                              textColor=colors.HexColor("#444444"), spaceAfter=9)
    h1 = ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=18, leading=22, spaceBefore=36, spaceAfter=6)
    kicker = ParagraphStyle("kicker", fontName="Helvetica", fontSize=9, leading=12, textColor=colors.HexColor("#8a6d1d"),
                            spaceBefore=0, spaceAfter=2)
    h2 = ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=12, leading=15, spaceBefore=10, spaceAfter=4)
    small = ParagraphStyle("small", fontName="Times-Roman", fontSize=9.5, leading=13, spaceAfter=6)
    ref = ParagraphStyle("ref", parent=small, leftIndent=22, firstLineIndent=-22, alignment=TA_LEFT)
    cover_title = ParagraphStyle("ct", fontName="Helvetica-Bold", fontSize=26, leading=31, alignment=TA_CENTER,
                                 spaceAfter=10)
    cover_sub = ParagraphStyle("cs", fontName="Times-Italic", fontSize=14, leading=18, alignment=TA_CENTER,
                               spaceAfter=24)
    cover_by = ParagraphStyle("cb", fontName="Helvetica", fontSize=11, leading=14, alignment=TA_CENTER)

    page_w, page_h = 6 * inch, 9 * inch

    def decorate(canvas, doc, number: bool) -> None:
        canvas.saveState()
        if draft:
            canvas.setFillColor(colors.Color(0.82, 0.82, 0.82, alpha=0.6))
            canvas.setFont("Helvetica-Bold", 34)
            canvas.translate(page_w / 2, page_h / 2)
            canvas.rotate(40)
            canvas.drawCentredString(0, 0, "DRAFT - NOT YET REVIEWED")
            canvas.rotate(-40)
            canvas.translate(-page_w / 2, -page_h / 2)
        if number:
            canvas.setFillColor(colors.HexColor("#555555"))
            canvas.setFont("Times-Roman", 9)
            canvas.drawCentredString(page_w / 2, 0.45 * inch, str(doc.page))
            canvas.drawString(0.75 * inch, page_h - 0.5 * inch, clean(title)[:70])
        canvas.restoreState()

    class Doc(BaseDocTemplate):
        def afterFlowable(self, flowable) -> None:
            toc = getattr(flowable, "toc", None)
            if toc:
                level, text, key = toc
                self.canv.bookmarkPage(key)
                self.canv.addOutlineEntry(clean(text), key, level=level, closed=False)
                self.notify("TOCEntry", (level, clean(text), self.page, key))

    doc = Doc(str(path), pagesize=(page_w, page_h), leftMargin=0.75 * inch, rightMargin=0.75 * inch,
              topMargin=0.8 * inch, bottomMargin=0.8 * inch, title=clean(title), author=clean(author),
              subject=clean(subtitle), creator="Followers or Facts Studio")
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="f")
    doc.addPageTemplates([PageTemplate("front", [frame], onPage=lambda c, d: decorate(c, d, False)),
                          PageTemplate("body", [frame], onPage=lambda c, d: decorate(c, d, True))])

    order, numbers = references(book, mat)
    s = stats(book)
    m = book.get("material") or mat.counts()
    flow: list = []

    # ---- title page
    flow.append(Spacer(1, 0.5 * inch))
    flow.append(Paragraph(x(title), cover_title))
    if subtitle:
        flow.append(Paragraph(x(subtitle), cover_sub))
    if ART.exists():
        from PIL import Image as PILImage
        with PILImage.open(ART) as im:
            w, h = im.size
        width = 2.2 * inch
        flow.append(Image(str(ART), width=width, height=width * h / w))
        flow.append(Spacer(1, 0.3 * inch))
    flow.append(Paragraph(x(author), cover_by))
    flow.append(PageBreak())

    # ---- about this book
    reviewed = ("It has not been reviewed yet: this is a draft." if draft else
                f"It was read, checked and approved by {x(author)} before publication.")
    about = [
        f"This book was drafted with the help of a local AI model from the research files of the {x(author)} "
        f"channel. It covers {_n(m.get('claims', 0), 'claim')} and cites {_n(len(order), 'source')}; "
        f"its {_n(m.get('quotes', 0), 'quotation')} were checked word for word against saved copies of their "
        "sources.",
        "The AI was allowed to use only that material. Every paragraph names the sources it relies on (the "
        "numbers in brackets point to the References at the back). A program checked every paragraph: any "
        "number, date or quotation that couldn't be found in the sources it cites was removed"
        + (f" ({s['dropped']} paragraph{'s' if s['dropped'] != 1 else ''} in all)." if s["dropped"] else ".")
        + " Quotations are printed exactly as they appear in the source. " + reviewed,
        "Where a source shows someone knowingly said something false, the book says so and cites it. "
        "Otherwise it sets out what was claimed and what the record shows, and leaves the judgment to you.",
    ]
    if kf_episodes:
        about.append("Research leads came from the Knowledge Fight podcast's episode index (episodes "
                     + x(", ".join(kf_episodes[:30])) + "). Knowledge Fight is a guide to where to look, "
                     "never a source of evidence; every fact here comes from the sources listed.")
    about.append("Corrections: if you find a mistake, please tell us. Corrections are made in public, and the "
                 "next edition fixes them.")
    about.append(f"© {date.today().year} {x(author)}.")
    flow.append(Paragraph("About this book", h2))
    for a in about:
        flow.append(Paragraph(a, small))
    flow.append(PageBreak())

    # ---- contents
    toc = TableOfContents()
    toc.levelStyles = [ParagraphStyle("toc1", fontName="Times-Roman", fontSize=11, leading=15, leftIndent=12,
                                      firstLineIndent=-12)]
    flow.append(Paragraph("Contents", h2))
    flow.append(toc)
    flow.append(NextPageTemplate("body"))
    flow.append(PageBreak())

    # ---- chapters
    chapters = [ch for ch in book.get("chapters", []) if ch.get("paragraphs")]
    for n, ch in enumerate(chapters, 1):
        if n > 1:
            flow.append(PageBreak())
        flow.append(Paragraph(f"CHAPTER {n}", kicker))
        head = Paragraph(x(ch["title"]), h1)
        head.toc = (0, f"{n}. {ch['title']}", f"ch{n}")
        flow.append(head)
        new_section = True
        for p in ch["paragraphs"]:
            if p.get("heading"):
                flow.append(Paragraph(x(p["heading"]), h2))
                new_section = True
            refs = sorted({numbers[sid] for c in p["cites"] if (sid := mat.source_of(c)) in numbers})
            mark = f" <super>[{', '.join(map(str, refs))}]</super>" if refs else ""
            flow.append(Paragraph(x(p["text"]) + mark, first if new_section else body))
            new_section = False
            if p.get("quote_after") and p["quote_after"] in mat.evidence:
                e = mat.evidence[p["quote_after"]]
                sid = e["source_id"]
                flow.append(Paragraph("“" + x(e["quote"]) + "”", quote))
                by = ", ".join(v for v in (clean(e.get("title")), clean(e.get("publisher")), clean(e.get("date"))) if v)
                flow.append(Paragraph(f"- {html.escape(by, quote=False)}"
                                      + (f" [{numbers[sid]}]" if sid in numbers else ""), quote_by))
                new_section = True

    # ---- references
    flow.append(PageBreak())
    head = Paragraph("References", h1)
    head.toc = (0, "References", "refs")
    flow.append(head)
    for sid in order:
        src = mat.sources.get(sid) or {"title": sid}
        bits = [x(src.get("publisher")) if src.get("publisher") else "", f"“{x(src.get('title'))}.”",
                x(src.get("date")) + "." if src.get("date") else ""]
        if src.get("url"):
            u = html.escape(clean(src["url"]))
            bits.append(f"<link href=\"{u}\" color=\"#1a4f8a\">{u}</link>")
        if src.get("archive_url"):
            a = html.escape(clean(src["archive_url"]))
            bits.append(f"Archived copy: <link href=\"{a}\" color=\"#1a4f8a\">{a}</link>")
        if src.get("accessed_at"):
            bits.append(f"Accessed {x(str(src['accessed_at'])[:10])}.")
        flow.append(Paragraph(f"[{numbers[sid]}]&nbsp;&nbsp;" + " ".join(b for b in bits if b), ref))

    path.parent.mkdir(parents=True, exist_ok=True)
    doc.multiBuild(flow)
    return path
