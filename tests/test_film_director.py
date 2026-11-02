"""The AI directing pipeline (Dave, 2026-10-31): shots follow the script, don't repeat, animate safely, and a
quality review redoes what fails."""

import re
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
        # the first picture "has writing in it": it gets painted again once; otherwise no writing, no grey
        # blockout, no stray bird
        qs = [ln for ln in messages[0]["content"].splitlines() if ln[:1].isdigit()]
        bad = ("writing", "grey 3D model", "bird")
        return "\n".join(f"{n}. " + ("yes" if (any(b in q for b in bad) == (len(looked) == 1 and "writing" in q))
                                      else "no") for n, q in enumerate(qs, 1))
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
    for name in ("wide-depth.png", "close-depth.png", "wide-lines.png"):
        Image.new("RGB", (64, 36), "gray").save(folder / name)
    uploaded = []
    monkeypatch.setattr(comfy.Comfy, "upload_image", lambda self, p: uploaded.append(p) or p.name)
    shots = [sh for sh in ep.storyboard()["scenes"][0]["shots"] if sh["kind"] == "broll"]
    room = dict(shots[0], shows="place", look={"shot_type": "wide", "angle": "eye level"})
    assert controlmaps.guide_for(ep, room) == folder / "wide-depth.png"          # depth, the matching camera
    near = dict(room, look={"shot_type": "close-up", "angle": "eye level"})
    assert controlmaps.guide_for(ep, near) == folder / "close-depth.png"
    # 2026-11-02: a close-up of a document or an object has nothing to do with the room's layout
    assert controlmaps.guide_for(ep, dict(room, shows="document")) is None
    assert controlmaps.guide_for(ep, dict(room, look={"shot_type": "extreme close-up"})) is None
    pipeline.run_now(ep, "storyboard", {"replan": [sid]})
    painted = [sh for sh in ep.storyboard()["scenes"][0]["shots"] if sh["kind"] == "broll"]
    for sh in painted:
        guided = controlmaps.guide_for(ep, sh) is not None
        assert all(bool(c.get("guide")) == guided for c in sh["candidates"] if c), sh["shows"]
    # a scene's own guide pictures win over its place's
    own = ep.path("control", sid)
    own.mkdir(parents=True)
    Image.new("RGB", (64, 36), "white").save(own / "pose.png")
    assert controlmaps.guide_for(ep, room) == own / "pose.png"


def test_unreal_script_job_and_bringing_its_captures_in(episode):
    """Dave (2026-10-31): "make a script that can do what you need": the Studio writes the job and a ready-to-run
    Unreal script; what Unreal saves becomes guide pictures by itself."""
    import json
    import py_compile

    import numpy as np
    from PIL import Image

    from fofstudio import controlmaps, unreal_bridge
    from fofstudio.util import write_json
    ep = episode
    research_and_story(ep)
    pipeline.run_now(ep, "script")
    pipeline.approve(ep, "script")
    pipeline.run_now(ep, "storyboard")
    r = unreal_bridge.prepare(ep)
    job = json.loads(r["job"].read_text(encoding="utf-8"))
    assert job["places"] and set(job["places"][0]) >= {"id", "name", "architecture", "props"}
    script = r["script"].read_text(encoding="utf-8")
    assert "{{JOB_PATH}}" not in script and str(r["job"]) in script
    py_compile.compile(str(r["script"]), doraise=True)        # Unreal will be able to run it
    # pretend Unreal ran: one place, one camera, depth (cm) and a layout picture at 672x384
    place = job["places"][0]["id"]
    out = Path(job["out"]) / place
    out.mkdir(parents=True, exist_ok=True)
    w, h = 672, 384
    depth = np.full((h, w), 2000.0, "<f4")
    depth[100:300, 200:450] = 400.0                            # a box near the camera
    depth[:40] = 1e10                                          # sky
    depth.tofile(out / "wide.depth.bin")
    layout = np.zeros((h, w, 3), np.uint8)
    layout[100:300, 200:450] = 200
    layout.tofile(out / "wide.layout.bin")
    write_json(out / "wide.json", {"width": w, "height": h, "camera": "wide", "fov": 70})
    write_json(out / "place.json", {"id": place, "kind": "room"})
    assert unreal_bridge.pending()
    sid = next(s for s, v in bible.load(ep)["scenes"].items() if v.get("location") == place)
    found = controlmaps.guides(ep, sid)                         # brings them in by itself
    names = {p.name for p in found}
    assert {"wide-depth.png", "wide-lines.png"} <= names
    d = Image.open(controlmaps.folder_for_location(place) / "wide-depth.png").convert("L")
    assert d.size == (1344, 768) or d.size[0] > w
    px = np.array(d)
    assert px[384, 650] > px[600, 100] and px[5, 5] == 0      # near is bright, far is dark, sky is black
    assert not unreal_bridge.pending() and not out.exists()    # the raw files are tidied away
    assert unreal_bridge.status(ep)[0]["guides"] >= 2


