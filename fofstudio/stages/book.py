"""Book: the whole story with references, as a PDF you could sell later.

For subjects with too much for a video. The book is a full breakdown: where it started, who was
involved, how it spread, what the record shows, who profited, the damage it did, how the deception
worked, and the verdict. It is written ONLY from the evidence ticked on the Research page.

How "nothing made up" is enforced (plain text checks, not AI opinions - see EDITORIAL-RULES):
  * The local AI plans chapters and can only point at evidence IDs that exist (the answer format only
    allows those IDs).
  * Each chapter is written from that chapter's material only: the ticked quotes and source write-ups
    and passages from the saved copies of those sources. Every paragraph must cite what it relies on.
  * Quotes are never typed by the AI: it names a quote's E-number and the program prints the verified,
    word-for-word quote. Anything the AI put in quotation marks must be found word for word in the
    sources, or the paragraph fails.
  * Every number and year in a paragraph must appear in the material that paragraph cites.
  * Names that aren't in the material are flagged for you to check.
  * A failing chapter gets one rewrite with the problems listed; paragraphs that still fail are
    removed and listed in the book's review notes. You read it and press Approve the book; until then
    every page says DRAFT.

The book is saved chapter by chapter (book/book.json), so a stopped job carries on where it left off.

Craft (research "Bestseller book craft for nonfiction"): the chapters follow a shape that suits the chosen
story type (BOOK_SHAPES, not one fixed order), the chosen writing style is used throughout, the plan names
one action line and a cast of at most four, and each chapter is written in beats of a few hundred words
(local models lose quality past ~2,000 words in one answer): an opening scene from a dated, sourced moment,
the evidence beats, a fairness beat where people are named, and an ending that pulls forward with something
from the record. Guessing words ("must have", "probably felt", "imagine") are not allowed. Questions the
material can't answer become "look it up" tasks (gap questions), never facts.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from .. import sources as srcmod
from .. import techniques
from ..episode import Episode
from ..llm import Ollama
from ..util import StageError, normalize_for_match, read_json, utc_now, write_json
from .base import BLOCK, OK, WARN, Check, Context

PARTS = [
    ("introduction", "What was claimed, and why it matters"),
    ("origin", "Where it started: the kernel of truth (if any) and the first people to tell it"),
    ("players", "Who was involved: the people and groups who made, spread and profited from it"),
    ("spread", "How it spread: the shows, sites, books, events and years it grew through"),
    ("record", "What the record shows: the evidence, claim by claim"),
    ("profit", "Who profited, and how"),
    ("damage", "The damage: what the lies and deception did to real people and to society"),
    ("techniques", "How the deception worked: the tricks used, so readers can spot them"),
    ("verdict", "The verdict: what we know, what is still unknown, and what to ask next time"),
]
PART_KEYS = [k for k, _ in PARTS]
KNOWN_NAMES = {"followers or facts", "professor owlbert", "owlbert mcfinnegan", "professor owlbert mcfinnegan",
               "knowledge fight", "wayback machine", "internet archive"}
LEADING = {"the", "a", "an", "in", "on", "at", "by", "but", "and", "when", "after", "before", "this", "that",
           "his", "her", "their", "as", "for", "from", "if", "it", "so", "then", "while", "with", "during",
           "according", "since", "until", "under", "over", "one", "two", "some", "many", "most", "these",
           "those", "its", "our", "we", "they", "he", "she", "there", "here", "what", "who", "how", "why"}
MONTHS = {"january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}

BOOK_RULES = """You are writing one chapter of a non-fiction book for "Followers or Facts", a fact-check
channel. The book is the complete breakdown of a lie: where it started, who was involved, how it spread,
what the record shows, who profited, the damage it did, and how the deception worked.

HARD RULES (a program checks them; paragraphs that break them are thrown away):
1. Use ONLY the material given for this chapter. Never add facts, dates, numbers, names, places or events
   from your own knowledge, even if you are sure they are true. If the material doesn't say it, leave it out.
2. Every paragraph lists in "cites" the IDs of the material it relies on (E-numbers for quotes, S-IDs for
   sources). Only cite an item that really says what the paragraph says.
3. Never put words in quotation marks yourself. To quote a source, put the quote's E-number in
   "quote_after" and the program prints it word for word under the paragraph.
4. Every number and year you write must be written in the material you cite, written the same way (digits).
5. Say that someone lied, knew it was false or set out to deceive ONLY when the cited material (a court
   finding, an official record, or their own words) says so. Otherwise say what they claimed and what the
   record shows, and let the reader judge.
6. Never mock the people who believed it; anyone can be fooled, that's why it works. Aim criticism at the
   people who sold it. Follow every careful-topic rule.
7. "Database notes" are background to help you understand. Don't state anything from them unless the
   evidence you cite also says it.
8. Clear, plain non-fiction for a general adult reader. Short paragraphs (60 to 160 words). Use "heading"
   for a short subheading when a new section of the chapter starts, otherwise "".
9. Don't repeat what other chapters cover (their titles are listed). Tell this chapter's part fully.
10. Never guess at what people thought, felt or must have done: no "must have", "probably felt", "one can
    imagine", no scene that starts with "Imagine". Thoughts and feelings only when the person said so, with
    attribution. No made-up people, composites or dialogue.

