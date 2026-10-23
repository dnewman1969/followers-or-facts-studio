"""Stages 10-11 - Package (title, description, chapters, sources, thumbnail) and Upload.

Upload uses the free YouTube Data API. It always uploads as PRIVATE (or the
privacy in Settings) and marks the video as containing altered/synthetic
media, as YouTube requires for realistic AI content. You flip it public yourself.
Quota: one upload costs about 1,600 of the default 10,000 daily units.
"""

from __future__ import annotations

from typing import Any

from .. import cards, db
from ..config import settings
from ..episode import Episode
from ..scriptfmt import parse
from ..util import StageError, read_json, utc_now, write_json, write_text
from .base import BLOCK, OK, WARN, Check, Context
from .common import cited_sources, credit_line, source_line
from .storyboard import shots as board_shots



def _stamp(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def _chapter_name(scene: dict[str, Any]) -> str:
    text = scene["on_screen_text"] if scene["on_screen_text"] not in ("", "-") else scene["narration"]
    words = text.replace("\n", " ").split()
    return " ".join(words[:7]).rstrip(".,;:") or scene["scene_id"]


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
    tail = ["", credit_line(ep), "",
            "Illustrations are made with AI on our own computer and are labelled on screen. Quotes are "
            "shown exactly as they appear in the sources. Owlbert is a cartoon with a synthetic voice."
            + (" Caricatures are satirical cartoon illustrations of the documented public conduct of public "
               "figures, not real images; every claim about them is sourced below."
               if any(sh.get("kind") == "caricature" for sh in board_shots(ep)) else ""),
            "Spotted a mistake? Tell us in the comments. Corrections are pinned and logged publicly."]
    description, left_out = fit_description(head, proof_links(ep), tail)
    proof = proof_links(ep)
    write_text(ep.path("publish", "proof-links.txt"), "\n".join(
        f"{n}. {x['line']}\n   {x.get('url') or ''}" + (f"\n   Archived: {x['archive_url']}" if x.get("archive_url") else "")
        for n, x in enumerate(proof, 1)))
    if left_out:
        ctx.log(f"The description was full, so {left_out} proof link(s) went into proof-links.txt "
                "(paste them into the pinned comment).")

    arc = db.one("SELECT title FROM arc WHERE arc_id=?", (ep.info.get("arc_id"),)) or {}
    tags = ["fact check", "Followers or Facts", "conspiracy theories", "media literacy",
            "debunk", "history"] + ([arc["title"][:60]] if arc.get("title") else [])

    from .stories import chosen
    story = chosen(ep) or {}
    thumb_words = (ctx.options.get("thumbnail_text") or story.get("thumbnail_words")
                   or " ".join(title.split()[:4]))
    first_ai = next((s for s in ep.storyboard().get("shots", [])
                     if s["type"] == "ai_image" and s.get("image", {}).get("raw")), None)
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
    out.append(Check(OK, "Read description.txt and look at thumbnail.png, then approve."))
    return out


def _youtube():
    """Uses the sign-in from Settings; never opens a browser in the middle of a job."""
    from .. import youtube
    try:
        return youtube.service(interactive=False)
    except StageError:
        raise StageError("Not signed in to YouTube (or the sign-in ran out). Go to Settings → YouTube → Sign in, "
                         "then press Upload again. To stop it running out every 7 days, set your Google Cloud app "
                         "to 'In production' (docs/YOUTUBE.md, step 6).")


def upload(ctx: Context) -> None:
    ep = ctx.episode
    meta = read_json(ep.path("publish", "metadata.json"))
    if not meta:
        raise StageError("Approve Package first.")
    from googleapiclient.http import MediaFileUpload  # noqa: imported after _youtube's check
    yt = _youtube()
    body = {
        "snippet": {"title": meta["title"], "description": meta["description"],
                    "tags": meta["tags"], "categoryId": meta["category_id"]},
        "status": {"privacyStatus": meta["privacy"], "selfDeclaredMadeForKids": meta["made_for_kids"],
                   "containsSyntheticMedia": True},
    }
    media = MediaFileUpload(str(ep.abs(meta["video"])), chunksize=8 * 1024 * 1024, resumable=True,
                            mimetype="video/mp4")
    from .. import youtube
    acct = youtube.account() or {}
    ctx.progress(f"Uploading to {acct.get('title', 'your channel')} as {meta['privacy']}...", 1)
    request = yt.videos().insert(part="snippet,status", body=body, media_body=media, notifySubscribers=False)
    response, retries = None, 0
    import time as _time
    while response is None:
        ctx.check_cancel()
        try:
            status, response = request.next_chunk()
        except Exception as exc:  # noqa: BLE001 - retry YouTube's brief server errors, stop on anything else
            code = getattr(getattr(exc, "resp", None), "status", None)
            if code in (500, 502, 503, 504) and retries < 6:
                retries += 1
                ctx.progress(f"YouTube had a hiccup ({code}); trying again in {2 ** retries} s...", None)
                _time.sleep(2 ** retries)
                continue
            raise
        if status:
            ctx.progress(f"Uploading the video: {int(status.progress() * 100)}%", status.progress() * 95)
    video_id = response["id"]
    db.execute("UPDATE project SET youtube_id=? WHERE project_id=?", (video_id, ep.project_id))
    write_json(ep.path("publish", "upload.json"), {"youtube_id": video_id, "privacy": meta["privacy"],
                                                     "uploaded_at": utc_now()})
    ctx.log(f"Uploaded: https://youtu.be/{video_id} ({meta['privacy']})")
    ctx.progress("Uploaded. Setting the thumbnail and captions...", 96)
    try:
        yt.thumbnails().set(videoId=video_id,
                            media_body=MediaFileUpload(str(ep.abs(meta["thumbnail"])))).execute()
    except Exception as exc:  # noqa: BLE001 - needs a phone-verified channel
        ctx.log(f"Thumbnail not set ({exc}). Verify the channel by phone, then set it in Studio.")
    if meta.get("captions") and ep.abs(meta["captions"]).exists():
        try:
            yt.captions().insert(part="snippet", body={"snippet": {
                "videoId": video_id, "language": "en", "name": "English"}},
                media_body=MediaFileUpload(str(ep.abs(meta["captions"])))).execute()
        except Exception as exc:  # noqa: BLE001
            ctx.log(f"Captions not uploaded ({exc}); add the .srt in YouTube Studio.")


def check_upload(ep: Episode) -> list[Check]:
    info = read_json(ep.path("publish", "upload.json"))
    if not info:
        return [Check(BLOCK, "Not uploaded yet.")]
    return [Check(OK, f"On YouTube as {info['privacy']}: https://youtu.be/{info['youtube_id']}. "
                      "Check it in YouTube Studio, pin the comment, then make it public.")]