def test_studio_finds_unreal_and_makes_its_own_project(data, tmp_path, monkeypatch):
    """Dave (2026-11-01): nothing happened when he ran the script by hand; the Studio now finds Unreal itself and
    uses a small project of its own with the Python plugin switched on."""
    import json

    from fofstudio import unreal_bridge as ub
    for ver, minor in (("5.4", 4), ("5.6", 6)):
        root = tmp_path / "Epic Games" / f"UE_{ver}"
        (root / "Engine" / "Binaries" / "Win64").mkdir(parents=True)
        (root / "Engine" / "Binaries" / "Win64" / "UnrealEditor-Cmd.exe").write_text("")
        (root / "Engine" / "Build").mkdir(parents=True)
        (root / "Engine" / "Build" / "Build.version").write_text(json.dumps({"MajorVersion": 5, "MinorVersion": minor}))
    listing = tmp_path / "LauncherInstalled.dat"
    listing.write_text(json.dumps({"InstallationList": [
        {"InstallLocation": str(tmp_path / "Epic Games" / f"UE_{v}"), "AppName": f"UE_{v}"} for v in ("5.4", "5.6")]
        + [{"InstallLocation": "C:/nowhere", "AppName": "Fortnite"}]}))
    monkeypatch.setattr(ub, "LAUNCHER_LIST", listing)
    exe, ver = ub.find_editor()
    assert ver == "5.6" and exe.name == "UnrealEditor-Cmd.exe" and "UE_5.6" in str(exe)
    proj = json.loads(ub.make_project(ver).read_text())
    ini = (ub.folder() / ub.PROJECT / "Config" / "DefaultEditorSettings.ini").read_text()
    assert "bThrottleCPUWhenNotForeground=False" in ini           # Unreal doesn't slow down behind the Studio
    assert proj["EngineAssociation"] == "5.6"
    assert {p["Name"] for p in proj["Plugins"] if p["Enabled"]} >= {"PythonScriptPlugin", "EditorScriptingUtilities"}
    from fofstudio import config
    config.settings()["paths"]["unreal_editor"] = str(tmp_path / "Epic Games" / "UE_5.4")
    assert ub.find_editor()[1] == "5.4"                         # Settings wins


def _fake_unreal(monkeypatch, ub, behave):
    """Stand in for Unreal: read the job the script would read, then do what `behave` says."""
    import re

    class Proc:
        def __init__(self, cmd, **kw):
            self.cmd = cmd
            script = next(a.split("=", 1)[1] for a in cmd if a.startswith("-ExecutePythonScript="))
            job_path = re.search(r'JOB = r"([^"]+)"', Path(script).read_text(encoding="utf-8")).group(1)
            behave(json_load(job_path))
            self.code = 0

        def poll(self):
            return self.code

        def kill(self):
            self.code = -9
    monkeypatch.setattr(ub.subprocess, "Popen", Proc)


def json_load(path):
    import json
    return json.loads(Path(path).read_text(encoding="utf-8"))