CRAFT (what bestselling narrative non-fiction does):
- Follow the book's action line: every beat moves it forward.
- Open a chapter on a concrete, dated or placed moment from the material (a post, a broadcast, a filing, a
  hearing), never a rhetorical question or a definition. Say what the chapter's question is early.
- Turn documents into events: when it was made or exposed, who saw it, then its key line (as a quote_after).
- Explain a hard idea with one concrete example from the material first, then the general point.
- Be fair: when you name someone who spread the claim, give their documented response or defence from the
  material; if there is none, say no public response was found in these sources. Use legal words exactly as
  the record does (alleged, charged, convicted, settled, found liable).
- End a chapter by pulling forward with something real: an open question the material answers next, a dated
  event coming, a document about to be opened. No moral summary, no invented suspense.
- Plain adult prose (about grade 8-10), sentences under 35 words, third person.
"""
GUESSING = ["must have", "probably felt", "probably thought", "one can imagine", "can only imagine", "we can imagine",
            "must surely have", "no doubt felt", "little did", "surely knew"]

# the shape of the book for each story type: the order of the parts and where the turn falls
# (research "Bestseller book craft for nonfiction", table "The thirteen types as book structures")
BOOK_SHAPES: dict[str, tuple[list[str], str]] = {
    "fact_sandwich": (["introduction", "origin", "record", "players", "spread", "profit", "damage", "techniques",
                       "verdict"], "Frame: truth, myth, truth. Open on the true fact; state the myth once, early; "
                                   "the verdict restates the fact."),
    "patient_zero": (["introduction", "origin", "spread", "players", "record", "profit", "damage", "techniques",
                      "verdict"], "A straight line from origin to outbreak; the rumor is the main character; the "
                                  "moment the truth was bent comes about a quarter of the way in."),
    "whodunit": (["introduction", "record", "players", "spread", "origin", "profit", "damage", "techniques",
                  "verdict"], "A mystery: who started it? Clues are record items; be fair to wrong suspects; hold "
                              "the answer to the last third ('no originator can be found' is a valid answer)."),
    "follow_money": (["introduction", "profit", "players", "origin", "spread", "record", "damage", "techniques",
                      "verdict"],
                     "A chain of transactions; the money is the spine; the trail reaches its owner about 60% in."),
    "rise_and_fall": (["introduction", "origin", "players", "spread", "profit", "record", "damage", "techniques",
                       "verdict"], "An arc: the rise fills the first half, the first public crack about halfway, "
                                   "the fall after; only public figures as the seller."),
    "long_con": (["introduction", "origin", "players", "techniques", "spread", "profit", "record", "damage", "verdict"],
                 "Con stages: setup, hook, convincer, raising the stakes, the sting (about 70% in), the blow-off. "
                 "Show the tricks stage by stage, never as a how-to."),
    "trial": (["introduction", "players", "record", "origin", "spread", "profit", "damage", "techniques", "verdict"],
              "An argument: the charge, the prosecution, the defence (the believers' best case gets one full, fair "
              "chapter), cross-examination, verdict; the evidence gets at least twice the defence's space."),
    "lab": (["introduction", "origin", "record", "techniques", "spread", "players", "profit", "damage", "verdict"],
            "Hypothesis, test, result: only tests that others really ran and the material reports."),
    "trick_first": (["techniques", "introduction", "origin", "spread", "record", "players", "profit", "damage",
                     "verdict"], "Teach the technique first with a harmless example, then switch to the real case."),
    "the_turn": (["introduction", "origin", "spread", "record", "damage", "techniques", "profit", "verdict"],
                 "Four movements with a shift of perspective about 60% in that reframes everything; suits honest "
                 "mistakes; profit and damage may be short."),
    "rabbit_hole": (["introduction", "spread", "techniques", "players", "record", "damage", "profit", "verdict"],
                    "Descent, bottom (about 55% in), climb out, told through a real former believer's published "
                    "account in the material; never a made-up believer."),
    "abt": (["introduction", "origin", "record", "techniques", "verdict"], "And, But, Therefore: a short guide."),
    "history_rhymes": (["introduction", "origin", "spread", "record", "players", "profit", "damage", "techniques",
                        "verdict"], "Two timelines, then and now, that meet about 65% in; the historical half is "
                                    "at most about 40% of the book."),
}
BEAT_JOBS = {
    "scene": "Open on a concrete, dated or placed moment from this beat's material; say what the chapter is about.",
    "evidence": "Lay out what this beat's material shows, strongest first, as a story moving forward.",
    "document": "Treat the document as an event: when it was made or exposed, who saw it, then its key line.",
    "fairness": "Give the documented response or defence of the people named in this chapter, from the material; "
                "if there is none, say no public response was found in these sources.",
    "pull": "Finish the chapter by pulling forward with something real from the material: an open question, a "
            "dated event coming, a document about to be opened. No moral summary.",
}


# ---------------------------------------------------------------- the material
def _packet(ep: Episode) -> dict[str, Any]:
    from .research import selected
    return selected(read_json(ep.path("research.json")) or {})


class Material:
    """Everything ticked, indexed by ID, with the careful-topic rules applied."""

    def __init__(self, packet: dict[str, Any]):
        self.packet = packet
        rules = packet.get("restrictions", [])
        claim_ids = [c["claim_id"] for c in packet.get("claims", [])]
        arc_rule = {r["rule"] for r in rules if r.get("subject_type") == "arc"}
        self.rules = {cid: arc_rule | {r["rule"] for r in rules if r.get("subject_type") == "claim"
                                       and r.get("subject_id") == cid} for cid in claim_ids}
        self.claims = {c["claim_id"]: c for c in packet.get("claims", [])}
        self.evidence: dict[str, dict[str, Any]] = {}
        for e in packet.get("evidence", []):
            if "courts_only" in self.rules.get(e["claim_id"], set()) and e.get("type") not in ("court", "gov"):
                continue      # victims: courts and documents only
            self.evidence[e["id"]] = e
        self.sources: dict[str, dict[str, Any]] = {}
        accessed = {s["source_id"]: s.get("accessed_at") for c in packet.get("claims", []) for s in c.get("sources", [])}
        for e in self.evidence.values():
            s = self.sources.setdefault(e["source_id"], {
                "source_id": e["source_id"], "title": e.get("title") or e["source_id"], "publisher": e.get("publisher"),
                "date": e.get("date"), "url": e.get("url"), "archive_url": e.get("archive_url"),
                "type": e.get("type"), "accessed_at": accessed.get(e["source_id"]), "summary": ""})
            if e.get("kind") == "link" and e.get("summary"):
                s["summary"] = e["summary"]
        self._texts: dict[str, str | None] = {}

    @property
    def quote_ids(self) -> list[str]:
        return [i for i, e in self.evidence.items() if e.get("kind") == "quote"]

    def cite_ids(self) -> list[str]:
        return sorted(set(self.evidence) | set(self.sources))

    def source_of(self, cite: str) -> str | None:
        if cite in self.sources:
            return cite
        e = self.evidence.get(cite)
        return e["source_id"] if e else None

    def saved_text(self, source_id: str) -> str | None:
        if source_id not in self._texts:
            try:
                self._texts[source_id] = srcmod.source_text(source_id)
            except Exception:  # noqa: BLE001 - an unreadable copy just means no passages
                self._texts[source_id] = None
        return self._texts[source_id]

    def names(self) -> set[str]:
        out = set(KNOWN_NAMES)
        for c in self.claims.values():
            out |= {p["name"].lower() for p in c.get("people", [])} | {o["name"].lower() for o in c.get("orgs", [])}
        if self.packet.get("title"):
            out.add(str(self.packet["title"]).lower())
        return out

    def careful_rules(self) -> list[str]:
        return [f"{r['rule']}: {r.get('note') or ''}" for r in self.packet.get("restrictions", [])]

    def key(self) -> str:
        """Changes when the ticked evidence changes (the book is then written again)."""
        return hashlib.sha1(json.dumps(sorted(self.evidence), ensure_ascii=False).encode()).hexdigest()[:12]

    def counts(self) -> dict[str, int]:
        return {"claims": len(self.claims), "sources": len(self.sources), "quotes": len(self.quote_ids)}


def _claim_note(c: dict[str, Any]) -> dict[str, Any]:
    return {"claim_id": c["claim_id"], "claim": c.get("short_title"), "verdict": c.get("falsity_status"),
            "database_notes": " ".join(str(c.get(k) or "") for k in ("claim_summary", "harm_summary",
                                                                      "who_benefited", "society_effect")).strip(),
            "first_known_year": c.get("first_known_year"), "peak_years": c.get("peak_years"),
            "people": [p["name"] for p in c.get("people", [])], "groups": [o["name"] for o in c.get("orgs", [])]}


def _item(e: dict[str, Any], long: bool = True) -> dict[str, Any]:
    cut = 1200 if long else 220
    out = {"id": e["id"], "kind": e.get("kind"), "claim_id": e["claim_id"], "source_id": e["source_id"],
           "source": f"{e.get('publisher') or ''}: {e.get('title') or ''} ({e.get('date') or 'no date'})".strip(": "),
           "source_type": e.get("type")}
    if e.get("quote"):
        out["quote"] = e["quote"] if long else e["quote"][:cut]
    shows = e.get("summary") or e.get("supports") or ""
    if shows:
        out["what_it_shows"] = shows[:cut]
    return out


def chapter_material(mat: Material, ch: dict[str, Any], per_source: int = 2500,
                     max_sources: int = 6) -> dict[str, Any]:
    """What the writer gets for one chapter: its evidence, passages of the saved sources, background."""
    ev = [mat.evidence[i] for i in ch["evidence_ids"] if i in mat.evidence]
    query = " ".join([ch["title"], ch.get("purpose", "")] +
                     [str(mat.claims[c].get("short_title") or "") for c in ch.get("claim_ids", []) if c in mat.claims])
    passages = []
    for sid in list(dict.fromkeys(e["source_id"] for e in ev))[:max_sources]:
        text = mat.saved_text(sid)
        if text:
            p = srcmod.relevant_passages(text, query, limit_chars=per_source)
            if p:
                passages.append({"id": sid, "kind": "passages from the saved copy of the source", "text": p})
    out = {"evidence": [_item(e) for e in ev], "source_passages": passages,
           "database_notes": [_claim_note(mat.claims[c]) for c in ch.get("claim_ids", []) if c in mat.claims]}
    if ch.get("part") == "techniques":
        out["tricks"] = [{"id": f"T-{t['key']}", **t} for t in techniques.for_prompt()]
    return out


def cited_text(mat: Material, block: dict[str, Any], cites: list[str]) -> str:
    """All the words a paragraph's citations stand on: their quotes, write-ups and source passages."""
    parts = []
    srcs = {mat.source_of(c) for c in cites} - {None}
    for e in block["evidence"]:
        if e["id"] in cites or e["source_id"] in srcs:
            parts += [e.get("source", ""), e.get("quote", ""), e.get("what_it_shows", "")]
    for p in block["source_passages"]:
        if p["id"] in srcs:
            parts.append(p["text"])
    for s in srcs:
        info = mat.sources.get(s) or {}
        parts += [str(info.get("title") or ""), str(info.get("date") or ""), str(info.get("summary") or "")]
    return "\n".join(x for x in parts if x)


