"""v0.4.3: Owlbert's moving parts and moves (flying, pointing, the hat trick)."""

import numpy as np
import pytest
from PIL import Image

from fofstudio import bits, media, owl, rig
from fofstudio.stages import production
from fofstudio.util import read_json
from tests.test_pipeline import episode  # noqa: F401 - the shared fixture

pytest.importorskip("cv2")


def test_parts_are_cut_where_they_belong():
    m = rig.masks()
    assert m["cap"][150, 400] and m["cap"][250, 512]          # board and skull cap
    assert m["tassel"][450, 820] and not m["cap"][450, 820]    # the tassel is its own part
    assert m["wing_l"][680, 200] and m["wing_r"][680, 824]
    assert not m["wing_l"][680, 512] and not m["cap"][466, 392]   # not his belly or his eyes
    body = rig.body()
    assert body.getpixel((400, 140))[3] == 0                   # no cap on the body...
    r, g, b, a = body.getpixel((512, 250))
    assert a == 255 and b > r + 25                             # ...but the top of his head is drawn in


def test_at_rest_he_looks_like_the_corner_presenter(data):
    st = rig.Stage(640, 360)
    img = np.asarray(rig.to_image(st.draw(st.rest()))).astype(float)
    x, y, pw, ph = st.box
    pres = owl.mouth_frame("X", 0).crop(owl.base().getbbox()).resize((pw, ph), Image.LANCZOS)
    ref = Image.new("RGBA", (640, 360), (0, 0, 0, 0))
    ref.alpha_composite(pres, (x, y))
    ref = np.asarray(ref).astype(float)

    def premul(a):
        return np.concatenate([a[..., :3] * a[..., 3:] / 255, a[..., 3:]], axis=2)[y:y + ph, x:x + pw]
    diff = np.abs(premul(img) - premul(ref))
    assert diff[..., 3].mean() < 8 and diff[..., :3].mean() < 8    # no jump when a move starts or ends


def _gold_x(img: Image.Image) -> float:
    a = np.asarray(img).astype(int)
    gold = (a[..., 3] > 200) & (a[..., 0] > 200) & (a[..., 1] > 140) & (a[..., 1] < 200) & (a[..., 2] < 90)
    return float(np.nonzero(gold)[1].mean())


def test_every_move_starts_and_ends_at_rest_and_never_flips_him(data):
    st = rig.Stage(640, 360)
    rest = np.asarray(rig.to_image(st.draw(st.rest())))
    centre = st.home[0]
    for kind in ("point", "hat_trick", "flourish"):
        frames = list(bits.frames(st, kind, bits.LENGTH[kind], 15, lambda t: ("X", 0.0),
                                  {"kind": "card", "text": "Cherry Picking"}))
        first, last = np.asarray(frames[0][1]), np.asarray(frames[-1][1])
        assert np.abs(first.astype(int) - rest).mean() < 2, kind
        assert np.abs(last.astype(int) - rest).mean() < 3, kind
        assert _gold_x(frames[0][1]) > centre and _gold_x(frames[-1][1]) > centre   # tassel on the viewer's right
    # flying: he starts off screen and lands exactly in the corner
    fly = list(bits.frames(st, "fly_in", bits.LENGTH["fly_in"], 15, lambda t: ("X", 0.0)))
    assert np.asarray(fly[0][1])[..., 3].sum() < np.asarray(fly[-1][1])[..., 3].sum() * 0.5
    assert np.abs(np.asarray(fly[-1][1]).astype(int) - rest).mean() < 3


def test_the_hat_trick_pulls_out_the_trick_card(data):
    st = rig.Stage(640, 360)
    frames = list(bits.frames(st, "hat_trick", bits.LENGTH["hat_trick"], 15, lambda t: ("X", 0.0),
                              {"kind": "card", "text": "Cherry Picking"}))
    mid = np.asarray(frames[int(len(frames) * 0.5)][1]).astype(int)
    cream = (mid[..., 0] > 240) & (mid[..., 1] > 228) & (mid[..., 2] > 200) & (mid[..., 3] > 240)
    assert cream.sum() > 2000                                   # the card is up, big
    assert mid[5, 5, 3] > 40                                    # and the picture behind is dimmed


def _scenes(roles):
    out, t = [], 6.0
    for k, role in enumerate(roles):
        talk = 22.0 if role not in ("intro", "outro") else 12.0
        out.append({"scene_id": f"S{k + 1:02d}", "role": role, "start": t, "speech_start": t + 0.35,
                    "speech_end": t + 0.35 + talk, "end": t + talk + 1.0})
        t += talk + 1.0
    return out


ROLES = ["intro", "claim", "record", "record", "harm", "tell", "toolkit", "verdict", "outro"]


def test_moves_are_planned_with_a_job_and_a_budget():
    moves = bits.plan(_scenes(ROLES), {"careful": False, "humor": 1}, ["cherry_picking"], "EP1")
    kinds = [m["kind"] for m in moves]
    assert kinds[0] == "fly_in" and kinds[-1] == "fly_out"
    hat = [m for m in moves if m["kind"] == "hat_trick"]
    assert 1 <= len(hat) <= 2 and hat[0]["prop"] == {"kind": "card", "text": "Cherry Picking"}
    assert "point" in kinds and "flourish" in kinds
    for a, b in zip(moves, moves[1:]):
        assert b["start"] >= a["start"] + a["duration"]          # never two at once
    big = [m["start"] for m in moves if m["kind"] in bits.BIG and m["kind"] != "fly_out"]
    assert all(b - a >= 20 for a, b in zip(big, big[1:]))
    per_scene = {}
    for m in moves:
        per_scene[m["scene_id"]] = per_scene.get(m["scene_id"], 0) + 1
    assert max(per_scene.values()) == 1


