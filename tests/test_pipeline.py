"""Runs a whole episode from the research database to a packaged video, with fake GPU services."""

import pytest

from fofstudio import media, pipeline, scriptfmt
from fofstudio.episode import Episode
from fofstudio.llm import Ollama
from fofstudio.util import StageError, read_json


def fake_llm(packet_holder):
    def chat_json(self, messages, schema, model=None, **kw):
        props = schema["properties"]
        if "excerpts" in props:
            return {"excerpts": []}
        if "scenes" in props:
            claims = packet_holder()["claims"]
            scenes = []
            for role, c in zip(["intro", "claim", "record", "benefit", "harm", "verdict"],
                               (claims * 6)[:6]):
                prim = [s["source_id"] for s in c["sources"] if s["is_primary"]][:2]
                scenes.append({"role": role, "visual": "An old desk with a newspaper and a clock",
                               "narration": f"This is the {role} part. It is short and plain. "
                                            "People were scared, and someone sold that fear.",
                               "on_screen_text": "December 31, 1999" if role == "intro" else "",
                               "claim_ids": [] if role in ("intro", "verdict") else [c["claim_id"]],
                               "source_ids": [] if role in ("intro", "verdict") else prim,
                               "excerpt_ids": []})
            return {"title": "The Y2K Fear Machine", "scenes": scenes}
        if "shots" in props:
            return {"shots": [
                {"type": "ai_image", "prompt": "a radio studio at night", "text": "", "weight": 2,
                 "camera": "zoom_in"},
                {"type": "title_card", "prompt": "", "text": "Midnight, 1999", "weight": 1,
                 "camera": "static"}]}
        raise AssertionError(schema)
    return chat_json


@pytest.fixture()
def episode(data, fakes):
    ep = Episode.create("S01E01", "Y2K fear industry", "A-Y2K-FEAR-INDUSTRY")
    fakes.setattr(Ollama, "chat_json", fake_llm(lambda: read_json(ep.path("research.json"))))
    return ep


def test_full_episode(episode):
    ep = episode
    pipeline.run_now(ep, "research", {"fetch_sources": False, "find_quotes": False})
    pipeline.approve(ep, "research")

    with pytest.raises(StageError):
        pipeline.approve(ep, "storyboard")  # can't skip ahead

    pipeline.run_now(ep, "script")
    pipeline.approve(ep, "script")
    pipeline.run_now(ep, "storyboard")
    board = ep.storyboard()
    assert board["shots"][-1]["type"] == "credits"
    assert all("no recognizable real people" in s["full_prompt"]
               for s in board["shots"] if s["type"] == "ai_image")
    pipeline.approve(ep, "storyboard")

    pipeline.run_now(ep, "narration")
    pipeline.approve(ep, "narration")
    pipeline.run_now(ep, "images")
    pipeline.approve(ep, "images")
    pipeline.run_now(ep, "video")
    pipeline.approve(ep, "video")
    pipeline.run_now(ep, "captions")
    pipeline.approve(ep, "captions")
    pipeline.run_now(ep, "music")
    pipeline.approve(ep, "music")

    pipeline.run_now(ep, "render")
    pipeline.approve(ep, "render")
    timeline = read_json(ep.path("render", "timeline.json"))
    out = ep.abs(timeline["output"])
    narr = read_json(ep.path("audio", "narration.json"))
    speech = sum(m["seconds"] for m in narr.values())
    length = media.duration(out)
    assert media.has_audio(out)
    assert speech + 10 < length < speech + 10 + len(narr) * 2  # narration + credits + small gaps
    srt = ep.abs(timeline["srt"]).read_text(encoding="utf-8")
    assert "-->" in srt and "fear" in srt
    assert any(s["kind"] == "clip" for s in timeline["shots"])

    pipeline.run_now(ep, "package")
    meta = read_json(ep.path("publish", "metadata.json"))
    assert "Knowledge Fight" in meta["description"] and "Sources" in meta["description"]
    assert meta["contains_synthetic_media"] is True
    assert ep.path("publish", "thumbnail.png").exists()
    pipeline.approve(ep, "package")


def test_invented_source_is_blocked(episode):
    ep = episode
    pipeline.run_now(ep, "research", {"fetch_sources": False, "find_quotes": False})
    pipeline.approve(ep, "research")
    pipeline.run_now(ep, "script")
    text = ep.path("script.md").read_text(encoding="utf-8")
    ep.path("script.md").write_text(text.replace("sources: S-", "sources: S-MADE-UP-123, S-", 1),
                                    encoding="utf-8")
    with pytest.raises(StageError, match="doesn't exist"):
        pipeline.approve(ep, "script")


def test_unverified_quote_is_blocked(episode):
    ep = episode
    pipeline.run_now(ep, "research", {"fetch_sources": False, "find_quotes": False})
    pipeline.approve(ep, "research")
    pipeline.run_now(ep, "script")
    text = ep.path("script.md").read_text(encoding="utf-8")
    ep.path("script.md").write_text(text.replace(
        "This is the record part.", 'The report said "the grid will fail on New Year\'s Day".', 1),
        encoding="utf-8")
    with pytest.raises(StageError, match="verified quote"):
        pipeline.approve(ep, "script")


def test_redo_resets_later_approvals(episode):
    ep = episode
    pipeline.run_now(ep, "research", {"fetch_sources": False, "find_quotes": False})
    pipeline.approve(ep, "research")
    pipeline.run_now(ep, "script")
    pipeline.approve(ep, "script")
    pipeline.run_now(ep, "research", {"fetch_sources": False, "find_quotes": False})
    assert ep.stage_status("script")["status"] == "reset"


def test_real_person_in_prompt_is_blocked(episode):
    ep = episode
    pipeline.run_now(ep, "research", {"fetch_sources": False, "find_quotes": False})
    pipeline.approve(ep, "research")
    pipeline.run_now(ep, "script")
    pipeline.approve(ep, "script")
    pipeline.run_now(ep, "storyboard")
    board = ep.storyboard()
    board["shots"][0]["prompt"] = "Alex Jones shouting into a microphone"
    ep.save_storyboard(board)
    with pytest.raises(StageError, match="real person"):
        pipeline.approve(ep, "storyboard")


def test_script_roundtrip():
    scenes = [{"scene_id": "SCENE_001", "role": "claim", "est_seconds": 30, "visual": "v",
               "narration": "Hello there.", "on_screen_text": "1999", "claim_ids": ["C-A"],
               "source_ids": ["S-B", "S-C"], "excerpt_ids": [12]}]
    parsed = scriptfmt.parse(scriptfmt.render("T", scenes))
    sc = parsed["scenes"][0]
    assert parsed["title"] == "T" and sc["role"] == "claim" and sc["source_ids"] == ["S-B", "S-C"]
    assert sc["excerpt_ids"] == ["12"] and sc["narration"] == "Hello there."
