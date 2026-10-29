"""Claims that don't hold up stay out; each quote once; repeats deleted; the length follows the material."""

import pytest

from fofstudio import claimcheck, pipeline
from fofstudio.stages import script as script_stage
from fofstudio.util import StageError, read_json
from tests.test_pipeline import episode, research_and_story  # noqa: F401 - the shared fixture and setup


def claim(cid="C-1", verdict="false", sources=(), excerpts=()):
    return {"claim_id": cid, "short_title": "A claim", "falsity_status": verdict, "sources": list(sources),
            "excerpts": list(excerpts)}


def src(sid, url, primary=0, found_by="agent", publisher=""):
    return {"source_id": sid, "url": url, "is_primary": primary, "found_by": found_by, "publisher": publisher}


def ex(eid, sid, text):
    return {"excerpt_id": eid, "source_id": sid, "text": text}


def test_a_claim_holds_up_with_a_primary_record_or_two_independent_sources():
    court = claim(sources=[src("S-1", "https://www.courtlistener.com/x", primary=1)],
                  excerpts=[ex(1, "S-1", "The court finds the defendant sold supplies.")])
    assert claimcheck.assess(court)["status"] == "supported" and claimcheck.assess(court)["rule"] == "A"
    database = claim(sources=[src("S-2", "https://gov.example/x", primary=1, found_by="database")])
    assert claimcheck.assess(database)["rule"] == "A"            # your vetted research database
    two = claim(sources=[src("S-3", "https://apnews.com/a"), src("S-4", "https://www.npr.org/b")],
                excerpts=[ex(3, "S-3", "Prices for survival kits tripled in the final week of December."),
                          ex(4, "S-4", "The host told listeners the grid would fail and read out an order line.")])
    assert claimcheck.assess(two)["rule"] == "B"


def test_copies_and_one_website_count_once():
    same_site = claim(sources=[src("S-3", "https://www.example.com/a"), src("S-4", "https://example.com/b")],
                      excerpts=[ex(3, "S-3", "Prices for survival kits tripled in the final week."),
                                ex(4, "S-4", "The host told listeners the grid would fail tonight.")])
    assert claimcheck.assess(same_site)["status"] == "weak"
    wire = "Prices for survival kits tripled in the final week of December, records show."
    copied = claim(sources=[src("S-5", "https://paper-one.com/a"), src("S-6", "https://paper-two.com/b")],
                   excerpts=[ex(5, "S-5", wire), ex(6, "S-6", wire.replace("records show", "records showed"))])
    assert claimcheck.assess(copied)["status"] == "weak"            # syndicated wire copy counts once
    unproven = claim(verdict="unverified", sources=[src("S-1", "https://x.gov/a", primary=1, found_by="database")])
    assert claimcheck.assess(unproven)["status"] == "weak" and "unverified" in claimcheck.assess(unproven)["why"]
    packet, out = claimcheck.split_packet({"claims": [unproven, same_site], "evidence": [{"claim_id": "C-1"}]})
    assert packet["claims"] == [] and packet["evidence"] == [] and len(out) == 2


def test_each_scene_sees_only_its_own_quotes():
    packet = {"claims": [{"claim_id": "C-1", "short_title": "t", "falsity_status": "false",
                          "sources": [{"source_id": "S-1", "title": "Ruling", "date": "2001"}],
                          "excerpts": [ex(7, "S-1", "Quote seven."), ex(8, "S-1", "Quote eight.")]}]}
    mine = script_stage._facts_for({"claim_ids": ["C-1"], "source_ids": ["S-1"], "excerpt_ids": [8]}, packet)
    assert "Quote eight." in mine and "Quote seven." not in mine   # a shared source doesn't bring its quotes