def test_careful_topics_get_no_playful_moves():
    moves = bits.plan(_scenes(ROLES), {"careful": True, "humor": 0}, ["fear"], "EP2")
    assert not {m["kind"] for m in moves} & bits.PLAYFUL
    assert moves[0]["kind"] == "fly_in"


def test_corner_owlbert_hides_while_a_move_plays():
    shown = bits.merge([(1.0, 10.0), (11.0, 20.0), (30.0, 40.0)])
    assert shown == [(1.0, 20.0), (30.0, 40.0)]                 # no blinking out between scenes
    assert bits.subtract(shown, [(0.5, 3.0), (15.0, 17.0)]) == [(3.0, 15.0), (17.0, 20.0), (30.0, 40.0)]


def test_moves_track_and_render(tmp_path, data):
    from fofstudio.engines.render import Segment, Timeline, render
    Image.new("RGB", (320, 180), (40, 90, 120)).save(tmp_path / "a.png")
    moves = [{"kind": "point", "start": 0.5, "duration": 1.0}, {"kind": "flourish", "start": 2.0, "duration": 1.0}]
    concat, ranges = bits.render_track(moves, [], 4.0, tmp_path / "moves", 320, 180, 10)
    assert [round(a, 2) for a, _ in ranges] == [0.5, 2.0] and concat.exists()
    tl = Timeline([Segment(tmp_path / "a.png", 4, camera="static")], width=320, height=180, fps=10,
                  moves=concat, moves_ranges=ranges)
    out = render(tl, tmp_path / "out.mp4", encoder="libx264")
    assert abs(out["seconds"] - 4.0) < 0.3
    assert media.duration(tmp_path / "out.mp4") > 3.5


def test_assembled_timeline_has_moves(episode):
    from fofstudio import pipeline
    from tests.test_window import _finish
    ep = episode
    _finish(ep)
    tl = production.load(ep)
    assert tl["moves"] and tl["moves"][0]["kind"] == "fly_in"
    pipeline.approve(ep, "production")
    pipeline.run_now(ep, "render", {"draft": True})
    assert ep.path("render", "moves-480.txt").exists()
    assert read_json(ep.path("production.json"))["moves"] == tl["moves"]



def test_only_one_owlbert_on_screen(episode):
    """Owl shots are painted empty and Owlbert is laid on top live; the corner Owlbert and his moves stay out."""
    from fofstudio import pipeline
    from fofstudio.stages import storyboard, video
    from tests.test_pipeline import research_and_story
    from fofstudio.config import settings
    ep = episode
    settings()["owl"]["in_scenes"] = True        # the optional big on-set Owlbert
    research_and_story(ep)
    for st in ("script",):
        pipeline.run_now(ep, st)
        pipeline.approve(ep, st)
    pipeline.run_now(ep, "storyboard")
    owl_shots = [s for s in storyboard.shots(ep) if s.get("kind") == "owl"]
    assert owl_shots and all(s.get("owl_live") in ("left", "right") for s in owl_shots)
    assert all(s["image"]["path"].endswith("-set.png") for s in owl_shots)
    assert "owl" not in storyboard.set_only("Owlbert leans on his desk, his wings spread, beside an owl clock").lower()
    pipeline.approve(ep, "storyboard")
    pipeline.run_now(ep, "video_plan", {"level": "fast"})
    plan = video.load_plan(ep)["shots"]
    assert {s["method"] for s in plan} >= {"parallax"}
    assert not any(s["method"] == "animate" and s.get("owl_live") for s in plan)
    pipeline.approve(ep, "video_plan")
    pipeline.run_now(ep, "video")
    for s in video.load_plan(ep)["shots"]:
        video.update_shot(ep, s["shot_id"], approved=True)
    pipeline.approve(ep, "video")
    for st in ("narration", "captions"):
        pipeline.run_now(ep, st)
        pipeline.approve(ep, st)
    pipeline.skip(ep, "music")
    pipeline.run_now(ep, "production")
    tl = production.load(ep)
    assert production.owl_shot_ranges(tl) and any(c.get("owl_live") for c in tl["video"])
    assert any(c.get("depth") for c in tl["video"])
    for m in tl["moves"]:   # painted-in Owlbert shots never share the screen with a move
        assert not any(m["start"] < b and m["start"] + m["duration"] > a
                       for a, b in production.owl_shot_ranges(tl, painted_only=True))
    pipeline.approve(ep, "production")
    pipeline.run_now(ep, "render", {"draft": True})
    assert ep.path("render", "owl-stage-480.txt").exists() and ep.path("render", "preview.mp4").exists()


def test_by_default_only_the_corner_owlbert(episode):
    from fofstudio import pipeline
    from fofstudio.stages import storyboard
    from tests.test_pipeline import research_and_story
    ep = episode
    research_and_story(ep)
    pipeline.run_now(ep, "script")
    pipeline.approve(ep, "script")
    pipeline.run_now(ep, "storyboard")
    assert not any(sh["kind"] == "owl" for sc in ep.storyboard()["scenes"] for sh in sc["shots"])
    assert not any(s.get("owl_live") for s in storyboard.shots(ep))
