"""The script writer as a cinematic story architect: the film treatment and the arc."""

from fofstudio import pipeline, repeats
from fofstudio.stages import treatment as tr
from fofstudio.util import read_json

from tests.test_pipeline import episode, research_and_story  # noqa: F401 - the shared episode fixture and setup


def test_arc_runs_in_order_from_hook_to_implications():
    for n in (3, 5, 8, 12, 20):
        planned = [{"role": "record"} for _ in range(n)]
        tr.assign_arc(planned)
        arcs = [p["arc"] for p in planned]
        assert arcs[0] == "hook" and arcs[-1] == "implications"
        order = [tr.ARC_KEYS.index(a) for a in arcs]
        assert order == sorted(order), arcs
    planned = [{"role": "record"} for _ in range(12)]
    tr.assign_arc(planned)
    assert {"hook", "setup", "rising", "discovery", "climax", "resolution", "implications"} <= \
        {p["arc"] for p in planned}


def test_invented_characters_and_unproved_revelations_are_dropped():
    packet = {"claims": [{"claim_id": "C1", "people": [{"name": "Hal Turner"}], "orgs": [{"name": "WXYZ Radio"}],
                          "sources": [{"source_id": "S-1"}], "excerpts": [{"excerpt_id": 7}]}]}
    ids = {"claim_ids": ["C1"], "source_ids": ["S-1"], "excerpt_ids": [7]}
    raw = {"film_title": "T", "logline": "L", "opening_scene": "O",
           "acts": [{"act": 2, "title": "b"}, {"act": 1, "title": "a"}, {"act": 3, "title": "c"}],
           "key_characters": [{"name": "Hal Turner", "evidence": ["S-1", "S-9"]},
                              {"name": "WXYZ Radio", "evidence": []},
                              {"name": "the believers", "evidence": []},
                              {"name": "Sarah Miller, a worried mom", "evidence": ["S-1"]}],
           "revelations": [{"reveal": "Proved", "arc": "climax", "evidence": ["E7"]},
                           {"reveal": "Made up", "arc": "climax", "evidence": ["S-9"]}]}
    t = tr.tidy(raw, packet, ids)
    assert [c["name"] for c in t["key_characters"]] == ["Hal Turner", "WXYZ Radio", "the believers"]
    assert t["dropped_characters"] == ["Sarah Miller, a worried mom"]
    assert t["key_characters"][0]["evidence"] == ["S-1"]
    assert [r["reveal"] for r in t["revelations"]] == ["Proved"]
    assert [a["act"] for a in t["acts"]] == [1, 2, 3]


def test_revelation_goes_to_the_scene_with_its_proof():
    planned = [{"source_ids": ["S-1"], "excerpt_ids": []}, {"source_ids": ["S-2"], "excerpt_ids": [4]},
               {"source_ids": [], "excerpt_ids": []}]
    tr.assign_arc(planned)
    tr.place_revelations({"revelations": [{"reveal": "The receipt", "arc": "hook", "evidence": ["E4"]}]}, planned)
    assert planned[1]["revelation"] == "The receipt" and "revelation" not in planned[0]


def test_report_language_counts_as_stock():
    found = repeats.stock_phrases("According to the research, the bug was real. In summary, it was sold.")
    assert "according to the research" in found and "in summary" in found


def test_script_is_written_from_a_film_treatment(episode):
    ep = episode
    research_and_story(ep)
    pipeline.run_now(ep, "script")
    t = read_json(ep.path("treatment.json"))
    assert t["film_title"] == "Midnight Money" and len(t["acts"]) == 3
    names = [c["name"] for c in t["key_characters"]]
    assert "Dr. Invented Person" not in names and "Radio listeners" in names
    assert all("S-MADE-UP" not in c["evidence"] for c in t["key_characters"])
    assert [r["reveal"] for r in t["revelations"]] == ["The court found he sold the supplies."]
    md = ep.path("treatment.md").read_text(encoding="utf-8")
    for part in ("Logline", "Opening scene", "Three-act structure", "Key characters", "Major revelations",
                 "Emotional arc"):
        assert part in md
    script = ep.path("script.md").read_text(encoding="utf-8")
    assert "Midnight Money" in script   # the header names the film
    assert "Dr. Invented Person" not in script
    html = tr.to_html(t)
    assert "Midnight Money" in html and "<script" not in html


def test_every_scene_gets_its_place_in_the_film(episode, monkeypatch):
    from fofstudio.llm import Ollama
    ep = episode
    research_and_story(ep)
    seen = []
    inner = Ollama.chat_json

    def spy(self, messages, schema, **kw):
        if "narration" in schema["properties"]:
            seen.append(messages[1]["content"])
        return inner(self, messages, schema, **kw)
    monkeypatch.setattr(Ollama, "chat_json", spy)
    pipeline.run_now(ep, "script")
    firsts = list(dict.fromkeys(m for m in seen if "Write scene" in m))   # a polish re-sends the same brief
    assert firsts and all("THE FILM: \"Midnight Money\"" in m and "place in the arc" in m for m in firsts)
    assert "Hook:" in firsts[0] and "Open the film like this" in firsts[0]
    assert "End on this thought" in firsts[-1]
    assert sum("The revelation this scene must land" in m for m in firsts) == 1
