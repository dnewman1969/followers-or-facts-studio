"""Stories: two different ways to tell the tale and take the lie apart, each as a short video.

Each story comes with the local AI's estimate of how long its video should be (a YouTube Short is up to
3 minutes); choosing a story sets the video length to it. A book-sized subject can also become a long
documentary video ("the movie", make_movie_story) built from the book's chapters.

Each option has a title, a one-line pitch, the angle it takes, and a beat-by-beat
outline that names the evidence each beat leans on. You pick one; you can ask for
any option to be rewritten with your notes. The chosen story goes to the Script stage.
"""

from __future__ import annotations

import json
from typing import Any

from .. import storytypes, techniques
from ..scriptfmt import ROLES
from ..episode import Episode
from ..llm import Ollama
from ..util import StageError, read_json, utc_now, write_json
from .base import BLOCK, OK, WARN, Check, Context

BEAT_SCHEMA = {
    "type": "object",
    "properties": {
        "role": {"type": "string", "enum": list(ROLES[:-1])},
        "beat": {"type": "string"},
        "evidence_ids": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["role", "beat", "evidence_ids"],
}
STORY_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "logline": {"type": "string"},
        "angle": {"type": "string"},
        "opening_hook": {"type": "string"},
        "beats": {"type": "array", "items": BEAT_SCHEMA},
        "owl_moments": {"type": "array", "items": {"type": "string"}},
        "thumbnail_words": {"type": "string"},
        "techniques": {"type": "array", "items": {"type": "string", "enum": list(techniques.TECHNIQUES)}},
        "length_seconds": {"type": "integer", "minimum": 30, "maximum": 600},
        "length_why": {"type": "string"},
    },
    "required": ["title", "logline", "angle", "opening_hook", "beats", "owl_moments", "thumbnail_words",
                 "techniques", "length_seconds", "length_why"],
}
THREE_SCHEMA = {"type": "object", "properties": {"stories": {"type": "array", "items": STORY_SCHEMA}},
                "required": ["stories"]}

ANGLES = [
    "How the lie was built: tell it like a con, beat by beat. The kernel of truth at the start, who saw "
    "an opportunity, the twist they put on it, how they spread it, what they gained, who paid the price, "
    "the reveal of what really happened, and the lesson.",
    "Follow the money: tell it through who sold the fear and what they earned, receipts first.",
    "Then and now: walk the timeline from the first rumor to what the record shows today, and what it did "
    "to real people (respectfully; courts and documents only for victims).",
]
RULES = """You plan stories for "Followers or Facts", a fact-check channel narrated by Professor Owlbert
McFinnegan, a warm, curious cartoon owl professor and the mascot of Critical Thinking. The goal is not
only to correct one claim but to show HOW the information was twisted into a lie, so viewers learn to
spot the trick next time.
Rules: use only facts in the evidence list; never invent people or characters (no made-up kids, neighbors or
experts: the only character is Owlbert, everyone else is a real person or group in the evidence); never put
quote marks around anything but a quote copied exactly from the evidence; every beat names the evidence IDs it relies on
(E-numbers and S-IDs from the list, nothing else); never mock the people who believed it;
aim criticism at the people who sold it; respect every careful-topic rule; plain words.
Every story must have beats for: claim (what was claimed), record (what the record says),
benefit (who benefited), harm (what it did to people), and end with a verdict.
owl_moments: 2-4 places where Owlbert appears on camera (e.g. "opens at his desk").
Structure: open on a true, surprising fact (not the myth). Show the myth only once, clearly as a claim
someone sold, attributed to its seller. Then show how it was built. Include a "tell" beat where Owlbert
names the manipulation trick (pick 1 or 2 from the techniques list) with a harmless everyday example,
then shows it in this case. End on the fact again. Link beats with "but" or "therefore", never "and then".
techniques: the keys of the 1-2 tricks this story teaches.
length_seconds: how long THIS story's short video needs to tell it well, with no padding: count the beats, the
evidence each needs and the trick (about 150 spoken words a minute). Up to 180 for a YouTube Short; up to 600
for a short video. length_why: one line on why.
thumbnail_words: 2 to 4 big, punchy words for the YouTube thumbnail that make people curious and fit
this story's angle (e.g. "FEAR FOR SALE", "WHO GOT PAID?"). No names of private people, no victims.
"""