def test_one_button_runs_unreal_and_brings_the_guides_in(episode, tmp_path, monkeypatch):
    import json

    import numpy as np

    from fofstudio import config, controlmaps
    from fofstudio import unreal_bridge as ub
    from fofstudio.util import write_json
    ep = episode
    research_and_story(ep)
    pipeline.run_now(ep, "script")
    pipeline.approve(ep, "script")
    pipeline.run_now(ep, "storyboard")
    editor = tmp_path / "UE_5.6" / "Engine" / "Binaries" / "Win64" / "UnrealEditor-Cmd.exe"
    editor.parent.mkdir(parents=True)
    editor.write_text("")
    config.settings()["paths"]["unreal_editor"] = str(editor)

    def works(job):
        assert job["auto"] is True                              # no message boxes, Unreal closes by itself
        place = job["places"][0]["id"]
        out = Path(job["out"]) / place
        out.mkdir(parents=True, exist_ok=True)
        d = np.full((384, 672), 1500.0, "<f4")
        d[150:250, 300:400] = 300.0
        d.tofile(out / "wide.depth.bin")
        write_json(out / "wide.json", {"width": 672, "height": 384, "camera": "wide"})
        (Path(job["out"]) / "run-log.txt").write_text("01:00:00 Started\n01:00:05 Finished: 1 place(s) done\n")
        write_json(Path(job["out"]) / "done.json", {"places": [place], "problems": []})
    _fake_unreal(monkeypatch, ub, works)
    r = ub.start(ep)
    assert r["version"] in ("5.6", "5.5", "5.4") or r["version"]
    out = ub.check()
    assert out["state"] == "done" and sum(len(v) for v in out["made"].values()) >= 2   # depth + lines from depth
    place = json_load(ub.folder() / "job.json")["places"][0]["id"]
    assert (controlmaps.folder_for_location(place) / "wide-lines.png").exists()
    assert ub.check()["state"] == "idle"

    def play_mode(job):                                         # Dave's first try: the Play button was on
        (Path(job["out"]) / "run-log.txt").write_text(
            "01:00:00 Started\n01:00:00 STOPPED: Unreal is in Play mode (the green Play button was pressed).\n")
    _fake_unreal(monkeypatch, ub, play_mode)
    ub.start(ep)
    bad = ub.check()
    assert bad["state"] == "failed" and "Play mode" in bad["text"]
    assert json.loads((ub.folder() / "job.json").read_text())["auto"] is True


def test_guide_model_downloads_into_comfyuis_model_patches(data, tmp_path, monkeypatch):
    import requests

    from fofstudio import config, guidemodel
    comfy = tmp_path / "ComfyUI"
    (comfy / "models" / "vae").mkdir(parents=True)
    (comfy / "main.py").write_text("")
    config.settings()["paths"]["comfyui_dir"] = str(comfy)
    assert guidemodel.models_folder() == comfy / "models"
    assert guidemodel.target() == comfy / "models" / "model_patches" / guidemodel.filename()
    assert "lite" in guidemodel.filename()                      # the one meant for a 12 GB card
    blob = b"x" * 150_000_000
    seen = []

    class Resp:
        def __init__(self, start):
            self.status_code = 206 if start else 200
            self.body = blob[start:]
            self.headers = {"Content-Length": str(len(self.body))}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def raise_for_status(self):
            pass

        def iter_content(self, chunk_size):
            for i in range(0, len(self.body), chunk_size):
                yield self.body[i:i + chunk_size]

    def get(url, headers=None, stream=True, timeout=60):
        seen.append((url, headers))
        start = int(headers["Range"].split("=")[1].rstrip("-")) if headers else 0
        return Resp(start)
    monkeypatch.setattr(requests, "get", get)
    part = guidemodel.target().with_name(guidemodel.filename() + ".part")
    part.parent.mkdir(parents=True)
    part.write_bytes(blob[:40_000_000])                         # an interrupted earlier download
    got = guidemodel.download()
    assert got.stat().st_size == len(blob) and guidemodel.have() and not part.exists()
    assert seen[0][0].startswith("https://huggingface.co/alibaba-pai/Z-Image-Turbo-Fun-Controlnet-Union-2.1/")
    assert seen[0][1] == {"Range": "bytes=40000000-"}           # carried on where it left off