# ---------------------------------------------------------------- the checks
NUMBER = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)")
NAME = re.compile(r"\b[A-Z][a-zA-Z'’\-]+(?:\s+[A-Z][a-zA-Z'’\-]+)+")


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "") for n in NUMBER.findall(text) if len(n.replace(",", "").split(".")[0]) >= 2}


def check_paragraph(p: dict[str, Any], mat: Material, block: dict[str, Any], known_names: set[str],
                    techniques_ok: bool = False) -> tuple[list[str], list[str]]:
    """(problems that remove the paragraph, things for you to check)."""
    hard: list[str] = []
    soft: list[str] = []
    cites = [c for c in p.get("cites", []) if c in mat.evidence or c in mat.sources or
             (techniques_ok and c.startswith("T-"))]
    real = [c for c in cites if not c.startswith("T-")]
    if not real and not cites:
        hard.append("it doesn't cite any of the material")
    support = cited_text(mat, block, real)
    if techniques_ok and any(c.startswith("T-") for c in cites):
        support += "\n" + json.dumps(block.get("tricks", []))
    text = p.get("text", "")
    missing = sorted(_numbers(text) - _numbers(support))
    if missing:
        hard.append(f"the number(s) {', '.join(missing)} aren't in the material it cites")
    low_text = text.lower()
    guesses = [g for g in GUESSING if g in low_text] + (["it starts with 'Imagine'"]
                                                         if low_text.lstrip().startswith("imagine") else [])
    if guesses:
        hard.append(f"it guesses at what people thought or did ({', '.join(guesses)}); only what the record shows")
    everything = support + "\n" + "\n".join(e.get("quote", "") for e in block["evidence"])
    from ..scriptfmt import quotes_in
    for q in quotes_in(text):
        if len(q.split()) >= 3 and not srcmod.quote_in_text(q, everything):
            hard.append(f"it puts words in quotation marks that aren't in the sources: \"{q[:80]}\"")
    low = normalize_for_match(support + " " + " ".join(known_names))
    for name in NAME.findall(text):
        words = name.split()
        while words and words[0].lower() in LEADING | MONTHS:
            words = words[1:]
        if len(words) < 2:
            continue
        nm = " ".join(words)
        if normalize_for_match(nm) not in low and not all(w.lower() in low for w in words):
            soft.append(f"the name \"{nm}\" isn't in the material it cites")
    p["cites"] = cites
    return hard, sorted(set(soft))