def _packet(ep: Episode) -> dict[str, Any]:
    from .research import selected
    return selected(read_json(ep.path("research.json")) or {})


def style_note(ep: Episode) -> str:
    c = ep.creative()
    humor = ["no jokes at all", "a light touch of warmth", "some gentle humor aimed at the trick or the sellers",
             "plenty of satire, always punching up at the sellers, never at believers or victims"][c["humor"]]
    return (f"\nHumor: {humor}.\n"
            f"Tricks you can name: {json.dumps(techniques.for_prompt())}\n")


def evidence_for_prompt(ep: Episode) -> str:
    packet = _packet(ep)
    items = []
    for c in packet.get("claims", []):
        items.append({"claim_id": c["claim_id"], "claim": c["short_title"], "verdict": c["falsity_status"],
                      "summary": c.get("claim_summary"), "harm": c.get("harm_summary"),
                      "who_benefited": c.get("who_benefited")})
    evidence = [{"id": e["id"], "claim_id": e["claim_id"], "kind": e.get("kind"), "source_type": e.get("type"),
                 "title": e.get("title"), "date": e.get("date"), "quote": e.get("quote") or None,
                 "what_it_shows": e.get("summary") or e.get("supports")}
                for e in packet.get("evidence", [])]
    return json.dumps({"subject": packet.get("subject"), "claims": items, "evidence": evidence,
                       "careful_rules": [f"{r['rule']}: {r.get('note') or ''}"
                                         for r in packet.get("restrictions", [])]},
                      ensure_ascii=False, indent=1)


def _valid_ids(ep: Episode) -> set[str]:
    packet = _packet(ep)
    ids = {e["id"] for e in packet.get("evidence", [])}
    for c in packet.get("claims", []):
        ids |= {s["source_id"] for s in c.get("sources", []) if s.get("is_primary")}
    return ids


def thumbnail_words(text: str) -> str:
    """At most four words, upper case, tidy."""
    words = [w.strip(" .,;:\"'") for w in (text or "").split()]
    return " ".join([w for w in words if w][:4]).upper()


STORY_COUNT = 2
SHORT_MAX = 180          # a YouTube Short is up to 3 minutes


def _clean(story: dict[str, Any], valid: set[str]) -> dict[str, Any]:
    story["length_seconds"] = max(30, min(600, int(story.get("length_seconds") or 120)))
    for b in story.get("beats", []):
        b["evidence_ids"] = [e for e in b.get("evidence_ids", []) if e in valid]
    story["thumbnail_words"] = thumbnail_words(story.get("thumbnail_words") or story.get("title", ""))
    story["techniques"] = [t for t in story.get("techniques", []) if t in techniques.TECHNIQUES][:2]
    return story


