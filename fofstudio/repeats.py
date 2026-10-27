"""Finding repeats: so scripts, books and stories don't say the same thing over and over.

From the research "Video quality 3D Owlbert and variety" (avoiding repetition): most repetition comes from
writing each scene with only the end of the one before, so the writer re-explains what it can't see. The fix
is in the plan, not in Ollama's repeat settings (those penalise words, not ideas, and can garble names,
numbers and quotes). So:
  * a ledger: every later scene or chapter is told what was already said (ledger_text)
  * a check after each scene: sentences that say again what an earlier one said (similar word runs), long
    phrases used over and over, and stock "AI" phrases (find_repeats, overused_phrases, stock_phrases)
  * the writer rewrites only what was flagged; whatever is left is shown to you as a warning.
Plain text matching, no AI opinions (see EDITORIAL-RULES).
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Iterable

WORD = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")
STOP = {"the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "at", "for", "with", "by", "from", "as", "is",
        "was", "were", "are", "be", "been", "it", "its", "that", "this", "these", "those", "he", "she", "they",
        "his", "her", "their", "we", "you", "i", "so", "then", "than", "into", "about", "not", "no", "had", "has",
        "have", "do", "did", "does", "just", "also", "very", "there", "here", "what", "which", "who", "when"}

# phrases local models overuse ("slop"); the writers are told to avoid them and the check flags them
STOCK = ["in today's video", "buckle up", "let's dive in", "dive deep", "delve", "tapestry", "it's important to note",
         "it is important to note", "it's worth noting", "game-changer", "game changer", "little did they know",
         "in conclusion", "the truth is out there", "in today's world", "a testament to", "folks", "imagine a world",
         "in a world where", "navigate the complexities", "a stark reminder", "serves as a reminder", "shed light on",
         "sheds light on", "let that sink in", "here's the thing", "stay tuned", "unravel the", "at the end of the day",
         "plays a crucial role", "a crucial role", "the realm of", "in the realm", "a double-edged sword",
         "a web of", "a cautionary tale", "only time will tell", "the rest is history", "fast forward to",
         "but here's the kicker", "spoiler alert", "make no mistake", "needless to say", "it goes without saying",
         "a perfect storm", "the stakes have never been higher", "a chilling reminder", "sent shockwaves",
         # report language: the script tells a story, it doesn't summarise research (Dave, 2026-10-27)
         "according to the research", "the research shows", "the research packet", "research indicates",
         "in summary", "to summarize", "to sum up", "this report", "as mentioned earlier", "as mentioned before",
         "in this video we will", "in this video, we will", "this video will explore", "let's take a look at",
         "the evidence suggests that", "studies show"]


def sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text or "") if s.strip()]


def content_words(text: str) -> list[str]:
    return [w for w in WORD.findall((text or "").lower().replace("’", "'")) if w not in STOP]


def _grams(words: list[str], n: int) -> set[tuple[str, ...]]:
    return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}


def similarity(a: str, b: str) -> float:
    """How much two sentences say the same thing: overlap of their 2-word runs of content words (0 to 1),
    measured against the shorter one, so a sentence that repeats part of a longer one still counts."""
    ga, gb = _grams(content_words(a), 2), _grams(content_words(b), 2)
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / min(len(ga), len(gb))


def shared_run(a: str, b: str, n: int = 7) -> bool:
    """The same 7 words in a row (ignoring case and punctuation)."""
    wa = WORD.findall((a or "").lower())
    wb = WORD.findall((b or "").lower())
    return bool(_grams(wa, n) & _grams(wb, n))


def find_repeats(text: str, earlier: Iterable[tuple[str, str]], threshold: float = 0.6,
                 min_words: int = 6, keep_quotes: Iterable[str] = ()) -> list[dict[str, Any]]:
    """Sentences in `text` that say again what an earlier piece said. earlier = [(label, text)].
    Verified quotes (keep_quotes) may be repeated word for word only once, so they're ignored here."""
    quotes = [q.lower() for q in keep_quotes if q]
    before = [(label, s) for label, t in earlier for s in sentences(t)]
    out = []
    for s in sentences(text):
        if len(content_words(s)) < min_words or any(q[:40] in s.lower() for q in quotes):
            continue
        best = None
        for label, old in before:
            score = similarity(s, old)
            if score >= threshold or shared_run(s, old):
                if best is None or score > best["score"]:
                    best = {"sentence": s, "where": label, "earlier": old, "score": round(max(score, 0.6), 2)}
        if best:
            out.append(best)
    return out


def overused_phrases(texts: dict[str, str], n: int = 4, min_places: int = 3) -> list[tuple[str, list[str]]]:
    """Runs of n content words that turn up in min_places or more different scenes/chapters."""
    where: dict[tuple[str, ...], set[str]] = defaultdict(set)
    for label, t in texts.items():
        for g in _grams(content_words(t), n):
            where[g].add(label)
    out = [(" ".join(g), sorted(p)) for g, p in where.items() if len(p) >= min_places]
    return sorted(out, key=lambda x: -len(x[1]))[:10]


def stock_phrases(text: str) -> list[str]:
    low = (text or "").lower().replace("’", "'")
    return [p for p in STOCK if p in low]


def key_sentences(text: str, limit: int = 4) -> list[str]:
    """The sentences that carry the facts: ones with numbers, dates or names first, then the opening one."""
    ss = sentences(text)
    factual = [s for s in ss if re.search(r"\d", s) or len(re.findall(r"\b[A-Z][a-z]+", s[1:])) >= 2]
    picked = list(dict.fromkeys(([ss[0]] if ss else []) + factual))
    return picked[:limit]


def ledger_text(pieces: list[tuple[str, str]], limit: int = 45, chars: int = 6000) -> str:
    """'Already said' list for the next scene or chapter: the key sentences of what came before."""
    lines: list[str] = []
    for label, t in pieces:
        for s in key_sentences(t):
            lines.append(f"- ({label}) {s}")
    lines = lines[-limit:]
    text = "\n".join(lines)
    return text[-chars:] if text else ""


def opening_and_ending(scenes: list[dict[str, Any]]) -> tuple[str, str]:
    first = sentences(scenes[0].get("narration", "")) if scenes else []
    last = sentences(scenes[-1].get("narration", "")) if scenes else []
    return " ".join(first[:2]), " ".join(last[-2:])