# ---------------------------------------------------------------- the AI
def outline_schema(claim_ids: list[str], ev_ids: list[str], most: int) -> dict[str, Any]:
    return {"type": "object", "properties": {
        "title": {"type": "string"}, "subtitle": {"type": "string"},
        "action_line": {"type": "string"},
        "cast": {"type": "array", "maxItems": 4, "items": {"type": "string"}},
        "gap_questions": {"type": "array", "maxItems": 8, "items": {"type": "object", "properties": {
            "claim_id": {"type": "string", "enum": claim_ids}, "question": {"type": "string"}},
            "required": ["claim_id", "question"]}},
        "chapters": {"type": "array", "minItems": 5, "maxItems": most, "items": {"type": "object", "properties": {
            "part": {"type": "string", "enum": PART_KEYS},
            "title": {"type": "string"}, "purpose": {"type": "string"},
            "claim_ids": {"type": "array", "items": {"type": "string", "enum": claim_ids}},
            "evidence_ids": {"type": "array", "items": {"type": "string", "enum": ev_ids}}},
            "required": ["part", "title", "purpose", "claim_ids", "evidence_ids"]}}},
        "required": ["title", "subtitle", "chapters"]}


def chapter_schema(cite_ids: list[str], quote_ids: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": {"paragraphs": {
        "type": "array", "minItems": 2, "maxItems": 40, "items": {"type": "object", "properties": {
            "heading": {"type": "string"}, "text": {"type": "string"},
            "cites": {"type": "array", "minItems": 1, "items": {"type": "string", "enum": cite_ids or ["none"]}},
            "quote_after": {"type": "string", "enum": [""] + quote_ids}},
            "required": ["heading", "text", "cites", "quote_after"]}}}, "required": ["paragraphs"]}


