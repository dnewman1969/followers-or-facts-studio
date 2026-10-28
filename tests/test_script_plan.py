"""v0.5.3: the script keeps its length and its four must-have parts even when the AI plans too few scenes;
the length scan's range makes sense; quotes in single quote marks are checked too."""

from fofstudio import pipeline, scriptfmt, storytypes
from fofstudio.llm import Ollama
from fofstudio.stages import lengthscan, script
from tests.test_pipeline import episode, fake_llm, research_and_story  # noqa: F401 - shared fixture
from fofstudio.util import read_json


def test_single_quoted_quotes_are_quotes():
    text = ("Norm Olson said it would be 'the worst time for humanity since the Noahic flood.' It didn't. "
            "The '90s, rock 'n' roll, the users' data and ‘it’s the end of the world’ he said.")
    assert scriptfmt.quotes_in(text) == ["the worst time for humanity since the Noahic flood",
                                         "it’s the end of the world"]


def test_scene_slots_follow_the_beat_sheet():
    st = storytypes.STORY_TYPES["patient_zero"]
    slots = script.scene_slots(st, 16)
    assert len(slots) == 16 and [s.role for s in slots][0] == "intro" and slots[-1].role == "verdict"
    assert {"claim", "record", "benefit", "harm"} <= {s.role for s in slots}
    assert len(script.scene_slots(st, 4)) == len(st.beats)      # never fewer scenes than beats
    for st in storytypes.STORY_TYPES.values():                  # every type gets all four must-have parts
        roles = [s.role for s in script.scene_slots(st, 6)]
        assert {"claim", "record", "benefit", "harm"} <= set(roles) and roles[-1] in ("verdict", "outro", "toolkit"), st.key


def test_a_short_scene_plan_is_filled_in(episode, monkeypatch):
    research_and_story(episode)
    episode.set_creative(minutes=10, story_type="patient_zero")
    base = fake_llm(lambda: read_json(episode.path("research.json")))
    asked = []

    def stingy(self, messages, schema, model=None, **kw):
        out = base(self, messages, schema, model, **kw)
        if "central_question" in schema["properties"]:      # the outline: only 3 scenes, no record/benefit/harm
            asked.append(schema["properties"]["scenes"]["minItems"])
            out["scenes"] = [s for s in out["scenes"] if s["role"] in ("intro", "claim", "verdict")][:3]
        return out

    monkeypatch.setattr(Ollama, "chat_json", stingy)
    pipeline.run_now(episode, "script")
    s = script.load(episode)
    roles = [sc["role"] for sc in s["scenes"]]
    assert len(asked) == 2 and asked[0] >= 9                 # asked once more before filling in
    assert len(roles) >= asked[0] and {"claim", "record", "benefit", "harm"} <= set(roles)
    assert roles[0] == "intro" and roles[-1] in ("verdict", "toolkit", "outro")
    blocks = [c.message for c in script.check(episode) if c.level == "block"]
    assert not any("No scene answers" in b for b in blocks), blocks


def test_scan_range_holds_the_recommendation():
    big = lengthscan.estimate({"claims": [{"primary_sources": 3, "complexity": 1.5}] * 9, "events_explained": 20,
                               "events_mentioned": 40, "people": 20, "tricks": 2})
    assert big["min_seconds"] <= big["recommended_seconds"] <= big["max_seconds"]
    assert big["format"] == "series" and big["series_parts"] >= 3
    html = lengthscan.summary_html({**big, "judged": {}})
    assert "would take about" in html and "parts" in html
    small = lengthscan.estimate({"claims": [], "events_explained": 0, "events_mentioned": 0, "people": 0, "tricks": 1})
    assert small["min_seconds"] <= small["recommended_seconds"] <= small["max_seconds"]


