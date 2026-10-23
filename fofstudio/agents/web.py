"""Polite downloading: one request at a time per site, robots.txt respected, everything cached,
and the Wayback Machine used when a page is gone."""

from __future__ import annotations

import hashlib
import json
import threading
import time
import urllib.robotparser
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import requests

from .. import db
from ..config import Paths, settings
from ..sources import html_to_text, pdf_to_text
from ..util import utc_now, write_text

_last_hit: dict[str, float] = {}
_robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
_lock = threading.Lock()
PER_HOST_DELAY = 1.5


def user_agent() -> str:
    contact = settings()["research"].get("contact_email") or ""
    return "FollowersOrFactsStudio/0.2 (fact-check research archive" + (f"; {contact}" if contact else "") + ")"


def session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = user_agent()
    return s


def count_call(provider: str) -> int:
    day = date.today().isoformat()
    with db.transaction() as con:
        con.execute("INSERT INTO api_usage(day, provider, calls) VALUES (?,?,1) "
                    "ON CONFLICT(day, provider) DO UPDATE SET calls = calls + 1", (day, provider))
        return con.execute("SELECT calls FROM api_usage WHERE day=? AND provider=?", (day, provider)).fetchone()[0]


def calls_today(provider: str) -> int:
    row = db.one("SELECT calls FROM api_usage WHERE day=? AND provider=?", (date.today().isoformat(), provider))
    return row["calls"] if row else 0


def _wait_turn(host: str) -> None:
    with _lock:
        wait = PER_HOST_DELAY - (time.time() - _last_hit.get(host, 0))
        if wait > 0:
            time.sleep(wait)
        _last_hit[host] = time.time()


def allowed(url: str) -> bool:
    p = urlparse(url)
    base = f"{p.scheme}://{p.netloc}"
    if base not in _robots:
        rp = urllib.robotparser.RobotFileParser()
        try:
            r = session().get(base + "/robots.txt", timeout=10)
            if r.status_code >= 400:
                _robots[base] = None
            else:
                rp.parse(r.text.splitlines())
                _robots[base] = rp
        except requests.RequestException:
            _robots[base] = None
    rp = _robots[base]
    return True if rp is None else rp.can_fetch(user_agent(), url)


def extract_text(raw: bytes, content_type: str, url: str, path: Path) -> str | None:
    if "pdf" in content_type or url.lower().endswith(".pdf"):
        return pdf_to_text(path)
    html = raw.decode("utf-8", errors="replace")
    try:
        import trafilatura
        text = trafilatura.extract(html, url=url, include_comments=False, include_tables=True,
                                   favor_recall=True)
        if text and len(text) > 200:
            return text
    except Exception:  # noqa: BLE001 - fall back to the simple extractor
        pass
    return html_to_text(html)


def fetch(url: str, timeout: float = 40) -> dict[str, Any]:
    """Download a page once and keep it. Returns {ok, url, final_url, status, text, path, via}."""
    cached = db.one("SELECT * FROM web_cache WHERE url=?", (url,))
    if cached and cached["text_path"] and Path(cached["text_path"]).exists():
        return {"ok": True, "url": url, "final_url": cached["final_url"], "status": cached["status"],
                "text": Path(cached["text_path"]).read_text(encoding="utf-8", errors="replace"),
                "path": cached["path"], "via": cached["via"], "cached": True}
    if not allowed(url):
        return {"ok": False, "url": url, "error": "the site asks robots not to read this page"}
    _wait_turn(urlparse(url).netloc)
    try:
        r = session().get(url, timeout=timeout, allow_redirects=True)
    except requests.RequestException as exc:
        return {"ok": False, "url": url, "error": str(exc)[:200]}
    if r.status_code >= 400:
        return {"ok": False, "url": url, "status": r.status_code, "error": f"HTTP {r.status_code}"}
    return _store(url, r.url, r.status_code, r.headers.get("content-type", "").lower(), r.content, "web")


