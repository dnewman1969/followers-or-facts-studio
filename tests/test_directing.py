"""v0.4.4: the script directs the music and Owlbert; the program keeps both within the rules."""

import pytest

from fofstudio import bits, media, musicbook, pipeline, scriptfmt, sfx
from fofstudio.stages import music as music_stage
from fofstudio.stages import production
from fofstudio.stages.script import load as load_script, tidy_directions
from fofstudio.util import read_json
from tests.test_pipeline import episode, research_and_story  # noqa: F401 - shared fixture


def test_music_and_owlbert_lines_survive_editing():
    sc = {"scene_id": "SCENE_003", "role": "record", "visual": "v", "narration": "The memo itself says no.",
          "music": {"mood": "investigative", "energy": 2, "change": "crossfade", "drop_before": "The memo"},
          "owlbert": [{"move": "hat_trick", "prop": "document", "at": "The memo itself"}, {"move": "glasses"}]}
    back = scriptfmt.parse(scriptfmt.render("T", [sc]))["scenes"][0]
    assert back["music"] == sc["music"] and back["owlbert"] == sc["owlbert"]


def test_the_writer_is_kept_to_the_rules():
    before = [{"music": {"change": "sting"}}] * 6
    harm = {"scene_id": "S5", "role": "harm", "narration": "Families lost their savings. It was real.",
            "music": {"mood": "playful", "energy": 5, "change": "sting", "sting_at": "lost their savings"},
            "owlbert": [{"move": "point", "prop": "", "at": "words he never says"}, {"move": "dance", "prop": "", "at": ""}]}
    notes = tidy_directions(harm, {"careful": False}, before)
    assert harm["music"]["mood"] == "somber"                 # never playful over harm
    assert harm["music"]["change"] == "crossfade"            # the sting budget was used up
    assert harm["owlbert"] == [{"move": "point"}]            # made-up move gone, untied words dropped
    assert any("aren't in the narration" in n for n in notes)
    verdict = {"scene_id": "S8", "role": "verdict", "narration": "So what's the answer? The verdict: false.",
               "music": {}, "owlbert": []}
    tidy_directions(verdict, {}, [{}])
    assert verdict["music"]["drop_before"] == "The verdict: false."   # the voice gives the verdict alone


def _scenes():
    words = [{"word": w, "start": i * 0.4, "end": i * 0.4 + 0.35} for i, w in
             enumerate("Here is the original agency caption and it is dated May 2009 in another city".split())]
    out = []
    t = 4.0
    for k, role in enumerate(["intro", "record", "record", "harm", "tell", "verdict", "outro"]):
        out.append({"scene_id": f"S{k + 1}", "role": role, "start": t, "speech_start": t + 0.35,
                    "speech_end": t + 15, "end": t + 16, "words": words, "source_ids": ["S-1"] if role == "record" else []})
        t += 16
    return out


def test_directions_become_moves_on_the_right_words():
    sc = _scenes()
    sc[1]["directions"] = [{"move": "hat_trick", "prop": "document", "at": "the original agency caption"},
                           {"move": "glasses", "at": "dated May 2009"}, {"move": "point", "at": "another city"}]
    sc[2]["directions"] = [{"move": "hat_trick", "prop": "document", "at": "agency caption"}]   # two in a row
    sc[3]["directions"] = [{"move": "surprised", "at": "Here is"}, {"move": "solemn", "at": "Here is"}]
    sc[4]["directions"] = [{"move": "hat_trick", "prop": "card", "at": "original agency"}]
    sc[5]["directions"] = [{"move": "stamp", "at": "another city"}, {"move": "fly_out"}]
    moves = bits.plan_directed(sc, {"careful": False, "humor": 1}, ["cherry_picking"],
                               {"S2": {"document": "Agency caption|AP · 2009"}, "S6": {"verdict": "FALSE"}})
    kinds = [(m["scene_id"], m["kind"]) for m in moves]
    assert kinds[0] == ("S1", "fly_in") and kinds[-1] == ("S7", "fly_out")
    hat = next(m for m in moves if m["scene_id"] == "S2" and m["kind"] == "hat_trick")
    assert hat["prop"] == {"kind": "document", "text": "Agency caption|AP · 2009"}
    assert hat["start"] == pytest.approx(20.35 + 0.8 - 1.1)   # the prop is up as he says "original"
    assert ("S3", "hat_trick") not in kinds                    # not two scenes in a row
    assert ("S4", "surprised") not in kinds and ("S4", "solemn") in kinds   # harm: respectful only
    assert ("S5", "hat_trick") in kinds and next(m for m in moves if m["scene_id"] == "S5")["prop"]["text"] == \
        "Cherry Picking"
    stamp = next(m for m in moves if m["kind"] == "stamp")
    assert stamp["prop"]["text"] == "FALSE"
    s2 = [m for m in moves if m["scene_id"] == "S2"]
    assert len(s2) <= 3 and sum(m["kind"] in bits.BIG for m in s2) == 1
    for a, b in zip(moves, moves[1:]):
        assert b["start"] >= a["start"] + a["duration"]