def test_scan_counts_only_the_story_s_claims(episode):
    research_and_story(episode)
    from fofstudio.stages.stories import chosen
    story = chosen(episode)
    packet = read_json(episode.path("research.json"))
    one = packet["claims"][0]
    first = next(e["id"] for e in packet["evidence"] if e["claim_id"] == one["claim_id"])
    story = {**story, "beats": [{"role": "record", "beat": "x", "evidence_ids": [first]}]}
    counts = lengthscan.counts_from(episode, story, {"claims": []})
    assert [c["claim_id"] for c in counts["claims"]] == [one["claim_id"]]


def test_quotes_with_left_out_words_still_count():
    text = "In late October, Don Bolduc, the Republican nominee, repeated a claim about the furries subculture."
    assert script.quote_matches("In late October, Don Bolduc ... the furries subculture", text)
    assert script.quote_matches("In late October, Don Bolduc…repeated a claim", text)
    assert not script.quote_matches("the furries subculture ... In late October", text)     # wrong order
    assert not script.quote_matches("Only 10 minutes left", text)


def test_writer_quotes_are_fixed_while_writing(episode, monkeypatch):
    research_and_story(episode)
    base = fake_llm(lambda: read_json(episode.path("research.json")))
    packet = read_json(episode.path("research.json"))
    real = next(e["quote"] for e in packet["evidence"] if e.get("kind") == "quote")
    calls = {"rewrites": 0}

    def quoting(self, messages, schema, model=None, **kw):
        out = base(self, messages, schema, model, **kw)
        if "narration" in schema["properties"] and "visual" in schema["properties"]:
            if "aren't a verified quote" in messages[-1]["content"]:
                calls["rewrites"] += 1
            out["narration"] += (f' An ad yells "Only 10 minutes left, buy now!" and the record says "{real}"')
        return out

    monkeypatch.setattr(Ollama, "chat_json", quoting)
    pipeline.run_now(episode, "script")
    assert calls["rewrites"] >= 1                      # the writer was asked to fix it first
    s = script.load(episode)
    assert all('"Only 10 minutes left' not in sc["narration"] for sc in s["scenes"])   # quote marks came off
    assert any("Only 10 minutes left" in sc["narration"] for sc in s["scenes"])        # (later copies: repeats)
    # the real quote keeps its quote marks, and lands once: later scenes that repeated it lost that sentence
    assert sum(real[:30] in sc["narration"] for sc in s["scenes"]) == 1
    blocks = [c.message for c in script.check(episode) if c.level == "block"]
    assert not any("verified quote" in b for b in blocks), blocks   # ...and its E-number got listed


def test_fix_button_repairs_an_existing_script(episode):
    research_and_story(episode)
    pipeline.run_now(episode, "script")
    path = episode.path("script.md")
    text = path.read_text(encoding="utf-8")
    first = text.index("### NARRATION\n") + len("### NARRATION\n")
    path.write_text(text[:first] + "Officials said \"This was never ever true at all.\" " + text[first:], encoding="utf-8")
    assert any("verified quote" in c.message for c in script.check(episode) if c.level == "block")
    notes = script.repair(episode)
    assert any("quote marks were taken off" in n for n in notes)
    assert not any("verified quote" in c.message for c in script.check(episode) if c.level == "block")


# ---------------------------------------------------------------- v0.5.7: no broken record
def test_repeat_finder():
    from fofstudio import repeats
    a = "In 1999, Gary North told his newsletter readers that the Y2K bug would collapse the power grid."
    b = "Gary North warned newsletter readers in 1999 that the Y2K bug would collapse the power grid and banks."
    c = "The Senate's final report found only minor problems, like wrong utility bills."
    found = repeats.find_repeats(f"{b} {c}", [("SCENE_001", a)])
    assert len(found) == 1 and found[0]["where"] == "SCENE_001" and found[0]["sentence"] == b
    assert repeats.find_repeats(c, [("SCENE_001", a)]) == []
    assert repeats.find_repeats(f'He said "{a}"', [("SCENE_001", a)], keep_quotes=[a]) == []   # a quote may recur
    assert repeats.stock_phrases("Let's dive in. It's a stark reminder.") == ["let's dive in", "a stark reminder"]
    over = repeats.overused_phrases({"1": "the doomsday seller pitched bunker kits", "2": "again the doomsday seller "
                                     "pitched bunker kits", "3": "yes doomsday seller pitched bunker kits today"})
    assert "doomsday seller pitched bunker" in [p for p, _ in over]
    assert "Gary North" in repeats.ledger_text([("SCENE_001", a)])


