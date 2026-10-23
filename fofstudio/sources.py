"""Save copies of sources, pull out their text, and check quotes word for word.

The rule from Nimrod's Tower and the Scout workflow: the AI never originates a
citation. A quote is usable only if it appears, word for word, in a saved copy
of a source that is in the database.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import requests

from . import db
from .config import Paths
from .util import normalize_for_match, sha256_file, utc_now, write_text



class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "nav", "footer", "header", "aside", "svg", "form"}
    BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section",
             "article", "blockquote", "pre"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in self.SKIP:
            self.skip += 1
        if tag == "title":
            self._in_title = True
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        if tag == "title":
            self._in_title = False
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        if not self.skip:
            self.parts.append(data)

    def text(self) -> str:
        raw = "".join(self.parts)
        lines = [re.sub(r"[ \t ]+", " ", ln).strip() for ln in raw.splitlines()]
        out, blank = [], 0
        for ln in lines:
            if ln:
                out.append(ln)
                blank = 0
            elif not blank:
                out.append("")
                blank = 1
        return "\n".join(out).strip()


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    return parser.text()


def pdf_to_text(path: Path) -> str | None:
    try:
        from pypdf import PdfReader  # optional dependency
    except ImportError:
        return None
    try:
        reader = PdfReader(str(path))
        return "\n\n".join((page.extract_text() or "") for page in reader.pages).strip()
    except Exception:  # noqa: BLE001 - a broken PDF just has no text
        return None


def fetch_source(source_id: str, refresh: bool = False, timeout: float = 40) -> dict[str, Any]:
    """Download one source's URL, save the copy and its text, record when we looked."""
    row = db.one("SELECT * FROM source WHERE source_id=?", (source_id,))
    if not row:
        return {"source_id": source_id, "ok": False, "error": "not in database"}
    if row["text_path"] and not refresh and Path(row["text_path"]).exists():
        return {"source_id": source_id, "ok": True, "cached": True}
    url = (row["url"] or "").strip()
    if not url.startswith(("http://", "https://")):
        return {"source_id": source_id, "ok": False, "error": "no web address"}

    folder = Paths().ensure().source_copies / source_id
    folder.mkdir(parents=True, exist_ok=True)
    stamp = utc_now().replace(":", "")[:15]
    from .agents import web  # honest User-Agent, robots.txt and one request at a time per site
    if not web.allowed(url):
        return {"source_id": source_id, "ok": False, "error": "the site asks robots not to read this page"}
    try:
        web._wait_turn(web.urlparse(url).netloc)
        r = web.session().get(url, timeout=timeout, allow_redirects=True)
    except requests.RequestException as exc:
        db.execute("UPDATE source SET accessed_at=?, http_status=? WHERE source_id=?",
                   (utc_now(), None, source_id))
        return {"source_id": source_id, "ok": False, "error": str(exc)[:200]}

    ctype = r.headers.get("content-type", "").lower()
    if "pdf" in ctype or url.lower().endswith(".pdf"):
        copy = folder / f"{stamp}.pdf"
        copy.write_bytes(r.content)
        text = pdf_to_text(copy)
    else:
        copy = folder / f"{stamp}.html"
        copy.write_bytes(r.content)
        text = html_to_text(r.text)
    text_path = None
    if text:
        text_path = write_text(folder / f"{stamp}.txt", f"SOURCE {source_id}\nURL {url}\n"
                               f"FETCHED {utc_now()}\nHTTP {r.status_code}\n\n{text}")
    db.execute("""UPDATE source SET local_copy_path=?, text_path=?, accessed_at=?, http_status=?,
                  content_sha256=? WHERE source_id=?""",
               (str(copy), str(text_path) if text_path else None, utc_now(), r.status_code,
                sha256_file(copy), source_id))
    ok = r.status_code < 400 and bool(text)
    return {"source_id": source_id, "ok": ok, "status": r.status_code,
            "error": None if ok else f"HTTP {r.status_code}" if r.status_code >= 400 else
            "no readable text (install pypdf for PDFs)"}


def source_text(source_id: str) -> str | None:
    row = db.one("SELECT text_path FROM source WHERE source_id=?", (source_id,))
    if not row or not row["text_path"] or not Path(row["text_path"]).exists():
        return None
    return Path(row["text_path"]).read_text(encoding="utf-8", errors="replace")


def quote_in_text(quote: str, text: str) -> bool:
    q = normalize_for_match(quote).strip(" .\"'")
    return len(q) >= 8 and q in normalize_for_match(text)


def add_excerpt(source_id: str, text: str, claim_id: str | None = None) -> tuple[int, bool]:
    """Store an excerpt. It is marked verified only if found word for word in the saved copy."""
    full = source_text(source_id)
    verified = bool(full and quote_in_text(text, full))
    existing = db.one("SELECT excerpt_id, verified FROM source_excerpt WHERE source_id=? AND text=?",
                      (source_id, text.strip()))
    if existing:
        return existing["excerpt_id"], bool(existing["verified"])
    with db.transaction() as con:
        cur = con.execute(
            "INSERT INTO source_excerpt(source_id,claim_id,text,verified,verified_at,added_at) "
            "VALUES (?,?,?,?,?,?)",
            (source_id, claim_id, text.strip(), int(verified), utc_now() if verified else None,
             utc_now()))
        return cur.lastrowid, verified


def relevant_passages(text: str, query: str, limit_chars: int = 7000) -> str:
    """Pick the paragraphs that share the most words with the claim (keeps prompts small)."""
    words = {w for w in re.findall(r"[a-z]{4,}", query.lower())}
    paras = [p.strip() for p in re.split(r"\n\s*\n|\n", text) if len(p.strip()) > 40]
    scored = sorted(((len(words & set(re.findall(r"[a-z]{4,}", p.lower()))), i, p)
                     for i, p in enumerate(paras)), reverse=True)
    chosen, total = [], 0
    for score, i, p in scored:
        if score == 0 or total + len(p) > limit_chars:
            continue
        chosen.append((i, p))
        total += len(p)
    return "\n\n".join(p for _, p in sorted(chosen))
