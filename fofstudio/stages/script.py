"""Script: Owlbert's narration, written the way a film-maker works, not in one go.

0. Treatment: the writer works as a cinematic story architect, not a report writer (treatment.py): film
   title, logline, opening scene, three acts, the real characters, the major revelations (each with its
   proof) and the emotional arc. Every scene then gets its place in the arc (hook, setup, rising tension,
   discovery, climax, resolution, future implications) and the revelation it must land.
1. Outline: the local AI plans the scenes from the chosen story, the ticked evidence and the
   video style: the fact first, the myth shown once as a claim, how the lie was built, the trick
   named ("tell"), the real story, the question to ask next time, the fact again. Each scene gets
   a word budget so the video comes out as long as you asked.
2. Scenes: one call per scene, in Owlbert's voice and the style's tone, with only that scene's
   evidence in front of it and the end of the previous scene for flow.
3. Fix-ups: a scene that's too short or uses stock phrases gets one rewrite.
Every scene still lists the claims, sources and quotes it relies on, and the checks are the same:
nothing reaches the screen without a source. You can edit script.md by hand and press Save.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .. import db
from ..episode import Episode
from ..llm import Ollama
from ..scriptfmt import CHANGES, MOODS, MOVES, PROPS, ROLES, parse, quotes_in, render
from ..util import StageError, normalize_for_match, read_json, reading_grade, utc_now, write_json, write_text
from .base import BLOCK, OK, WARN, Check, Context

WORDS_PER_MINUTE = 150   # Owlbert's average; each style has its own pace (styles.py)

SCRIPT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "scenes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "role": {"type": "string", "enum": list(ROLES[:-1])},
                    "visual": {"type": "string"},
                    "narration": {"type": "string"},
                    "on_screen_text": {"type": "string"},
                    "claim_ids": {"type": "array", "items": {"type": "string"}},
                    "source_ids": {"type": "array", "items": {"type": "string"}},
                    "excerpt_ids": {"type": "array", "items": {"type": "integer"}},
                },
                "required": ["role", "visual", "narration", "on_screen_text",
                             "claim_ids", "source_ids", "excerpt_ids"],
            },
        },
    },
    "required": ["title", "scenes"],
}

OUTLINE_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "central_question": {"type": "string"},
        "gap_questions": {"type": "array", "maxItems": 6, "items": {"type": "string"}},
        "scenes": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "role": {"type": "string", "enum": list(ROLES[:-2])},
                "purpose": {"type": "string"},
                "link": {"type": "string", "enum": ["open", "but", "therefore"]},
                "claim_ids": {"type": "array", "items": {"type": "string"}},
                "source_ids": {"type": "array", "items": {"type": "string"}},
                "excerpt_ids": {"type": "array", "items": {"type": "integer"}},
                "owl_on_camera": {"type": "boolean"},
                "visual_idea": {"type": "string"},
            },
            "required": ["role", "purpose", "link", "claim_ids", "source_ids", "excerpt_ids", "owl_on_camera",
                         "visual_idea"],
        }},
    },
    "required": ["title", "central_question", "scenes"],
}
SCENE_SCHEMA = {
    "type": "object",
    "properties": {
        "narration": {"type": "string"},
        "visual": {"type": "string"},
        "on_screen_text": {"type": "string"},
        "claim_ids": {"type": "array", "items": {"type": "string"}},
        "source_ids": {"type": "array", "items": {"type": "string"}},
        "excerpt_ids": {"type": "array", "items": {"type": "integer"}},
    },
    "required": ["narration", "visual", "on_screen_text", "claim_ids", "source_ids", "excerpt_ids"],
}
# written after the narration, so the quoted words can be copied from it
SCENE_SCHEMA["properties"]["music"] = {"type": "object", "properties": {
    "mood": {"type": "string", "enum": list(MOODS)},
    "energy": {"type": "integer", "minimum": 1, "maximum": 5},
    "change": {"type": "string", "enum": list(CHANGES)},
    "drop_before": {"type": "string"},
    "sting_at": {"type": "string"}},
    "required": ["mood", "energy", "change", "drop_before", "sting_at"]}
SCENE_SCHEMA["properties"]["owlbert"] = {"type": "array", "maxItems": 3, "items": {"type": "object", "properties": {
    "move": {"type": "string", "enum": list(MOVES)},
    "prop": {"type": "string", "enum": ["", *PROPS]},
    "at": {"type": "string"}},
    "required": ["move", "prop", "at"]}}
SCENE_SCHEMA["required"] += ["music", "owlbert"]

DIRECTING = """Music and Owlbert's moves for this scene (the program does the timing from your words):

