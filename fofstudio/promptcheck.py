"""What leaves the app in words: picture prompts and YouTube text.

From the research "Art styles caricatures and hybrids":
  * the turbo image model runs without guidance (8 steps, cfg 1), so "no X" and "Avoid: X" do nothing at
    best and at worst put X into the picture: a prompt says only what to draw ("wordless blank surfaces",
    not "no text");
  * brand, show, studio and format names, and the names of the artists that inspired a look, never go into
    a prompt, a LoRA trigger word, a title, a description or tags (trademark and false-endorsement risk);
    looks are described by their traits.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).parent / "data"
NEGATION = re.compile(r"(?:,\s*|\.\s*|\b)(?:with\s+)?(?:no|never|not|don't|do not)\s+[^,.;]*"
                      r"|\bavoid:?\s[^.]*", re.IGNORECASE)
NAME = re.compile(r"\b(?:[A-Z][a-zà-ÿ'-]+(?:\s+(?:de|van|von|la|le)?\s*[A-Z][a-zà-ÿ'-]+)+)\b")


@lru_cache(maxsize=1)
def watch_terms() -> tuple[str, ...]:
    """Every word on the watchlist, plus the names inside each look's 'inspired_by' note."""
    w = json.loads((DATA / "watchlist.json").read_text(encoding="utf-8"))
    terms = set(w["brands"]) | set(w["artists"])
    for fname, key in (("styles.json", "styles"), ("caricature_traditions.json", "traditions"),
                       ("directors.json", None)):   # (the mixes' notes hold your own labels, not names)
        data = json.loads((DATA / fname).read_text(encoding="utf-8"))
        for item in (data if key is None else data[key]):
            note = item.get("inspired_by") or ""
            terms |= {m.strip() for m in NAME.findall(note) if len(m) > 4}
    # common words that look like names in the notes but describe things, not people
    terms -= {"Art Deco", "Art Nouveau", "Day of the Dead", "New Deal", "Saturday Morning", "West End",
              "Victorian West End", "Grand Opera", "Old World", "Supermarionation-style", "German Expressionist",
              "Oscar-winning British", "Poster Collection"}
    return tuple(sorted(terms, key=len, reverse=True))


def found(text: str) -> list[str]:
    """Watchlist words in this text (whole words, any case)."""
    low = text or ""
    return [t for t in watch_terms() if re.search(rf"(?<!\w){re.escape(t)}(?!\w)", low, re.IGNORECASE)]


def strip_watch(text: str) -> tuple[str, list[str]]:
    hits = found(text)
    for t in hits:
        text = re.sub(rf"(?<!\w){re.escape(t)}(?:'s)?(?:[- ](?:style|like|inspired|esque))?(?!\w)", "", text,
                      flags=re.IGNORECASE)
    return re.sub(r"\s{2,}", " ", text).strip(" ,"), hits


def negations(text: str) -> list[str]:
    return [m.group(0).strip(" ,.") for m in NEGATION.finditer(text or "")]


def positive_only(text: str) -> str:
    """The text with 'no X' / 'without X' / 'Avoid: X' phrases taken out (the image model can't use them)."""
    out = NEGATION.sub("", text or "")
    out = re.sub(r"\s+([,.;])", r"\1", out)
    out = re.sub(r"([,.;])\s*[,.;]+", r"\1", out)
    return re.sub(r"\s{2,}", " ", out).strip(" ,;")


def clean_prompt(text: str) -> tuple[str, list[str]]:
    """A prompt ready for the image model: no negations, no watchlist words. Returns (prompt, words removed)."""
    text, hits = strip_watch(text)
    return positive_only(text), hits


# Words the image model would paint as visible text (Dave's storyboard 2026-11-02 had "11:9", "16:9" and "10.9"
# painted in: nearly every style ended with ", 16:9", and the camcorder one asked for a "date timestamp in corner").
# The picture's shape is set by its width and height, so these words only ever add text to the picture.
_RATIO = re.compile(r"(?:\bextreme\s+widescreen\s+)?\b\d+(?:\.\d+)?\s*:\s*\d+(?:\.\d+)?\b(?:\s+(?:frame|aspect(?:\s+ratio)?|"
                    r"cinematic\s+composition|composition|format))?", re.I)
_TEXT_ASK = re.compile(r"[^,.;]*\b(?:time\s*stamp|timestamps?|time\s*code|date\s+stamp|captions?|subtitles?|"
                       r"title\s+cards?|lettering|labels?|signage|headlines?|on-screen\s+text|written\s+text|"
                       r"numbers?\s+in\s+the\s+corner)\b[^,.;]*", re.I)


_SAYS = re.compile(r"\s*\b(?:[Ll]abell?ed|[Tt]itled|[Ee]ntitled|that\s+reads|with\s+the\s+(?:words?|text|label|title))\b"
                   r"[^,.;]*")
# "reading", "marked", "stamped" only count when what follows is the text itself (a quote, a capital, a number):
# "a reading lamp", "a man reading", "a stamped envelope" stay
_SAYS_IF_TEXT = re.compile(r"\s*\b(?:reading|reads|marked|stamped|printed\s+with)\s+(?=[\"'\u201c\u2018A-Z0-9])[^,.;]*")


def no_text_cues(text: str) -> str:
    """Remove aspect ratios, timestamps, captions, labels and similar requests that make the model paint text.
    "a document labelled HR 645" keeps the document and loses what it says."""
    t = _RATIO.sub("", text or "")
    t = _SAYS.sub("", t)
    t = _SAYS_IF_TEXT.sub("", t)
    t = _TEXT_ASK.sub("", t)
    t = re.sub(r"\s*,\s*(?=[,.;])", "", t)          # a comma left in front of other punctuation
    t = re.sub(r"(?:\s*[,;]\s*){2,}", ", ", t)
    t = re.sub(r"\.\s*[,;]\s*", ". ", t)
    t = re.sub(r"\s{2,}", " ", t)
    return t.strip(" ,;")
