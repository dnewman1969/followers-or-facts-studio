"""A whole episode, Database choice to packaged video, with fake AI services (ffmpeg is real)."""

import pytest

from fofstudio import db, media, pipeline, scriptfmt, subjects
from fofstudio.agents import search, web
from fofstudio.episode import Episode
from fofstudio.llm import Ollama
from fofstudio.stages import production, stories, storyboard, video
from fofstudio.util import StageError, read_json

FOUND_URL = "https://www.courtlistener.com/opinion/123/test-v-jones/"
FOUND_TEXT = ("Background. The court finds that the defendant sold survival supplies while telling "
              "listeners the grid would fail. The jury awarded damages to the families.")


def fake_llm(get_packet):
    def chat_json(self, messages, schema, model=None, **kw):
        props = schema["properties"]
        if "queries" in props:
            return {"queries": ["survival supplies court ruling", "y2k radio fear"]}
        if "excerpts" in props:
            text = messages[-1]["content"]
            if "survival supplies" in text:
                return {"excerpts": [{"quote": "The court finds that the defendant sold survival supplies "
                                               "while telling listeners the grid would fail.",
                                      "supports": "who profited"},
                                     {"quote": "The court found he was a great man.", "supports": "made up"}]}
            return {"excerpts": []}
        if "beats" in props:
            ev = [e["id"] for e in get_packet()["evidence"]][:2]
            return {"title": "The Y2K Fear Machine", "logline": "A real bug, sold as doom.", "angle": "money",
                    "opening_hook": "Midnight, 1999.", "owl_moments": ["opens at his desk"],
                    "beats": [{"role": r, "beat": f"The {r} beat.", "evidence_ids": ev + ["E-MADE-UP"]}
                              for r in ("intro", "claim", "record", "benefit", "harm", "verdict")]}
        if "scenes" in props:
            claims = get_packet()["claims"]
            scenes = []
            for role, c in zip(["intro", "claim", "record", "benefit", "harm", "verdict"], (claims * 6)[:6]):
                prim = [s["source_id"] for s in c["sources"] if s["is_primary"]][:2]
                scenes.append({"role": role, "visual": "An old desk with a newspaper and a clock",
                               "narration": f"This is the {role} part. It is short and plain. "
                                            "People were scared, and someone sold that fear.",
                               "on_screen_text": "December 31, 1999" if role == "intro" else "",
                               "claim_ids": [] if role in ("intro", "verdict") else [c["claim_id"]],
                               "source_ids": [] if role in ("intro", "verdict") else prim, "excerpt_ids": []})
            return {"title": "The Y2K Fear Machine", "scenes": scenes}
        if "ideas" in props:
            return {"ideas": ["a radio studio at night", "a close-up of a clock at midnight",
                              "a candle beside a stack of canned food"]}
        if "how_it_plays" in props:
            return {"how_it_plays": "The camera drifts toward the clock.", "motion_prompt": "slow push in",
                    "camera": "zoom_in", "seconds": 4}
        raise AssertionError(schema)
    return chat_json


@pytest.fixture()
def episode(data, fakes):
    b = subjects.breakdown("story", "A-Y2K-FEAR-INDUSTRY")
    ep = Episode.create("S01E01", b["title"], "A-Y2K-FEAR-INDUSTRY", b["claim_ids"])
    fakes.setattr(Ollama, "chat_json", fake_llm(lambda: read_json(ep.path("research.json"))))
    fakes.setattr(search, "search_all", lambda q: [{"title": "Test v. Jones", "url": FOUND_URL, "snippet": "",
                                                     "finder": "courtlistener"}])
    fakes.setattr(web, "fetch", lambda url, timeout=40: (
        web._store(url, url, 200, "text/html", f"<html><body><p>{FOUND_TEXT}</p></body></html>".encode(), "web")
        if url == FOUND_URL else {"ok": False, "url": url, "error": "offline in tests"}))
    fakes.setattr(web, "fetch_via_wayback", lambda url: {"ok": False, "url": url, "error": "offline"})
    fakes.setattr(web, "save_page_now", lambda url: "https://web.archive.org/web/2026/" + url)
    fakes.setattr(web, "wayback_closest", lambda url, timestamp=None: None)
    from fofstudio import sources
    fakes.setattr(sources, "fetch_source", lambda sid, refresh=False: {"source_id": sid, "ok": False,
                                                                        "error": "offline in tests"})
    return ep