def run(ctx: Context) -> None:
    ep = ctx.episode
    if not ep.path("research.json").exists():
        raise StageError("Approve Research first.")
    if not _packet(ep).get("evidence"):
        raise StageError("No evidence is ticked on the Research page. Tick what this video should use.")
    data = read_json(ep.path("stories.json"), {}) or {}
    valid = _valid_ids(ep)
    llm = Ollama(job="stories")
    rewrite = ctx.options.get("rewrite")  # {"index": 1, "notes": "..."}
    if rewrite:
        i = int(rewrite["index"])
        old = data["options"][i]
        ctx.progress(f"Rewriting story {i + 1} with your notes", 20)
        new = llm.chat_json([
            {"role": "system", "content": RULES},
            {"role": "user", "content": f"{style_note(ep)}Evidence:\n{evidence_for_prompt(ep)}\n\nHere is a story plan:\n"
                                        f"{json.dumps(old, ensure_ascii=False)}\n\nRewrite it with these notes "
                                        f"from the producer: {rewrite['notes']}"},
        ], STORY_SCHEMA, temperature=0.6, on_text=ctx.writing(f"Rewriting story {i + 1}", 20, 95, 450))
        new = _clean(new, valid)
        for key in ("story_type", "writer", "angle_hint"):
            if old.get(key):
                new[key] = old[key]
        new["revision"] = old.get("revision", 1) + 1
        new["notes_applied"] = rewrite["notes"]
        data["options"][i] = new
        data.pop("chosen", None)
    else:
        from . import storysize
        ctx.progress("Sizing up the story: a Short, one video, a series or a book?", 3)
        size = storysize.assess(ep, _packet(ep), evidence_for_prompt(ep), llm,
                                on_text=ctx.writing("Sizing up the story", 3, 9, 250))
        ctx.progress(f"Size: {storysize.FORMATS[size['format']]} (about {size['video_seconds'] / 60:.0f} min of "
                     f"video, or a {size['pages']}-page book).", 10)
        options: list[dict[str, Any]] = []
        picks = storytypes.pick(ep.creative(), f"{ep.project_id}-{utc_now()}", STORY_COUNT)
        step = 88 / len(picks)
        for n, (stype, writer) in enumerate(picks):
            ctx.check_cancel()
            ctx.progress(f"Writing story option {n + 1} of {len(picks)}: {stype.name}, written as {writer.name}",
                         10 + n * step)
            from .. import channelmemory
            earlier = channelmemory.for_prompt(ep, "story")
            other = ("\n\nAnother story was already planned; make this one clearly different (a different opening, "
                     "a different main piece of evidence up front, a different angle):\n"
                     + "\n".join(f"- {o['title']}: {o['angle']} Opening: {o['opening_hook']}" for o in options)) \
                if options else ""
            story = llm.chat_json([
                {"role": "system", "content": RULES + "\n" + storytypes.SHARED_RULES},
                {"role": "user", "content": f"{style_note(ep)}Evidence:\n{evidence_for_prompt(ep)}\n\nPlan ONE story "
                                            f"as this story type. Its beats follow the beat sheet in order (one beat each; "
                                            f"use the beat sheet's roles):\n{stype.sheet()}\n\nThe script will be "
                                            f"written by {writer.name}: {writer.sounds_like} Write the logline and "
                                            "the opening hook with that flavor. It becomes a short video on the "
                                            "subject." + other + (f"\n\n{earlier}" if earlier else "")},
            ], STORY_SCHEMA, temperature=0.8,
                on_text=ctx.writing(f"Writing story {n + 1} of {len(picks)}", 10 + n * step, 10 + (n + 1) * step - 2,
                                    450))
            story = _clean(story, valid)
            story["angle_hint"] = f"{stype.name}: {stype.blurb}"
            story["story_type"], story["writer"] = stype.key, writer.key
            story["revision"] = 1
            options.append(story)
        data = {"options": options, "made_at": utc_now(), "set_id": f"{ep.project_id}-{utc_now()}",
                "size": size["format"]}
    write_json(ep.path("stories.json"), data)
    ctx.progress("Stories ready. Pick one.", 100)


def choose(ep: Episode, index: int) -> None:
    data = read_json(ep.path("stories.json"))
    if not data or not 0 <= index < len(data["options"]):
        raise StageError("No such story option.")
    data["chosen"] = index
    write_json(ep.path("stories.json"), data)
    story = data["options"][index]
    if story.get("length_seconds"):          # the video length follows the chosen story
        ep.set_creative(minutes=max(1.0, round(story["length_seconds"] / 30) / 2))


# ---------------------------------------------------------------- the book as a long video ("the movie")
PART_ROLE = {"introduction": "claim", "origin": "record", "players": "benefit", "spread": "record",
             "record": "record", "profit": "benefit", "damage": "harm", "techniques": "tell", "verdict": "verdict"}


def movie_minutes(ep: Episode) -> int:
    """How long the documentary made from the book should run: about 40% of the book's words narrated at
    150 a minute (a film condenses a book), or the full-telling estimate before the book is written;
    30 to 120 minutes."""
    from . import book as bookmod
    from . import storysize
    b = bookmod.load(ep)
    words = bookmod.stats(b)["words"] if b.get("chapters") else 0
    if words:
        mins = words * 0.4 / 150
    else:
        mins = (storysize.load(ep).get("video_seconds") or 1800) / 60
    return int(max(30, min(120, round(mins / 5) * 5)))