def test_repeats_and_reused_quotes_are_deleted_not_rewritten():
    quote = "the grid would fail and every family needed a generator by Christmas"
    packet = {"claims": [{"claim_id": "C-1", "sources": [], "excerpts": [ex(5, "S-1", quote)]}]}
    scenes = [
        {"scene_id": "SCENE_001", "role": "record", "excerpt_ids": [5],
         "narration": f'He said "{quote}". The county sold four hundred generators that month. Hoo.'},
        {"scene_id": "SCENE_002", "role": "harm", "excerpt_ids": [5],
         "narration": f'Remember, he said "{quote}". Families emptied their savings accounts for useless '
                      "generators. The county sold four hundred generators that month. Some waited a year for refunds."},
    ]
    notes = script_stage.dedupe_scenes(scenes, packet)
    second = scenes[1]["narration"]
    assert quote not in second and "four hundred generators that month" not in second
    assert "emptied their savings" in second and "refunds" in second
    assert scenes[1]["excerpt_ids"] == [] and quote in scenes[0]["narration"]
    assert any("E5" in n for n in notes)


def test_the_ledger_lists_topics_not_sentences():
    packet = {"claims": [{"claim_id": "C-1", "short_title": "Y2K grid failure"}]}
    led = script_stage.topic_ledger([{"scene_id": "SCENE_001", "role": "record", "claim_ids": ["C-1"],
                                      "excerpt_ids": [5], "narration": "In 1999 the county sold 400 generators."}],
                                    packet)
    assert "C-1 (Y2K grid failure)" in led and "E5" in led and "1999" in led and "400" in led
    assert "county sold" not in led


def test_length_follows_the_material():
    thin = {"role": "record", "excerpt_ids": [], "source_ids": []}
    rich = {"role": "record", "excerpt_ids": [1, 2], "source_ids": ["S-1", "S-2"]}
    assert script_stage.material_cap(thin) < script_stage.material_cap(rich)
    assert script_stage.material_cap({"role": "intro"}) >= 80


def test_the_script_is_fact_checked_sentence_by_sentence(episode, monkeypatch):
    from fofstudio.llm import Ollama
    ep = episode
    research_and_story(ep)
    inner = Ollama.chat_json

    def writer_invents(self, messages, schema, **kw):
        out = inner(self, messages, schema, **kw)
        if "narration" in schema["properties"] and "Role: record" in messages[1]["content"]:
            out["narration"] += " An invented 1997 lawsuit settled for 9 million dollars."
        return out
    monkeypatch.setattr(Ollama, "chat_json", writer_invents)
    pipeline.run_now(ep, "script")
    text = ep.path("script.md").read_text(encoding="utf-8")
    assert "invented 1997 lawsuit" not in text
    log = read_json(ep.path("claim-check.json"))
    assert any("invented" in r["sentence"] for r in log["sentences"]["removed"])
    assert any("fact check took out" in c.message for c in pipeline.checks(ep, "script"))


def test_claims_that_dont_hold_up_stay_out_and_get_a_deep_dive(episode, monkeypatch):
    ep = episode
    research_and_story(ep)
    from fofstudio import claimcheck as cc
    real = cc.assess
    monkeypatch.setattr(cc, "assess", lambda c: {**real(c), "status": "weak", "rule": "", "why": "test: weak"})
    assert script_stage.selected_packet(ep)["claims"] == []
    with pytest.raises(StageError, match="holds up"):
        pipeline.run_now(ep, "script")
    pipeline.run_now(ep, "deepdive")
    dive = read_json(ep.path("claim-check.json"))["deep_dive"]["claims"]
    assert dive and all(len(d["questions"]) >= 3 and d["result"] for d in dive)


def test_two_sources_from_your_own_database_hold_up():
    vetted = claim(sources=[src("S-7", "https://www.nytimes.com/a", found_by="database"),
                            src("S-8", "https://www.mediamatters.org/b", found_by="database")])
    assert claimcheck.assess(vetted)["rule"] == "C"
    one = claim(sources=[src("S-7", "https://www.nytimes.com/a", found_by="database")])
    assert claimcheck.assess(one)["status"] == "weak"
    agents = claim(sources=[src("S-9", "https://a.example/x"), src("S-10", "https://b.example/y")])
    assert claimcheck.assess(agents)["status"] == "weak"       # an agent's finds still need checked quotes