def _store(url: str, final_url: str, status: int, ctype: str, raw: bytes, via: str) -> dict[str, Any]:
    key = hashlib.sha1(url.encode()).hexdigest()[:16]
    folder = Paths().ensure().root / "web-cache" / key[:2]
    folder.mkdir(parents=True, exist_ok=True)
    ext = ".pdf" if "pdf" in ctype or final_url.lower().endswith(".pdf") else ".html"
    path = folder / f"{key}{ext}"
    path.write_bytes(raw)
    text = extract_text(raw, ctype, final_url, path) or ""
    text_path = None
    if text.strip():
        text_path = write_text(folder / f"{key}.txt", text)
    db.execute("INSERT OR REPLACE INTO web_cache VALUES (?,?,?,?,?,?,?,?)",
               (url, utc_now(), status, ctype, str(path), str(text_path) if text_path else None, final_url, via))
    return {"ok": bool(text.strip()), "url": url, "final_url": final_url, "status": status, "text": text,
            "path": str(path), "via": via, "error": None if text.strip() else "no readable text"}


# ---------------------------------------------------------------- Wayback Machine
def wayback_closest(url: str, timestamp: str | None = None) -> str | None:
    """The archived copy closest to a date (or the newest), as a web.archive.org link."""
    params = {"url": url}
    if timestamp:
        params["timestamp"] = timestamp
    try:
        _wait_turn("archive.org")
        r = session().get("https://archive.org/wayback/available", params=params, timeout=30)
        snap = r.json().get("archived_snapshots", {}).get("closest")
        if snap and snap.get("available") and str(snap.get("status", "200")).startswith("2"):
            return snap["url"].replace("http://", "https://", 1)
    except (requests.RequestException, ValueError):
        pass
    return None


def fetch_via_wayback(url: str) -> dict[str, Any]:
    snap = wayback_closest(url)
    if not snap:
        return {"ok": False, "url": url, "error": "no Wayback Machine copy"}
    # "id_" after the timestamp returns the page as archived, without the Wayback toolbar
    raw_url = snap.replace("/web/", "/web/", 1)
    parts = raw_url.split("/")
    try:
        i = parts.index("web") + 1
        parts[i] = parts[i] + "id_"
        raw_url = "/".join(parts)
    except ValueError:
        pass
    _wait_turn("web.archive.org")
    try:
        r = session().get(raw_url, timeout=60)
    except requests.RequestException as exc:
        return {"ok": False, "url": url, "error": str(exc)[:200]}
    if r.status_code >= 400:
        return {"ok": False, "url": url, "error": f"Wayback HTTP {r.status_code}"}
    result = _store(url, snap, r.status_code, r.headers.get("content-type", "").lower(), r.content, "wayback")
    result["archive_url"] = snap
    return result


def save_page_now(url: str) -> str | None:
    """Ask the Wayback Machine to keep a copy, so the link in the description never dies."""
    cfg = settings()["research"]
    s = session()
    try:
        _wait_turn("web.archive.org-save")
        if cfg.get("archive_access_key") and cfg.get("archive_secret_key"):
            s.headers["Authorization"] = f"LOW {cfg['archive_access_key']}:{cfg['archive_secret_key']}"
            s.headers["Accept"] = "application/json"
            r = s.post("https://web.archive.org/save", data={"url": url}, timeout=60)
            job = r.json().get("job_id")
            for _ in range(20):
                if not job:
                    break
                time.sleep(4)
                st = s.get(f"https://web.archive.org/save/status/{job}", timeout=30).json()
                if st.get("status") == "success":
                    return f"https://web.archive.org/web/{st['timestamp']}/{st['original_url']}"
                if st.get("status") == "error":
                    break
        else:
            r = s.get("https://web.archive.org/save/" + quote(url, safe=":/?=&%"), timeout=90,
                      allow_redirects=True)
            if "/web/" in r.url:
                return r.url
    except (requests.RequestException, ValueError, KeyError):
        pass
    return wayback_closest(url)


def get_json(url: str, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None,
             host_key: str | None = None, timeout: float = 30) -> Any:
    _wait_turn(host_key or urlparse(url).netloc)
    s = session()
    if headers:
        s.headers.update(headers)
    r = s.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)