MUSIC: the mood under this scene, chosen by the scene's ROLE, never by the verdict (music must not tell
the viewer what to think before the evidence does).
  intro: curious, energy 4 · claim: tense, 3 · record: investigative, 2 · benefit: warm, 2 · harm: somber, 2
  (or change "silence") · tell: playful, 4 (warm if the topic is careful) · toolkit: encouraging, 3 ·
  verdict: resolved, 3 · outro: theme, 4.
  change: "continue" when this scene carries on the same thought as the last one (most scenes in the same
  section), "crossfade" for a new section, "sting" for a reveal (set sting_at to the words it lands on, at
  most one sting every few scenes), "hard_cut" for a sharp change, "silence" for no music.
  drop_before: words copied exactly from your narration where the music stops so the voice arrives alone
  (always the verdict sentence in the verdict scene; also a claim's exact quote). Otherwise "".
OWLBERT: 0 to 2 moves, each tied to 2-6 words copied EXACTLY from your narration (put moves on the new
fact, the number, the name or the source, never on "I", "we" or "this"). Empty is fine: never add motion
just to fill a scene.
  point: point at the evidence while it's on screen (claim, record, benefit, toolkit).
  glasses: push up his spectacles before reading a quote closely.
  hat_trick + prop: pulls something out of his cap as the transition into what he's talking about:
    document = the source he's about to quote (record or claim scenes), card = the trick's name (tell),
    bulb = the question to ask (toolkit), magnifier = "let's look closer". Not two scenes in a row.
  think: wing to chin before a question. surprised: a little jump at a number or contradiction (only about
  the trick or the seller). hat_tip: hello or thanks to a source. stamp: the verdict stamp, on the verdict
  word, verdict scene only. swoop: flies across the screen at a big section change. flourish: spreads his
  wings (intro title or toolkit). fly_in: first scene only. fly_out: last scene only. solemn: cap to his
  chest, for harm to real people (the only move allowed in a harm scene besides point and glasses).
  Never react to the people who believed it; react with the viewer, to the trick or the seller.
  Example (record scene): narration "...The answer is in the original agency caption. It's dated May 2009..."
  -> [{"move": "hat_trick", "prop": "document", "at": "the original agency caption"},
      {"move": "glasses", "prop": "", "at": "It's dated May 2009"}]"""

FACT_ROLES = ("claim", "record", "benefit", "harm")


def known_ids(packet: dict[str, Any]) -> dict[str, list]:
    """Every claim, source and quote ID the writer may use (only the ticked evidence)."""
    claims = [c["claim_id"] for c in packet.get("claims", [])]
    sources = list(dict.fromkeys(s["source_id"] for c in packet.get("claims", []) for s in c["sources"]))
    quotes = list(dict.fromkeys(int(e["excerpt_id"]) for c in packet.get("claims", []) for e in c["excerpts"]))
    return {"claim_ids": claims, "source_ids": sources, "excerpt_ids": quotes}


def _id_field(values: list, kind: str) -> dict[str, Any]:
    item: dict[str, Any] = {"type": kind}
    if values:
        item["enum"] = values   # the model can only pick real IDs, never invent one
    return {"type": "array", "items": item, **({} if values else {"maxItems": 0})}


def with_known_ids(schema: dict[str, Any], ids: dict[str, list], inside_scenes: bool = False) -> dict[str, Any]:
    import copy
    out = copy.deepcopy(schema)
    props = out["properties"]["scenes"]["items"]["properties"] if inside_scenes else out["properties"]
    props["claim_ids"] = _id_field(ids["claim_ids"], "string")
    props["source_ids"] = _id_field(ids["source_ids"], "string")
    props["excerpt_ids"] = _id_field(ids["excerpt_ids"], "integer")
    return out


def drop_unknown(sc: dict[str, Any], ids: dict[str, list]) -> list[str]:
    """Remove any ID that isn't in the ticked evidence (E-numbers are kept for fix_refs to read)."""
    dropped = []
    for key in ("claim_ids", "source_ids", "excerpt_ids"):
        keep = []
        for v in sc.get(key) or []:
            sv = str(v).strip()
            ok = (sv.isdigit() and int(sv) in ids["excerpt_ids"]) if key == "excerpt_ids" else \
                (sv in ids[key] or (key == "source_ids" and re.fullmatch(r"[Ee]\d+", sv)
                                    and int(sv[1:]) in ids["excerpt_ids"]))
            (keep if ok else dropped).append(v)
        sc[key] = keep
    return [str(d) for d in dropped]


OWLBERT = """Owlbert's voice:
- A warm, curious owl professor, the mascot of Critical Thinking. Smart, never smug. Talks to the viewer
  like a bright twelve-year-old, never down to them.
- Mixes short punchy lines (four or five words) with longer flowing ones. Asks the viewer questions.
- Little habits: "Hoo." when something doesn't add up; pushes his spectacles up before a reveal.
- Shows, doesn't tell: instead of "this was shocking", give the number, the date, the receipt that makes
  the viewer feel it.
- Never sneers, never mocks believers ("anyone can be fooled by this, that's why it works"), never says
  "folks", "in today's video", "buckle up", "let's dive in", "delve", "tapestry", "it's important to note",
  "game-changer", "little did they know", "in conclusion", "the truth is out there"."""
from ..repeats import STOCK as STOCK_PHRASES  # noqa: E402 - the shared list of overused phrases

VOICE_RULES = """You write the narration of a true-story film for "Followers or Facts", a kind fact-check channel
that tells real stories like documentaries. The narrator is Professor Owlbert McFinnegan, a warm, curious owl
professor. The story is cinematic; the facts are fixed.

Hard rules (breaking any of them makes the script unusable):
1. Use ONLY facts from the research packet. Never invent a date, number, name, quote or source.
   Never invent people or characters (no made-up kids, neighbors, experts or "a man named..."): the only
   character is Owlbert; everyone else is a real person or group from the packet.
2. Every scene that states a fact lists the claim_ids and source_ids it relies on. source_ids
   are the "source_id" values in the packet (they start with "S-"), only ones listed under that
   claim. Quote numbers like E14 are NOT source IDs: put the number (14) in excerpt_ids instead.
3. Direct quotes: only copy text from a verified quote (by its excerpt_id) word for word,
   inside double quotes, and list that excerpt_id. Otherwise paraphrase with no quote marks (single quote
   marks count as quote marks too). Never put quote marks around a summary of a source, a shortened quote,
   or a made-up example line (what an ad, a seller or a rumor might say, or a question to ask yourself):
   write those as plain speech, e.g.  An ad yells: only ten minutes left!
4. Plain 6th-grade English: short sentences, everyday words, explain any jargon.
5. Never mock the people who believed the claim. Aim criticism at the people who sold it.
6. If a claim's verdict is "unverified" or "contested", say so plainly. Don't call it false.
7. Careful topics: follow every restriction listed in the packet (for victims: courts and
   documents only, no names of private people, no description of the violence).
8. The video must answer four questions, each in at least one scene with that role:
   claim (what was claimed), record (what the record says), benefit (who benefited),
   harm (what it did to people). Start with an "intro" scene and end with a "verdict" scene.
   A "tell" scene names the manipulation trick; a "toolkit" scene gives the question to ask next time.
   Show the myth only once, clearly as something someone sold; open and close on the fact.
9. VISUAL describes a picture for an illustrator: scrapbook documentary style, objects,
   places, documents, moods. No real people's faces, no readable text, no logos.
10. ON_SCREEN_TEXT is at most 8 words (a date, a place, a short label) or empty."""


def selected_packet(ep: Episode) -> dict[str, Any]:
    from .research import selected
    return selected(read_json(ep.path("research.json")) or {"claims": [], "evidence": []})


def _excerpt_map(packet: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(e["excerpt_id"]): e for c in packet.get("claims", []) for e in c.get("excerpts", [])}


def fix_refs(sc: dict[str, Any], packet: dict[str, Any], fill: bool = True) -> list[str]:
    """Tidy one scene's SOURCES line: quote numbers written as sources (E14) become the quote's
    source plus the quote number, and a scene with sources but no claims gets the claims those
    sources belong to. Returns notes about anything it had to fill in."""
    notes = []
    excerpts = _excerpt_map(packet)
    claim_of = {s["source_id"]: c["claim_id"] for c in packet.get("claims", []) for s in c["sources"]}
    srcs, quotes = [], [str(q).lstrip("Ee") for q in sc.get("excerpt_ids", [])]
    for ref in sc.get("source_ids", []):
        ref = str(ref).strip()
        m = re.fullmatch(r"[Ee](\d+)", ref)
        if m:
            quotes.append(m.group(1))
            if m.group(1) in excerpts:
                ref = excerpts[m.group(1)]["source_id"]
            else:
                srcs.append(ref)  # leave it for the check to flag
                continue
        srcs.append(ref)
    for q in quotes:  # a quote implies its source
        if q in excerpts and excerpts[q]["source_id"] not in srcs:
            srcs.append(excerpts[q]["source_id"])
    sc["source_ids"] = list(dict.fromkeys(srcs))
    sc["excerpt_ids"] = list(dict.fromkeys(quotes))
    if sc["source_ids"] and not sc.get("claim_ids"):
        sc["claim_ids"] = list(dict.fromkeys(claim_of[s] for s in sc["source_ids"] if s in claim_of))
    if fill and sc.get("claim_ids") and not sc["source_ids"]:
        for cid in sc["claim_ids"]:
            c = next((c for c in packet.get("claims", []) if c["claim_id"] == cid), None)
            if c and c["sources"]:
                best = sorted(c["sources"], key=lambda s: (not s.get("is_primary"), s["source_id"]))[:2]
                sc["source_ids"] += [s["source_id"] for s in best]
                notes.append(f"{sc.get('scene_id', '?')}: no sources given for {cid}; used "
                             f"{', '.join(s['source_id'] for s in best)} (your ticked evidence for it). Check they fit.")
    return notes


def _packet_for_prompt(packet: dict[str, Any]) -> str:
    slim = {"arc": (packet.get("arc") or {}).get("title"), "restrictions": [
        f"{r['rule']} ({r['subject_id']}): {r.get('note') or ''}" for r in packet["restrictions"]],
        "claims": []}
    for c in packet["claims"]:
        slim["claims"].append({
            "claim_id": c["claim_id"], "title": c["short_title"], "summary": c.get("claim_summary"),
            "first_known_year": c.get("first_known_year"), "verdict": c["falsity_status"],
            "harm": c.get("harm_summary"), "who_benefited": c.get("who_benefited"),
            "society_effect": c.get("society_effect"),
            "people": [f"{p['name']} ({p['link_role']})" for p in c["people"]],
            "sources": [{"source_id": s["source_id"], "type": s["source_type"], "title": s["title"],
                         "publisher": s.get("publisher"), "date": s.get("date"),
                         "what_it_shows": s.get("summary") or s.get("supports_field") or ""}
                        for s in c["sources"]],
            "verified_quotes": [{"excerpt_id": e["excerpt_id"], "source_id": e["source_id"],
                                 "text": e["text"]} for e in c["excerpts"]],
        })
    return json.dumps(slim, ensure_ascii=False, indent=1)


def _scene_count(minutes: float) -> int:
    """About one scene a minute (more for short videos); a long documentary (the movie) gets up to 90."""
    return max(6, min(16 if minutes <= 20 else 90, round(minutes * 1.2) + 2))


def scene_slots(stype, n: int) -> list:
    """The beat sheet spread over n scenes (at least one per beat; big beats get more), in order."""
    from ..storytypes import Beat
    beats = list(stype.beats)
    must = {"claim": ("The claim", "Warning, then the claim once, attributed to who sold it."),
            "record": ("The record", "What the documents and records really show, with their sources."),
            "benefit": ("Who gained", "Who made money or gained power from it, documented."),
            "harm": ("The cost", "What it did to real people, documented and respectful.")}
    for role, (name, how) in must.items():      # every video answers all four, whatever the story type
        if role not in {b.role for b in beats}:
            at = next((i for i, b in enumerate(beats) if b.role in ("tell", "toolkit", "verdict")), len(beats))
            beats.insert(at, Beat(name, role, 8, how))
    n = max(n, len(beats))
    total = sum(b.share for b in beats) or 1
    exact = [n * b.share / total for b in beats]
    count = [max(1, int(x)) for x in exact]
    while sum(count) > n:
        k = max((i for i in range(len(beats)) if count[i] > 1), key=lambda i: count[i] - exact[i])
        count[k] -= 1
    while sum(count) < n:
        k = max(range(len(beats)), key=lambda i: exact[i] - count[i])
        count[k] += 1
    return [b for b, c in zip(beats, count) for _ in range(c)]


def outline_problems(planned: list[dict[str, Any]], n: int) -> list[str]:
    out = []
    if len(planned) < n:
        out.append(f"you planned {len(planned)} scenes but the video needs {n}")
    missing = [r for r in FACT_ROLES if r not in {p.get("role") for p in planned}]
    if missing:
        out.append(f"no scene has the role {', '.join(missing)} (every video says what was claimed, what the record "
                   "says, who benefited and what it did to people)")
    return out


def fill_outline(planned: list[dict[str, Any]], slots: list, packet: dict[str, Any],
                 claim_order: list[str]) -> list[dict[str, Any]]:
    """Put the AI's scenes into the beat sheet's slots in order; empty slots get a scene from their beat."""
    claims = {c["claim_id"]: c for c in packet["claims"]}
    order = [c for c in claim_order if c in claims] or list(claims)
    left = list(planned)
    out, k = [], 0
    for slot in slots:
        mine = next((p for p in left if p.get("role") == slot.role), None)
        if mine:
            left.remove(mine)
            out.append(mine)
            continue
        sc = {"role": slot.role, "purpose": f"{slot.name}: {slot.how}", "link": "therefore" if out else "open",
              "claim_ids": [], "source_ids": [], "excerpt_ids": [],
              "owl_on_camera": slot.role in ("intro", "tell", "toolkit", "verdict"), "visual_idea": ""}
        if slot.role in FACT_ROLES and order:
            cid = order[k % len(order)]
            k += 1
            sc["claim_ids"] = [cid]
            sc["source_ids"] = [s["source_id"] for s in claims[cid]["sources"]][:2]
        out.append(sc)
    return out


def _claims_of(beat: dict[str, Any], packet: dict[str, Any]) -> list[str]:
    """The claims a story beat's evidence IDs belong to."""
    want = set(beat.get("evidence_ids", []))
    out = []
    for c in packet["claims"]:
        srcs = {s["source_id"] for s in c["sources"]} | {f"E{e['excerpt_id']}" for e in c["excerpts"]}
        if want & srcs:
            out.append(c["claim_id"])
    return out


ELLIPSIS = re.compile(r"\s*(?:\.\.\.|…)\s*")


def quote_matches(quote: str, text: str) -> bool:
    """Word for word, allowing "..." where words were left out (each piece must be there, in order)."""
    hay = normalize_for_match(text)
    pos = 0
    pieces = [normalize_for_match(p).strip(" .,;:!?\"'") for p in ELLIPSIS.split(quote)]
    pieces = [p for p in pieces if p]
    if not pieces or sum(len(p) for p in pieces) < 8:
        return False
    for p in pieces:
        k = hay.find(p, pos)
        if k < 0:
            return False
        pos = k + len(p)
    return True


def quote_report(sc: dict[str, Any], packet: dict[str, Any]) -> tuple[dict[str, int], list[str]]:
    """Quoted words in a scene: {quote: excerpt it really comes from} and the quotes that match nothing."""
    excerpts = {int(k): v for k, v in _excerpt_map(packet).items()}
    listed = [int(e) for e in sc.get("excerpt_ids", []) if str(e).isdigit()]
    found, bad = {}, []
    for q in quotes_in((sc.get("narration") or "") + " " + (sc.get("on_screen_text") or "")):
        hit = next((e for e in listed if e in excerpts and quote_matches(q, excerpts[e]["text"])), None)
        if hit is None:
            hit = next((e for e, x in excerpts.items() if quote_matches(q, x["text"])), None)
        if hit is None:
            bad.append(q)
        else:
            found[q] = hit
    return found, bad


def _unquote(text: str, quote: str) -> str:
    """Take the quote marks off one quoted passage (the words stay)."""
    for a, b in (('"', '"'), ("“", "”"), ("'", "'"), ("‘", "’"), ("'", "’"), ("‘", "'")):
        for tail in ("", ".", ",", "!", "?", "...", "…", "?!", "!?"):
            span = f"{a}{quote}{tail}{b}"
            if span in text:
                return text.replace(span, quote + tail, 1)
    return text


def fix_quotes(sc: dict[str, Any], packet: dict[str, Any]) -> list[str]:
    """A quote that is a real verified quote gets its E-number listed (and its source); quote marks around
    anything else come off, so it's said as a paraphrase. Returns notes."""
    found, bad = quote_report(sc, packet)
    notes = []
    excerpts = _excerpt_map(packet)
    for q, e in found.items():
        if e not in [int(x) for x in sc.get("excerpt_ids", []) if str(x).isdigit()]:
            sc.setdefault("excerpt_ids", []).append(e)
            src = excerpts[str(e)]["source_id"]
            if src not in sc.setdefault("source_ids", []):
                sc["source_ids"].append(src)
            notes.append(f"{sc.get('scene_id')}: the quote \"{q[:50]}...\" is verified quote E{e}; listed it")
    for q in bad:
        for key in ("narration", "on_screen_text"):
            sc[key] = _unquote(sc.get(key) or "", q)
        notes.append(f"{sc.get('scene_id')}: \"{q[:50]}...\" isn't a word-for-word verified quote, so its quote "
                     "marks were taken off (it's now said as a paraphrase; check it reads right)")
    return notes


def _words_for(role: str, base: int) -> int:
    return int(base * {"intro": 0.7, "verdict": 0.8, "toolkit": 0.6, "outro": 0.4}.get(role, 1.0))


def _facts_for(scene: dict[str, Any], packet: dict[str, Any]) -> str:
    """Only this scene's evidence, in full, for the scene writer."""
    want_src = set(scene.get("source_ids") or [])
    want_q = {int(x) for x in scene.get("excerpt_ids") or [] if str(x).isdigit()}
    want_claims = set(scene.get("claim_ids") or [])
    out = []
    for c in packet["claims"]:
        srcs = [s for s in c["sources"] if s["source_id"] in want_src]
        quotes = [e for e in c["excerpts"] if int(e["excerpt_id"]) in want_q or e["source_id"] in want_src]
        if c["claim_id"] in want_claims or srcs or quotes:
            out.append({"claim_id": c["claim_id"], "claim": c["short_title"], "verdict": c["falsity_status"],
                        "summary": c.get("claim_summary"), "who_benefited": c.get("who_benefited"),
                        "harm": c.get("harm_summary"), "year": c.get("first_known_year"),
                        "sources": [{"source_id": s["source_id"], "title": s["title"], "date": s.get("date"),
                                     "what_it_shows": s.get("summary") or ""} for s in srcs],
                        "verified_quotes": [{"excerpt_id": e["excerpt_id"], "source_id": e["source_id"],
                                             "text": e["text"]} for e in quotes]})
    return json.dumps(out, ensure_ascii=False, indent=1) if out else "(no facts: this scene must not state facts)"


def _in_narration(words: str, narration: str) -> str:
    """The quoted words if they really are in the narration (ignoring case and punctuation), else ""."""
    def norm(x: str) -> str:
        return " ".join("".join(ch for ch in w.lower() if ch.isalnum()) for w in x.split()).strip()
    w = norm(words or "")
    return words.strip().strip('"“”') if w and w in norm(narration) else ""


def _sentences(text: str) -> list[str]:
    return [x.strip() for x in re.split(r"(?<=[.!?])\s+", text) if x.strip()]


def tidy_directions(sc: dict[str, Any], creative: dict[str, Any], before: list[dict[str, Any]]) -> list[str]:
    """Check the writer's music and Owlbert lines against the rules, fixing or dropping what breaks them."""
    notes = []
    role, nar = sc.get("role", ""), sc.get("narration", "")
    m = dict(sc.get("music") or {})
    defaults = {"intro": ("curious", 4), "claim": ("tense", 3), "record": ("investigative", 2),
                "benefit": ("warm", 2), "harm": ("somber", 2), "tell": ("playful", 4),
                "toolkit": ("encouraging", 3), "verdict": ("resolved", 3), "outro": ("theme", 4)}
    mood0, energy0 = defaults.get(role, ("investigative", 2))
    if m.get("mood") not in MOODS:
        m["mood"] = mood0
    m["energy"] = max(1, min(5, int(m.get("energy") or energy0)))
    if m.get("change") not in CHANGES:
        m["change"] = "crossfade" if not before else "continue"
    for key in ("drop_before", "sting_at"):
        m[key] = _in_narration(m.get(key, ""), nar)
    if m["mood"] == "playful" and (role == "harm" or creative.get("careful")):
        m["mood"] = "somber" if role == "harm" else "warm"
        notes.append(f"{sc.get('scene_id')}: no playful music here; changed to {m['mood']}.")
    if role in ("record", "claim", "benefit") and m["energy"] > 3:
        m["energy"] = 3                               # no big music under the evidence
    if role == "verdict" and not m["drop_before"]:
        sents = _sentences(nar)
        pick = next((x for x in sents if re.search(r"verdict|false|true|unproven|misleading", x, re.I)),
                    sents[-1] if sents else "")
        m["drop_before"] = " ".join(pick.split()[:6])
    stings = sum(1 for b in before if (b.get("music") or {}).get("change") == "sting")
    if m["change"] == "sting" and (stings >= 6 or not m["sting_at"]):
        m["change"] = "crossfade"
    if not before and m["change"] == "continue":
        m["change"] = "crossfade"
    sc["music"] = {k: v for k, v in m.items() if v not in ("", None)}
    moves = []
    for d in sc.get("owlbert") or []:
        if d.get("move") not in MOVES:
            continue
        x = {"move": d["move"]}
        if d.get("prop") in PROPS and d["move"] == "hat_trick":
            x["prop"] = d["prop"]
        at = _in_narration(d.get("at", ""), nar)
        if at:
            x["at"] = at
        elif d.get("at") and d["move"] not in ("fly_in", "fly_out"):
            notes.append(f"{sc.get('scene_id')}: Owlbert's {d['move']} was tied to words that aren't in the "
                         "narration, so it plays near the start of the scene.")
        moves.append(x)
    sc["owlbert"] = moves[:3]
    return notes


def scene_repeats(sc: dict[str, Any], earlier: list[dict[str, Any]], packet: dict[str, Any]) -> list[dict[str, Any]]:
    """Sentences in this scene that say again what an earlier scene said (verified quotes aside)."""
    from ..repeats import find_repeats
    quotes = [e["text"] for e in _excerpt_map(packet).values()]
    return find_repeats(sc.get("narration", ""), [(e.get("scene_id", "an earlier scene"), e.get("narration", ""))
                                                    for e in earlier], keep_quotes=quotes)


def budget_facts(planned: list[dict[str, Any]], packet: dict[str, Any]) -> list[str]:
    """Each verified quote goes to one scene only, and every ticked quote and source is used somewhere, so
    each scene has its own material instead of re-telling the same facts (the "fact budget")."""
    notes = []
    excerpts = {int(k): v for k, v in _excerpt_map(packet).items()}
    claim_of_src = {s["source_id"]: c["claim_id"] for c in packet["claims"] for s in c["sources"]}
    seen: set[int] = set()
    for sc in planned:
        mine = []
        for e in sc.get("excerpt_ids", []) or []:
            e = int(e) if str(e).isdigit() else None
            if e is None or e in seen:
                continue
            seen.add(e)
            mine.append(e)
        sc["excerpt_ids"] = mine
    fact = [sc for sc in planned if sc.get("role") in FACT_ROLES] or planned

    def home(claim_id: str | None) -> dict[str, Any]:
        same = [sc for sc in fact if claim_id and claim_id in (sc.get("claim_ids") or [])] or fact
        return min(same, key=lambda sc: len(sc.get("excerpt_ids", [])) + len(sc.get("source_ids", [])))

    for e, x in excerpts.items():
        if e not in seen:
            sc = home(claim_of_src.get(x["source_id"]))
            sc.setdefault("excerpt_ids", []).append(e)
            if x["source_id"] not in sc.setdefault("source_ids", []):
                sc["source_ids"].append(x["source_id"])
            notes.append(f"quote E{e} given to a {sc.get('role')} scene")
    used_src = {s for sc in planned for s in sc.get("source_ids", []) or []}
    for sid, cid in claim_of_src.items():
        if sid not in used_src and any(s["source_id"] == sid and s.get("is_primary") for c in packet["claims"]
                                       for s in c["sources"]):
            sc = home(cid)
            sc.setdefault("source_ids", []).append(sid)
            if cid not in sc.setdefault("claim_ids", []):
                sc["claim_ids"].append(cid)
            notes.append(f"source {sid} given to a {sc.get('role')} scene")
    return notes


def material_note(packet: dict[str, Any], minutes: float) -> str:
    """'' if there's enough research for this length, else a plain warning (about 1.5 ticked items a minute)."""
    items = len(packet.get("evidence", [])) or sum(len(c["sources"]) + len(c["excerpts"]) for c in packet["claims"])
    need = int(minutes * 1.5)
    if items >= need:
        return ""
    fits = max(1.0, round(items / 1.5 * 2) / 2)
    return (f"Thin research for {minutes:g} minutes: {items} ticked items (about {need} keeps a video from repeating "
            f"itself). Tick more, Dig deeper on Research, or make it about {fits:g} minutes.")


def _problems(sc: dict[str, Any], target: int, packet: dict[str, Any] | None = None,
              earlier: list[dict[str, Any]] | None = None) -> list[str]:
    words = len(sc.get("narration", "").split())
    low = sc.get("narration", "").lower()
    out = []
    if words < target * 0.75:
        out.append(f"It's too short: {words} words. Write about {target} words: add the concrete details from "
                   "the facts (dates, numbers, places, what the documents say), not padding.")
    stock = [p for p in STOCK_PHRASES if p in low]
    if stock:
        out.append(f"Remove these stock phrases: {', '.join(stock)}.")
    if packet is not None:
        _, bad = quote_report(sc, packet)
        if bad:
            out.append("These words are in quote marks but aren't a verified quote word for word: "
                       + "; ".join(f'"{q[:80]}"' for q in bad) + ". Say them without quote marks (as a paraphrase "
                       "or plain speech), or copy a verified quote exactly and list its excerpt_id.")
        if earlier:
            reps = scene_repeats(sc, earlier, packet)
            if reps:
                out.append("These sentences say again what an earlier scene already said: "
                           + "; ".join(f'"{r["sentence"][:110]}" ({r["where"]})' for r in reps[:5])
                           + ". Replace them with NEW details from this scene's facts (or cut them); never re-tell.")
    return out


def _treatment(ctx: Context, llm: Ollama, planner: str, packet: dict[str, Any], ids: dict[str, list],
               story_text: str, style_text: str, film_text: str, type_text: str, minutes: float) -> dict[str, Any]:
    """The film treatment (treatment.py). If the planner can't make a usable one, the script is still written
    from the outline alone, and the log says so."""
    from . import treatment as tr
    ep = ctx.episode
    ctx.progress(f"Finding the story in the research (film treatment) with {planner}", 1)
    for old in ("treatment.json", "treatment.md"):   # never show last time's treatment with a new script
        ep.path(old).unlink(missing_ok=True)
    careful = ep.creative().get("careful")
    msgs = [{"role": "system", "content": tr.ARCHITECT + "\n\n" + VOICE_RULES},
            {"role": "user", "content": (
                f"Make the film treatment for a {minutes:g}-minute true-story video: {ep.title}\n{style_text}\n"
                + (f"\n{film_text}\nEmulate this directing style (pacing, themes, camera language, symbolism, "
                   "emotional tone) without copying any film and without naming any director.\n" if film_text else "")
                + type_text + story_text
                + ("Careful topic: the victims are never dramatised; their story comes from courts and documents.\n"
                   if careful else "")
                + "\nfilm_title: short and memorable. logline: one sentence with the protagonist, the conflict and "
                  "the stakes. opening_scene: the first image and moment, using only real facts. acts: three, each "
                  "with what happens, the feeling and its turning point. key_characters: up to 5 REAL people or "
                  "groups from the packet (their real names), with what they wanted and what stood in the way, as "
                  "the record shows; never invent anyone. revelations: the surprises in the order the viewer learns "
                  "them, each with the evidence that proves it and its place in the arc. emotional_arc: how the "
                  "viewer should feel from start to end. unanswered_questions: what the record still can't answer. "
                  "closing_thought: the line to leave the viewer thinking (true to the facts).\n"
                + f"\nResearch packet:\n{_packet_for_prompt(packet)}")}]
    try:
        raw = llm.chat_json(msgs, tr.schema(ids), model=planner, lenient=True, temperature=0.7,
                            on_text=ctx.writing("Finding the story in the research", 1, 3, 700))
    except StageError as exc:
        ctx.log(f"No film treatment this time ({exc}); the scenes are planned from the story alone.")
        return {}
    treat = tr.tidy(raw or {}, packet, ids)
    if not (treat["film_title"] and treat["logline"] and treat["acts"]):
        ctx.log("The film treatment came back empty; the scenes are planned from the story alone.")
        return {}
    if treat["dropped_characters"]:
        ctx.log("Treatment: left out characters who aren't in the research (nobody is invented): "
                + ", ".join(treat["dropped_characters"]))
    tr.save(ep, treat)
    ctx.log(f"Film treatment: \"{treat['film_title']}\" - {treat['logline']}")
    return treat


def run(ctx: Context) -> None:
    ep = ctx.episode
    if not ep.path("research.json").exists():
        raise StageError("Run and approve the Research stage first.")
    packet = selected_packet(ep)
    if not packet["claims"]:
        raise StageError("No evidence is ticked on the Research page.")
    if ctx.options.get("expand"):
        return _expand(ctx, packet)
    if ctx.options.get("derepeat"):
        return _derepeat(ctx, packet)
    from .. import styles, techniques
    from .stories import chosen
    story = chosen(ep)
    creative = ep.creative()
    style = styles.get(creative["style"])
    minutes = float(ctx.options.get("minutes", creative.get("minutes", 8)))
    ep.set_creative(minutes=minutes)
    words = int(minutes * style.wpm * 0.92)   # a little room for music stings and quote cards
    n_scenes = _scene_count(minutes)
    base = int(words / max(1, n_scenes - 0.9))
    from ..llm import model_for
    model = model_for("script_write")
    planner = model_for("script_plan")
    humor = ["No jokes.", "A light touch of warmth.", "Some gentle humor aimed at the trick or the sellers.",
             "Plenty of satire, punching up at the sellers only, never at believers or victims."][creative["humor"]]
    style_text = (f"Video style: {style.name}. {style.tone}\nHumor: {humor}\n"
                  f"A sample of the voice in this style (match the register, don't copy the content):\n"
                  f"\"{style.sample}\"")
    story_text = ""
    if story:
        excerpts = _excerpt_map(packet)
        beats = []
        for b in story.get("beats", []):
            src, quotes = [], []
            for ref in b.get("evidence_ids", []):
                m = re.fullmatch(r"E(\d+)", ref)
                if m and m.group(1) in excerpts:
                    quotes.append(int(m.group(1)))
                    src.append(excerpts[m.group(1)]["source_id"])
                elif not m:
                    src.append(ref)
            beats.append({"role": b["role"], "beat": b["beat"], "source_ids": list(dict.fromkeys(src)),
                          "excerpt_ids": quotes})
        plan = {k: story.get(k) for k in ("title", "logline", "angle", "opening_hook")}
        plan["beats"] = beats
        plan["tricks_to_teach"] = [{"name": t.name, "meaning": t.meaning, "everyday_example": t.everyday.replace('"', "").replace("'", ""),
                                    "ask": t.ask} for t in (techniques.get(k) for k in story.get("techniques", [])) if t]
        story_text = ("\nThe approved story plan (follow it; each beat lists the source_ids and excerpt_ids to "
                      "use):\n" + json.dumps(plan, ensure_ascii=False, indent=1) + "\n")
    from .. import storytypes
    stype = storytypes.STORY_TYPES.get((story or {}).get("story_type") or creative.get("story_type", "")) or \
        storytypes.STORY_TYPES[storytypes.DEFAULT_TYPE]
    writer = storytypes.writers().get((story or {}).get("writer") or creative.get("writer", "")) or \
        storytypes.writers()[storytypes.DEFAULT_WRITER]
    from .. import filmstyles
    genre, director = filmstyles.chosen(creative)
    film_text = filmstyles.script_block(genre, director) if (genre or director) else ""
    movie = (story or {}).get("format") == "movie"
    if movie:
        from types import SimpleNamespace

        from ..storytypes import Beat
        sheet = SimpleNamespace(beats=tuple(Beat(b["beat"][:60], b["role"], max(1, len(b.get("evidence_ids", []))),
                                                 b["beat"]) for b in story["beats"]))
    else:
        sheet = stype
    type_text = ("\nThis is the long documentary made from the book: follow the movie plan's beats in order "
                 "(one or more scenes per chapter, more for chapters with more evidence).\n" + storytypes.SHARED_RULES
                 + "\n") if movie else (f"\n{stype.sheet()}\nFollow this beat sheet in order: each scene's role is its beat's role; a beat "
                 "with a big share can take two or more scenes.\n" + storytypes.SHARED_RULES + "\n")
    llm = Ollama(job="script_write")
    ids = known_ids(packet)
    scene_schema = with_known_ids(SCENE_SCHEMA, ids)
    from .. import channelmemory
    from ..repeats import ledger_text

    # 0. the film treatment: find the story in the research before planning any scene
    from . import treatment as tr
    treat = _treatment(ctx, llm, planner, packet, ids, story_text, style_text, film_text, type_text, minutes)
    treat_text = f"\n{tr.brief_for_outline(treat)}\n" if treat else ""

    # 1. outline
    slots = scene_slots(sheet, n_scenes)
    n_scenes = len(slots)
    outline_schema = with_known_ids(OUTLINE_SCHEMA, ids, inside_scenes=True)
    outline_schema["properties"]["scenes"].update(minItems=n_scenes, maxItems=max(16, n_scenes))
    ctx.progress(f"Planning {n_scenes} scenes in the {style.name} style with {planner}", 3)
    outline_msgs = [
        {"role": "system", "content": VOICE_RULES},
        {"role": "user", "content": (
            f"Plan the scenes for: {story['title'] if story else ep.title}\n{style_text}\n"
            f"Plan exactly {n_scenes} scenes for a {minutes:g}-minute video. For each: its role, what it must do "
            "(purpose), how it links to the one before (open / but / therefore; avoid 'and then'), the claim_ids, "
            "source_ids (S-...) and excerpt_ids (numbers) it uses, whether Owlbert is on camera, and a picture "
            "idea that fits the style. Include a 'tell' scene and a 'toolkit' scene.\n"
            f"The {n_scenes} roles in order: {', '.join(s.role for s in slots)}.\n" + type_text
            + (f"\n{film_text}\n" if film_text else "")
            + (f"Producer's direction: {ctx.options['direction']}\n" if ctx.options.get("direction") else "")
            + story_text + treat_text
            + ("Follow the treatment: the opening scene first, the acts in order, each revelation in a scene "
               "that holds its proof, building to the climax; end on the open questions and the closing thought.\n"
               if treat else "")
            + (f"\n{channelmemory.for_prompt(ep)}\n" if channelmemory.for_prompt(ep) else "")
            + "Give each scene its OWN facts (each quote in one scene only); never plan two scenes that say the "
              "same thing. gap_questions: up to 6 questions a viewer would ask that the research packet can't answer "
              "(they become 'look it up' tasks; never guess the answers).\n"
            + f"\nResearch packet:\n{_packet_for_prompt(packet)}")},
    ]
    outline = llm.chat_json(outline_msgs, outline_schema, model=planner, lenient=True, temperature=0.6,
                            on_text=ctx.writing("Planning the scenes", 3, 12, 60 * n_scenes))
    planned = (outline.get("scenes") or [])[:max(16, n_scenes)]
    problems = outline_problems(planned, n_scenes)
    if problems:   # the plan is too short or skips a part every video needs: one more try, then fill it in
        ctx.progress(f"The scene plan came back short ({'; '.join(problems)}); asking again", 12)
        again = llm.chat_json(outline_msgs + [
            {"role": "assistant", "content": json.dumps(outline, ensure_ascii=False)},
            {"role": "user", "content": f"Problem: {'; '.join(problems)}. Plan all {n_scenes} scenes again, with "
                                        f"these roles in this order: {', '.join(s.role for s in slots)}."}],
            outline_schema, model=planner, lenient=True, temperature=0.5, on_text=ctx.writing("Planning the scenes again", 12, 15, 60 * n_scenes))
        if len(again.get("scenes") or []) >= len(planned):
            outline, planned = again, (again.get("scenes") or [])[:max(16, n_scenes)]
        problems = outline_problems(planned, n_scenes)
        if problems:
            used = [cid for b in (story or {}).get("beats", []) for cid in _claims_of(b, packet)]
            planned = fill_outline(planned, slots, packet, list(dict.fromkeys(used)))
            ctx.log(f"The scene plan was still short ({'; '.join(problems)}), so the program filled the gaps from "
                    f"the {stype.name} beat sheet ({len(planned)} scenes).")
    for i, plan_sc in enumerate(planned):
        drop_unknown(plan_sc, ids)
        if plan_sc.get("role") in FACT_ROLES and not plan_sc.get("source_ids") and ids["claim_ids"]:
            # a fact scene with no usable evidence: give it a ticked claim, in turn
            cid = plan_sc["claim_ids"][0] if plan_sc.get("claim_ids") else ids["claim_ids"][i % len(ids["claim_ids"])]
            c = next(c for c in packet["claims"] if c["claim_id"] == cid)
            plan_sc["claim_ids"] = [cid]
            plan_sc["source_ids"] = [x["source_id"] for x in c["sources"]][:2]
    if len(planned) < 3:
        raise StageError("The outline came back with fewer than 3 scenes. Press Write it again.")
    budget = budget_facts(planned, packet)
    tr.assign_arc(planned)
    tr.place_revelations(treat, planned)
    if budget:
        ctx.log(f"Fact budget: {len(budget)} unused quote(s)/source(s) given to scenes, each quote to one scene only.")
    thin = material_note(packet, minutes)
    if thin:
        ctx.log(thin)
    from .. import channelmemory
    memory = channelmemory.for_prompt(ep)
    title = outline.get("title") or (story or {}).get("title") or ep.title
    gaps = [q.strip() for q in outline.get("gap_questions", []) or [] if len(q.split()) >= 4][:6]
    write_json(ep.path("script-questions.json"), {"questions": [{"claim_id": "", "question": q} for q in gaps],
                                                  "made_at": utc_now()})
    base = int(words / max(1.0, sum(_words_for(p["role"], 1000) / 1000 for p in planned) - 0.6))

    # 2. one scene at a time
    scenes: list[dict[str, Any]] = []
    for n, plan_sc in enumerate(planned, 1):
        ctx.check_cancel()
        target = _words_for(plan_sc["role"], base)
        prev = scenes[-1]["narration"] if scenes else ""
        pct0, pct1 = 15 + 80 * (n - 1) / len(planned), 15 + 80 * n / len(planned)
        messages = [
            {"role": "system", "content": tr.ARCHITECT + "\n\n" + VOICE_RULES + "\n\n" + OWLBERT + "\n\n"
             + storytypes.writer_block(writer)
             + (f"\n\n{film_text}" if film_text else "")},
            {"role": "user", "content": (
                f"Video: {title}. Central question: {outline.get('central_question', '')}\n{style_text}\n"
                f"Story type: {stype.name}. Writing style: {writer.name} (keep to it in every scene).\n\n"
                + (f"{tr.scene_brief(treat, plan_sc, n, len(planned))}\n\n" if treat else "")
                + f"Write scene {n} of {len(planned)}. Role: {plan_sc['role']}. Purpose: {plan_sc['purpose']}. "
                f"It links to the previous scene with '{plan_sc['link']}'. "
                f"{'Owlbert is on camera. ' if plan_sc.get('owl_on_camera') else ''}"
                f"Picture idea: {plan_sc.get('visual_idea', '')}\n"
                f"Write about {target} words of narration (that matters: the video must fill "
                f"{minutes:g} minutes). Every fact must come from the facts below; list the claim_ids, "
                "source_ids and excerpt_ids you used. The visual describes the picture for an illustrator in "
                "this style.\n"
                + (f"The previous scene ended: \"{' '.join(prev.split()[-40:])}\"\n" if prev else "")
                + (f"Already said in earlier scenes (never say these again; build on them with new details):\n"
                   f"{ledger_text([(x['scene_id'], x['narration']) for x in scenes])}\n" if scenes else "")
                + (f"{memory}\n" if memory and plan_sc["role"] in ("intro", "verdict", "outro") else "")
                + (f"The music in the previous scene: {json.dumps(scenes[-1].get('music', {}))}\n" if scenes else "")
                + ("This is a careful topic: no playful music or moves.\n" if creative.get("careful") else "")
                + f"\nFacts for this scene:\n{_facts_for(plan_sc, packet)}\n\n{DIRECTING}")},
        ]
        sc = llm.chat_json(messages, scene_schema, lenient=True, temperature=0.75,
                           on_text=ctx.writing(f"Writing scene {n} of {len(planned)}", pct0, pct1 - 2, target + 60))
        # 3. one fix-up if it's short or full of stock phrases
        fix_refs(sc, packet, fill=False)
        issues = _problems(sc, target, packet, scenes)
        if issues:
            ctx.progress(f"Polishing scene {n} of {len(planned)}: " + issues[0].split(":")[0], pct1 - 2)
            sc = llm.chat_json(messages + [
                {"role": "assistant", "content": json.dumps(sc, ensure_ascii=False)},
                {"role": "user", "content": "Rewrite this scene. " + " ".join(issues) + " Keep every fact sourced."},
            ], scene_schema, lenient=True, temperature=0.7, on_text=ctx.writing(f"Polishing scene {n}", pct1 - 2, pct1, target + 60))
        sc["role"] = plan_sc["role"]
        sc["scene_id"] = f"SCENE_{n:03d}"
        if plan_sc.get("arc"):
            sc["arc"] = plan_sc["arc"]
        for note in tidy_directions(sc, creative, scenes):
            ctx.log(note)
        dropped = drop_unknown(sc, ids)
        if dropped:
            ctx.log(f"{sc['scene_id']}: removed IDs that aren't in the ticked evidence: {', '.join(dropped)}")
        if not sc.get("claim_ids") and plan_sc.get("claim_ids"):
            sc["claim_ids"] = plan_sc["claim_ids"]
        if not sc.get("source_ids") and plan_sc.get("source_ids"):
            sc["source_ids"] = list(plan_sc["source_ids"])
        for note in fix_refs(sc, packet):
            ctx.log(note)
        for note in fix_quotes(sc, packet):
            ctx.log(note)
        left = scene_repeats(sc, scenes, packet)
        if left:
            ctx.log(f"{sc['scene_id']}: {len(left)} sentence(s) still repeat earlier scenes (shown in the checks; "
                    "press Fix repeats)")
        scenes.append(sc)
    for sc in scenes:
        sc["est_seconds"] = round(len(sc.get("narration", "").split()) / style.wpm * 60)
    header = {"Episode": ep.project_id, "Arc": (packet.get("arc") or {}).get("arc_id", "-"),
              "Style": style.name, "Story type": stype.name, "Writer": writer.name,
              **({"Genre": genre.name} if genre else {}), **({"Director": director.label} if director else {}),
              **({"Film": treat["film_title"]} if treat.get("film_title") else {}),
              "Target": f"{minutes:g} min",
              "Drafted by": model}
    write_text(ep.path("script.md"), render(title, scenes, header))
    channelmemory.record(ep, scenes, story, title)
    total = sum(len(sc.get("narration", "").split()) for sc in scenes)
    ctx.log(f"Draft written: {len(scenes)} scenes, {total} words (aim {words}). Read and edit, then approve.")


def _expand(ctx: Context, packet: dict[str, Any]) -> None:
    """'Make it longer': rewrite only the scenes that are shorter than their share of the target."""
    from .. import styles
    ep = ctx.episode
    creative = ep.creative()
    style = styles.get(creative["style"])
    minutes = float(ctx.options.get("minutes", creative.get("minutes", 8)))
    script = load(ep)
    scenes = script["scenes"]
    words = int(minutes * style.wpm * 0.92)
    base = int(words / max(1, len(scenes) - 0.9))
    llm = Ollama(job="script_write")
    ids = known_ids(packet)
    scene_schema = with_known_ids(SCENE_SCHEMA, ids)
    short = [sc for sc in scenes if len(sc["narration"].split()) < _words_for(sc["role"], base) * 0.9]
    if not short:
        ctx.progress("Every scene is already long enough.", 100)
        return
    for n, sc in enumerate(short, 1):
        ctx.check_cancel()
        target = _words_for(sc["role"], base)
        new = llm.chat_json([
            {"role": "system", "content": VOICE_RULES + "\n\n" + OWLBERT},
            {"role": "user", "content": (
                f"Style: {style.name}. {style.tone}\nThis scene is too short ({len(sc['narration'].split())} "
                f"words). Rewrite it at about {target} words by adding concrete detail from its facts (dates, "
                "numbers, what the documents say, what it meant for people), not padding. Keep its sources.\n"
                f"Scene: {json.dumps({k: sc[k] for k in ('role', 'narration', 'visual', 'on_screen_text', 'claim_ids', 'source_ids', 'excerpt_ids')}, ensure_ascii=False)}\n"
                f"Facts:\n{_facts_for(sc, packet)}")},
        ], scene_schema, lenient=True, temperature=0.7,
            on_text=ctx.writing(f"Lengthening {sc['scene_id']} ({n}/{len(short)})",
                                100 * (n - 1) / len(short), 100 * n / len(short), target + 60))
        drop_unknown(new, ids)
        for k in ("narration", "visual", "on_screen_text", "claim_ids", "source_ids", "excerpt_ids"):
            if new.get(k):
                sc[k] = new[k]
        drop_unknown(sc, ids)
        fix_refs(sc, packet)
        fix_quotes(sc, packet)
        sc["est_seconds"] = round(len(sc["narration"].split()) / style.wpm * 60)
    text = ep.path("script.md").read_text(encoding="utf-8")
    header_line = next((ln for ln in text.splitlines() if ln.startswith("**Episode:**")), "")
    header = dict(re.findall(r"\*\*(.+?):\*\* ([^·]+?)(?: · |$)", header_line)) or {"Episode": ep.project_id}
    write_text(ep.path("script.md"), render(script["title"], scenes, {k: v.strip() for k, v in header.items()}))
    ctx.progress(f"Lengthened {len(short)} scene(s).", 100)


def check(ep: Episode) -> list[Check]:
    path = ep.path("script.md")
    if not path.exists():
        return [Check(BLOCK, "No script yet. Run this stage (or write script.md yourself).")]
    packet = selected_packet(ep)
    raw_ev = (read_json(ep.path("research.json")) or {}).get("evidence", [])
    script = parse(path.read_text(encoding="utf-8"))
    scenes = script["scenes"]
    out: list[Check] = []
    if not scenes:
        return [Check(BLOCK, "script.md has no '## SCENE_###' headings.")]

    claim_sources = {c["claim_id"]: {s["source_id"] for s in c["sources"]} for c in packet["claims"]}
    all_ticked = set().union(*claim_sources.values()) if claim_sources else set()
    excerpts = _excerpt_map(packet)
    known_sources = {r["source_id"] for r in db.rows("SELECT source_id FROM source")}
    kf = {r["source_id"] for r in db.rows("SELECT source_id FROM source WHERE source_type='kf_index'")}
    all_claims = {r["claim_id"] for r in db.rows("SELECT claim_id FROM claim")}

    for sc in scenes:
        sid = sc["scene_id"]
        fix_refs(sc, packet, fill=False)  # read E-numbers in the sources list as quotes (for hand edits)
        for cid in sc["claim_ids"]:
            if cid not in claim_sources:
                why = ("has nothing ticked on the Research page" if cid in all_claims
                       else "isn't in the database (the AI may have invented it)")
                out.append(Check(BLOCK, f"{sid}: claim {cid} {why}."))
        for src in sc["source_ids"]:
            if re.fullmatch(r"[Ee]\d+", src):
                out.append(Check(BLOCK, f"{sid}: quote {src} isn't one of the quotes you ticked on the Research page."))
            elif src not in known_sources:
                out.append(Check(BLOCK, f"{sid}: source {src} doesn't exist in the database "
                                        "(the AI may have invented it)."))
            elif src in kf:
                out.append(Check(BLOCK, f"{sid}: source {src} is a Knowledge Fight episode. It's a research "
                                        "index, not evidence."))
            elif src not in all_ticked:
                title = next((e.get("title") for e in raw_ev if e["source_id"] == src), None)
                if title:
                    out.append(Check(BLOCK, f"{sid} uses \"{title[:60]}\", which isn't ticked. "
                                            "Press Tick what the script needs, or take it out of this scene."))
                else:
                    out.append(Check(BLOCK, f"{sid}: source {src} isn't part of this video's research (the AI "
                                            "brought it in). Take it out of this scene."))
        if sc["claim_ids"] and not sc["source_ids"]:
            out.append(Check(BLOCK, f"{sid}: states facts about {', '.join(sc['claim_ids'])} "
                                    "but lists no source IDs."))
        for quote in quotes_in(sc["narration"] + " " + sc["on_screen_text"]):
            if not any(quote_matches(quote, excerpts[e]["text"]) for e in sc["excerpt_ids"] if e in excerpts):
                out.append(Check(BLOCK, f"{sid}: the quote \"{quote[:60]}...\" doesn't match any "
                                        "verified quote listed for the scene. Paraphrase it or "
                                        "list the right quote (E-number)."))
        if len(sc["on_screen_text"].split()) > 10:
            out.append(Check(WARN, f"{sid}: on-screen text is long; keep it to ~8 words."))

    roles = {sc["role"] for sc in scenes}
    for need in ("claim", "record", "benefit", "harm"):
        if need not in roles:
            out.append(Check(BLOCK, f"No scene answers '{need}'. Every video says what was "
                                    "claimed, what the record says, who benefited and what it "
                                    "did to people (mark scenes with | claim, | record, | "
                                    "benefit, | harm)."))
    narration = " ".join(sc["narration"] for sc in scenes)
    grade = reading_grade(narration)
    words = len(narration.split())
    from .. import styles
    creative = ep.creative()
    style = styles.get(creative["style"])
    target_min = float(creative.get("minutes", 8))
    minutes = words / style.wpm
    if minutes < target_min * 0.8:
        out.append(Check(BLOCK, f"The script runs about {minutes:.1f} minutes but you asked for {target_min:g}. "
                                "Press Make it longer (or lower the Length and write it again)."))
    elif minutes < target_min * 0.95:
        out.append(Check(WARN, f"The script runs about {minutes:.1f} of the {target_min:g} minutes you asked for. "
                               "Make it longer if you want the full length."))
    if grade > 8:
        out.append(Check(WARN, f"Reading level is about grade {grade}; aim for 6-7. Shorter "
                               "sentences and plainer words will fix it."))
    out += repeat_checks(scenes, packet)
    thin = material_note(packet, target_min)
    if thin:
        out.append(Check(WARN, thin))
    out.append(Check(OK, f"{len(scenes)} scenes, {words} words (about {minutes:.1f} min in the {style.name} "
                         f"style), reading grade {grade}."))
    return out


REPEAT_WARNING = "repeat"     # the Script page shows "Fix repeats" when a check says this


def all_repeats(scenes: list[dict[str, Any]], packet: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """{scene_id: its sentences that say again what an earlier scene said}."""
    out = {}
    for k, sc in enumerate(scenes):
        reps = scene_repeats(sc, scenes[:k], packet)
        if reps:
            out[sc["scene_id"]] = reps
    return out


def repeat_checks(scenes: list[dict[str, Any]], packet: dict[str, Any]) -> list[Check]:
    from ..repeats import overused_phrases, stock_phrases
    out = []
    reps = all_repeats(scenes, packet)
    if reps:
        n = sum(len(v) for v in reps.values())
        first_scene, first = next(iter(reps.items()))
        out.append(Check(WARN, f"{n} sentence(s) repeat what an earlier scene said, in {', '.join(list(reps)[:6])}: "
                               f"{first_scene} \"{first[0]['sentence'][:80]}...\" repeats {first[0]['where']}. "
                               "Press Fix repeats."))
    over = overused_phrases({sc["scene_id"]: sc["narration"] for sc in scenes})
    if over:
        out.append(Check(WARN, "Phrases used over and over (" + "; ".join(f"\"{p}\" in {len(w)} scenes"
                                                                           for p, w in over[:3]) + "): vary them."))
    stock = sorted({p for sc in scenes for p in stock_phrases(sc["narration"])})
    if stock:
        out.append(Check(WARN, f"Stock phrases that make it sound machine-written: {', '.join(stock[:6])}."))
    quoted: dict[int, list[str]] = {}
    for sc in scenes:
        for e in sc.get("excerpt_ids", []):
            quoted.setdefault(e, []).append(sc["scene_id"])
    twice = {e: s for e, s in quoted.items() if len(s) > 1}
    if twice:
        e, s = next(iter(twice.items()))
        out.append(Check(WARN, f"{len(twice)} quote(s) are used in more than one scene (E{e} in {', '.join(s)}): "
                               "each quote should land once."))
    return out


def _derepeat(ctx: Context, packet: dict[str, Any]) -> None:
    """'Fix repeats': rewrite only the sentences that re-tell what an earlier scene said."""
    from .. import styles
    from ..repeats import ledger_text
    ep = ctx.episode
    style = styles.get(ep.creative()["style"])
    script = load(ep)
    scenes = script["scenes"]
    reps = all_repeats(scenes, packet)
    if not reps:
        ctx.progress("No scene repeats an earlier one.", 100)
        return
    llm = Ollama(job="script_write")
    ids = known_ids(packet)
    scene_schema = with_known_ids(SCENE_SCHEMA, ids)
    for n, (sid, found) in enumerate(reps.items(), 1):
        ctx.check_cancel()
        k = next(i for i, s in enumerate(scenes) if s["scene_id"] == sid)
        sc = scenes[k]
        new = llm.chat_json([
            {"role": "system", "content": VOICE_RULES + "\n\n" + OWLBERT},
            {"role": "user", "content": (
                f"Style: {style.name}. {style.tone}\nThis scene re-tells things earlier scenes already said:\n"
                + "\n".join(f'- "{r["sentence"]}" (already in {r["where"]})' for r in found)
                + "\nRewrite ONLY those sentences: replace each with a new detail from this scene's facts that hasn't "
                  "been said yet, or cut it. Keep everything else word for word, keep the length about the same, and "
                  "keep its sources.\n"
                f"Already said in earlier scenes:\n{ledger_text([(x['scene_id'], x['narration']) for x in scenes[:k]])}\n"
                f"Scene: {json.dumps({x: sc[x] for x in ('role', 'narration', 'visual', 'on_screen_text', 'claim_ids', 'source_ids', 'excerpt_ids')}, ensure_ascii=False)}\n"
                f"Facts:\n{_facts_for(sc, packet)}")},
        ], scene_schema, lenient=True, temperature=0.6,
            on_text=ctx.writing(f"Fixing repeats in {sid} ({n}/{len(reps)})", 100 * (n - 1) / len(reps),
                                100 * n / len(reps), len(sc["narration"].split()) + 40))
        drop_unknown(new, ids)
        if new.get("narration"):
            sc["narration"] = new["narration"]
        for x in ("claim_ids", "source_ids", "excerpt_ids"):
            if new.get(x):
                sc[x] = new[x]
        drop_unknown(sc, ids)
        fix_refs(sc, packet)
        fix_quotes(sc, packet)
        sc["est_seconds"] = round(len(sc["narration"].split()) / style.wpm * 60)
    text = ep.path("script.md").read_text(encoding="utf-8")
    header_line = next((ln for ln in text.splitlines() if ln.startswith("**Episode:**")), "")
    header = dict(re.findall(r"\*\*(.+?):\*\* ([^·]+?)(?: · |$)", header_line)) or {"Episode": ep.project_id}
    write_text(ep.path("script.md"), render(script["title"], scenes, {k: v.strip() for k, v in header.items()}))
    left = all_repeats(scenes, packet)
    ctx.progress(f"Rewrote {len(reps)} scene(s)." + (f" {sum(len(v) for v in left.values())} repeat(s) are left: "
                                                     "edit them by hand or press Fix repeats again." if left else ""), 100)


def repair(ep: Episode) -> list[str]:
    """Take made-up IDs out of script.md, fill each fact scene's sources from the ticked evidence for its
    claims, and fix quotes (list real ones, take quote marks off the rest). Returns notes about what changed."""
    path = ep.path("script.md")
    text = path.read_text(encoding="utf-8")
    script = parse(text)
    packet = selected_packet(ep)
    ids = known_ids(packet)
    notes = []
    for sc in script["scenes"]:
        dropped = drop_unknown(sc, ids)
        if dropped:
            notes.append(f"{sc['scene_id']}: removed {', '.join(dropped)}")
        notes += fix_refs(sc, packet)
        notes += fix_quotes(sc, packet)
        if sc.get("role") in FACT_ROLES and not sc["claim_ids"] and ids["claim_ids"]:
            notes.append(f"{sc['scene_id']}: no claim left; add one by hand or write the scene again")
    header_line = next((ln for ln in text.splitlines() if ln.startswith("**Episode:**")), "")
    header = {k: v.strip() for k, v in re.findall(r"\*\*(.+?):\*\* ([^·]+?)(?: · |$)", header_line)}
    write_text(path, render(script["title"], script["scenes"], header or {"Episode": ep.project_id}))
    return notes


def wanted_unticked(ep: Episode) -> dict[str, list[str]]:
    """Evidence the script uses that isn't ticked on the Research page: {evidence id: [scenes]}.
    For a source, the item to tick is its link row (or, failing that, its quote rows)."""
    path = ep.path("script.md")
    raw = read_json(ep.path("research.json")) or {}
    evidence = raw.get("evidence", [])
    if not path.exists() or not evidence:
        return {}
    ticked_sources = {e["source_id"] for e in evidence if e.get("include")}
    ticked_ids = {e["id"] for e in evidence if e.get("include")}
    full = {**raw, "claims": raw.get("claims", [])}  # E-numbers resolve against everything on file
    out: dict[str, list[str]] = {}
    for sc in parse(path.read_text(encoding="utf-8"))["scenes"]:
        fix_refs(sc, full, fill=False)
        for src in sc["source_ids"]:
            if src in ticked_sources:
                continue
            rows = [e for e in evidence if e["source_id"] == src]
            pick = [e for e in rows if e["kind"] == "link"] or rows
            for e in pick:
                out.setdefault(e["id"], []).append(sc["scene_id"])
        for q in sc["excerpt_ids"]:
            eid = f"E{q}"
            if eid not in ticked_ids and any(e["id"] == eid for e in evidence):
                out.setdefault(eid, []).append(sc["scene_id"])
    return {k: list(dict.fromkeys(v)) for k, v in out.items()}


def load(ep: Episode) -> dict[str, Any]:
    return parse(ep.path("script.md").read_text(encoding="utf-8"))
