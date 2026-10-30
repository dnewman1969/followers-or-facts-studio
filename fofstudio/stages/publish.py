"""Stages 10-11 - Package (title, description, chapters, sources, thumbnail, search tags) and Upload.

Upload is done on YouTube's own upload page in your browser (Dave, 2026-10-30: no Google setup). The Studio
opens the page and puts the title, description and tags one click away (publishkit.py); you paste the
video's link back and the Upload step is marked done.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from .. import cards, db
from ..config import settings
from ..episode import Episode
from ..scriptfmt import parse
from ..util import StageError, read_json, utc_now, write_json, write_text
from .base import BLOCK, OK, WARN, Check, Context
from .common import cited_sources, credit_line, source_line
from .storyboard import shots as board_shots

log = logging.getLogger(__name__)



def _stamp(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def _chapter_name(scene: dict[str, Any]) -> str:
    text = scene["on_screen_text"] if scene["on_screen_text"] not in ("", "-") else scene["narration"]
    words = text.replace("\n", " ").split()
    return " ".join(words[:7]).rstrip(".,;:") or scene["scene_id"]


SEARCH_SCHEMA = {"type": "object", "properties": {
    "search_phrases": {"type": "array", "minItems": 10, "maxItems": 40, "items": {"type": "string"}},
    "hashtags": {"type": "array", "maxItems": 3, "items": {"type": "string"}}},
    "required": ["search_phrases", "hashtags"]}


def _basics(ep: Episode, story: dict[str, Any]) -> dict[str, list[str]]:
    """What this video is about, straight from the database: people, groups, claims, the story's trick."""
    from .. import techniques
    from .script import selected_packet
    arc = db.one("SELECT title FROM arc WHERE arc_id=?", (ep.info.get("arc_id"),)) or {}
    claims = [r["short_title"] for r in db.rows(
        "SELECT c.short_title FROM project_claim pc JOIN claim c USING(claim_id) WHERE pc.project_id=? "
        "ORDER BY pc.order_no", (ep.project_id,))]
    try:
        ids = [c["claim_id"] for c in selected_packet(ep, check=False)["claims"]]
    except StageError:
        ids = []
    people, orgs = [], []
    if ids:
        marks = ",".join("?" * len(ids))
        people = [r["name"] for r in db.rows(
            f"""SELECT p.name, COUNT(*) n FROM claim_entity ce JOIN person p ON p.person_id=ce.entity_id
                WHERE ce.entity_type='person' AND ce.claim_id IN ({marks})
                  AND ce.link_role IN ('said_it','amplified','benefited','platformed')
                GROUP BY p.person_id ORDER BY n DESC LIMIT 4""", tuple(ids))]
        orgs = [r["name"] for r in db.rows(
            f"""SELECT o.name, COUNT(*) n FROM claim_entity ce JOIN organization o ON o.org_id=ce.entity_id
                WHERE ce.entity_type IN ('org','organization') AND ce.claim_id IN ({marks})
                GROUP BY o.org_id ORDER BY n DESC LIMIT 3""", tuple(ids))] if _has_table("organization") else []
    tricks = [t.name for t in (techniques.get(k) for k in story.get("techniques", [])) if t]
    return {"arc": [arc["title"].split(":")[0][:60]] if arc.get("title") else [], "claims": claims,
            "people": people, "orgs": orgs, "tricks": tricks}


