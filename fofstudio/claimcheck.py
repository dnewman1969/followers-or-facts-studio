"""Does it hold up? Claims that aren't well proven stay out of the video (Dave, 2026-10-28).

From the research "AI writer repetition and claim checks" (fact-checking pipelines and professional standards):
  * a claim is used only if its debunk is SUPPORTED: rule A, a primary record (court, government, the
    subject's own official statement) from your research database or with a word-for-word verified quote;
    or rule B, at least two INDEPENDENT sources each with a verified quote; or rule C, two independent sources
    from your own research database (you checked those yourself). Independent means a different
    website and publisher, and quotes that aren't near-copies of each other (wire copy counts once);
  * a claim whose own verdict is "unverified" or "contested" doesn't hold up either;
  * a claim that falls short gets a DEEP DIVE (hidden stage `deepdive`): who/what/when/where/which-document
    questions, searched primary-records first by the research agents. Finds arrive on the Research page NEW and
    unticked (nothing reaches a script until you tick it). If it still doesn't hold up, it's left out;
  * "not found" never means "false": a claim that can't be proven is left out, never debunked;
  * after the script is written, every sentence that states a fact is checked against the scene's own quotes
    and sources by a different model than the writer; a sentence it can't support is taken out, never added
    to (the check can only remove, so your Approve stays the final word). Everything is logged in
    claim-check.json: under US defamation law the record of what was checked and dropped shows good faith.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from .repeats import similarity
from .util import StageError, read_json, utc_now, write_json

WEAK_VERDICTS = ("unverified", "contested", "unproven", "unknown", "disputed")
SUPPORT_SCHEMA = {"type": "object", "properties": {"verdicts": {"type": "array", "items": {
    "type": "object", "properties": {"sentence": {"type": "integer"},
                                     "verdict": {"type": "string", "enum": ["supported", "not_supported", "no_fact"]},
                                     "why": {"type": "string"}},
    "required": ["sentence", "verdict", "why"]}}}, "required": ["verdicts"]}
QUESTION_SCHEMA = {"type": "object", "properties": {"questions": {"type": "array", "minItems": 3, "maxItems": 6,
                                                                  "items": {"type": "string"}}},
                   "required": ["questions"]}


def site(url: str | None) -> str:
    host = (urlparse(url or "").netloc or "").lower().removeprefix("www.")
    parts = host.split(".")
    if len(parts) >= 3 and parts[-2] in ("co", "com", "org", "gov", "ac", "net"):
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if host else ""


def independent_groups(sources: list[dict[str, Any]], excerpts: list[dict[str, Any]]) -> list[list[str]]:
    """Sources that count as separate confirmations: one per website/publisher, near-copies merged."""
    quotes = {s["source_id"]: [e["text"] for e in excerpts if e["source_id"] == s["source_id"]] for s in sources}
    groups: list[list[str]] = []
    keys: list[set[str]] = []
    for s in sources:
        mine = {k for k in (site(s.get("url")), (s.get("publisher") or "").strip().lower()) if k}
        home = None
        for i, g in enumerate(groups):
            same_owner = bool(mine & keys[i])
            copied = any(similarity(a, b) >= 0.6 for a in quotes[s["source_id"]] for o in g for b in quotes.get(o, []))
            if same_owner or copied:
                home = i
                break
        if home is None:
            groups.append([s["source_id"]])
            keys.append(mine)
        else:
            groups[home].append(s["source_id"])
            keys[home] |= mine
    return groups


def assess(claim: dict[str, Any]) -> dict[str, Any]:
    """Whether this (ticked) claim holds up, and why."""
    verdict = (claim.get("falsity_status") or "").lower()
    srcs, ex = claim.get("sources", []), claim.get("excerpts", [])
    quoted = {e["source_id"] for e in ex}
    base = {"claim_id": claim["claim_id"], "title": claim.get("short_title", "")}
    if any(w in verdict for w in WEAK_VERDICTS):
        return {**base, "status": "weak", "rule": "", "why": f"its verdict is '{verdict}', not proven"}
    primary = [s["source_id"] for s in srcs if s.get("is_primary") and
               (s["source_id"] in quoted or (s.get("found_by") or "database") == "database")]
    if primary:
        return {**base, "status": "supported", "rule": "A", "why": f"primary record(s): {', '.join(primary[:3])}"}
    groups = independent_groups([s for s in srcs if s["source_id"] in quoted], ex)
    if len(groups) >= 2:
        return {**base, "status": "supported", "rule": "B",
                "why": f"{len(groups)} independent sources with verified quotes"}
    # rule C: your own research database was checked by you, so two independent sources from it count, quoted or
    # not (an agent's find still needs its words checked against the saved page)
    vetted = [s for s in srcs if (s.get("found_by") or "database") == "database" and s.get("source_type") != "kf_index"]
    vetted_groups = independent_groups(vetted + [s for s in srcs if s["source_id"] in quoted and s not in vetted], ex)
    if len(vetted_groups) >= 2 and vetted:
        return {**base, "status": "supported", "rule": "C",
                "why": f"{len(vetted_groups)} independent sources, from your research database"}
    return {**base, "status": "weak", "rule": "",
            "why": (f"only {len(groups)} independent source with a verified quote and no primary record"
                    if groups else "no verified quote and no primary record")}


def split_packet(packet: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """(the packet with only claims that hold up, the claims left out and why)."""
    keep, out = [], []
    for c in packet.get("claims", []):
        a = assess(c)
        (keep if a["status"] == "supported" else out).append(c if a["status"] == "supported" else a)
    kept_ids = {c["claim_id"] for c in keep}
    return {**packet, "claims": keep,
            "evidence": [e for e in packet.get("evidence", []) if e.get("claim_id") in kept_ids]}, out


def log(ep, **fields: Any) -> None:
    data = read_json(ep.path("claim-check.json"), {}) or {}
    data.update(fields, updated_at=utc_now())
    write_json(ep.path("claim-check.json"), data)


# ------------------------------------------------------------------ deep dive (hidden stage `deepdive`)
def deep_dive(ctx) -> None:
    """For each ticked claim that doesn't hold up: plan 3-6 questions, search primary records first, and say
    what turned up. Finds arrive NEW and unticked on the Research page."""
    from .llm import Ollama
    from .stages import research
    from .stages.script import selected_packet
    ep = ctx.episode
    _, weak = split_packet(selected_packet(ep, check=False))
    if not weak:
        ctx.progress("Every ticked claim already holds up: nothing to dig for.", 100)
        log(ep, deep_dive={"at": utc_now(), "claims": []})
        return
    packet = research.build_packet(ep)
    by_id = {c["claim_id"]: c for c in packet["claims"]}
    llm = Ollama(job="research_plan")
    questions, plans = [], []
    for n, w in enumerate(weak):
        c = by_id.get(w["claim_id"])
        if not c:
            continue
        ctx.progress(f"Planning the deep dive for {w['claim_id']} ({n + 1} of {len(weak)})", 5 + 10 * n / len(weak))
        ans = llm.chat_json([
            {"role": "system", "content": (
                "You plan a fact-checker's deep dive on a FALSE claim sold by people who are known to lie (for "
                "example a conspiracy broadcaster and his guests). Never try to prove the claim itself true. Write "
                "3 to 6 short questions that check the RECORD from primary documents: (1) attribution: when and "
                "where exactly did they say or sell it (show date, episode, archived web page, transcript, court "
                "exhibit or deposition); (2) what courts, regulators, official records or independent experts "
                "found; (3) who profited and how, as documented (sales pages, filings, judgments). One fact per "
                "question. Never assume the answer.")},
            {"role": "user", "content": f"Claim: {c['short_title']}\nWhat we have: {c.get('claim_summary') or ''}\n"
                                        f"Why it doesn't hold up yet: {w['why']}"}],
            QUESTION_SCHEMA, lenient=True, temperature=0.3)
        qs = [q.strip() for q in (ans.get("questions") or []) if len(q.split()) >= 4][:6]
        plans.append({"claim_id": w["claim_id"], "why_weak": w["why"], "questions": qs})
        questions += [{"claim_id": w["claim_id"], "question": q} for q in qs]
    if not questions:
        raise StageError("The deep dive couldn't plan any questions. Check that Ollama is running, then try again.")
    before = {e["id"] for e in packet["evidence"]}
    ctx.options["questions"] = questions
    research.lookup(ctx)   # the research agents: primary documents first, quotes verified word for word
    after = research.build_packet(ep)
    new = [e for e in after["evidence"] if e["id"] not in before]
    for p in plans:
        p["found"] = [e["id"] for e in new if e["claim_id"] == p["claim_id"]]
        p["result"] = (f"{len(p['found'])} new item(s): tick them on the Research page if they're right" if p["found"]
                       else "searched, nothing new found: it stays out of the video")
    log(ep, deep_dive={"at": utc_now(), "claims": plans})
    found = sum(len(p["found"]) for p in plans)
    ctx.progress(f"Deep dive done: {found} new item(s) for {len(plans)} claim(s). Tick the right ones on the "
                 "Research page; claims that still don't hold up stay out of the script.", 100)


# ------------------------------------------------------------------ every fact sentence, after writing
FACTY = re.compile(r"\d|\b(?:court|judge|jury|ruled|filed|paid|sold|million|billion|percent|dollars|sued|"
                   r"found|according|records?|report(?:ed)?)\b", re.IGNORECASE)


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text or "") if s.strip()]


def check_sentences(sc: dict[str, Any], evidence: str, quotes: list[str], llm, model: str) -> tuple[str, list[dict]]:
    """Take out sentences in this scene that state a fact its own evidence doesn't support. Only removes."""
    ss = _sentences(sc.get("narration", ""))
    candidates = [(i, s) for i, s in enumerate(ss) if FACTY.search(s)
                  and not any(q[:40].lower() in s.lower() for q in quotes if q)]   # a verified quote is its own proof
    if not candidates or not evidence.strip():
        return sc.get("narration", ""), []
    ans = llm.chat_json([
        {"role": "system", "content": (
            "You are a strict fact-checker. For each numbered sentence, say whether the EVIDENCE below supports "
            "every fact it states (names, dates, numbers, who did what): 'supported', 'not_supported' (a fact in "
            "it isn't in the evidence or goes beyond it), or 'no_fact' (an opinion, question, transition or "
            "general idea with no specific fact). Judge only against the evidence, never your own knowledge.")},
        {"role": "user", "content": "EVIDENCE:\n" + evidence + "\n\nSENTENCES:\n"
                                    + "\n".join(f"[{i}] {s}" for i, s in candidates)}],
        SUPPORT_SCHEMA, model=model, lenient=True, temperature=0)
    drop = {v["sentence"]: v.get("why", "") for v in (ans.get("verdicts") or [])
            if v.get("verdict") == "not_supported" and isinstance(v.get("sentence"), int)}
    drop = {i: why for i, why in drop.items() if 0 <= i < len(ss) and any(i == c for c, _ in candidates)}
    if len(ss) - len(drop) < 1:
        return sc.get("narration", ""), [{"sentence": ss[i], "why": w, "kept": "the only sentence left"}
                                         for i, w in drop.items()]
    kept = " ".join(s for i, s in enumerate(ss) if i not in drop)
    return kept, [{"sentence": ss[i], "why": w} for i, w in drop.items()]
