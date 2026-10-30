"""YouTube, the simple way (Dave, 2026-10-30): no Google setup at all.

The Studio opens YouTube's own upload page in your browser and puts the title, description and search tags
one click away (Publish → Upload on YouTube; publishkit.py). You drag the video in, paste the parts, and paste
the video's link back so the Studio knows it's up. The old Google Cloud sign-in (client file, API, the 7-day
sign-outs) is gone.

YouTube has no way for another program to fill its upload form for you, and driving YouTube Studio with a
robot is against its rules, so copy-and-paste with buttons is the fastest allowed way.
"""

from __future__ import annotations

UPLOAD_PAGE = "https://www.youtube.com/upload"
TAG_LIMIT = 500     # YouTube allows 500 characters of tags in total


def tag_length(tags: list[str]) -> int:
    """How YouTube counts the tags box: commas between tags, and a tag with a space counts its quotes."""
    return sum(len(t) + (2 if " " in t else 0) for t in tags) + max(0, len(tags) - 1)


def sanitize_tags(tags: list[str], limit: int = TAG_LIMIT) -> list[str]:
    """No angle brackets, no duplicates, each under 100 characters, the most important first, and only as many
    as fit in YouTube's 500 characters."""
    seen, out = set(), []
    for tag in tags:
        t = " ".join(str(tag).replace("<", "").replace(">", "").replace(",", " ").replace("#", "").split())[:100]
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    keep: list[str] = []
    for t in out:                         # skip one that doesn't fit, but keep trying shorter ones after it
        if tag_length(keep + [t]) <= limit:
            keep.append(t)
    return keep


def studio_url(video_id: str) -> str:
    """Where to check YouTube's checks (copyright, ad suitability) before making the video public."""
    return f"https://studio.youtube.com/video/{video_id}/edit"


def video_url(video_id: str) -> str:
    return f"https://youtu.be/{video_id}"