def test_unreal_58_saved_pictures_and_nothing_made_is_a_failure(episode, tmp_path, monkeypatch):
    """Dave's run 2026-11-01 (Unreal 5.8.4): reading pixels in Python gave nothing, every camera "failed" and the
    window still said Done in green. Now Unreal saves the pictures itself (.hdr depth, .png colour) and the
    Studio reads those; a run that makes no pictures is reported as a failure."""
    import cv2
    import numpy as np

    from fofstudio import config, controlmaps
    from fofstudio import unreal_bridge as ub
    from fofstudio.util import write_json
    ep = episode
    research_and_story(ep)
    pipeline.run_now(ep, "script")
    pipeline.approve(ep, "script")
    pipeline.run_now(ep, "storyboard")
    editor = tmp_path / "UE_5.8" / "Engine" / "Binaries" / "Win64" / "UnrealEditor-Cmd.exe"
    editor.parent.mkdir(parents=True)
    editor.write_text("")
    config.settings()["paths"]["unreal_editor"] = str(editor)

    def saves_files(job):
        place = job["places"][0]["id"]
        out = Path(job["out"]) / place
        out.mkdir(parents=True, exist_ok=True)
        d = np.zeros((384, 672, 3), np.float32)               # Unreal puts the depth in red (BGR index 2)
        d[..., 2] = 1500.0
        d[150:250, 300:400, 2] = 300.0
        d[:120, :, 2] = 65504.0                               # nothing there: a half-float file caps it here
        cv2.imwrite(str(out / "wide.depth.hdr"), d)
        lay = np.zeros((384, 672, 3), np.uint8)
        lay[150:250, 300:400] = 180
        cv2.imwrite(str(out / "wide.layout.png"), lay)
        write_json(out / "wide.json", {"width": 672, "height": 384, "camera": "wide",
                                       "depth_file": "wide.depth.hdr", "layout_file": "wide.layout.png"})
        write_json(Path(job["out"]) / "done.json", {"places": [place], "problems": []})
    _fake_unreal(monkeypatch, ub, saves_files)
    ub.start(ep)
    r = ub.check()
    assert r["state"] == "done", r
    place = json_load(ub.folder() / "job.json")["places"][0]["id"]
    depth = np.array(__import__("PIL.Image", fromlist=["Image"]).open(
        controlmaps.folder_for_location(place) / "wide-depth.png").convert("L"))
    assert depth[384, 700] > depth[600, 100] + 100            # the near box is brighter than the far wall
    assert depth[600, 100] < 60 and depth[40, 600] == 0       # not a flat white guide; empty background black
    assert (controlmaps.folder_for_location(place) / "wide-lines.png").exists()
    assert not (Path(json_load(ub.folder() / "job.json")["out"]) / place).exists()   # tidied away

    def nothing(job):                                         # every camera failed, as on Dave's first run
        (Path(job["out"]) / "run-log.txt").write_text("06:28:51 Started\n06:28:53 Finished: 0 place(s) done\n")
        write_json(Path(job["out"]) / "done.json", {"places": [], "problems": [
            "The Internet Map / wide: object of type 'NoneType' has no len()"]})
    _fake_unreal(monkeypatch, ub, nothing)
    ub.start(ep)
    bad = ub.check()
    assert bad["state"] == "failed" and "no guide pictures" in bad["text"] and "NoneType" in bad["text"]


def test_unreal_script_saves_the_file_itself_when_reading_pixels_gives_nothing(tmp_path, monkeypatch):
    import runpy
    import sys
    from unittest import mock

    fake = mock.MagicMock()
    fake.RenderingLibrary.read_render_target_raw.return_value = None          # what Unreal 5.8.4 did
    fake.RenderingLibrary.read_render_target.return_value = None

    def export(world, rt, folder, name):
        Path(folder, name).write_bytes(b"#?RADIANCE fake")
    fake.RenderingLibrary.export_render_target.side_effect = export
    monkeypatch.setitem(sys.modules, "unreal", fake)
    script = Path("fofstudio/data/unreal/fof_unreal_guides.py")
    ns = runpy.run_path(str(script), run_name="fof_test")          # its main() fails quietly: no job file here
    assert ns["save_picture"]("rt", str(tmp_path), "wide.depth", ".hdr", raw=True) == "wide.depth.hdr"
    assert ns["HOW"]["depth"] == "export"
    assert ns["save_picture"]("rt", str(tmp_path), "medium.depth", ".hdr", raw=True) == "medium.depth.hdr"
    assert fake.RenderingLibrary.read_render_target_raw.call_count == 1   # tried once, then straight to saving
    # and when reading does work (older Unreal), the exact numbers are written raw
    ns["HOW"].clear()
    px = [mock.Mock(r=float(i % 50)) for i in range(ns["WIDTH"] * ns["HEIGHT"])]
    fake.RenderingLibrary.read_render_target_raw.return_value = px
    assert ns["save_picture"]("rt", str(tmp_path), "low.depth", ".hdr", raw=True) == "low.depth.bin"
    assert (tmp_path / "low.depth.bin").stat().st_size == 4 * len(px)