def _chapters_wanted(mat: Material) -> int:
    c = mat.counts()
    return max(5, min(16, 4 + c["claims"] + c["sources"] // 12))


def tidy_outline(raw: dict[str, Any], mat: Material, order: list[str] | None = None) -> list[dict[str, Any]]:
    """Valid IDs only, parts in the story type's order, and every ticked item used somewhere."""
    order = order or PART_KEYS
    rank = {k: (order.index(k) if k in order else len(order) + PART_KEYS.index(k)) for k in PART_KEYS}
    chapters = []
    for ch in raw.get("chapters", []):
        if ch.get("part") not in PART_KEYS or not (ch.get("title") or "").strip():
            continue
        chapters.append({"part": ch["part"], "title": ch["title"].strip(), "purpose": ch.get("purpose", ""),
                         "claim_ids": [c for c in dict.fromkeys(ch.get("claim_ids", [])) if c in mat.claims],
                         "evidence_ids": [e for e in dict.fromkeys(ch.get("evidence_ids", [])) if e in mat.evidence]})
    chapters.sort(key=lambda c: rank[c["part"]])      # stable: keeps the AI's order within a part
    if not chapters:
        raise StageError("The local AI didn't plan any chapters. Press Write the book again.")
    used = {e for ch in chapters for e in ch["evidence_ids"]}
    for eid, e in mat.evidence.items():
        if eid in used:
            continue
        home = next((ch for ch in chapters if ch["part"] == "record" and e["claim_id"] in ch["claim_ids"]), None) \
            or next((ch for ch in chapters if e["claim_id"] in ch["claim_ids"]), None) \
            or next((ch for ch in chapters if ch["part"] == "record"), None) or chapters[len(chapters) // 2]
        home["evidence_ids"].append(eid)
    for ch in chapters:
        if not ch["evidence_ids"]:   # a chapter needs something to stand on: its claims' strongest items
            cl = ch["claim_ids"] or list(mat.claims)
            ch["evidence_ids"] = [e["id"] for e in mat.evidence.values() if e["claim_id"] in cl][:8]
        if not ch["claim_ids"]:
            ch["claim_ids"] = list(dict.fromkeys(mat.evidence[e]["claim_id"] for e in ch["evidence_ids"]))
    for n, ch in enumerate(chapters, 1):
        ch["number"] = n
    return [ch for ch in chapters if ch["evidence_ids"]]


def book_type_and_writer(ep: Episode, options: dict[str, Any] | None = None):
    """The story type and writing style for the book: chosen on the Stories page (or the chosen story's), the
    sober ones on careful topics."""
    from .. import storytypes
    from .stories import chosen
    o = options or {}
    c = ep.creative()
    story = chosen(ep) or {}
    ok_types = {t.key for t in storytypes.allowed_types(bool(c.get("careful")))}
    key = next((k for k in (o.get("story_type"), c.get("story_type"), story.get("story_type"))
                if k in storytypes.STORY_TYPES and k in ok_types), storytypes.DEFAULT_TYPE)
    ok_writers = {w.key: w for w in storytypes.allowed_writers(bool(c.get("careful")), int(c.get("humor", 1)))}
    wkey = next((k for k in (o.get("writer"), c.get("writer"), story.get("writer")) if k in ok_writers),
                storytypes.DEFAULT_WRITER if storytypes.DEFAULT_WRITER in ok_writers else next(iter(ok_writers)))
    return storytypes.STORY_TYPES[key], ok_writers.get(wkey) or storytypes.writers()[storytypes.DEFAULT_WRITER]


def make_outline(ctx: Context, llm: Ollama, mat: Material, title: str, stype=None, memory: str = "") -> dict[str, Any]:
    want = _chapters_wanted(mat)
    overview = {"subject": title, "claims": [_claim_note(c) for c in mat.claims.values()],
                "evidence": [_item(e, long=False) for e in mat.evidence.values()],
                "careful_rules": mat.careful_rules()}
    order, shape = BOOK_SHAPES.get(getattr(stype, "key", ""), BOOK_SHAPES["fact_sandwich"])
    descr = dict(PARTS)
    parts = "\n".join(f"- {k}: {descr[k]}" for k in order)
    raw = llm.chat_json([
        {"role": "system", "content": (
            "You plan non-fiction books for the fact-check channel Followers or Facts. Plan the chapters of a book "
            "that is the complete breakdown of this subject, using ONLY the evidence listed. "
            + (f"The book is told as '{stype.name}': {shape}\n" if stype else "")
            + "Use these parts in this order (a part can have several chapters; 'record' usually has one chapter per "
              f"claim or group of claims):\n{parts}\nFor each chapter give its part, a clear title (no chapter "
              "numbers), one sentence on what it covers and how it moves the action line forward, and the IDs of the "
              "claims and evidence it draws on. Use every evidence item at least once, and give each item its main "
              "home in one chapter. Put the strongest true, dated moment in chapter 1 (no method or background "
              "chapter in the first three). action_line: one sentence naming the thread every chapter advances "
              "(e.g. 'We follow the claim from a 1997 radio show to a 2000 court ruling'). cast: up to four main "
              "people or groups from the material (prefer an investigator, a skeptic, or the claim itself as the "
              "lead; never a victim). gap_questions: up to 8 questions the material can't answer that a reader would "
              "ask (they become 'look it up' tasks; never guess the answers). A title and subtitle that say what it "
              "is about, honest and not sensational. Never mock believers; aim at the people who sold it. Follow the "
              "careful-topic rules.")},
        {"role": "user", "content": f"About {want} chapters.\n\nMaterial:\n"
                                    f"{json.dumps(overview, ensure_ascii=False, indent=1)[:40000]}"
                                    + (f"\n\n{memory}" if memory else "")},
    ], outline_schema(sorted(mat.claims), sorted(mat.evidence), min(20, want + 4)), lenient=True, temperature=0.4,
        on_text=ctx.writing("Planning the chapters", 2, 9, 60 * want))
    names = {n.lower() for n in mat.names()}
    cast = [x.strip() for x in raw.get("cast", []) if x.strip() and (x.strip().lower() in names or any(
        x.strip().lower() in n or n in x.strip().lower() for n in names if len(n) > 3))][:4]
    questions = [q for q in raw.get("gap_questions", []) if q.get("claim_id") in mat.claims and
                 len((q.get("question") or "").split()) >= 4][:8]
    return {"title": (raw.get("title") or title).strip(), "subtitle": (raw.get("subtitle") or "").strip(),
            "action_line": (raw.get("action_line") or "").strip(), "cast": cast, "questions": questions,
            "chapters": tidy_outline(raw, mat, order)}


def plan_beats(ch: dict[str, Any], mat: Material) -> list[dict[str, Any]]:
    """Split a chapter into beats of a few hundred words, each with its own evidence (used only there):
    an opening scene, evidence or document beats, a fairness beat where people are named, a forward pull."""
    ev = [mat.evidence[i] for i in ch["evidence_ids"] if i in mat.evidence]
    ev.sort(key=lambda e: (str(e.get("date") or "9999"), e["source_id"]))
    groups = [ev[i:i + 3] for i in range(0, len(ev), 3)] or [[]]
    beats = []
    for k, g in enumerate(groups):
        job = "scene" if k == 0 else ("document" if any(e.get("kind") == "quote" for e in g) else "evidence")
        beats.append({"job": job, "evidence_ids": [e["id"] for e in g]})
    named = ch["part"] in ("players", "profit", "spread", "record", "damage") and any(
        mat.claims.get(c, {}).get("people") or mat.claims.get(c, {}).get("orgs") for c in ch.get("claim_ids", []))
    if named:
        beats.append({"job": "fairness", "evidence_ids": [e["id"] for e in ev][:4]})
    if len(beats) > 1:
        beats[-1]["job"] = "pull" if beats[-1]["job"] != "fairness" else "fairness"
        if beats[-1]["job"] == "fairness":
            beats.append({"job": "pull", "evidence_ids": [e["id"] for e in ev][-2:]})
    else:
        beats[0]["job"] = "scene"
    for b in beats:
        b["words"] = max(300, min(700, 170 * max(1, len(b["evidence_ids"])) + 120))
    return beats


def write_chapter(ctx: Context, llm: Ollama, mat: Material, book: dict[str, Any], ch: dict[str, Any],
                  start: float, end: float, writer=None) -> None:
    from .. import storytypes
    from ..repeats import ledger_text
    names = mat.names()
    techniques_ok = ch["part"] == "techniques"
    others = [f"{c['number']}. {c['title']}" for c in book["chapters"] if c is not ch]
    earlier = [(f"chapter {c['number']}", p["text"]) for c in book["chapters"]
               if c["number"] < ch["number"] for p in (c.get("paragraphs") or [])]
    beats = plan_beats(ch, mat)
    shape = BOOK_SHAPES.get(book.get("story_type", ""), BOOK_SHAPES["fact_sandwich"])[1]
    system = (BOOK_RULES + (f"\n\nWRITING STYLE (rhythm and devices only; it never loosens the rules):\n"
                            f"{storytypes.writer_block(writer)}" if writer else "")
              + ("\nThis is the chapter on the tricks: you may explain a trick in general citing its T-ID, but every "
                 "claim about this case cites the evidence." if techniques_ok else ""))
    paras: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for k, beat in enumerate(beats):
        ctx.check_cancel()
        b0 = start + (end - start) * k / len(beats)
        b1 = start + (end - start) * (k + 1) / len(beats)
        block = chapter_material(mat, {**ch, "evidence_ids": beat["evidence_ids"] or ch["evidence_ids"][:3]},
                                 per_source=1800, max_sources=4)
        cite_ids = sorted({e["id"] for e in block["evidence"]} | {e["source_id"] for e in block["evidence"]}
                          | ({t["id"] for t in block.get("tricks", [])} if techniques_ok else set()))
        quote_ids = [e["id"] for e in block["evidence"] if e.get("kind") == "quote"]
        before = earlier + [(f"chapter {ch['number']}", p["text"]) for p in paras]
        said = ledger_text(before, limit=60, chars=7000)
        last = "\n\n".join(p["text"] for p in paras[-2:])
        label = f"Writing chapter {ch['number']} of {len(book['chapters'])}, part {k + 1} of {len(beats)}: {ch['title']}"
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": (
                f"Book: {book['title']}" + (f": {book['subtitle']}" if book.get("subtitle") else "")
                + f"\nHow the book is told: {shape}"
                + (f"\nAction line (every part moves it forward): {book['action_line']}" if book.get("action_line") else "")
                + (f"\nMain people: {', '.join(book['cast'])}" if book.get("cast") else "")
                + f"\nOther chapters: {'; '.join(others)}\n\nChapter {ch['number']}: {ch['title']}. What it covers: "
                f"{ch['purpose']}\nWrite part {k + 1} of {len(beats)} of this chapter, about {beat['words']} words. "
                f"Its job: {BEAT_JOBS[beat['job']]}\nCareful-topic rules: {json.dumps(mat.careful_rules())}\n\n"
                + (f"The chapter so far ends:\n{last}\n\n" if last else "")
                + (f"Already said (never re-tell these; refer back in a few words at most and add new detail):\n"
                   f"{said}\n\n" if said else "")
                + f"Material for this part (use nothing else):\n{json.dumps(block, ensure_ascii=False, indent=1)}")},
        ]
        schema = chapter_schema(cite_ids, quote_ids)
        schema["properties"]["paragraphs"]["minItems"] = 1
        answer = llm.chat_json(messages, schema, lenient=True, temperature=0.6,
                               on_text=ctx.writing(label, b0, b0 + (b1 - b0) * 0.6, beat["words"]))
        got, problems = _checked(answer, mat, block, names, techniques_ok, before)
        if problems:
            ctx.progress(f"Chapter {ch['number']}, part {k + 1}: {len(problems)} paragraph(s) need fixing",
                         b0 + (b1 - b0) * 0.6)
            fix = "\n".join(f"- Paragraph {i + 1}: {'; '.join(why)}" for i, why in problems)
            answer = llm.chat_json(messages + [
                {"role": "assistant", "content": json.dumps(answer, ensure_ascii=False)},
                {"role": "user", "content": "A program checked this part against the material and found problems:\n"
                                            f"{fix}\nReturn the part again. Fix ONLY those paragraphs using only the "
                                            "material (cut a detail rather than guess it); keep the other paragraphs "
                                            "word for word."}],
                schema, lenient=True, temperature=0.3,
                on_text=ctx.writing(f"Fixing chapter {ch['number']}, part {k + 1}", b0 + (b1 - b0) * 0.6, b1,
                                    beat["words"]))
            got, problems = _checked(answer, mat, block, names, techniques_ok, before)
        for i, why in sorted(problems, reverse=True):
            p = got.pop(i)
            dropped.append({"text": p["text"], "why": why})
        for p in got:
            p["beat"] = beat["job"]
        paras += got
    ch["beats"] = [{"job": b["job"], "evidence_ids": b["evidence_ids"]} for b in beats]
    ch["paragraphs"] = paras
    ch["dropped"] = dropped
    ch["written_at"] = utc_now()


