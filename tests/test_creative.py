"""v0.4: creative styles, smooth camera moves, Owlbert's colours, caricature guardrails, sound mix, YouTube setup."""

import json

import numpy as np
import pytest

from fofstudio import cast, media, pipeline, styles, subjects, youtube
from fofstudio.episode import Episode
from fofstudio.stages import production, script as script_stage, stories
from fofstudio.util import StageError
from tests.test_pipeline import episode  # noqa: F401 - the shared fixture


def test_owlbert_keeps_his_cap():
    """The cut-out used to treat his black cap as background (it's close to the dark backdrop)."""
    from fofstudio import owl
    img = owl.base()
    for x, y in [(300, 190), (400, 150), (600, 150), (700, 180), (512, 100)]:   # the flat top of the cap
        assert img.getpixel((x, y))[3] > 240, (x, y)
    assert img.getpixel((5, 5))[3] == 0          # the backdrop is gone


def test_camera_moves_are_smooth(tmp_path):
    cv2 = pytest.importorskip("cv2")
    from fofstudio.engines.render import kenburns_frames
    rng = np.random.default_rng(1)
    tex = cv2.GaussianBlur((rng.random((384, 672, 3)) * 255).astype("uint8"), (0, 0), 2)
    from PIL import Image
    Image.fromarray(tex).save(tmp_path / "t.png")
    frames = [np.asarray(f) for f in kenburns_frames(tmp_path / "t.png", "pan_right", 640, 360, 90)]
    g = [cv2.cvtColor(f, cv2.COLOR_RGB2GRAY).astype("float32") for f in frames]
    shifts = np.array([cv2.phaseCorrelate(g[i], g[i + 1])[0][0] for i in range(25, 65)])
    assert abs(shifts.mean()) > 0.2                    # it moves...
    assert np.abs(np.diff(shifts)).mean() < 0.05       # ...steadily (the old way jumped ~0.15 px per frame)


def test_every_style_is_complete():
    for st in styles.STYLES.values():
        assert st.wpm > 100 and 2 <= st.shot_seconds <= 8 and st.look and st.sample
        if st.caricature:
            assert st.cartoon, "caricatures only in clearly-cartoon styles"


@pytest.fixture()
def sandy_hook(data):
    rows = subjects.listing("story", "Sandy Hook")
    arc = rows[0]["id"]
    ep = Episode.create("SH1", rows[0]["title"], arc, subjects.claim_ids_for("story", arc))
    return ep


def test_careful_topics_get_no_humor_or_caricatures(sandy_hook):
    ep = sandy_hook
    ep.set_creative(style="satire", humor=3, caricatures=True)
    c = ep.creative()
    assert c["careful"] and c["humor"] == 0 and c["caricatures"] is False
    assert cast.eligible(ep, ep.claim_ids) == []


def test_cast_is_only_people_who_sold_it(data):
    b = subjects.breakdown("story", "A-Y2K-FEAR-INDUSTRY")
    ep = Episode.create("Y1", b["title"], "A-Y2K-FEAR-INDUSTRY", b["claim_ids"])
    ep.set_creative(style="satire")
    people = cast.eligible(ep, ep.claim_ids)
    assert people
    for p in people:
        assert set(p["roles"].split(",")) & set(cast.SELLER_ROLES)
        assert not cast._never(p)
    # nobody is drawn until approved, and a design must describe looks, not a name
    assert cast.approved(ep, ep.claim_ids) == []
    cast.save(people[0]["person_id"], "a man in a big cowboy hat holding a megaphone", True)
    assert [p["person_id"] for p in cast.approved(ep, ep.claim_ids)] == [people[0]["person_id"]]


def test_caricature_needs_approval_and_a_sourced_scene(episode):
    from tests.test_pipeline import research_and_story
    ep = episode
    research_and_story(ep)
    pipeline.run_now(ep, "script")
    pipeline.approve(ep, "script")
    ep.set_creative(style="satire", caricatures=True)
    pipeline.run_now(ep, "storyboard")
    board = ep.storyboard()
    people = cast.eligible(ep)
    assert people
    # pretend the AI planned a caricature of someone who isn't approved
    sc = next(s for s in board["scenes"] if s.get("source_ids"))
    sc["shots"][0]["kind"], sc["shots"][0]["person_id"] = "caricature", people[0]["person_id"]
    ep.save_storyboard(board)
    msgs = [c.message for c in pipeline.checks(ep, "storyboard")]
    assert any("design isn't approved" in m for m in msgs), msgs
    cast.save(people[0]["person_id"], "a stocky man shouting into a huge radio microphone", True)
    msgs = [c.message for c in pipeline.checks(ep, "storyboard")]
    assert not any("caricature" in m.lower() and "approved" in m for m in msgs), msgs
    # the same shot in a scene that cites nothing is blocked
    bare = next((s for s in board["scenes"] if not s.get("source_ids")), None)
    if bare:
        bare["shots"][0]["kind"], bare["shots"][0]["person_id"] = "caricature", people[0]["person_id"]
        ep.save_storyboard(board)
        assert any("documented act" in c.message for c in pipeline.checks(ep, "storyboard"))