def _has_table(name: str) -> bool:
    return bool(db.one("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)))


def keywords(ep: Episode, story: dict[str, Any], title: str = "", ask_ai: bool = True) -> list[str]:
    """Lots of search tags (Dave, 2026-10-30: "we want this to be found in search"): the phrases people
    actually type into YouTube about this subject (the local AI writes them from the video's own subject,
    claims and people), then the names, claims and the channel's own tags, as many as fit in YouTube's 500
    characters. Only true, on-topic terms: YouTube treats misleading or off-topic tags as spam."""
    from ..youtube import sanitize_tags
    b = _basics(ep, story)
    phrases: list[str] = []
    if ask_ai:
        try:
            from ..llm import Ollama
            ans = Ollama(job="stories").chat_json([
                {"role": "system", "content": (
                    "You write YouTube search tags for a fact-check documentary. List 25-40 short search phrases "
                    "(2-5 words, lower case) that real people type into YouTube when looking for THIS subject: the "
                    "people's names with the topic, the claim in plain words, questions like 'was ... real' or "
                    "'is ... true', 'debunked', 'explained', the year or event, and common misspellings of names. "
                    "Every phrase must be honestly about this video. No other channels, shows, brands or creators; "
                    "no clickbait that the video doesn't deliver. Also give up to 3 hashtags (no spaces).")},
                {"role": "user", "content": json.dumps({"title": title or ep.title, "subject": b["arc"],
                                                        "claims": b["claims"][:8], "people": b["people"],
                                                        "organisations": b["orgs"], "lesson": b["tricks"],
                                                        "logline": story.get("logline") or story.get("hook") or ""},
                                                       ensure_ascii=False)}],
                SEARCH_SCHEMA, lenient=True, temperature=0.4)
            phrases = [str(x).strip().lower() for x in ans.get("search_phrases") or [] if 1 < len(str(x).split()) <= 6]
        except Exception as exc:  # noqa: BLE001 - the tags from the database are still written; logged
            log.warning("The local AI couldn't write search phrases (%s); using the database tags only.", exc)
    names = b["people"] + b["orgs"]
    tags = [*b["arc"], *names[:3], *phrases[:12], *[c[:60] for c in b["claims"][:4]],
            *[f"{n} {w}" for n in b["people"][:2] for w in ("debunked", "fact check")],
            "fact check", "Followers or Facts", *phrases[12:], *b["tricks"], "debunked", "misinformation",
            "conspiracy theories explained", "media literacy", "critical thinking", "Professor Owlbert",
            *names[3:], *[c[:60] for c in b["claims"][4:8]],
            *([story["thumbnail_words"].title()] if story.get("thumbnail_words") else []), "history", "documentary"]
    from .. import promptcheck      # no brand, show or artist names (the check below would block them anyway)
    return sanitize_tags([t for t in tags if not promptcheck.found(t)])


def hashtags(tags: list[str]) -> list[str]:
    """Three hashtags for above the title: #FactCheck plus two from the subject."""
    out = ["#FactCheck"]
    for t in tags:
        h = "#" + "".join(w[:1].upper() + w[1:] for w in re.findall(r"[A-Za-z0-9]+", t))
        if 3 < len(h) <= 30 and h.lower() not in {x.lower() for x in out} and h.lower() != "#followersorfacts":
            out.append(h)
        if len(out) == 3:
            break
    return out


def package(ctx: Context) -> None:
    ep = ctx.episode
    timeline = read_json(ep.path("render", "timeline.json"))
    if not timeline or timeline.get("draft"):
        raise StageError("Approve a full (not draft) render first.")
    script = parse(ep.path("script.md").read_text(encoding="utf-8"))
    title = (ctx.options.get("title") or script["title"] or ep.title)[:100]
    scenes = {s["scene_id"]: s for s in script["scenes"]}

    hook = ""
    if script["scenes"]:
        sentences = script["scenes"][0]["narration"].split(". ")
        hook = ". ".join(sentences[:2]).strip()
        if hook and not hook.endswith((".", "?", "!")):
            hook += "."

    chapters = []
    for ch in timeline["chapters"]:
        name = {"CREDITS": "Sources and credits", "OUTRO": "Sources and credits", "INTRO": "Intro"}.get(
            ch["scene_id"]) or (_chapter_name(scenes[ch["scene_id"]]) if ch["scene_id"] in scenes else ch["scene_id"])
        if chapters and ch["start"] - chapters[-1]["start"] < 10:
            continue
        chapters.append({"start": 0.0 if not chapters else ch["start"], "name": name})

    head = [hook, ""]
    if len(chapters) >= 3:
        head += ["Chapters:"] + [f"{_stamp(c['start'])} {c['name']}" for c in chapters] + [""]
    real = [sh["image"] for sh in board_shots(ep) if sh.get("image", {}).get("real")]
    media = ["", "Image credits:"] + list(dict.fromkeys(
        f"{c['credit']} - {c.get('source_url', '')}" + (f" ({c['licence_url']})" if c.get("licence_url") else "")
        for c in real)) if real else []
    recreated = any(sh.get("image", {}).get("recreation") for sh in board_shots(ep))
    tail = media + ["", credit_line(ep), "",
            "Illustrations are made with AI on our own computer and are labelled on screen. Quotes are "
            "shown exactly as they appear in the sources. Owlbert is a cartoon with a synthetic voice."
            + (" Scenes marked RE-CREATION are illustrations of real events, not footage." if recreated else "")
            + (" Caricatures are satirical cartoon illustrations of the documented public conduct of public "
               "figures, not real images; every claim about them is sourced below."
               if any(sh.get("kind") == "caricature" for sh in board_shots(ep)) else ""),
            "Spotted a mistake? Tell us in the comments. Corrections are pinned and logged publicly."]
    from .stories import chosen
    story = chosen(ep) or {}
    ctx.progress("Writing lots of search tags", 40)
    tags = keywords(ep, story, title)
    tail += ["", " ".join(hashtags(tags))]
    description, left_out = fit_description(head, proof_links(ep), tail)
    proof = proof_links(ep)
    write_text(ep.path("publish", "proof-links.txt"), "\n".join(
        f"{n}. {x['line']}\n   {x.get('url') or ''}" + (f"\n   Archived: {x['archive_url']}" if x.get("archive_url") else "")
        for n, x in enumerate(proof, 1)))
    if left_out:
        ctx.log(f"The description was full, so {left_out} proof link(s) went into proof-links.txt "
                "(paste them into the pinned comment).")

    thumb_words = (ctx.options.get("thumbnail_text") or story.get("thumbnail_words")
                   or " ".join(title.split()[:4]))
    first_ai = next((s for s in board_shots(ep)
                     if s["type"] == "ai_image" and s.get("kind") != "caricature" and s.get("image", {}).get("raw")),
                    None)
    background = ep.abs(first_ai["image"]["raw"]) if first_ai else None
    verdict = ctx.options.get("verdict", "FALSE")
    cards.thumbnail(thumb_words, ep.path("publish", "thumbnail.png"), background, verdict)

    pinned = ("Every claim in this video links to a primary source in the description. "
              "If we got something wrong, reply here with a source and we'll correct it "
              "publicly. Be kind to people who believed this; aim at the people who sold it.")
    meta = {"title": title, "description": description, "tags": tags,
            "category_id": settings()["youtube"]["category_id"],
            "privacy": settings()["youtube"]["privacy"],
            "made_for_kids": bool(settings()["youtube"]["made_for_kids"]),
            "contains_synthetic_media": True, "chapters": chapters,
            "video": timeline["output"], "captions": timeline.get("srt"),
            "thumbnail": "publish/thumbnail.png", "made_at": utc_now()}
    write_json(ep.path("publish", "metadata.json"), meta)
    write_text(ep.path("publish", "description.txt"), description)
    write_text(ep.path("publish", "pinned-comment.txt"), pinned)
    ctx.log("Package ready: title, description, chapters, sources, thumbnail, pinned comment.")


LIMIT = 4900  # YouTube allows 5,000 characters


def fit_description(head: list[str], proof: list[dict[str, Any]], tail: list[str]) -> tuple[str, int]:
    """Fit the proof list between the opening and the credits. If it's too long, first drop the
    archive copies of the later links, then the later links themselves - never the credit lines."""
    fixed = len("\n".join(head + tail)) + 120

    def block(items, archived):
        out = ["THE PROOF (click to check it yourself; archived copies never disappear):"]
        for n, s in enumerate(items, 1):
            out.append(f"{n}. {s['line']}")
            if s.get("url"):
                out.append(f"   {s['url']}")
            if s.get("archive_url") and (n <= archived or not s.get("url")):
                out.append(f"   Archived: {s['archive_url']}")
        return out

    for keep in range(len(proof), -1, -1):
        for archived in range(keep, -1, -1):
            body = block(proof[:keep], archived)
            if keep < len(proof):
                body.append(f"...and {len(proof) - keep} more sources in the pinned comment.")
            if fixed + len("\n".join(body)) <= LIMIT:
                return "\n".join(head + body + tail).strip(), len(proof) - keep
    return "\n".join(head + tail).strip()[:LIMIT], len(proof)


def proof_links(ep: Episode) -> list[dict[str, Any]]:
    """The evidence you kept on the Research page, one line per source, cited ones first."""
    packet = read_json(ep.path("research.json")) or {}
    cited = [x["source_id"] for x in cited_sources(ep)]
    seen: dict[str, dict[str, Any]] = {}
    for e in packet.get("evidence", []):
        if not e.get("include") or e.get("type") == "kf_index" or not (e.get("url") or e.get("archive_url")):
            continue
        sid = e["source_id"]
        if sid in seen:
            continue
        bits = [e.get("title") or sid]
        if e.get("publisher"):
            bits.append(e["publisher"])
        if e.get("date"):
            bits.append(str(e["date"]))
        seen[sid] = {"source_id": sid, "line": " - ".join(bits), "url": e.get("url"),
                     "archive_url": e.get("archive_url")}
    for sid in cited:  # anything the script cites that isn't in the evidence list
        if sid not in seen:
            row = next((x for x in cited_sources(ep) if x["source_id"] == sid), None)
            if row:
                seen[sid] = {"source_id": sid, "line": source_line(row), "url": row.get("url"),
                             "archive_url": row.get("archive_url")}
    order = {sid: i for i, sid in enumerate(cited)}
    rank = {"court": 0, "gov": 1, "wire": 2, "academic": 3, "museum": 3, "archive_audio": 3, "journalism": 4}
    types = {e["source_id"]: e.get("type") for e in packet.get("evidence", [])}
    return sorted(seen.values(), key=lambda x: (order.get(x["source_id"], 10_000),
                                                rank.get(types.get(x["source_id"]), 6)))


def check_package(ep: Episode) -> list[Check]:
    meta = read_json(ep.path("publish", "metadata.json"))
    if not meta:
        return [Check(BLOCK, "Not packaged yet.")]
    out = []
    if len(meta["title"]) > 100:
        out.append(Check(BLOCK, "Title is over 100 characters."))
    if not ep.path("publish", "thumbnail.png").exists():
        out.append(Check(BLOCK, "Thumbnail missing."))
    if "THE PROOF" not in meta["description"] and "Sources" not in meta["description"]:
        out.append(Check(BLOCK, "Description has no sources list."))
    if "Knowledge Fight" not in meta["description"]:
        out.append(Check(BLOCK, "Description is missing the Knowledge Fight credit."))
    nourl = [s["source_id"] for s in cited_sources(ep) if not s.get("url")]
    if nourl:
        out.append(Check(WARN, f"Sources without a link in the description: {', '.join(nourl)}"))
    if len(meta.get("chapters", [])) < 3:
        out.append(Check(WARN, "Fewer than 3 chapters, so YouTube won't show chapters."))
    from .. import promptcheck   # brand, show and artist names: trademark and false-endorsement risk
    named = promptcheck.found(f"{meta['title']} {' '.join(meta.get('tags', []))}")
    if named:
        out.append(Check(BLOCK, f"The title or tags name a brand, show or artist ({', '.join(named)}). Describe "
                                "the look in your own words instead; a 'X style' title can read as an endorsement."))
    in_desc = promptcheck.found(meta["description"])
    if in_desc:
        out.append(Check(WARN, f"The description mentions {', '.join(in_desc)}. Fine if a source is about them; "
                               "never as 'in the style of'."))
    out.append(Check(OK, "Read description.txt and look at thumbnail.png, then approve."))
    return out


def upload(ctx: Context) -> None:
    """Uploading happens in your browser (Publish → Upload on YouTube), so there's nothing to run here."""
    if read_json(ctx.episode.path("publish", "upload.json")):
        ctx.log("Already on YouTube.")
        return
    raise StageError("Upload in your browser: Publish → Upload on YouTube opens YouTube's upload page with the "
                     "title, description and tags ready to paste. Then paste the video's link back.")


def check_upload(ep: Episode) -> list[Check]:
    info = read_json(ep.path("publish", "upload.json"))
    if not info:
        return [Check(BLOCK, "Not uploaded yet.")]
    studio = info.get("studio_url") or f"https://studio.youtube.com/video/{info['youtube_id']}/edit"
    return [Check(OK, f"On YouTube as {info['privacy']}: https://youtu.be/{info['youtube_id']}. Check YouTube's "
                      f"checks in YouTube Studio ({studio}), pin the comment, then make it public.")]
