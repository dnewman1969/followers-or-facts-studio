"""The Virtual Director: the quality gate between the storyboard plan and the painting."""

from fofstudio import director as vd
from fofstudio import pipeline
from fofstudio.llm import Ollama
from fofstudio.stages import storyboard
from fofstudio.util import read_json
from tests.test_pipeline import episode, research_and_story  # noqa: F401 - the shared fixture and setup

SAME = "A close-up of a ticking clock on an office desk, harsh shadows, blue tones"


def scene(ideas, narration="Late at night in the office, the clock ticks toward midnight.", sid="SCENE_001"):
    return {"scene_id": sid, "narration": narration, "visual": "an office at night",
            "shots": [{"shot_id": f"{sid}-s{i + 1:02d}", "kind": "broll", "idea": x, "person_id": "",
                       "candidates": [None]} for i, x in enumerate(ideas)]}


def flat(scenes):
    return [sh for sc in scenes for sh in sc["shots"]]


def test_reading_the_look_from_an_idea():
    look = vd.infer_look("Low angle wide shot of a radio station at night, moonlit, sepia tones, a man pointing")
    assert look["shot_type"] == "wide" and look["angle"] == "low angle" and look["lighting"] == "moonlight"
    assert look["palette"] == "sepia" and look["pose"] == "pointing" and "radio station" in look["location"]
    planned = vd.infer_look("whatever", {"shot_type": "crane", "angle": "nonsense", "intensity": "12"})
    assert planned["shot_type"] == "crane" and planned["angle"] == "" and planned["intensity"] == 10


def test_similarity_scores_and_decisions():
    a = {"idea": SAME, "look": vd.infer_look(SAME)}
    other = "Wide establishing view of a snowy train station at golden hour, travellers walking"
    b = {"idea": other, "look": vd.infer_look(other)}
    assert vd.similarity(a, a) >= 90 and vd.similarity(a, b) < 30
    seq = [{"shot_id": f"s{i}", **a} for i in range(2)]
    r = vd.score(seq, 1)
    assert r["similarity"] >= 90 and vd.verdict(r) == "REJECT" and r["similar_to"] == "s0"


def test_pattern_rules():
    def shot(t, angle="eye level", move="static", loc="office", pose="none", light="", pal="", i=None):
        return {"shot_id": "x", "idea": f"{t} {loc}", "look": {"shot_type": t, "angle": angle, "movement": move,
                "location": loc, "pose": pose, "lighting": light, "palette": pal, "intensity": i}}
    seq = [shot("close-up"), shot("extreme close-up", angle="high angle"), shot("close-up", angle="low angle")]
    assert "close-ups" in {k for k, _ in vd.rule_issues(seq, 2)}
    seq = [shot(t, move="static", angle=a, loc=l) for t, a, l in
           zip(["wide", "medium", "close-up", "wide", "medium"], ["high angle", "low angle", "eye level",
               "overhead", "high angle"], ["a", "b", "c", "d", "e"])]
    assert "static" in {k for k, _ in vd.rule_issues(seq, 4)}
    seq = [shot("wide", loc=f"p{n}", angle=a, i=9) for n, a in enumerate(
        ["high angle", "low angle", "eye level", "overhead", "high angle"])]
    assert "pacing" in {k for k, _ in vd.rule_issues(seq, 4)}
    seq = [shot(t, angle="eye level", loc=f"p{n}", move=m) for n, (t, m) in enumerate(
        [("wide", "pan"), ("medium", "tilt"), ("close-up", "orbit"), ("wide", "crane")])]
    assert {k for k, _ in vd.rule_issues(seq, 3)} == {"angle"}


def test_repeated_shots_are_repaired_before_painting(monkeypatch):
    calls = []
    monkeypatch.setattr(Ollama, "chat_json", lambda self, m, schema, **kw: calls.append(1) or
                        {"idea": SAME, "why": "same again", **vd.infer_look(SAME)})   # an AI that can't fix it
    scenes = [scene([SAME] * 6)]
    review = vd.direct(scenes)
    seq = flat(scenes)
    assert calls, "failing shots go to the director AI first"
    assert review["summary"]["REJECTED"] == 0 and review["summary"]["REPAIRED"] >= 4
    assert seq[0]["review"]["decision"] == "APPROVED" and seq[0]["idea"] == SAME
    for i in range(len(seq)):
        assert vd.history_similarity(seq, i)[0] < vd.REJECT_AT
        assert not {k for k, _ in vd.rule_issues(seq, i)} & set(vd.HARD)
    assert all(sh["review"].get("before", {}).get("idea") == SAME for sh in seq[1:] if sh["review"]["decision"] == "REPAIRED")
    md = vd.to_markdown(review)
    assert "DIRECTOR REVIEW" in md and "Similarity Score" in md and "Decision: **REPAIRED**" in md


