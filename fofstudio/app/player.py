"""A video player with Play / Pause / Stop, a scrub bar and a time readout (Qt Multimedia)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidget)

from ..config import settings
from . import sound


def fmt(ms: int) -> str:
    s = max(0, ms) // 1000
    return f"{s // 60}:{s % 60:02d}.{(max(0, ms) % 1000) // 100}"


class Player(QWidget):
    position_changed = Signal(float)  # seconds, for timeline playheads

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.video = QVideoWidget()
        self.video.setMinimumSize(320, 180)
        self.video.setStyleSheet("background:black;")
        lay.addWidget(self.video, 1)
        self.player = QMediaPlayer(self)
        # always connect to the speakers chosen in Settings (kept as self.audio so it isn't thrown away)
        self.audio = sound.make_output(self)
        if self.audio:
            self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video)
        controls = QHBoxLayout()
        self.play_btn = QPushButton("▶  Play")
        self.play_btn.clicked.connect(self.toggle)
        self.stop_btn = QPushButton("■  Stop")
        self.stop_btn.clicked.connect(self.stop)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.sliderMoved.connect(lambda v: self.player.setPosition(v))
        self.time = QLabel("0:00.0 / 0:00.0")
        self.time.setMinimumWidth(130)
        for w in (self.play_btn, self.stop_btn):
            w.setMinimumWidth(90)
        controls.addWidget(self.play_btn)
        controls.addWidget(self.stop_btn)
        controls.addWidget(self.slider, 1)
        controls.addWidget(self.time)
        self.vol = QSlider(Qt.Horizontal)
        self.vol.setRange(0, 100)
        self.vol.setFixedWidth(90)
        self.vol.setValue(int(settings()["sound"]["listen_volume"]))
        self.vol.setToolTip("How loud the preview plays on this PC (doesn't change the video)")
        self.vol.valueChanged.connect(self._volume)
        self.mute_btn = QPushButton("🔊")
        self.mute_btn.setFixedWidth(40)
        self.mute_btn.setToolTip("Mute / unmute")
        self.mute_btn.clicked.connect(self._mute)
        controls.addWidget(self.mute_btn)
        controls.addWidget(self.vol)
        if not self.audio:
            self.mute_btn.setText("🔇")
            self.mute_btn.setToolTip("No sound in this run")
            self.mute_btn.setEnabled(False)
            self.vol.setEnabled(False)
        lay.addLayout(controls)
        self.player.positionChanged.connect(self._pos)
        self.player.durationChanged.connect(lambda d: self.slider.setRange(0, d))
        self.player.playbackStateChanged.connect(self._state)
        self.player.errorOccurred.connect(lambda *_: self.time.setText("Can't play this file"))

    def load(self, path: Path | str | None) -> None:
        self.player.stop()
        if path and Path(path).exists():
            self.player.setSource(QUrl.fromLocalFile(str(path)))
            self.time.setText("Ready — press Play")
        else:
            self.player.setSource(QUrl())
            self.time.setText("Nothing to play yet")

    def _volume(self, v: int) -> None:
        if self.audio:
            self.audio.setVolume(sound.linear(v))
            self.audio.setMuted(False)
            self.mute_btn.setText("🔊")

    def _mute(self) -> None:
        if self.audio:
            self.audio.setMuted(not self.audio.isMuted())
            self.mute_btn.setText("🔇" if self.audio.isMuted() else "🔊")

    def refresh_audio(self) -> None:
        """Settings changed: use the new speaker and volume."""
        if self.audio:
            sound.apply(self.audio)
            self.vol.blockSignals(True)
            self.vol.setValue(int(settings()["sound"]["listen_volume"]))
            self.vol.blockSignals(False)

    def toggle(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def stop(self) -> None:
        # pause and go back to the start (a real stop() blanks the picture)
        self.player.pause()
        self.player.setPosition(0)

    def seek(self, seconds: float) -> None:
        self.player.setPosition(int(seconds * 1000))

    def _pos(self, ms: int) -> None:
        if not self.slider.isSliderDown():
            self.slider.setValue(ms)
        self.time.setText(f"{fmt(ms)} / {fmt(self.player.duration())}")
        self.position_changed.emit(ms / 1000)

    def _state(self, state) -> None:
        self.play_btn.setText("❚❚  Pause" if state == QMediaPlayer.PlayingState else "▶  Play")


class PlayerDialog(QDialog):
    def __init__(self, path: Path, title: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(960, 600)
        lay = QVBoxLayout(self)
        self.p = Player(self)
        lay.addWidget(self.p)
        self.p.load(path)
        self.p.player.play()

    def closeEvent(self, e) -> None:  # noqa: N802
        self.p.player.stop()
        super().closeEvent(e)