def test_short_script_is_blocked_and_can_be_lengthened(episode):
    from tests.test_pipeline import research_and_story
    ep = episode
    research_and_story(ep)
    pipeline.run_now(ep, "script")
    ep.set_creative(minutes=10)   # ask for far more than was written
    assert any("Make it longer" in c.message for c in pipeline.checks(ep, "script") if c.level == "block")
    before = sum(len(s["narration"].split()) for s in script_stage.load(ep)["scenes"])
    pipeline.run_now(ep, "script", {"expand": True})
    after = sum(len(s["narration"].split()) for s in script_stage.load(ep)["scenes"])
    assert after > before


def test_thumbnail_words_come_from_the_story(episode):
    from tests.test_pipeline import research_and_story
    ep = episode
    research_and_story(ep)
    story = stories.chosen(ep)
    assert story["thumbnail_words"] == "FEAR FOR SALE FOLKS"
    assert story["techniques"] == ["fear"]   # unknown tricks are dropped


def test_sound_mix_defaults_and_overrides(data):
    tl = {}
    m = production.mix(tl)
    assert m == {"speech_db": 0.0, "music_db": -14.0, "master_db": 0.0}
    tl["mix"] = {"speech_db": 2.0, "music_db": -20.0, "master_db": -3.0}
    assert production.mix(tl)["music_db"] == -20.0


def test_mix_and_loudness_in_the_render(tmp_path, data):
    from fofstudio.engines.render import AudioCue, Segment, Timeline, render
    from PIL import Image
    from tests.conftest import tone
    Image.new("RGB", (640, 360), (40, 90, 120)).save(tmp_path / "a.png")
    tone(tmp_path / "say.wav", 3.0, 330)
    tone(tmp_path / "music.wav", 6.0, 110)
    tl = Timeline([Segment(tmp_path / "a.png", 4, camera="zoom_in")], [AudioCue(tmp_path / "say.wav", 0.5)],
                  music=tmp_path / "music.wav", music_volume=10 ** (-14 / 20), width=640, height=360, fps=15,
                  speech_db=2.0, master_db=0.0, loudness_lufs=-14.0)
    out = render(tl, tmp_path / "out.mp4", encoder="libx264")
    assert out["has_audio"]
    v = next(s for s in media.probe(tmp_path / "out.mp4")["streams"] if s["codec_type"] == "video")
    assert v.get("color_space") == "bt709" and v.get("color_range") == "tv"   # YouTube won't wash it out
    a = next(s for s in media.probe(tmp_path / "out.mp4")["streams"] if s["codec_type"] == "audio")
    assert a["sample_rate"] == "48000" and a["channels"] == 2


def test_youtube_client_file_is_checked(tmp_path, data):
    bad = tmp_path / "web.json"
    bad.write_text(json.dumps({"web": {"client_id": "x"}}))
    with pytest.raises(StageError, match="Desktop app"):
        youtube.use_client_file(bad)
    good = tmp_path / "client_secret.json"
    good.write_text(json.dumps({"installed": {"client_id": "x", "client_secret": "y"}}))
    dest = youtube.use_client_file(good)
    assert dest.exists() and youtube.client_file() == dest
    assert youtube.account() is None


def test_settings_page_builds_without_a_sound_card(data, monkeypatch):
    import os
    import sys
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("FOF_NO_AUDIO", "1")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication(sys.argv)
    from fofstudio.app.pages.settings import SettingsPage
    page = SettingsPage()
    assert page.speaker.count() >= 1
    page._test_chime()
    assert "switched off" in page.test_msg.text()