def _checked(answer: dict[str, Any], mat: Material, block: dict[str, Any], names: set[str],
             techniques_ok: bool, earlier: list[tuple[str, str]] | None = None
             ) -> tuple[list[dict[str, Any]], list[tuple[int, list[str]]]]:
    from ..repeats import find_repeats
    before = list(earlier or [])
    paras, problems = [], []
    valid_quotes = {e["id"] for e in block["evidence"] if e.get("kind") == "quote"}
    for p in answer.get("paragraphs", []):
        text = (p.get("text") or "").strip()
        if not text:
            continue
        p = {"heading": (p.get("heading") or "").strip(), "text": text, "cites": list(p.get("cites", [])),
             "quote_after": p.get("quote_after") if p.get("quote_after") in valid_quotes else ""}
        hard, soft = check_paragraph(p, mat, block, names, techniques_ok)
        reps = find_repeats(text, before)
        if reps:     # a paragraph that mostly re-tells earlier text is removed; a stray sentence is flagged
            share = len(reps) / max(1, len(re.split(r"(?<=[.!?])\s+", text)))
            (hard if share >= 0.5 else soft).append(
                f"it repeats what {reps[0]['where']} already said: \"{reps[0]['sentence'][:90]}\"")
        before.append(("this chapter", text))
        p["warnings"] = soft
        if hard:
            problems.append((len(paras), hard))
        paras.append(p)
    return paras, problems


