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
