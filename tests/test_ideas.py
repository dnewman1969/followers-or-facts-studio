"""Scan data for stories (Dave, 2026-10-30): list every info clip, short and long story with its length, then make
2 stories, 2 info clips or 1 book from the one picked, with the chosen writer."""

from fofstudio import pipeline
from fofstudio.stages import ideas, stories
from fofstudio.util import read_json
from tests.test_pipeline import episode, research_and_story, tick_all  # noqa: F401 - shared fixture


def _approved_research(ep):
    pipeline.run_now(ep, "research", {"depth": "quick"})
    tick_all(ep)
    pipeline.approve(ep, "research")


def test_scan_lists_ideas_with_honest_lengths(episode):
    ep = episode
    _approved_research(ep)
    pipeline.run_now(ep, "ideas")
    found = ideas.load(ep)
    titles = [i["title"] for i in found]
    assert "Made-up idea" not in titles                       # uses nothing from the research: dropped
    assert sum(1 for t in titles if t.lower() == "the radio that sold fear") == 1    # repeats dropped
    clip = next(i for i in found if i["kind"] == "clip")
    assert 30 <= clip["seconds"] <= 90 and clip["evidence_ids"]
    saga = next(i for i in found if "saga" in i["pitch"])
    assert saga["kind"] == "short" and saga["seconds"] <= 600   # thin material isn't padded into a long story
    assert [i["id"] for i in found] == [f"I{n:02d}" for n in range(1, len(found) + 1)]


def test_two_info_clips_from_an_idea_with_the_chosen_writer(episode):
    ep = episode
    _approved_research(ep)
    pipeline.run_now(ep, "ideas")
    clip = next(i for i in ideas.load(ep) if i["kind"] == "clip")
    ep.set_creative(writer="socratic_professor")
    pipeline.run_now(ep, "stories", {"idea": clip, "make": "clip"})
    data = read_json(ep.path("stories.json"))
    assert len(data["options"]) == stories.STORY_COUNT and data["idea"]["id"] == clip["id"]
    for o in data["options"]:
        assert o["format"] == "clip" and o["idea"] == clip["id"] and o["length_seconds"] <= 90
        assert o["writer"] == "socratic_professor"
    stories.choose(ep, 0)
    pipeline.approve(ep, "stories")          # an info clip goes on to the script like any story
    assert ep.creative()["minutes"] <= 1.5


def test_one_book_from_an_idea(episode):
    from fofstudio.stages import book
    ep = episode
    _approved_research(ep)
    pipeline.run_now(ep, "ideas")
    idea = ideas.load(ep)[-1]
    pipeline.run_now(ep, "book", {"idea": idea, "fresh": True})
    b = book.load(ep)
    assert b["idea"]["id"] == idea["id"] and b.get("pdf")