def test_careful_topics_keep_the_hat_for_documents():
    sc = _scenes()
    sc[4]["directions"] = [{"move": "hat_trick", "prop": "card", "at": "agency"}]
    sc[5]["directions"] = [{"move": "flourish"}, {"move": "swoop"}]
    moves = bits.plan_directed(sc, {"careful": True, "humor": 0}, ["fear"], {})
    assert not {m["kind"] for m in moves} & bits.PLAYFUL
    assert next(m for m in moves if m["kind"] == "hat_trick")["prop"]["kind"] != "card"


def test_cues_follow_the_script():
    scenes = [{"scene_id": f"S{k}", "role": r, "narration": "x", "music": m} for k, (r, m) in enumerate([
        ("intro", {"mood": "curious", "energy": 4, "change": "crossfade"}),
        ("record", {"mood": "investigative", "energy": 2, "change": "crossfade"}),
        ("benefit", {"mood": "investigative", "energy": 3, "change": "continue"}),
        ("harm", {"mood": "somber", "energy": 1, "change": "silence"}),
        ("tell", {"mood": "playful", "energy": 4, "change": "sting", "sting_at": "cherry picking"}),
        ("verdict", {"mood": "resolved", "energy": 3, "change": "crossfade", "drop_before": "The verdict"})])]
    cues = music_stage.plan_cues(scenes, {f"S{k}": 20.0 for k in range(6)})
    assert [c["mood"] for c in cues] == ["curious", "investigative", "somber", "playful", "resolved"]
    assert cues[1]["scenes"] == ["S1", "S2"] and cues[1]["energy"] == 3   # "continue" shares one piece
    assert cues[2]["silence"] and cues[3]["marks"] == [{"scene_id": "S4", "sting_at": "cherry picking"}]
    tags = musicbook.cue_tags(musicbook.genre_for("noir"), "tense", 3)
    assert "noir" in tags and "D minor" in tags and "no vocals" in tags
    assert all(g.bpm > 40 for g in musicbook.GENRES.values()) and len(musicbook.GENRES) >= 20
    assert all(p["year"] <= musicbook.PD_SONGS_UP_TO for p in musicbook.PUBLIC_DOMAIN)


def test_library_track_with_a_non_commercial_licence_is_refused(tmp_path, data):
    from fofstudio.config import Paths
    from fofstudio.util import StageError
    lib = Paths().music_library
    lib.mkdir(parents=True, exist_ok=True)
    (lib / "song.wav").write_bytes(b"")
    (lib / "song.txt").write_text("From somewhere. Licence: CC BY-NC 4.0")
    with pytest.raises(StageError, match="monetized"):
        music_stage._licence_note(lib / "song.wav")


def test_sound_effects_are_made(data):
    for name in sfx.SOUNDS:
        p = sfx.path(name)
        assert p.exists() and 0.1 < media.duration(p) < 3


def test_whole_video_uses_the_scripts_music_and_moves(episode):
    ep = episode
    research_and_story(ep)
    _finish_with_music(ep)
    script = load_script(ep)
    assert all(sc.get("music") for sc in script["scenes"])
    harm = next(sc for sc in script["scenes"] if sc["role"] == "harm")
    assert harm["music"]["mood"] == "somber"
    meta = read_json(ep.path("audio", "music", "music.json"))
    assert len(meta["cues"]) >= 3
    tl = production.load(ep)
    assert len(tl["music"]) >= 3 and all("fade_in" in m for m in tl["music"])
    kinds = {m["kind"] for m in tl["moves"]}
    assert {"fly_in", "hat_trick", "fly_out"} <= kinds and "surprised" not in kinds
    hats = [m for m in tl["moves"] if m["kind"] == "hat_trick"]
    assert any(m["prop"]["kind"] == "document" for m in hats)
    assert any(x["label"] == "whoosh" for x in tl["sfx"])
    pipeline.approve(ep, "production")
    pipeline.run_now(ep, "render", {"draft": True})
    out = ep.path("render", "preview.mp4")
    assert out.exists() and media.has_audio(out)