# ---------------------------------------------------------------- the stage
def book_dir(ep: Episode):
    d = ep.path("book")
    d.mkdir(parents=True, exist_ok=True)
    return d


def load(ep: Episode) -> dict[str, Any]:
    return read_json(ep.path("book", "book.json"), {}) or {}


def save(ep: Episode, book: dict[str, Any]) -> None:
    write_json(book_dir(ep) / "book.json", book)


def run(ctx: Context) -> None:
    ep = ctx.episode
    if not ep.path("research.json").exists():
        raise StageError("Approve Research first: the book is written only from the research.")
    mat = Material(_packet(ep))
    if not mat.evidence:
        raise StageError("No evidence is ticked on the Research page. Tick everything the book should use.")
    llm = Ollama(job="book")
    book = {} if ctx.options.get("fresh") else load(ep)
    if book and book.get("evidence_key") != mat.key():
        ctx.progress("The ticked evidence changed since the last book: starting it again.", 1)
        book = {}
    if not book.get("chapters"):
        ctx.progress("Planning the chapters from the research", 2)
        from .. import channelmemory
        stype, writer = book_type_and_writer(ep, ctx.options)
        book = {**make_outline(ctx, llm, mat, ep.title, stype, channelmemory.for_prompt(ep)),
                "evidence_key": mat.key(), "approved": False, "made_at": utc_now(), "material": mat.counts(),
                "story_type": stype.key, "story_type_name": stype.name, "writer": writer.key,
                "writer_name": writer.name}
        save(ep, book)
    book["approved"] = False
    from .. import storytypes
    writer = storytypes.writers().get(book.get("writer", "")) or book_type_and_writer(ep, ctx.options)[1]
    todo = [ch for ch in book["chapters"] if ch.get("paragraphs") is None]
    total = len(book["chapters"])
    for ch in todo:
        ctx.check_cancel()
        k = ch["number"] - 1
        start, end = 10 + 82 * k / total, 10 + 82 * (k + 1) / total
        ctx.progress(f"Writing chapter {ch['number']} of {total}: {ch['title']}", start)
        write_chapter(ctx, llm, mat, book, ch, start, end, writer)
        save(ep, book)                     # chapter by chapter, so a stopped job carries on
    ctx.progress("Laying out the PDF", 93)
    pdf = make_pdf(ep, book, mat)
    book["pdf"] = ep.rel(pdf)
    book["written_at"] = utc_now()
    save(ep, book)
    (book_dir(ep) / "review.md").write_text(review_notes(ep, book), encoding="utf-8")
    s = stats(book)
    ctx.progress(f"Book written: {s['chapters']} chapters, about {s['words']:,} words ({s['pages']} pages). "
                 f"{s['dropped']} paragraph(s) were removed because the sources didn't back them. Read it, then "
                 "press Approve the book.", 100)