def test_unreal_script_waits_for_frames_and_retries_an_empty_picture(tmp_path, monkeypatch):
    """Dave's run 2026-11-02: everything ran inside Unreal's second frame and every depth picture came back
    empty. Now the script works frame by frame, checks each depth picture, and waits and tries again."""
    import json
    import runpy
    import sys
    from unittest import mock

    class P:
        def __init__(self, r):
            self.r = r
    n = 672 * 384
    blank = [P(0.0)] * n
    good = [P(300.0 if i % 672 < 300 else 1500.0) for i in range(n)]
    reads = []

    def read(world, rt, normalize):
        reads.append(1)
        return blank if len(reads) == 1 else good           # the very first picture is empty, then fine
    fake = mock.MagicMock()
    fake.get_editor_subsystem.return_value.is_in_play_in_editor.return_value = False
    fake.RenderingLibrary.read_render_target_raw.side_effect = read
    fake.RenderingLibrary.export_render_target.side_effect = \
        lambda world, rt, folder, name: Path(folder, name).write_bytes(b"png")
    ticks = {}
    fake.register_slate_post_tick_callback.side_effect = lambda fn: ticks.setdefault("fn", fn) and "handle"
    # Unreal 5.8 draws frames inside "wait until ready", and each frame calls the script's tick again
    # (Dave's run 2026-11-02: "generator already executing")
    fake.AutomationLibrary.finish_loading_before_screenshot.side_effect = lambda: [ticks["fn"](0.0) for _ in range(3)]
    monkeypatch.setitem(sys.modules, "unreal", fake)
    job = tmp_path / "job.json"
    job.write_text(json.dumps({"out": str(tmp_path / "out"), "auto": True,
                               "places": [{"id": "loc_001", "name": "Radio Studio", "architecture": "radio studio"}]}))
    src = Path("fofstudio/data/unreal/fof_unreal_guides.py").read_text(encoding="utf-8")
    script = tmp_path / "fof_unreal_guides.py"
    script.write_text(src.replace("{{JOB_PATH}}", str(job)), encoding="utf-8")
    runpy.run_path(str(script), run_name="fof_test")
    fake.EditorPythonScripting.set_keep_python_script_alive.assert_any_call(True)   # Unreal stays open
    assert "fn" in ticks and not (tmp_path / "out" / "done.json").exists()          # nothing done yet
    for _ in range(5000):
        ticks["fn"](0.016)
        if (tmp_path / "out" / "done.json").exists():
            break
    done = json.loads((tmp_path / "out" / "done.json").read_text())
    assert done["problems"] == [] and "Radio Studio" in done["places"][0]
    out = tmp_path / "out" / "loc_001"
    assert {f"{c}.depth.bin" for c in ("wide", "medium", "low", "high", "close", "side")} <= \
        {f.name for f in out.iterdir()}
    log = (tmp_path / "out" / "run-log.txt").read_text()
    assert "the depth picture was empty (every value was 0)" in log and "waiting and trying again" in log
    assert "hit something, 300-1500 cm" in log
    fake.SystemLibrary.quit_editor.assert_called_once()                              # closes when done
    assert fake.AutomationLibrary.finish_loading_before_screenshot.called and "ERROR" not in log


def test_pictures_get_no_ratios_timestamps_or_labels():
    """Dave's storyboard 2026-11-02 had "11:9", "16:9" and "10.9" painted in: nearly every style ended with
    ", 16:9" and the camcorder look asked for a "date timestamp in corner"."""
    import json

    from fofstudio import shotplan
    from fofstudio.promptcheck import no_text_cues
    cam = ("analog camcorder home video still, chroma bleed and colour smear, harsh on-camera light, "
           "blocky date timestamp in corner, 16:9")
    assert no_text_cues(cam) == ("analog camcorder home video still, chroma bleed and colour smear, harsh "
                                 "on-camera light")
    assert no_text_cues("extreme widescreen 2.39:1 frame, dusty light, 16:9") == "dusty light"
    assert no_text_cues("a desk with a document labelled HR 645, warm lamp") == "a desk with a document, warm lamp"
    for keep in ("a reading lamp on a desk", "a man reading a newspaper", "a stamped envelope, cream paper texture"):
        assert no_text_cues(keep) == keep
    styles = json.loads(Path("fofstudio/data/styles.json").read_text(encoding="utf-8"))
    items = styles if isinstance(styles, list) else list(styles.get("styles", styles).values()) \
        if isinstance(styles.get("styles", styles), dict) else styles.get("styles")
    for st in items:
        out = no_text_cues(st["look"])
        assert not __import__("re").search(r"\d+\s*:\s*\d+|timestamp", out), (st["key"], out)
    motion = shotplan.motion_prompt("the camera pushes in, 16:9", "slowly", "", ["dust drifts"], "low")
    assert "16:9" not in motion