def _finish_with_music(ep):
    from fofstudio.stages import video
    for st in ("script",):
        pipeline.run_now(ep, st)
        pipeline.approve(ep, st)
    pipeline.run_now(ep, "storyboard")
    pipeline.approve(ep, "storyboard")
    pipeline.run_now(ep, "video_plan")
    pipeline.approve(ep, "video_plan")
    for s in video.load_plan(ep)["shots"]:
        video.update_shot(ep, s["shot_id"], method="camera_move")
    pipeline.run_now(ep, "video")
    for s in video.load_plan(ep)["shots"]:
        video.update_shot(ep, s["shot_id"], approved=True)
    pipeline.approve(ep, "video")
    for st in ("narration", "captions", "music"):
        pipeline.run_now(ep, st)
        pipeline.approve(ep, st)
    pipeline.run_now(ep, "production")


def test_new_topic_person_and_group_can_be_researched(data):
    from fofstudio import newsubject, subjects
    from fofstudio.util import StageError
    t = newsubject.add("story", "The Birds Aren't Real Hoax", "A joke movement taken seriously.",
                       "Birds are government drones", "2017", "Peter McIndoe")
    assert any(r["id"] == t["id"] for r in subjects.listing("story", "Birds Aren't Real"))
    assert subjects.claim_ids_for("story", t["id"]) == [t["claim_id"]]
    p = newsubject.add("person", "Ima Seller", "Sells survival buckets", "The grid will fail next week")
    assert any(r["id"] == p["id"] for r in subjects.listing("person", "Ima Seller"))
    g = newsubject.add("org", "Bucket Alliance", "", "Buy buckets now", careful=True)
    assert subjects.listing("org", "Bucket Alliance")[0]["claims"] == 1
    c = newsubject.add("conspiracy", "Clouds are painted on", "", year="2024", people="Ima Seller")
    assert subjects.claim_ids_for("conspiracy", c["id"]) == [c["claim_id"]]
    with pytest.raises(StageError):
        newsubject.add("person", "No Claim Given")
    with pytest.raises(StageError, match="already"):
        newsubject.add("story", "The Birds Aren't Real Hoax")
    assert g["claim_id"].startswith("C-NEW-")


def test_story_types_and_writers():
    from fofstudio import storytypes as stt
    from fofstudio.scriptfmt import ROLES
    assert len(stt.STORY_TYPES) >= 13 and len(stt.writers()) >= 14
    for t in stt.STORY_TYPES.values():
        assert {"claim", "record", "verdict"} <= set(t.roles) and set(t.roles) <= set(ROLES)
        assert t.roles.count("claim") == 1                          # the myth is stated once
        assert 90 <= sum(b.share for b in t.beats) <= 110
        assert all(w in stt.writers() for w in t.writers)
    for w in stt.writers().values():
        assert w.prompt and "[F#]" not in w.prompt
    three = stt.pick_three({"careful": False, "humor": 2, "story_type": "auto", "writer": "auto"}, "x")
    assert len({t.key for t, _ in three}) == 3 and len({w.key for _, w in three}) == 3
    careful = stt.pick_three({"careful": True, "humor": 0, "story_type": "trial", "writer": "gentle_satirist"}, "y")
    assert all(t.careful_ok and not w.light for t, w in careful)  # a careful topic overrides unsuitable choices
    fixed = stt.pick_three({"careful": False, "humor": 1, "story_type": "lab", "writer": "stargazer"}, "z")
    assert {(t.key, w.key) for t, w in fixed} == {("lab", "stargazer")}
    assert "WRITING STYLE" in stt.writer_block(stt.writers()["stargazer"])


def test_stories_carry_their_type_and_writer(episode):
    from fofstudio.stages import stories
    ep = episode
    ep.set_creative(story_type="auto", writer="auto")
    research_and_story(ep)
    data = read_json(ep.path("stories.json"))
    assert all(o.get("story_type") and o.get("writer") for o in data["options"])
    pipeline.run_now(ep, "script")
    text = ep.path("script.md").read_text(encoding="utf-8")
    chosen = stories.chosen(ep)
    from fofstudio import storytypes as stt
    assert f"**Writer:** {stt.writers()[chosen['writer']].name}" in text
