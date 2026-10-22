"""Test setup: a throwaway data folder, the real research data, and fake GPU services.

The fakes stand in for Ollama, ComfyUI and the voice model so the whole
pipeline (database -> script -> storyboard -> images -> narration -> captions
-> render -> package) can run on any machine. ffmpeg is real.
"""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

import pytest
from PIL import Image, ImageDraw


@pytest.fixture()
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("FOF_DATA", str(tmp_path / "data"))
    from fofstudio import config
    config.settings(reload=True)
    from fofstudio import db
    from fofstudio.db import importer
    db.init()
    importer.import_research(importer.SEED)
    # small, fast renders in tests
    s = config.settings()
    s["video"].update({"width": 640, "height": 360, "fps": 15, "encoder": "libx264"})
    s["voice"]["tail_seconds"] = 0.2
    yield tmp_path / "data"
    config.settings(reload=True)


def tone(path: Path, seconds: float, freq: float = 220.0, rate: int = 24000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * freq * i / rate)))
                          for i in range(int(seconds * rate)))
        w.writeframes(frames)


class FakeVoice:
    name = "fake"
    licence = "test"

    def synthesize(self, text, out, voice, speed=1.0, **kw):
        seconds = max(1.0, len(text.split()) * 0.12)
        tone(Path(out), seconds)
        return {"engine": "fake", "voice": voice, "speed": speed, "seconds": seconds, "licence": "test"}


def fake_run_template(setting_key, values, dest_stem, on_progress=None, cancelled=None):
    dest_stem = Path(dest_stem)
    dest_stem.parent.mkdir(parents=True, exist_ok=True)
    if setting_key == "image_workflow":
        img = Image.new("RGB", (values["WIDTH"], values["HEIGHT"]), (40, 60, 100))
        ImageDraw.Draw(img).ellipse((100, 100, 400, 400), fill=(212, 160, 23))
        out = Path(f"{dest_stem}.png")
        img.save(out)
    elif setting_key == "music_workflow":
        out = Path(f"{dest_stem}.wav")
        tone(out, 8, 330)
    else:
        import subprocess
        out = Path(f"{dest_stem}.mp4")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        "testsrc=size=416x240:rate=16:duration=2", "-pix_fmt", "yuv420p", str(out)],
                       check=True)
    return [out], {"workflow": f"fake-{setting_key}.json"}


@pytest.fixture()
def fakes(monkeypatch):
    from fofstudio.engines import tts
    from fofstudio.stages import images, music, video
    monkeypatch.setattr(tts, "get_engine", lambda name=None: FakeVoice())
    from fofstudio.stages import narration
    monkeypatch.setattr(narration, "get_engine", lambda name=None: FakeVoice())
    for mod in (images, music, video):
        monkeypatch.setattr(mod, "run_template", fake_run_template)

    class FakeComfy:
        def upload_image(self, path):
            return Path(path).name

        def free_memory(self):
            pass
    monkeypatch.setattr(video, "Comfy", FakeComfy)
    return monkeypatch
