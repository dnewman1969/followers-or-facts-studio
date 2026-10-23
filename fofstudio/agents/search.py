"""Where the agents look. Each finder returns hits: {title, url, snippet, finder}.
Links only ever come from these results - the AI never writes a link itself."""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlparse

from ..config import settings
from . import web

SKIP_DOMAINS = {"facebook.com", "x.com", "twitter.com", "instagram.com", "tiktok.com", "pinterest.com",
                "reddit.com", "quora.com", "youtube.com", "youtu.be", "rumble.com", "bitchute.com",
                "infowars.com", "banned.video", "naturalnews.com", "gab.com", "truthsocial.com"}
COURT = ("courtlistener.com", "uscourts.gov", "supremecourt.gov", "justia.com", "law.cornell.edu",
         "casetext.com", "govinfo.gov/app/details/USCOURTS")
WIRE = ("apnews.com", "reuters.com", "afp.com", "upi.com")
NEWS = ("nytimes.com", "washingtonpost.com", "npr.org", "pbs.org", "bbc.co.uk", "bbc.com", "cnn.com",
        "nbcnews.com", "cbsnews.com", "abcnews.go.com", "theguardian.com", "wsj.com", "latimes.com",
        "usatoday.com", "politico.com", "propublica.org", "theatlantic.com", "newyorker.com", "time.com",
        "chicagotribune.com", "texastribune.org", "statesman.com", "courant.com", "huffpost.com",
        "vox.com", "axios.com", "bloomberg.com", "ctpost.com", "snopes.com", "factcheck.org",
        "politifact.com", "splcenter.org", "adl.org", "mediamatters.org", "rollingstone.com", "wired.com")
ACADEMIC = (".edu", "jstor.org", "doi.org", "nih.gov/pmc", "ncbi.nlm.nih.gov", "sciencedirect.com",
            "nature.com", "arxiv.org", "springer.com", "tandfonline.com")
MUSEUM = (".museum", "si.edu", "loc.gov", "archives.gov")


def domain(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def skip(url: str) -> bool:
    d = domain(url)
    return not url.startswith(("http://", "https://")) or any(d == s or d.endswith("." + s) for s in SKIP_DOMAINS)


def source_type(url: str) -> str:
    """Classify a link the same way the database does (court, gov, wire, journalism...)."""
    d, full = domain(url), url.lower()
    if any(c in full for c in COURT):
        return "court"
    if "archive.org" in d and "/details/" in full and "tv" in full:
        return "archive_audio"
    if any(full.find(m) >= 0 for m in MUSEUM):
        return "museum"
    if d.endswith(".gov") or d.endswith(".mil") or ".gov." in d:
        return "gov"
    if any(d == w or d.endswith("." + w) for w in WIRE):
        return "wire"
    if any(a in full for a in ACADEMIC):
        return "academic"
    if any(d == n or d.endswith("." + n) for n in NEWS):
        return "journalism"
    return "other"


RANK = {"court": 0, "gov": 1, "wire": 2, "academic": 3, "museum": 3, "archive_audio": 3, "journalism": 4,
        "other": 6}


def rank(hit: dict[str, Any]) -> int:
    return RANK.get(source_type(hit["url"]), 6)


# ---------------------------------------------------------------- finders
def web_search(query: str, n: int = 8) -> list[dict[str, Any]]:
    if not settings()["research"]["use_web_search"]:
        return []
    try:
        from ddgs import DDGS
    except ImportError:
        return []
    for attempt, backend in enumerate(("auto", "duckduckgo,bing", "brave,mojeek,wikipedia")):
        try:
            results = DDGS().text(query, max_results=n, backend=backend)
            return [{"title": r.get("title", ""), "url": r.get("href", ""), "snippet": r.get("body", ""),
                     "finder": "web"} for r in results if r.get("href")]
        except Exception:  # noqa: BLE001 - rate limited or blocked: wait and try other engines
            time.sleep(4 * (attempt + 1))
    return []


def wikipedia(query: str, n: int = 3) -> list[dict[str, Any]]:
    try:
        data = web.get_json("https://en.wikipedia.org/w/api.php", {
            "action": "query", "list": "search", "srsearch": query, "format": "json", "srlimit": n})
    except Exception:  # noqa: BLE001
        return []
    return [{"title": h["title"], "url": "https://en.wikipedia.org/wiki/" + h["title"].replace(" ", "_"),
             "snippet": h.get("snippet", ""), "finder": "wikipedia", "map_only": True}
            for h in data.get("query", {}).get("search", [])]


def courtlistener(query: str, n: int = 5) -> list[dict[str, Any]]:
    token = settings()["research"].get("courtlistener_token")
    if not token or web.calls_today("courtlistener") >= 110:  # free accounts get ~125 a day
        return []
    web.count_call("courtlistener")
    try:
        data = web.get_json("https://www.courtlistener.com/api/rest/v4/search/",
                            {"q": query, "type": "o", "order_by": "score desc"},
                            headers={"Authorization": f"Token {token}"})
    except Exception:  # noqa: BLE001
        return []
    out = []
    for r in data.get("results", [])[:n]:
        url = "https://www.courtlistener.com" + r.get("absolute_url", "")
        out.append({"title": r.get("caseName") or r.get("case_name") or "Court record", "url": url,
                    "snippet": (r.get("snippet") or "")[:300], "finder": "courtlistener",
                    "date": r.get("dateFiled")})
    return out


def federal_register(query: str, n: int = 3) -> list[dict[str, Any]]:
    try:
        data = web.get_json("https://www.federalregister.gov/api/v1/documents.json",
                            {"conditions[term]": query, "per_page": n, "order": "relevance"})
    except Exception:  # noqa: BLE001
        return []
    return [{"title": r.get("title", ""), "url": r.get("html_url", ""), "snippet": r.get("abstract") or "",
             "finder": "federalregister", "date": r.get("publication_date")} for r in data.get("results", [])]


def library_of_congress(query: str, n: int = 3) -> list[dict[str, Any]]:
    try:
        data = web.get_json("https://www.loc.gov/search/", {"q": query, "fo": "json", "c": n})
    except Exception:  # noqa: BLE001
        return []
    out = []
    for r in data.get("results", [])[:n]:
        url = r.get("url") or r.get("id")
        if url:
            out.append({"title": r.get("title", ""), "url": url, "snippet": " ".join(r.get("description", []) or [])[:300],
                        "finder": "loc", "date": r.get("date")})
    return out


def fact_checks(query: str, n: int = 4) -> list[dict[str, Any]]:
    key = settings()["research"].get("factcheck_key")
    if not key:
        return []
    try:
        data = web.get_json("https://factchecktools.googleapis.com/v1alpha1/claims:search",
                            {"query": query, "languageCode": "en", "pageSize": n, "key": key})
    except Exception:  # noqa: BLE001
        return []
    out = []
    for c in data.get("claims", []):
        for review in c.get("claimReview", [])[:1]:
            out.append({"title": review.get("title") or c.get("text", ""), "url": review.get("url", ""),
                        "snippet": f"{review.get('publisher', {}).get('name', '')}: {review.get('textualRating', '')}",
                        "finder": "factcheck"})
    return out


FINDERS = [web_search, courtlistener, federal_register, library_of_congress, fact_checks, wikipedia]


def search_all(query: str) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for finder in FINDERS:
        hits += finder(query)
    seen, out = set(), []
    for h in hits:
        u = h["url"].split("#")[0]
        if u in seen or skip(u):
            continue
        seen.add(u)
        h["url"] = u
        out.append(h)
    return sorted(out, key=rank)
