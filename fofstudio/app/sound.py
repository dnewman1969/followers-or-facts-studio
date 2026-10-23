"""Speakers, listening volume and test sounds for the preview player and Settings.

Why preview sound could be missing before: the player only connected to the speakers if Windows
had already listed them when the window was built, and on some PCs that list is still empty at
startup. Now the player always gets an audio output, set to the speaker chosen in Settings (or
Windows' default), and re-attaches when speakers are plugged in or out.
"""

from __future__ import annotations

import math
import os
import struct
import wave
from pathlib import Path

from PySide6.QtCore import QObject, QUrl
from PySide6.QtMultimedia import QAudioDevice, QAudioOutput, QMediaDevices, QMediaPlayer, QtAudio

from ..config import Paths, settings

_devices = None


def audio_enabled() -> bool:
    return not os.environ.get("FOF_NO_AUDIO")  # automated tests run without a sound card


def watch(callback) -> None:
    """Call back when speakers are plugged in or out."""
    if audio_enabled():
        devices().audioOutputsChanged.connect(callback)


def devices() -> QMediaDevices:
    global _devices
    if _devices is None:
        _devices = QMediaDevices()
    return _devices


def device_key(dev: QAudioDevice) -> str:
    return bytes(dev.id()).hex()


def outputs() -> list[QAudioDevice]:
    return list(QMediaDevices.audioOutputs()) if audio_enabled() else []


def chosen_device(key: str | None = None) -> QAudioDevice:
    """The speaker picked in Settings, or Windows' default if it's gone or none was picked."""
    if not audio_enabled():
        return QAudioDevice()
    key = settings()["sound"]["device"] if key is None else key
    if key:
        for dev in outputs():
            if device_key(dev) == key:
                return dev
    return QMediaDevices.defaultAudioOutput()


def linear(percent: float) -> float:
    """A 0-100 slider (sounds even to the ear) -> Qt's 0..1 volume."""
    return QtAudio.convertVolume(max(0.0, min(100.0, percent)) / 100.0, QtAudio.VolumeScale.LogarithmicVolumeScale,
                                 QtAudio.VolumeScale.LinearVolumeScale)


def make_output(parent: QObject) -> QAudioOutput | None:
    """An audio output on the chosen speaker at the listening volume, that follows speaker changes."""
    if not audio_enabled():
        return None
    out = QAudioOutput(parent)
    apply(out)
    watch(lambda: apply(out))
    return out


def apply(out: QAudioOutput, key: str | None = None, percent: float | None = None) -> None:
    out.setDevice(chosen_device(key))
    out.setMuted(False)
    out.setVolume(linear(settings()["sound"]["listen_volume"] if percent is None else percent))


def test_tone() -> Path:
    """A short three-note chime (WAV) for 'Play test sound'."""
    path = Paths().root / "sounds" / "test-chime.wav"
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    rate, frames = 48000, []
    for freq in (523.25, 659.25, 783.99):
        n = int(rate * 0.32)
        for i in range(n):
            env = min(1.0, i / 400) * math.exp(-3.0 * i / n)
            v = int(12000 * env * math.sin(2 * math.pi * freq * i / rate))
            frames.append(struct.pack("<hh", v, v))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(frames))
    return path


class Tester(QObject):
    """Plays a file once on a given speaker at a given volume (keeps itself alive while playing)."""

    def __init__(self, parent: QObject):
        super().__init__(parent)
        self.player = QMediaPlayer(self)
        self.out = QAudioOutput(self) if audio_enabled() else None
        if self.out:
            self.player.setAudioOutput(self.out)

    def play(self, path: Path, key: str, percent: float) -> str:
        if not self.out:
            return "Sound is switched off for this run (FOF_NO_AUDIO is set)."
        dev = chosen_device(key)
        if dev.isNull():
            return "Windows reports no speakers or headphones. Plug some in, then press Refresh."
        apply(self.out, key, percent)
        self.player.stop()
        self.player.setSource(QUrl.fromLocalFile(str(path)))
        self.player.play()
        return f"Playing on: {dev.description()}"
