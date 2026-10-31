"""The AI directing pipeline (Dave, 2026-10-31): shots follow the script, don't repeat, animate safely, and a
quality review redoes what fails."""

from pathlib import Path

from fofstudio import bible, pipeline, review, shotplan
from fofstudio.util import read_json
from tests.test_pipeline import episode, research_and_story  # noqa: F401 - shared fixture


def test_narration_is_cut_into_one_piece_per_shot():
    text = ("In 1999 the radio host warned of collapse. He sold buckets of food, generators, and gold coins. "
            "The Senate report found the grid held. Nothing failed.")
    for n in (1, 2, 3, 4, 6):
        parts = shotplan.segments(text, n)
        assert len(parts) == n and " ".join(parts).split() == text.split()[:len(" ".join(parts).split())]
    assert shotplan.segments(text, 4)[2] == "The Senate report found the grid held."   # whole sentences first


def test_risky_pictures_never_go_to_the_animation_model():
    assert shotplan.animation_risk({"shows": "place", "idea": "a radio tower on a hill at dusk"})["band"] == "low"
    doc = shotplan.animation_risk({"shows": "document", "idea": "a stamped page under a lamp"})
    assert doc["band"] == "high" and doc["risk"] >= 65
    crowd = shotplan.animation_risk({"shows": "crowd from behind", "idea": "people watching a stage",
                                     "look": {"shot_type": "wide"}})
    assert crowd["band"] == "high"
    assert shotplan.motion_safety({"shows": "document", "idea": "a page"})[0] == "2.5d"


def test_motion_layers_and_no_negatives():
    p = shotplan.motion_prompt("a slow push-in", "slow", "the man raises a mug, no text", ["drifting smoke"], "low")
    assert "no text" not in p and "push-in" in p and "mug" in p and "smoke" in p
    assert "mug" not in shotplan.motion_prompt("a slow push-in", "slow", "the man raises a mug", [], "medium")


def test_storyboard_follows_the_script_and_varies_subjects(episode):
    ep = episode
    research_and_story(ep)
    pipeline.run_now(ep, "script")
    pipeline.approve(ep, "script")
    pipeline.run_now(ep, "storyboard")
    b = bible.load(ep)
    assert "radio_shop" in b["locations"] and "listener" in b["characters"]
    assert "kid" not in b["characters"]                                 # never a child, in any form
    board = ep.storyboard()
    for sc in board["scenes"]:
        covered = " ".join(sh["covers"] for sh in sc["shots"]).split()
        assert covered == sc["narration"].split()[:len(covered)] and sc["shots"]   # each shot has its own words
    seq = [sh for sc in board["scenes"] for sh in sc["shots"]]
    assert not shotplan.shows_problems([s for s in seq if s.get("shows")][:2]) or \
        any(sh.get("varied_from") for sh in seq)                          # repeated documents were re-planned
    assert all("anim" in sh and 1 <= sh["anim"]["risk"] <= 100 for sh in seq)
    shot = next(sh for sh in seq if sh["kind"] == "broll")
    prompt = shot["candidates"][0]["full_prompt"]
    assert "radio shop" in prompt or "courthouse" in prompt              # the bible's place, every time
    qr = read_json(ep.path("quality-review.json"))
    assert [k for k, _ in review.QUESTIONS] == list(qr["answers"])
    assert Path(ep.path("quality-review.md")).exists()


def test_quality_review_answers_and_repaints(episode, monkeypatch):
    from fofstudio.llm import Ollama
    ep = episode
    research_and_story(ep)
    pipeline.run_now(ep, "script")
    pipeline.approve(ep, "script")
    looked = []

    def vision(self, messages, model=None, **kw):
        looked.append(messages[0]["content"])
        # the first picture "has writing in it": it gets painted again once
        return "1. yes\n2. yes\n3. yes\n4. yes" if len(looked) == 1 else "1. yes\n2. no\n3. yes\n4. yes"
    monkeypatch.setattr(Ollama, "chat", vision)
    pipeline.run_now(ep, "storyboard")
    seq = [sh for sc in ep.storyboard()["scenes"] for sh in sc["shots"]]
    assert all(sh.get("vision") for sh in seq if sh["kind"] != "real")     # every picture was looked at
    qr = read_json(ep.path("quality-review.json"))
    # the fake planner never shows "a pile of generators" the bible asks for: failing scenes were re-planned once
    assert qr["redone"] and not qr["answers"]["moments"]["ok"] and not qr["approved"]
    assert len(looked) > len(seq)                                          # the repaint was looked at again


def test_a_broken_clip_is_caught(tmp_path):
    import subprocess

    from fofstudio import finishing, media
    good, bad = tmp_path / "good.mp4", tmp_path / "bad.mp4"
    subprocess.run([media.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=16",
                    "-t", "2", str(good)], check=True)
    subprocess.run([media.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=16",
                    "-f", "lavfi", "-i", "color=c=black:size=320x180:rate=16", "-filter_complex",
                    "[0:v]trim=0:1,setpts=PTS-STARTPTS[a];[1:v]trim=0:0.2,setpts=PTS-STARTPTS[b];"
                    "[0:v]trim=1:2,setpts=PTS-STARTPTS,hue=h=180[c];[a][b][c]concat=n=3:v=1", str(bad)], check=True)
    assert finishing.check_clip(good)["ok"] and not finishing.check_clip(bad)["ok"]
    out = finishing.finish_clip(good, None, tmp_path / "final.mp4", 30, 320, 180)
    assert abs(media.fps(out) - 30) < 0.5 and media.size(out) == (320, 180)


def test_unreal_guide_pictures_steer_the_painting(episode, monkeypatch):
    """Dave (2026-10-31): Unreal Engine renders (depth, outlines, poses) as guide pictures for a place."""
    from PIL import Image

    from fofstudio import comfy, controlmaps
    from fofstudio.util import write_json
    ep = episode
    research_and_story(ep)
    pipeline.run_now(ep, "script")
    pipeline.approve(ep, "script")
    pipeline.run_now(ep, "storyboard")
    sid = ep.storyboard()["scenes"][0]["scene_id"]
    loc = bible.load(ep)["scenes"][sid]["location"]
    folder = controlmaps.folder_for_location(loc)
    folder.mkdir(parents=True, exist_ok=True)
    for name in ("cam1-depth.png", "cam2-lineart.png"):
        Image.new("RGB", (64, 36), "gray").save(folder / name)
    uploaded = []
    monkeypatch.setattr(comfy.Comfy, "upload_image", lambda self, p: uploaded.append(p) or p.name)
    shots = [sh for sh in ep.storyboard()["scenes"][0]["shots"] if sh["kind"] == "broll"]
    assert controlmaps.guide_for(ep, shots[0]).parent == folder
    pipeline.run_now(ep, "storyboard", {"replan": [sid]})
    painted = [sh for sh in ep.storyboard()["scenes"][0]["shots"] if sh["kind"] == "broll"]
    assert uploaded and all(c.get("guide") for sh in painted for c in sh["candidates"] if c)
    # a scene's own guide pictures win over its place's
    own = ep.path("control", sid)
    own.mkdir(parents=True)
    Image.new("RGB", (64, 36), "white").save(own / "pose.png")
    assert controlmaps.guide_for(ep, painted[0]) == own / "pose.png"
