"""Voice engines behind one interface (the idea from EchoForge's voice.py/tts.py).

    engine = get_engine("kokoro")
    info = engine.synthesize("Hello.", Path("line.wav"), voice="bm_george", speed=0.95)

Kokoro (Apache-2.0): 50+ stock voices, runs on the CPU, no cloning. Default.
Chatterbox (MIT): clones a voice from a 5-20 s sample, with an emotion slider.
    Only voices with a rights record (voices/<name>/rights.json saying you have
    consent) can be used, so the channel never imitates someone without permission.

XTTS and F5-TTS are deliberately not here: their licences forbid commercial use.
"""

from __future__ import annotations

import json
import re
import wave
from pathlib import Path
from typing import Any

from ..config import REPO, Paths, settings
from ..util import StageError, read_json

KOKORO_FILES = {
    "kokoro-v1.0.onnx": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx",
    "voices-v1.0.bin": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin",
}

RESPELL = REPO / "brand" / "respellings.json"


def respell(text: str) -> str:
    """Swap words the voice says wrong for spellings it says right (brand/respellings.json)."""
    table: dict[str, str] = read_json(RESPELL, {}) or {}
    for word, spoken in sorted(table.items(), key=lambda kv: -len(kv[0])):
        text = re.sub(rf"(?<![\w-]){re.escape(word)}(?![\w-])", spoken, text, flags=re.IGNORECASE)
    return text


def write_wav(path: Path, samples: Any, rate: int) -> float:
    import numpy as np
    data = np.asarray(samples, dtype="float32").flatten()
    pcm = (np.clip(data, -1.0, 1.0) * 32767).astype("<i2")
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(rate))
        w.writeframes(pcm.tobytes())
    return len(pcm) / float(rate)


class TTSEngine:
    name = "base"
    licence = ""

    def voices(self) -> list[str]:
        return []

    def synthesize(self, text: str, out: Path, voice: str, speed: float = 1.0,
                   **kw: Any) -> dict[str, Any]:
        raise NotImplementedError


class KokoroEngine(TTSEngine):
    name = "kokoro"
    licence = "Apache-2.0"

    def __init__(self) -> None:
        self.dir = Paths().models / "kokoro"
        self._model = None

    def _load(self):
        if self._model is None:
            try:
                from kokoro_onnx import Kokoro
            except ImportError:
                raise StageError("The Kokoro voice isn't installed. Run setup.ps1 "
                                 "(or: pip install kokoro-onnx).")
            model = self.dir / "kokoro-v1.0.onnx"
            voices = self.dir / "voices-v1.0.bin"
            if not model.exists() or not voices.exists():
                raise StageError(f"Kokoro model files are missing in {self.dir}. Run: "
                                 "python -m fofstudio download-models")
            self._model = Kokoro(str(model), str(voices))
        return self._model

    def voices(self) -> list[str]:
        try:
            return sorted(self._load().get_voices())
        except StageError:
            return []

    def synthesize(self, text: str, out: Path, voice: str, speed: float = 1.0,
                   lang: str | None = None, **kw: Any) -> dict[str, Any]:
        model = self._load()
        lang = lang or settings()["voice"]["lang"]
        try:
            samples, rate = model.create(respell(text), voice=voice, speed=float(speed), lang=lang)
        except Exception as exc:  # noqa: BLE001
            raise StageError(f"Kokoro couldn't read this line: {exc}")
        seconds = write_wav(Path(out), samples, rate)
        return {"engine": self.name, "voice": voice, "speed": speed, "seconds": seconds,
                "licence": self.licence}


class ChatterboxEngine(TTSEngine):
    name = "chatterbox"
    licence = "MIT (adds an inaudible watermark)"

    def __init__(self) -> None:
        self.dir = Paths().models / "voices"
        self._model = None

    def voices(self) -> list[str]:
        if not self.dir.exists():
            return []
        return sorted(p.name for p in self.dir.iterdir() if (p / "rights.json").exists())

    def _reference(self, voice: str) -> Path:
        folder = self.dir / voice
        rights = read_json(folder / "rights.json")
        if not rights or rights.get("consent") is not True or not rights.get("owner"):
            raise StageError(
                f"Voice '{voice}' has no rights record. Create {folder / 'rights.json'} with "
                '{"owner": "who this voice belongs to", "consent": true, "note": "how consent '
                'was given"}. The channel only clones its own or consenting voices.')
        sample = next((p for p in folder.glob("*.wav")), None)
        if not sample:
            raise StageError(f"Put a 5-20 second clean WAV sample of the voice in {folder}.")
        return sample

    def synthesize(self, text: str, out: Path, voice: str, speed: float = 1.0,
                   emotion: float = 0.5, **kw: Any) -> dict[str, Any]:
        ref = self._reference(voice)
        if self._model is None:
            try:
                from chatterbox.tts import ChatterboxTTS
                import torch
            except ImportError:
                raise StageError("Chatterbox isn't installed. Run setup.ps1 -Chatterbox.")
            device = "cuda" if torch.cuda.is_available() else "cpu"
            self._model = ChatterboxTTS.from_pretrained(device=device)
        wav = self._model.generate(respell(text), audio_prompt_path=str(ref),
                                   exaggeration=float(emotion), cfg_weight=0.5)
        seconds = write_wav(Path(out), wav.squeeze().cpu().numpy(), self._model.sr)
        return {"engine": self.name, "voice": voice, "emotion": emotion, "seconds": seconds,
                "licence": self.licence, "reference": ref.name}


ENGINES = {"kokoro": KokoroEngine, "chatterbox": ChatterboxEngine}
_instances: dict[str, TTSEngine] = {}


def get_engine(name: str | None = None) -> TTSEngine:
    name = name or settings()["voice"]["engine"]
    if name not in ENGINES:
        raise StageError(f"Unknown voice engine '{name}'. Choose: {', '.join(ENGINES)}")
    if name not in _instances:
        _instances[name] = ENGINES[name]()
    return _instances[name]


def download_kokoro(progress=print) -> list[Path]:
    import requests
    folder = Paths().ensure().models / "kokoro"
    folder.mkdir(parents=True, exist_ok=True)
    got = []
    for name, url in KOKORO_FILES.items():
        dest = folder / name
        if dest.exists() and dest.stat().st_size > 1_000_000:
            got.append(dest)
            continue
        progress(f"Downloading {name} ...")
        with requests.get(url, stream=True, timeout=60) as r:
            r.raise_for_status()
            tmp = dest.with_suffix(dest.suffix + ".part")
            with open(tmp, "wb") as fh:
                for chunk in r.iter_content(1 << 20):
                    fh.write(chunk)
            tmp.replace(dest)
        got.append(dest)
    (folder / "SOURCE.json").write_text(json.dumps(
        {"model": "Kokoro-82M v1.0 (ONNX)", "licence": "Apache-2.0", "files": KOKORO_FILES},
        indent=2), encoding="utf-8")
    return got
