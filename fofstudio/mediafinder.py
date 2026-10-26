"""Real pictures of the people, places and things in a story, used only with a licence we can prove.

From the research "Bestseller book craft for nonfiction" (real media and re-creations):
  * search order: Wikimedia Commons (public domain, including US government works, and CC0 / CC BY /
    CC BY-SA), then Openverse with its commercial-use filter (its licence is re-read from the result);
  * allowed licences only: public domain, CC0, CC BY, CC BY-SA. Non-commercial (NC), no-derivatives (ND),
    "all rights reserved" and unknown licences are refused;
  * news agencies are blocked (Getty, AP, Reuters, AFP, Shutterstock...), and so is any file whose credit
    names one;
  * never real pictures of victims or private people (the caller passes role), and none at all on
    careful topics;
  * every picture keeps a provenance record (where it came from, author, licence, when) and gets a credit
    line on screen and in the description.
When nothing usable is found, the storyboard paints a re-creation instead, stamped "RE-CREATION" (never
photo-real people). Not legal advice: see the lawyer questions in that report.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .config import settings
from .util import StageError, utc_now

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
OPENVERSE_API = "https://api.openverse.org/v1/images/"
BLOCKED = ("gettyimages", "getty images", "apnews", "associated press", "ap photo", "reuters", "afp", "agence france",
           "shutterstock", "alamy", "corbis", "epa images", "zuma press", "imago", "dreamstime", "istock")
ALLOWED_ROLES = {"place", "object", "event", "document", "public_figure", "generic"}


@dataclass
class Candidate:
    title: str
    file_url: str
    page_url: str
    licence: str
    licence_url: str
    author: str
    source: str
    width: int = 0
    height: int = 0
    notes: list[str] = field(default_factory=list)

    def credit(self) -> str:
        who = self.author or "Unknown author"
        return f"{'Image' if self.source else 'Image'}: {who} / {self.licence} / {self.source}"


def licence_ok(name: str) -> tuple[bool, str]:
    """(allowed, normalised name). Public domain, CC0, CC BY, CC BY-SA only."""
    n = (name or "").strip().lower().replace("_", " ").replace("-", " ")
    if not n:
        return False, "unknown"
    if " nc" in f" {n}" or "noncommercial" in n or "non commercial" in n or " nd" in f" {n}" or "noderiv" in n:
        return False, name
    if "public domain" in n or n in ("pd", "pdm", "pdm 1.0") or n.startswith("pd ") or "pd us" in n or \
            "pd usgov" in n or "us government" in n:
        return True, "Public domain"
    if n.startswith("cc0") or n == "cc zero":
        return True, "CC0"
    m = re.match(r"cc by( sa)?(?: (\d\.\d))?", n)
    if m:
        return True, "CC BY" + (" SA" if m.group(1) else "") + (f" {m.group(2)}" if m.group(2) else "")
    return False, name


def blocked(*texts: str) -> bool:
    low = " ".join(t or "" for t in texts).lower()
    return any(b in low for b in BLOCKED)


def _clean_html(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()


def _get_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
    from .agents import web
    s = web.session()
    web._wait_turn(urlparse(url).netloc)
    try:
        r = s.get(url, params=params, timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception as exc:  # noqa: BLE001 - a search that fails just finds nothing; the caller says so
        raise StageError(f"Couldn't search {urlparse(url).netloc}: {exc}")


def search_commons(query: str, limit: int = 12) -> list[Candidate]:
    data = _get_json(COMMONS_API, {
        "action": "query", "format": "json", "generator": "search", "gsrsearch": f"{query} filetype:bitmap",
        "gsrnamespace": 6, "gsrlimit": limit, "prop": "imageinfo", "iiprop": "url|extmetadata|size",
        "iiurlwidth": 1920})
    out = []
    for page in (data.get("query") or {}).get("pages", {}).values():
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        val = lambda k: _clean_html((meta.get(k) or {}).get("value", ""))  # noqa: E731
        out.append(Candidate(title=page.get("title", "").replace("File:", ""), file_url=info.get("thumburl") or info.get("url", ""),
                             page_url=info.get("descriptionurl", ""), licence=val("LicenseShortName"),
                             licence_url=val("LicenseUrl"), author=val("Artist") or val("Credit"),
                             source="Wikimedia Commons", width=int(info.get("width") or 0),
                             height=int(info.get("height") or 0),
                             notes=[val("Credit"), val("UsageTerms"), val("ImageDescription")[:300]]))
    return out


def search_openverse(query: str, limit: int = 20) -> list[Candidate]:
    data = _get_json(OPENVERSE_API, {"q": query, "license_type": "commercial,modification",
                                     "page_size": min(20, limit), "mature": "false"})
    out = []
    for r in data.get("results", []):
        lic = f"CC {r.get('license', '').upper()} {r.get('license_version') or ''}".strip()
        if r.get("license") in ("pdm", "cc0"):
            lic = "Public domain" if r["license"] == "pdm" else "CC0"
        out.append(Candidate(title=r.get("title") or "", file_url=r.get("url") or "",
                             page_url=r.get("foreign_landing_url") or "", licence=lic,
                             licence_url=r.get("license_url") or "", author=r.get("creator") or "",
                             source=f"{r.get('source') or 'Openverse'} via Openverse",
                             width=int(r.get("width") or 0), height=int(r.get("height") or 0)))
    return out


def usable(c: Candidate) -> tuple[bool, str]:
    ok, name = licence_ok(c.licence)
    if not ok:
        return False, f"licence not allowed ({c.licence or 'unknown'})"
    if blocked(c.author, c.page_url, c.file_url, *c.notes):
        return False, "news-agency picture"
    if c.width and c.width < 640:
        return False, "too small"
    c.licence = name
    return True, ""


def find(query: str, role: str = "generic", careful: bool = False) -> tuple[Candidate | None, list[str]]:
    """The first usable picture for this search, or None with the reasons nothing was used."""
    why: list[str] = []
    if role not in ALLOWED_ROLES:
        return None, [f"no real pictures of a {role.replace('_', ' ')}: re-created instead"]
    if careful and role in ("public_figure", "event"):
        return None, ["careful topic: no real pictures of people or the event"]
    cfg = settings().get("media", {})
    for name, fn in (("commons", search_commons), ("openverse", search_openverse)):
        if name not in cfg.get("sources", ["commons", "openverse"]):
            continue
        try:
            found = fn(query)
        except StageError as exc:
            why.append(str(exc))
            continue
        for c in found:
            ok, reason = usable(c)
            if ok:
                return c, why
            why.append(f"{c.title[:40]}: {reason}")
    return None, why or ["nothing found"]


def download(c: Candidate, dest: Path) -> dict[str, Any]:
    """Save the picture and its provenance record (dest.json next to it)."""
    from .agents import web
    s = web.session()
    web._wait_turn(urlparse(c.file_url).netloc)
    r = s.get(c.file_url, timeout=60)
    r.raise_for_status()
    suffix = Path(urlparse(c.file_url).path).suffix.lower() or ".jpg"
    dest = dest.with_suffix(suffix if suffix in (".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".gif") else ".jpg")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(r.content)
    record = {**asdict(c), "credit": c.credit(), "path": str(dest), "sha256": hashlib.sha256(r.content).hexdigest(),
              "retrieved_at": utc_now()}
    dest.with_suffix(".json").write_text(json.dumps(record, indent=1), encoding="utf-8")
    return record