def test_continuity_beats_variety(monkeypatch):
    monkeypatch.setattr(Ollama, "chat_json", lambda self, m, schema, **kw: {
        "idea": "Wide shot of a sunny beach at golden hour", "why": "variety", "location": "beach",
        "shot_type": "wide", "angle": "high angle", "movement": "drone", "pose": "none", "emotion": "free",
        "lighting": "golden hour", "palette": "orange", "intensity": 3})
    night = "A close-up of a ticking clock on an office desk, moonlit, blue tones"
    scenes = [scene([night] * 3)]
    vd.direct(scenes)
    for sh in flat(scenes):
        assert "beach" not in sh["idea"], "a jump to a place the scene never goes is turned down"
    notes = " ".join(c for sh in flat(scenes) for c in sh["review"]["changes"])
    assert "continuity first" in notes
    assert vd.continuity_problem({"look": {"location": "office"}}, {"location": "office", "lighting": "golden hour"},
                                 "x", "the office", [{"look": {"lighting": "moonlight", "location": "office"}}])


def test_names_and_your_own_ideas_are_never_rewritten(monkeypatch):
    monkeypatch.setattr(Ollama, "chat_json", lambda self, m, schema, **kw: {
        "idea": "Gary Northman sits at the office desk", "why": "", "location": "office", "shot_type": "medium",
        "angle": "low angle", "movement": "push-in", "pose": "sitting", "emotion": "", "lighting": "",
        "palette": "", "intensity": 4})
    scenes = [scene([SAME] * 3)]
    scenes[0]["shots"][2]["by_hand"] = True
    vd.direct(scenes, names=["Gary Northman"])
    seq = flat(scenes)
    assert all("Northman" not in sh["idea"] for sh in seq)
    assert seq[2]["idea"] == SAME and seq[2]["review"]["by_hand"]


def test_review_only_mode_changes_nothing(monkeypatch):
    monkeypatch.setattr(Ollama, "chat_json", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no AI")))
    scenes = [scene([SAME] * 3)]
    review = vd.direct(scenes, repair=False)
    assert all(sh["idea"] == SAME for sh in flat(scenes)) and review["summary"]["REJECTED"] == 2


def test_camera_moves_reach_the_video_step():
    assert vd.camera_for({"movement": "push-in"}) == ("zoom_in", vd.MOVE_WORDS["push-in"])
    assert vd.camera_for({"movement": "pan"}, "pan_right")[0] == "pan_left"   # two pans don't drift the same way
    assert vd.camera_for({}) == ("", "")
    assert "low angle" in vd.look_words({"shot_type": "wide", "angle": "low angle", "lighting": "fog"})


def test_storyboard_goes_through_the_director(episode):
    ep = episode
    research_and_story(ep)
    pipeline.run_now(ep, "script")
    pipeline.approve(ep, "script")
    pipeline.run_now(ep, "storyboard")
    board = ep.storyboard()
    used = [sh for s in board["scenes"] for sh in s["shots"]]
    assert used and all(sh.get("review") and sh.get("look") for sh in used)
    review = read_json(ep.path("director-review.json"))
    assert review["summary"]["shots"] == len(used) and review["summary"]["REJECTED"] == 0
    assert ep.path("director-review.md").exists()
    checks = [c.message for c in pipeline.checks(ep, "storyboard")]
    assert any(m.startswith("Virtual Director:") for m in checks)
    framed = [sh for sh in used if sh["look"].get("shot_type")]
    assert framed and all(sh["look"]["shot_type"] in (sh["candidates"][0] or {}).get("full_prompt", "")
                          for sh in framed if (sh["candidates"][0] or {}).get("full_prompt"))
    # a repeat of the shots before blocks approval until it's fixed
    first = used[1]
    first["review"] = {**first["review"], "decision": "REJECTED", "issues": ["3 close-ups in a row"]}
    ep.save_storyboard(board)
    assert any("rejected 1 shot" in c.message for c in pipeline.checks(ep, "storyboard") if c.level == "block")
    first["review"]["decision"] = "APPROVED"
    ep.save_storyboard(board)
    # your own words are scored, never rewritten
    storyboard.set_idea(ep, used[2]["shot_id"], "My own idea: an empty radio studio at dawn")
    shot = next(sh for s in ep.storyboard()["scenes"] for sh in s["shots"] if sh["shot_id"] == used[2]["shot_id"])
    assert shot["by_hand"] and "look" not in shot