def test_a_scene_shot_with_owlbert_in_it_becomes_an_owlbert_shot():
    from fofstudio.stages.storyboard import OWLBERT_WORDS
    assert OWLBERT_WORDS.search("Owlbert stands at a small, cluttered desk in the corner of the studio")
    assert OWLBERT_WORDS.search("Professor Owl points at the map")
    assert not OWLBERT_WORDS.search("an owl-shaped weathervane on a barn roof at dusk")


def test_the_painter_is_never_handed_text_numbers_or_an_owl(data):
    """Dave 2026-11-02: "it's like taking the screen instructions literally". The last check before the painter."""
    from fofstudio.crew import numbers_as_words, painter_safe
    assert numbers_as_words("1980s cel anime, 35mm film grain") == "nineteen-eighties cel anime, thirty-five millimetre film grain"
    out = painter_safe("A medium view: Owlbert stands at a desk with a document labelled HR 645 in 1999, \"FEMA\" "
                       "papers, an owl statue on a shelf, 16:9, then the shot begins")
    assert not re.search(r"\d|owl|:|\"|then|shot begins", out, re.I), out
    assert "desk" in out and "document" in out
    assert "owl" in painter_safe("an owl on a branch", owl_allowed=True)


def test_the_crew_dresses_the_sets_draws_up_frames_and_supervises(episode):
    """Production designer → storyboard artist → script supervisor, before anything is painted; the painter
    paints the frozen moment, and every step is in the crew log."""
    from fofstudio import crew
    ep = episode
    research_and_story(ep)
    pipeline.run_now(ep, "script")
    pipeline.approve(ep, "script")
    pipeline.run_now(ep, "storyboard")
    b = bible.load(ep)
    loc = next(iter(b["locations"].values()))
    assert len(loc["dressing"]) >= 6 and loc["palette"] and "left" in loc["light"]
    sid = next(iter(b["scenes"]))
    assert "set pieces: cracked green leather armchair" in bible.location_words(b, sid)
    shots = [sh for s in ep.storyboard()["scenes"] for sh in s["shots"] if sh["kind"] in ("broll", "owl")]
    assert shots and all(sh.get("camera_sees") for sh in shots)
    for sh in shots:
        assert not re.search(r"\d", sh["camera_sees"]) and "typed page" in sh["camera_sees"]
        painted = sh["candidates"][0]["full_prompt"]
        assert "typed page" in painted and not re.search(r"\d+\s*:\s*\d+|\bowl\b|timestamp", painted, re.I)
        assert sh["continuity"]["owlbert"] == ("rig" if sh["kind"] == "owl" else "none")
    roles = {e["role"] for e in crew.entries(ep)}
    assert {"breakdown", "designer", "artist", "supervisor"} <= roles
    # a second run keeps the dressed sets; a frame is only drawn again when its shot's plan changed
    before = len(crew.entries(ep))
    kept = {sh["shot_id"]: (sh["idea"], sh["camera_sees"]) for s in ep.storyboard()["scenes"] for sh in s["shots"]
            if sh.get("camera_sees")}
    pipeline.run_now(ep, "storyboard")
    assert not [e for e in crew.entries(ep)[before:] if e["role"] == "designer"]
    for s in ep.storyboard()["scenes"]:
        for sh in s["shots"]:
            if sh.get("camera_sees"):
                assert sh["camera_sees_from"] == sh["idea"]
                if sh["shot_id"] in kept and kept[sh["shot_id"]][0] == sh["idea"]:
                    assert sh["camera_sees"] == kept[sh["shot_id"]][1]


def test_a_picture_that_may_hold_a_painted_owl_is_never_animated_by_wan():
    from fofstudio.stages.video import _may_hold_an_owl
    assert _may_hold_an_owl({"prompt": "Owlbert stands at a small desk", "image": {"full_prompt": "a desk"}})
    assert not _may_hold_an_owl({"prompt": "a typed page under a lamp", "image": {"full_prompt": "a typed page"}})
    # Owlbert's own empty set is fine: he was taken out before painting and is added from his rig
    assert not _may_hold_an_owl({"prompt": "Owlbert by the window", "image": {"set": "x.png",
                                                                             "full_prompt": "an empty quiet set"}})