def make_movie_story(ep: Episode) -> int:
    """Add the book's chapters as a story ("the movie") and choose it. Returns its index."""
    from . import book as bookmod
    b = bookmod.load(ep)
    if not b.get("chapters"):
        raise StageError("Write the book first (or at least let it plan its chapters): the movie follows the book's "
                         "chapters.")
    valid = _valid_ids(ep) | {e for ch in b["chapters"] for e in ch.get("evidence_ids", [])}
    first = b["chapters"][0]
    beats = [{"role": "intro", "beat": "Cold open: the most striking true fact from the record, before the claim.",
              "evidence_ids": [e for e in first.get("evidence_ids", []) if e in valid][:2]}]
    for ch in b["chapters"]:
        beats.append({"role": PART_ROLE.get(ch["part"], "record"), "beat": f"{ch['title']}: {ch.get('purpose', '')}",
                      "evidence_ids": [e for e in ch.get("evidence_ids", []) if e in valid], "chapter": ch["number"]})
    must = {"claim": "What was claimed, once, attributed to who sold it.",
            "record": "What the record really shows.", "benefit": "Who profited from it, documented.",
            "harm": "What it did to real people, documented and respectful."}
    for role, how in must.items():            # every video answers all four, whatever chapters the book has
        if not any(x["role"] == role for x in beats):
            at = next((k for k, x in enumerate(beats) if x["role"] in ("tell", "verdict")), len(beats))
            if role == "claim":
                at = 1
            ev = [e for ch in b["chapters"] for e in ch.get("evidence_ids", []) if e in valid][:3]
            beats.insert(at, {"role": role, "beat": how, "evidence_ids": ev})
    if not any(x["role"] == "verdict" for x in beats):
        beats.append({"role": "verdict", "beat": "The verdict.", "evidence_ids": []})
    minutes = movie_minutes(ep)
    creative = ep.creative()
    movie = {"title": b.get("title") or ep.title, "logline": b.get("subtitle") or "The full story, chapter by chapter.",
             "angle": "The full documentary, following the book chapter by chapter.",
             "opening_hook": beats[0]["beat"], "beats": beats,
             "owl_moments": ["opens the film at his desk", "introduces each chapter", "delivers the verdict"],
             "thumbnail_words": thumbnail_words(b.get("title") or ep.title), "techniques": [],
             "story_type": creative.get("story_type") if creative.get("story_type") in storytypes.STORY_TYPES
             else storytypes.DEFAULT_TYPE, "writer": creative.get("writer") if creative.get("writer") != "auto" else "",
             "format": "movie", "length_seconds": minutes * 60, "revision": 1,
             "angle_hint": f"The movie: about {minutes} minutes from the book's {len(b['chapters'])} chapters"}
    data = read_json(ep.path("stories.json"), {}) or {"options": [], "made_at": utc_now()}
    data["options"] = [o for o in data.get("options", []) if o.get("format") != "movie"] + [movie]
    data["chosen"] = len(data["options"]) - 1
    write_json(ep.path("stories.json"), data)
    ep.set_creative(minutes=float(minutes))
    return data["chosen"]


def chosen(ep: Episode) -> dict[str, Any] | None:
    data = read_json(ep.path("stories.json")) or {}
    if data.get("chosen") is None:
        return None
    return data["options"][data["chosen"]]


def used_by(ep: Episode) -> dict[int, list[str]]:
    """Which of these stories other videos already use (videos started from the same set)."""
    from ..episode import list_episodes, Episode as E
    data = read_json(ep.path("stories.json")) or {}
    if not data.get("set_id"):
        return {}
    out: dict[int, list[str]] = {}
    for row in list_episodes():
        if row["project_id"] == ep.project_id:
            continue
        other = read_json(E.load(row["project_id"]).path("stories.json")) or {}
        if other.get("set_id") == data["set_id"] and other.get("chosen") is not None:
            out.setdefault(int(other["chosen"]), []).append(row["project_id"])
    return out


def check(ep: Episode) -> list[Check]:
    data = read_json(ep.path("stories.json"))
    if not data:
        return [Check(BLOCK, "No stories yet. Press Create stories.")]
    if data.get("chosen") is None:
        return [Check(BLOCK, "Pick one of the stories.")]
    story = data["options"][data["chosen"]]
    out = []
    roles = {b["role"] for b in story["beats"]}
    for need in ("claim", "record", "benefit", "harm"):
        if need not in roles:
            out.append(Check(BLOCK, f"The chosen story has no '{need}' beat. Ask for a rewrite."))
    bare = [b["beat"][:50] for b in story["beats"] if b["role"] in ("record", "claim") and not b["evidence_ids"]]
    if bare:
        out.append(Check(WARN, f"{len(bare)} fact beat(s) don't name evidence yet: {bare[0]}..."))
    out.append(Check(OK, f"Chosen: \"{story['title']}\" ({len(story['beats'])} beats)."))
    return out
