"""Publish Kit: upload on YouTube's own page in your browser, with no Google setup at all.

From the research "Easy YouTube upload like PowerDirector": YouTube's own upload page needs no API, no
client file, no audit and no sign-in from the Studio, and it's fully within YouTube's rules (driving YouTube
Studio with a robot is not). The Studio does the rest: it opens the upload page, shows the video file, and
puts everything to fill in one click away (title, description with chapters and sources, tags, thumbnail,
captions) with the boxes to tick. Afterwards you paste the video's link back, so the Studio knows it's up.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .episode import Episode
from .util import StageError, read_json, utc_now, write_json, write_text

from .youtube import UPLOAD_PAGE  # noqa: F401 - used by the upload window

CHECKLIST = [
    "Drag the video file onto the upload page (the folder with it is open).",
    "Title and Description: paste them with the Copy buttons (the title is already copied).",
    "Thumbnail: Upload file → thumbnail.png (in the same folder).",
    "Audience: \"No, it's not made for kids\".",
    "Show more → Tags: press Copy tags and paste them all in one go (they're what people search for).",
    "Show more → Altered content: \"Yes\" (the video has AI illustrations). Category: Education.",
    "Subtitles: Upload file → With timing → the .srt file (same folder).",
    "Visibility: Private. Save. Check YouTube's copyright and ad checks in Studio, then make it public.",
    "Copy the video's link and paste it back here, so the Studio knows it's uploaded.",
]


def prepare(ep: Episode) -> dict[str, Any]:
    """Everything for the browser upload, from the write-up (Package) and the final render."""
    meta = read_json(ep.path("publish", "metadata.json"))
    if not meta:
        raise StageError("Make the write-up first (Publish → Write it up), then the browser upload has everything.")
    video = ep.abs(meta["video"])
    if not video.exists():
        raise StageError("The final video file is missing. Render it again on the Production page.")
    from .youtube import sanitize_tags
    tag_list = sanitize_tags(meta.get("tags", []))
    tags = ", ".join(tag_list)
    kit = {"title": meta["title"][:100], "description": meta["description"][:5000], "tags": tags, "tag_count": len(tag_list),
           "video": str(video), "thumbnail": str(ep.abs(meta["thumbnail"])) if meta.get("thumbnail") else "",
           "captions": str(ep.abs(meta["captions"])) if meta.get("captions") else "", "checklist": CHECKLIST,
           "made_at": utc_now()}
    write_text(ep.path("publish", "upload-kit.txt"),
               f"TITLE\n{kit['title']}\n\nDESCRIPTION\n{kit['description']}\n\nTAGS\n{kit['tags']}\n\nFILES\n"
               f"{kit['video']}\n{kit['thumbnail']}\n{kit['captions']}\n\nCHECKLIST\n"
               + "\n".join(f"{n}. {c}" for n, c in enumerate(CHECKLIST, 1)) + "\n")
    return kit


def video_id_from(link: str) -> str:
    """The 11-character video ID from any YouTube or YouTube Studio link (or the ID itself)."""
    link = (link or "").strip()
    for pat in (r"youtu\.be/([\w-]{11})", r"[?&]v=([\w-]{11})", r"/video/([\w-]{11})", r"/shorts/([\w-]{11})",
                r"^([\w-]{11})$"):
        m = re.search(pat, link)
        if m:
            return m.group(1)
    raise StageError("That doesn't look like a YouTube link. Copy it from YouTube Studio (Details → Video link).")


def record_upload(ep: Episode, link: str, privacy: str = "private") -> dict[str, Any]:
    from . import db
    from .youtube import studio_url, video_url
    vid = video_id_from(link)
    db.execute("UPDATE project SET youtube_id=? WHERE project_id=?", (vid, ep.project_id))
    info = {"youtube_id": vid, "privacy": privacy, "video_url": video_url(vid), "studio_url": studio_url(vid),
            "via": "browser", "uploaded_at": utc_now()}
    write_json(ep.path("publish", "upload.json"), info)
    ep.record("upload", "approved", "uploaded in the browser")
    return info


def folder_of(kit: dict[str, Any]) -> Path:
    return Path(kit["video"]).parent