def research_and_story(ep):
    pipeline.run_now(ep, "research", {"depth": "quick"})
    pipeline.approve(ep, "research")
    pipeline.run_now(ep, "stories")
    with pytest.raises(StageError, match="Pick one"):
        pipeline.approve(ep, "stories")
    stories.choose(ep, 1)
    pipeline.approve(ep, "stories")


def test_full_episode(episode):
    ep = episode
    research_and_story(ep)
    packet = read_json(ep.path("research.json"))
    found = [e for e in packet["evidence"] if e.get("found_by") == "agent"]
    assert found and found[0]["type"] == "court" and found[0]["archive_url"].startswith("https://web.archive.org")
    # the agent's made-up quote was thrown away; the real one kept
    quotes = [e["quote"] for e in packet["evidence"] if e["kind"] == "quote"]
    assert any("survival supplies" in q for q in quotes) and not any("great man" in q for q in quotes)
    # a made-up evidence ID in a story beat is dropped
    assert all("E-MADE-UP" not in b["evidence_ids"] for b in stories.chosen(ep)["beats"])

    pipeline.run_now(ep, "script")
    pipeline.approve(ep, "script")
    pipeline.run_now(ep, "storyboard")
    with pytest.raises(StageError, match="pick at least one"):
        pipeline.approve(ep, "storyboard")
    for s in ep.storyboard()["scenes"]:
        assert len([c for c in s["candidates"] if c]) == 3
        storyboard.set_picks(ep, s["scene_id"], [0, 2])
    pipeline.approve(ep, "storyboard")

    pipeline.run_now(ep, "video_plan")
    pipeline.approve(ep, "video_plan")
    pipeline.run_now(ep, "video")
    with pytest.raises(StageError, match="not approved"):
        pipeline.approve(ep, "video")
    plan = video.load_plan(ep)
    assert {s["method"] for s in plan["shots"]} == {"animate", "camera_move"}
    for s in plan["shots"]:
        video.update_shot(ep, s["shot_id"], approved=True)
    pipeline.approve(ep, "video")

    pipeline.run_now(ep, "narration")
    pipeline.approve(ep, "narration")
    pipeline.run_now(ep, "captions")
    pipeline.approve(ep, "captions")
    pipeline.run_now(ep, "music")
    pipeline.approve(ep, "music")
    pipeline.run_now(ep, "production")
    tl = production.load(ep)
    assert tl["video"][0]["kind"] == "bumper" and tl["video"][-1]["kind"] == "bumper"
    assert len(tl["speech"]) == 6 and len(tl["owl"]) == 6 and tl["music"]
    pipeline.approve(ep, "production")

    pipeline.run_now(ep, "preview")  # works any time, no approval needed
    prev = read_json(ep.path("render", "preview.json"))
    assert ep.abs(prev["output"]).exists() and prev["draft"]

    pipeline.run_now(ep, "render")
    pipeline.approve(ep, "render")
    info = read_json(ep.path("render", "timeline.json"))
    out = ep.abs(info["output"])
    assert media.has_audio(out)
    assert abs(media.duration(out) - production.timeline_end(tl)) < 1.0
    srt = ep.abs(info["srt"]).read_text(encoding="utf-8")
    assert "-->" in srt and "fear" in srt

    pipeline.run_now(ep, "package")
    meta = read_json(ep.path("publish", "metadata.json"))
    assert FOUND_URL in meta["description"] and "web.archive.org" in meta["description"]
    assert "Knowledge Fight" in meta["description"]
    pipeline.approve(ep, "package")