def stats(book: dict[str, Any]) -> dict[str, int]:
    chs = book.get("chapters", [])
    words = sum(len(p["text"].split()) for ch in chs for p in ch.get("paragraphs") or [])
    return {"chapters": len([c for c in chs if c.get("paragraphs")]), "words": words,
            "pages": max(1, round(words / 300)),
            "dropped": sum(len(ch.get("dropped", [])) for ch in chs),
            "warnings": sum(len(p.get("warnings", [])) for ch in chs for p in ch.get("paragraphs") or []),
            "unwritten": sum(1 for c in chs if c.get("paragraphs") is None)}


def references(book: dict[str, Any], mat: Material) -> tuple[list[str], dict[str, int]]:
    """Sources numbered in the order the book first cites them."""
    order: dict[str, int] = {}
    for ch in book.get("chapters", []):
        for p in ch.get("paragraphs") or []:
            cites = list(p["cites"]) + ([p["quote_after"]] if p.get("quote_after") else [])
            for c in cites:
                sid = mat.source_of(c)
                if sid and sid not in order:
                    order[sid] = len(order) + 1
    return list(order), order


def make_pdf(ep: Episode, book: dict[str, Any], mat: Material | None = None, draft: bool | None = None):
    from .. import bookpdf
    mat = mat or Material(_packet(ep))
    out = book_dir(ep) / "book.pdf"
    kf = sorted({k["kf_ep"] for c in mat.claims.values() for k in c.get("kf_episodes", [])})
    bookpdf.build(out, book, mat, draft=not book.get("approved") if draft is None else draft, kf_episodes=kf)
    return out


def approve(ep: Episode) -> None:
    """You read the book and it's good: make the final PDF (no DRAFT marks)."""
    from .. import pipeline
    book = load(ep)
    pipeline.approve(ep, "book")
    book["approved"] = True
    book["approved_at"] = utc_now()
    save(ep, book)
    make_pdf(ep, book)
    save(ep, book)


def check(ep: Episode) -> list[Check]:
    book = load(ep)
    if not book or not book.get("chapters"):
        return [Check(BLOCK, "No book yet. Press Write the book.")]
    s = stats(book)
    if s["unwritten"]:
        return [Check(BLOCK, f"{s['unwritten']} chapter(s) aren't written yet. Press Write the book to finish.")]
    if not book.get("pdf") or not ep.abs(book["pdf"]).exists():
        return [Check(BLOCK, "The PDF is missing. Press Write the book to make it again.")]
    out = [Check(OK, f"{s['chapters']} chapters, about {s['words']:,} words (about {s['pages']} pages). Read every "
                     "page before approving.")]
    empty = [c["title"] for c in book["chapters"] if c.get("paragraphs") == []]
    if empty:
        out.append(Check(WARN, f"{len(empty)} chapter(s) came out empty because nothing in them could be backed "
                               f"up, so they're left out: {empty[0]}"))
    if s["dropped"]:
        out.append(Check(WARN, f"{s['dropped']} paragraph(s) were removed because the sources didn't back them "
                               "(listed at the end of book/review.md)."))
    if s["warnings"]:
        out.append(Check(WARN, f"{s['warnings']} name(s) aren't in the cited material: check them "
                               "(book/review.md)."))
    return out


def review_notes(ep: Episode, book: dict[str, Any]) -> str:
    """book/review.md: what to check before approving."""
    lines = [f"# Review notes: {book.get('title', '')}", "",
             "Check these before you press Approve the book.", ""]
    for ch in book.get("chapters", []):
        warn = [(p, w) for p in ch.get("paragraphs") or [] for w in p.get("warnings", [])]
        if not warn and not ch.get("dropped"):
            continue
        lines.append(f"## Chapter {ch['number']}: {ch['title']}")
        for p, w in warn:
            lines.append(f"- Check: {w} - in \"{p['text'][:100]}...\"")
        for d in ch.get("dropped", []):
            lines.append(f"- Removed: \"{d['text'][:160]}...\" because {'; '.join(d['why'])}")
        lines.append("")
    if book.get("questions"):
        lines += ["## Questions to look up (press Look up questions on the Stories page)"]
        lines += [f"- {q['question']}" for q in book["questions"]] + [""]
    if len(lines) == 4:
        lines.append("Nothing was removed or flagged.")
    return "\n".join(lines) + "\n"
