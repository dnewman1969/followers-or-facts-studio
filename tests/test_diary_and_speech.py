"""Dave 2026-11-02: narration read out web addresses and sounded like a reference index; and he wants to send
the run's logs so we can see where the story gets lost."""

import json
import zipfile

from fofstudio import diary, pipeline
from fofstudio.speakable import speakable, spoken_source, unspeakable
from tests.test_pipeline import episode, research_and_story  # noqa: F401 - shared fixture


def test_owlbert_never_reads_out_a_reference():
    assert speakable("According to infowars.com/fema-camps-exposed, the camps were ready.") == \
        "According to Infowars' website, the camps were ready."
    assert speakable("A 2019 report (source: S-GOV-12) at https://www.gao.gov/x/gao-19-1.pdf says no camps "
                     "exist.") == "A 2019 report says no camps exist."
    assert speakable("Court records in case No. 1:18-cv-01234 show he lost. See doc. 45. Then he left.") == \
        "Court records show he lost. Then he left."
    kept = 'He said "go to infowars.com now" on air.'      # a verified quote is never changed
    assert speakable(kept) == kept
    for fine in ("He paid in cash. On the show, he sold buckets of food.", "HR 645 was about emergency centers."):
        assert speakable(fine) == fine and not unspeakable(fine)
    assert spoken_source({"source_type": "government", "publisher": "U.S. Senate", "date": "2019-05-01",
                          "title": "gao-19-1.pdf"}) == "a 2019 U.S. Senate report"
    assert spoken_source({"source_type": "court", "date": "2018"}) == "court records from 2018"


def test_the_saved_script_has_no_references_in_its_narration(episode):
    from fofstudio.scriptfmt import parse, render
    text = render("T", [{"scene_id": "SCENE_001", "narration": "Read it at www.example.com/a.pdf today.",
                         "visual": "x"}])
    assert parse(text)["scenes"][0]["narration"] == "Read it today."


def test_every_step_writes_the_diary_and_it_packs_into_one_zip(episode):
    ep = episode
    research_and_story(ep)
    pipeline.run_now(ep, "script")
    pipeline.approve(ep, "script")
    pipeline.run_now(ep, "storyboard")
    md = ep.path("diary", "diary.md").read_text(encoding="utf-8")
    assert "· script ·" in md and "· storyboard ·" in md and "you approved script" in md
    assert "story_thread" in md and "opens:" in md
    entries = [json.loads(x) for x in ep.path("diary", "diary.jsonl").read_text(encoding="utf-8").splitlines()]
    script_entry = next(e for e in entries if e.get("stage") == "script")
    assert script_entry["section"]["scenes"] and all("story_thread" in r for r in script_entry["section"]["scenes"])
    board_entry = next(e for e in entries if e.get("stage") == "storyboard")
    assert board_entry["section"]["shots"] and board_entry["log"]
    z = diary.bundle(ep)
    names = zipfile.ZipFile(z).namelist()
    assert "episode/diary/diary.md" in names and "episode/script.md" in names and "README.txt" in names
    assert not [n for n in names if n.endswith((".png", ".jpg", ".mp4", ".wav"))]
    assert diary.thread_score({"camps", "fema", "bill"}, "The bill was about emergency camps") > 0


def test_a_dull_picture_is_lifted_but_a_black_and_white_style_stays_grey(tmp_path):
    """Dave 2026-11-02: "the pics and video are still very bland"."""
    import numpy as np
    from PIL import Image

    from fofstudio import appeal
    y, x = np.mgrid[0:120, 0:200]
    dim = np.stack([40 + x * 0.15, 45 + y * 0.12, 55 + 0 * x], -1).clip(0, 255).astype(np.uint8)
    Image.fromarray(dim).save(tmp_path / "dim.png")
    r = appeal.lift(tmp_path / "dim.png", tmp_path / "lift.png", "documentary illustration")
    assert r["lifted"] and r["after"]["brightness"] > r["before"]["brightness"] + 0.15
    assert r["after"]["colourfulness"] > r["before"]["colourfulness"]
    mono = appeal.lift(tmp_path / "dim.png", tmp_path / "mono.png", "film noir, black and white")
    assert mono["lifted"] and "grey" not in mono["why"]
    flat = np.zeros((60, 80, 3), np.uint8)
    flat[..., 0], flat[..., 1] = 230, 120
    Image.fromarray(flat).save(tmp_path / "flat.png")
    assert not appeal.lift(tmp_path / "flat.png", tmp_path / "f2.png")["lifted"]    # flat colour is a style


def test_a_punchy_line_lands_once_and_a_story_beat_is_told_once():
    from fofstudio.stages.script import dedupe_scenes
    from fofstudio.stages.stories import _clean
    scenes = [{"scene_id": "SCENE_001", "narration": "He sold buckets of food. No one stopped him. The money came in."},
              {"scene_id": "SCENE_002", "narration": "The bill passed in a week. No one stopped him. Courts did later."}]
    notes = dedupe_scenes(scenes, {"claims": []})
    assert "No one stopped him" not in scenes[1]["narration"] and "No one stopped him" in scenes[0]["narration"]
    assert any("said before" in n for n in notes)
    story = {"title": "t", "beats": [
        {"role": "claim", "beat": "He told listeners the camps were ready at infowars.com/camps.", "evidence_ids": []},
        {"role": "record", "beat": "He told listeners the camps were ready", "evidence_ids": []},
        {"role": "verdict", "beat": "The bill was about emergency centers, not camps.", "evidence_ids": []}]}
    out = _clean(story, set())
    assert len(out["beats"]) == 2 and "infowars.com" not in out["beats"][0]["beat"]