def test_editing_the_timeline_needs_a_new_render(episode):
    ep = episode
    research_and_story(ep)
    for st in ("script",):
        pipeline.run_now(ep, st)
        pipeline.approve(ep, st)
    pipeline.run_now(ep, "storyboard")
    for s in ep.storyboard()["scenes"]:
        storyboard.set_picks(ep, s["scene_id"], [0])
    pipeline.approve(ep, "storyboard")
    pipeline.run_now(ep, "video_plan")
    pipeline.approve(ep, "video_plan")
    for s in video.load_plan(ep)["shots"]:
        video.update_shot(ep, s["shot_id"], method="camera_move")
    pipeline.run_now(ep, "video")
    for s in video.load_plan(ep)["shots"]:
        video.update_shot(ep, s["shot_id"], approved=True)
    pipeline.approve(ep, "video")
    for st in ("narration", "captions"):
        pipeline.run_now(ep, st)
        pipeline.approve(ep, st)
    pipeline.skip(ep, "music")
    pipeline.run_now(ep, "production")
    pipeline.approve(ep, "production")
    pipeline.run_now(ep, "render")
    pipeline.approve(ep, "render")
    tl = production.load(ep)
    tl["speech"][0]["start"] += 0.5
    production.save(ep, tl)
    assert any("changed the timeline" in c.message for c in pipeline.checks(ep, "render"))


def test_invented_source_is_blocked(episode):
    ep = episode
    research_and_story(ep)
    pipeline.run_now(ep, "script")
    text = ep.path("script.md").read_text(encoding="utf-8")
    ep.path("script.md").write_text(text.replace("sources: S-", "sources: S-MADE-UP-123, S-", 1), encoding="utf-8")
    with pytest.raises(StageError, match="doesn't exist"):
        pipeline.approve(ep, "script")


def test_unverified_quote_is_blocked(episode):
    ep = episode
    research_and_story(ep)
    pipeline.run_now(ep, "script")
    text = ep.path("script.md").read_text(encoding="utf-8")
    ep.path("script.md").write_text(text.replace(
        "This is the record part.", 'The report said "the grid will fail on New Year\'s Day".', 1), encoding="utf-8")
    with pytest.raises(StageError, match="verified quote"):
        pipeline.approve(ep, "script")


def test_real_person_in_picture_idea_is_blocked(episode):
    ep = episode
    research_and_story(ep)
    pipeline.run_now(ep, "script")
    pipeline.approve(ep, "script")
    pipeline.run_now(ep, "storyboard")
    board = ep.storyboard()
    for s in board["scenes"]:
        s["picked"] = [0]
    board["scenes"][0]["candidates"][0]["prompt"] = "Alex Jones shouting into a microphone"
    ep.save_storyboard(board)
    with pytest.raises(StageError, match="real person"):
        pipeline.approve(ep, "storyboard")


def test_redo_resets_later_approvals(episode):
    ep = episode
    research_and_story(ep)
    pipeline.run_now(ep, "research", {"depth": "quick"})
    assert ep.stage_status("stories")["status"] == "reset"


def test_database_page_lists_and_breakdowns(data):
    for kind in subjects.KINDS:
        rows = subjects.listing(kind)
        assert rows, kind
        b = subjects.breakdown(kind, rows[0]["id"])
        assert b["claims"] and "What the video will cover" in subjects.breakdown_html(b)


def test_script_roundtrip():
    scenes = [{"scene_id": "SCENE_001", "role": "claim", "est_seconds": 30, "visual": "v",
               "narration": "Hello there.", "on_screen_text": "1999", "claim_ids": ["C-A"],
               "source_ids": ["S-B", "S-C"], "excerpt_ids": [12]}]
    parsed = scriptfmt.parse(scriptfmt.render("T", scenes))
    sc = parsed["scenes"][0]
    assert parsed["title"] == "T" and sc["role"] == "claim" and sc["source_ids"] == ["S-B", "S-C"]
    assert sc["excerpt_ids"] == ["12"] and sc["narration"] == "Hello there."