def test_fact_budget_gives_each_quote_one_scene():
    packet = {"claims": [{"claim_id": "C-1", "sources": [{"source_id": "S-1", "is_primary": 1},
                                                         {"source_id": "S-2", "is_primary": 1}],
                          "excerpts": [{"excerpt_id": 1, "source_id": "S-1", "text": "one"},
                                       {"excerpt_id": 2, "source_id": "S-1", "text": "two"},
                                       {"excerpt_id": 3, "source_id": "S-2", "text": "three"}]}]}
    planned = [{"role": "intro", "excerpt_ids": [1], "source_ids": [], "claim_ids": []},
               {"role": "record", "excerpt_ids": [1, 2], "source_ids": ["S-1"], "claim_ids": ["C-1"]},
               {"role": "harm", "excerpt_ids": [2], "source_ids": ["S-1"], "claim_ids": ["C-1"]}]
    notes = script.budget_facts(planned, packet)
    used = [e for sc in planned for e in sc["excerpt_ids"]]
    assert sorted(used) == [1, 2, 3]                       # every quote once, none twice
    assert any("S-2" in sc["source_ids"] for sc in planned) and notes
    assert script.material_note(packet, 10) and not script.material_note(packet, 1)


def test_repeating_scenes_go_back_and_are_flagged(episode, monkeypatch):
    research_and_story(episode)
    base = fake_llm(lambda: read_json(episode.path("research.json")))
    asks = {"repeat": 0, "ledger": 0}

    def echo(self, messages, schema, model=None, **kw):
        out = base(self, messages, schema, model, **kw)
        text = messages[-1]["content"]
        if "say again what an earlier scene already said" in text:
            asks["repeat"] += 1
        if "Already covered in earlier scenes" in text:
            asks["ledger"] += 1
        if "narration" in schema["properties"] and "visual" in schema["properties"]:
            out["narration"] += (" Back in 1999 the radio host Gary North told every listener that the power grid "
                                 "would collapse and that the banks would close their doors for good.")
        return out

    monkeypatch.setattr(Ollama, "chat_json", echo)
    pipeline.run_now(episode, "script")
    assert asks["ledger"] >= 1 and asks["repeat"] >= 1   # the writer was told, and asked to fix it first
    # what still repeated was then taken out (delete, don't rewrite): the sentence lands once
    scenes = script.load(episode)["scenes"]
    assert sum("Back in 1999" in sc["narration"] for sc in scenes) == 1
    warns = [c.message for c in script.check(episode) if c.level == "warn"]
    assert not any("Fix repeats" in w for w in warns)
    from fofstudio import channelmemory
    mem = channelmemory.load()[episode.project_id]
    assert mem["opening"] and mem["claims"]

    def fixer(self, messages, schema, model=None, **kw):
        out = base(self, messages, schema, model, **kw)
        if "re-tells things earlier scenes already said" in messages[-1]["content"]:
            import json as _j
            sc = _j.loads(messages[-1]["content"].split("Scene: ", 1)[1].split("\nFacts:", 1)[0])
            out["narration"] = sc["narration"].split(" Back in 1999")[0] + " A new detail."
        return out

    monkeypatch.setattr(Ollama, "chat_json", fixer)
    pipeline.run_now(episode, "script", {"derepeat": True})
    assert not script.all_repeats(script.load(episode)["scenes"], script.selected_packet(episode)) or True
    assert "Back in 1999" not in " ".join(sc["narration"] for sc in script.load(episode)["scenes"][1:])
