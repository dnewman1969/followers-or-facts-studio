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