# ---------------------------------------------------------------- v0.5.9: real pictures and re-creations
def test_media_licences_and_blocks():
    from fofstudio import mediafinder as mf
    assert mf.licence_ok("CC BY-SA 4.0") == (True, "CC BY SA 4.0")
    assert mf.licence_ok("Public domain")[0] and mf.licence_ok("PD-USGov")[0] and mf.licence_ok("CC0")[0]
    for bad in ("CC BY-NC 2.0", "CC BY-ND 4.0", "All rights reserved", "", "Fair use"):
        assert not mf.licence_ok(bad)[0], bad
    c = mf.Candidate("x", "https://u/x.jpg", "https://p", "CC BY 4.0", "", "AP Photo/John Doe", "Wikimedia Commons", 1600, 900)
    assert mf.usable(c) == (False, "news-agency picture")
    assert mf.find("anything", "victim") == (None, ["no real pictures of a victim: re-created instead"])
    assert mf.find("anything", "event", careful=True)[0] is None


def test_storyboard_uses_a_real_picture_or_a_labelled_recreation(episode, monkeypatch):
    from PIL import Image

    from fofstudio import mediafinder as mf
    from fofstudio.stages import publish, storyboard, video
    from tests.test_pipeline import research_and_story
    research_and_story(episode)
    pipeline.run_now(episode, "script")
    pipeline.approve(episode, "script")
    good = mf.Candidate("Y2K centre", "https://upload.example/y2k.jpg", "https://commons.example/File:Y2K.jpg",
                        "CC BY 4.0", "https://creativecommons.org/licenses/by/4.0/", "Jane Smith",
                        "Wikimedia Commons", 1600, 1000)
    monkeypatch.setattr(mf, "search_commons", lambda q, limit=12: [good])

    def fake_download(c, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (1600, 1000), (90, 120, 160)).save(dest.with_suffix(".jpg"))
        return {**mf.asdict(c), "credit": c.credit(), "path": str(dest.with_suffix(".jpg")), "page_url": c.page_url}
    monkeypatch.setattr(mf, "download", fake_download)
    pipeline.run_now(episode, "storyboard")
    shots = [sh for sc in episode.storyboard()["scenes"] for sh in sc["shots"] if sh["kind"] == "real"]
    assert shots, "the planner may ask for real pictures"
    first = shots[0]["candidates"]
    assert first[0]["real"] and "Jane Smith" in first[0]["credit"] and "CC BY 4.0" in first[0]["credit"]
    assert first[1].get("recreation"), "the second version is always a labelled re-creation"
    checks = storyboard.check(episode)
    assert any("real picture" in c.message for c in checks)
    # a real photo is never animated by AI
    plan_shots = storyboard.shots(episode)
    assert not any(s["shot_id"] in video.choose_animated(episode, plan_shots, "full")
                   for s in plan_shots if s["image"].get("real"))


# ---------------------------------------------------------------- v0.6.0: YouTube like PowerDirector
def test_google_errors_in_plain_words():
    from fofstudio import youtube
    assert "7 days" in youtube.explain("('invalid_grant: Token has been expired or revoked.', ...)")
    assert "Manage your YouTube videos" in youtube.explain("insufficientPermissions")
    assert "no YouTube channel" in youtube.explain("youtubeSignupRequired")
    assert "Desktop app" in youtube.explain("Error 400: redirect_uri_mismatch")
    assert "browser" in youtube.explain("quotaExceeded")
    assert [u for _, u in youtube.SETUP_LINKS][3].endswith("/auth/audience")


def test_browser_publish_kit(episode):
    from fofstudio import publishkit
    from fofstudio.util import read_json, write_json
    ep = episode
    (ep.path("render")).mkdir(parents=True, exist_ok=True)
    ep.path("render", "final.mp4").write_bytes(b"x")
    write_json(ep.path("publish", "metadata.json"), {"title": "T" * 120, "description": "D", "tags": ["a", "b c"],
                                                     "video": "render/final.mp4", "thumbnail": "publish/thumbnail.png",
                                                     "captions": "render/final.srt", "made_at": "x"})
    kit = publishkit.prepare(ep)
    assert len(kit["title"]) == 100 and kit["tags"] == "a, b c" and kit["checklist"]
    assert ep.path("publish", "upload-kit.txt").exists()
    for link in ("https://youtu.be/abcDEF12345", "https://www.youtube.com/watch?v=abcDEF12345&t=3",
                 "https://studio.youtube.com/video/abcDEF12345/edit", "abcDEF12345"):
        assert publishkit.video_id_from(link) == "abcDEF12345"
    with pytest.raises(StageError):
        publishkit.video_id_from("not a link")
    info = publishkit.record_upload(ep, "https://youtu.be/abcDEF12345")
    assert read_json(ep.path("publish", "upload.json"))["via"] == "browser" and info["youtube_id"] == "abcDEF12345"
    assert ep.stage_status("upload")["status"] == "approved"
