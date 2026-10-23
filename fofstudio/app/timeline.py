"""A multi-track editing timeline (Qt graphics scene), like the bottom half of a video editor.

Tracks: V1 Video, V2 Owlbert, A1 Speech, A2 Music. Drag clips left/right (they stay on their
track and snap to neighbours, the playhead and 0), drag either end to trim, click the ruler to
move the playhead. Every change is written straight back to the production dictionary and
the `changed` signal fires so the page can save it.
"""

from __future__ import annotations

import math
import wave
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

import numpy as np
from PySide6.QtCore import QLineF, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen
from PySide6.QtWidgets import (QGraphicsItem, QGraphicsLineItem, QGraphicsRectItem, QGraphicsScene,
                               QGraphicsView, QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidget)

TRACK_H = 54
MIN_PPS, MAX_PPS = 1.0, 400.0  # pixels per second: whole hour visible ... single frames
RULER_H = 26
SNAP_PX = 8
TRACKS = [("video", "V1  Video"), ("owl", "V2  Owlbert"), ("speech", "A1  Speech"), ("music", "A2  Music")]
COLORS = {"bumper": "#b8860b", "clip": "#2f5d9e", "clip_ai": "#3a4f8f", "owl": "#6b4c9a",
          "speech": "#2f7d4f", "music": "#21717a"}


@lru_cache(maxsize=128)
def peaks(path: str, columns: int = 600) -> np.ndarray | None:
    """Loudness outline of a WAV for drawing (0..1 per column)."""
    try:
        with wave.open(path, "rb") as w:
            n, ch, width = w.getnframes(), w.getnchannels(), w.getsampwidth()
            data = np.frombuffer(w.readframes(n), dtype={1: np.int8, 2: np.int16, 4: np.int32}[width])
    except (wave.Error, OSError, KeyError, EOFError):
        return None
    data = np.abs(data.astype(np.float32))
    if ch > 1:
        data = data.reshape(-1, ch).max(axis=1)
    if len(data) < columns:
        return None
    usable = len(data) // columns * columns
    p = data[:usable].reshape(columns, -1).max(axis=1)
    top = np.percentile(p, 99) or 1.0
    return np.clip(p / top, 0, 1)


class TimelineScene(QGraphicsScene):
    def __init__(self):
        super().__init__()
        self.pps = 20.0            # pixels per second
        self.items_by_id: dict[str, ClipItem] = {}
        self.playhead_s = 0.0

    def x_of(self, s: float) -> float:
        return s * self.pps

    def s_of(self, x: float) -> float:
        return x / self.pps

    def snap_x(self, left: float, width: float, exclude) -> float:
        targets = [0.0, self.x_of(self.playhead_s)]
        for it in self.items_by_id.values():
            if it is not exclude:
                targets += [it.x(), it.x() + it.rect().width()]
        best = None
        for t in targets:
            for edge in (left, left + width):
                d = t - edge
                if abs(d) <= SNAP_PX and (best is None or abs(d) < abs(best)):
                    best = d
        return left + best if best is not None else left


class ClipItem(QGraphicsRectItem):
    HANDLE = 7

    def __init__(self, track: int, data: dict[str, Any], scene: TimelineScene, label: str, color: str,
                 wave_path: str | None, on_change: Callable[[], None], trimmable: bool):
        super().__init__(0, 0, scene.x_of(data["duration"]), TRACK_H - 8)
        self.track, self.data, self.sc = track, data, scene
        self.label, self.color, self.wave_path = label, color, wave_path
        self.on_change, self.trimmable = on_change, trimmable
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable |
                      QGraphicsItem.ItemSendsGeometryChanges)
        self.setAcceptHoverEvents(True)
        self.setPos(scene.x_of(data["start"]), RULER_H + track * TRACK_H + 4)
        self._mode = None
        self.setToolTip(f"{label}\nstart {data['start']:.2f}s · length {data['duration']:.2f}s\n"
                        "Drag to move · drag an end to trim")

    def itemChange(self, change, value):  # noqa: N802
        if change == QGraphicsItem.ItemPositionChange and self.scene():
            x = self.sc.snap_x(max(0.0, value.x()), self.rect().width(), self)
            return QPointF(x, self.pos().y())          # stays on its own track
        if change == QGraphicsItem.ItemPositionHasChanged:
            self.data["start"] = round(self.sc.s_of(self.x()), 3)
        return super().itemChange(change, value)

    def hoverMoveEvent(self, e):  # noqa: N802
        x, w = e.pos().x(), self.rect().width()
        edge = self.trimmable and (x < self.HANDLE or x > w - self.HANDLE)
        self.setCursor(Qt.SizeHorCursor if edge else Qt.OpenHandCursor)

    def mousePressEvent(self, e):  # noqa: N802
        x, w = e.pos().x(), self.rect().width()
        self._mode = ("trim_l" if self.trimmable and x < self.HANDLE else
                      "trim_r" if self.trimmable and x > w - self.HANDLE else "move")
        self._press_x = e.scenePos().x()
        self._orig = (self.x(), w, self.data.get("inpoint", 0.0))
        if self._mode == "move":
            super().mousePressEvent(e)
        else:
            self.setSelected(True)
            e.accept()

    def mouseMoveEvent(self, e):  # noqa: N802
        if self._mode == "move":
            return super().mouseMoveEvent(e)
        dx = e.scenePos().x() - self._press_x
        x0, w0, in0 = self._orig
        self.prepareGeometryChange()
        if self._mode == "trim_r":
            right = self.sc.snap_x(x0 + w0 + dx, 0, self)
            self.setRect(0, 0, max(6, right - x0), self.rect().height())
        else:
            left = self.sc.snap_x(min(x0 + dx, x0 + w0 - 6), 0, self)
            left = max(left, x0 - self.sc.x_of(in0)) if "inpoint" in self.data else left
            self.setRect(0, 0, x0 + w0 - left, self.rect().height())
            self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, False)
            self.setX(left)
            self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
            if "inpoint" in self.data:
                self.data["inpoint"] = round(max(0.0, in0 + self.sc.s_of(left - x0)), 3)
        self.data["start"] = round(self.sc.s_of(self.x()), 3)
        self.data["duration"] = round(self.sc.s_of(self.rect().width()), 3)

    def mouseReleaseEvent(self, e):  # noqa: N802
        moved = self._mode is not None
        self._mode = None
        super().mouseReleaseEvent(e)
        if moved:
            self.setToolTip(f"{self.label}\nstart {self.data['start']:.2f}s · length {self.data['duration']:.2f}s")
            self.on_change()

    def paint(self, p: QPainter, opt, widget=None):
        r = self.rect()
        sel = self.isSelected()
        p.setPen(QPen(QColor("#ffcc00") if sel else QColor("#0b0d13"), 2 if sel else 1))
        p.setBrush(QColor(self.color))
        p.drawRoundedRect(r, 5, 5)
        if self.wave_path:
            pk = peaks(self.wave_path)
            if pk is not None and r.width() > 4:
                mid, half = r.center().y(), r.height() / 2 - 4
                cols = int(r.width())
                idx = (np.arange(cols) * len(pk) / max(cols, 1)).astype(int).clip(0, len(pk) - 1)
                p.setPen(QColor(255, 255, 255, 110))
                p.drawLines([QLineF(i, mid - pk[j] * half, i, mid + pk[j] * half) for i, j in enumerate(idx)])
        if self.trimmable:
            p.fillRect(QRectF(0, 0, 3, r.height()), QColor(255, 255, 255, 60))
            p.fillRect(QRectF(r.width() - 3, 0, 3, r.height()), QColor(255, 255, 255, 60))
        p.setPen(Qt.white)
        p.drawText(r.adjusted(6, 0, -4, 0), Qt.AlignVCenter | Qt.AlignLeft, self.label)


class TimelineView(QGraphicsView):
    seek = Signal(float)
    zoom = Signal(float, float)  # factor, the second under the mouse

    def __init__(self, scene: TimelineScene):
        super().__init__(scene)
        self.sc = scene
        self.setRenderHint(QPainter.Antialiasing)
        self.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.setBackgroundBrush(QColor("#0f1118"))
        self.setDragMode(QGraphicsView.RubberBandDrag)

    def drawBackground(self, p, rect):  # noqa: N802
        super().drawBackground(p, rect)
        for i in range(len(TRACKS)):
            y = RULER_H + i * TRACK_H
            p.fillRect(QRectF(rect.left(), y, rect.width(), TRACK_H), QColor("#151826" if i % 2 else "#12141f"))

    def drawForeground(self, p, rect):  # noqa: N802
        p.fillRect(QRectF(rect.left(), rect.top(), rect.width(), RULER_H), QColor("#1b1e2a"))
        pps = self.sc.pps
        step = next((s for s in (0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300) if s * pps >= 70), 600)
        t = math.floor(self.sc.s_of(rect.left()) / step) * step
        p.setPen(QColor("#8a8fa3"))
        while self.sc.x_of(t) < rect.right():
            x = self.sc.x_of(t)
            p.drawLine(QLineF(x, rect.top() + RULER_H - 8, x, rect.top() + RULER_H))
            p.drawText(QPointF(x + 3, rect.top() + 15), f"{int(t // 60)}:{int(t % 60):02d}")
            t += step

    def wheelEvent(self, e):  # noqa: N802
        """Ctrl + wheel zooms around the mouse; the plain wheel scrolls along the timeline."""
        dy = e.angleDelta().y() or e.angleDelta().x()
        if e.modifiers() & Qt.ControlModifier:
            at = self.sc.s_of(self.mapToScene(e.position().toPoint()).x())
            self.zoom.emit(1.25 if dy > 0 else 0.8, at)
            e.accept()
            return
        bar = self.horizontalScrollBar()
        bar.setValue(bar.value() - dy)
        e.accept()

    def mousePressEvent(self, e):  # noqa: N802
        pos = self.mapToScene(e.position().toPoint())
        if pos.y() < self.mapToScene(0, RULER_H).y():
            self.seek.emit(max(0.0, self.sc.s_of(pos.x())))
            return
        super().mousePressEvent(e)


class TimelineEditor(QWidget):
    """The timeline with track names on the left and zoom buttons."""

    changed = Signal()
    seek = Signal(float)
    selected = Signal(object)  # (track name, clip dict) or None

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        self.zoom_out = QPushButton("−")
        self.zoom_in = QPushButton("+")
        for b in (self.zoom_out, self.zoom_in):
            b.setFixedWidth(36)
        self.zoom_out.setToolTip("Zoom out (or hold Ctrl and roll the mouse wheel)")
        self.zoom_in.setToolTip("Zoom in (or hold Ctrl and roll the mouse wheel)")
        self.fit_btn = QPushButton("Fit whole video")
        self.zoom_out.clicked.connect(lambda: self.set_zoom(self.scene.pps / 1.5))
        self.zoom_in.clicked.connect(lambda: self.set_zoom(self.scene.pps * 1.5))
        self.fit_btn.clicked.connect(self.fit)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.setFixedWidth(220)
        self.slider.setToolTip("Zoom: left shows the whole video, right shows every second up close")
        self.slider.valueChanged.connect(self._slid)
        self.zoom_label = QLabel("")
        self.zoom_label.setObjectName("muted")
        self.zoom_label.setMinimumWidth(110)
        self.info = QLabel("")
        self.info.setObjectName("muted")
        zl = QLabel("Zoom")
        for w in (zl, self.zoom_out, self.slider, self.zoom_in, self.zoom_label, self.fit_btn, self.info):
            bar.addWidget(w)
        lay.addLayout(bar)
        row = QHBoxLayout()
        heads = QWidget()
        heads.setFixedWidth(110)
        hl = QVBoxLayout(heads)
        hl.setContentsMargins(0, RULER_H, 0, 0)
        hl.setSpacing(0)
        for _, name in TRACKS:
            lab = QLabel(name)
            lab.setFixedHeight(TRACK_H)
            lab.setStyleSheet("background:#1b1e2a; border-bottom:1px solid #0b0d13; padding-left:8px; font-weight:600;")
            hl.addWidget(lab)
        hl.addStretch(1)
        row.addWidget(heads)
        self.scene = TimelineScene()
        self.view = TimelineView(self.scene)
        self.view.setMinimumHeight(RULER_H + TRACK_H * len(TRACKS) + 24)
        self.view.seek.connect(self._seek)
        self.view.zoom.connect(lambda f, at: self.set_zoom(self.scene.pps * f, at))
        self.scene.selectionChanged.connect(self._selection)
        row.addWidget(self.view, 1)
        lay.addLayout(row)
        self.playhead = None
        self.tl: dict[str, Any] = {}
        self.resolve = lambda rel: rel

    def load(self, tl: dict[str, Any], resolve: Callable[[str], Path]) -> None:
        self.tl, self.resolve = tl, resolve
        self._build()

    def _build(self) -> None:
        self.scene.clear()
        self.scene.items_by_id = {}
        end = 10.0
        for ti, (track, _) in enumerate(TRACKS):
            for c in self.tl.get(track, []):
                if track == "video":
                    color = COLORS["bumper"] if c.get("kind") == "bumper" else COLORS["clip_ai" if c.get("ai") else "clip"]
                    label, wav = c.get("label", c["id"]), None
                elif track == "owl":
                    color, label, wav = COLORS["owl"], "Owlbert on screen", None
                elif track == "speech":
                    color, label = COLORS["speech"], f"{c.get('scene_id', '')}  {c.get('text', '')[:60]}"
                    wav = str(self.resolve(c["src"]))
                else:
                    color, label, wav = COLORS["music"], "Music", str(self.resolve(c["src"]))
                item = ClipItem(ti, c, self.scene, label, color, wav, self._changed,
                                trimmable=track in ("video", "owl", "music"))
                self.scene.addItem(item)
                self.scene.items_by_id[f"{track}:{c['id']}"] = item
                end = max(end, c["start"] + c["duration"])
        self.scene.setSceneRect(0, 0, self.scene.x_of(end + 20), RULER_H + TRACK_H * len(TRACKS))
        self.playhead = QGraphicsLineItem(0, 0, 0, RULER_H + TRACK_H * len(TRACKS))
        self.playhead.setPen(QPen(QColor("#ff3b30"), 2))
        self.playhead.setZValue(1000)
        self.scene.addItem(self.playhead)
        self.set_playhead(self.scene.playhead_s)
        self.info.setText(f"{end / 60:.1f} min  ·  drag clips to move, drag ends to trim, click the ruler to "
                          "jump, Ctrl + mouse wheel to zoom")

    def set_zoom(self, pps: float, anchor_s: float | None = None) -> None:
        """Change how many pixels one second takes, keeping anchor_s (default: the middle of the view,
        or the playhead if it's on screen) at the same place on screen."""
        view = self.view.viewport().width()
        left = self.view.horizontalScrollBar().value()
        if anchor_s is None:
            ph = self.scene.x_of(self.scene.playhead_s)
            anchor_s = self.scene.playhead_s if left <= ph <= left + view else self.scene.s_of(left + view / 2)
        screen_x = self.scene.x_of(anchor_s) - left
        self.scene.pps = max(MIN_PPS, min(MAX_PPS, pps))
        self._build()
        self.view.horizontalScrollBar().setValue(int(self.scene.x_of(anchor_s) - screen_x))
        self.slider.blockSignals(True)
        self.slider.setValue(int(1000 * math.log(self.scene.pps / MIN_PPS) / math.log(MAX_PPS / MIN_PPS)))
        self.slider.blockSignals(False)
        shown = view / self.scene.pps
        self.zoom_label.setText(f"showing {shown / 60:.1f} min" if shown >= 90 else f"showing {shown:.0f} s")

    def _slid(self, v: int) -> None:
        self.set_zoom(MIN_PPS * (MAX_PPS / MIN_PPS) ** (v / 1000))

    def fit(self) -> None:
        end = max((c["start"] + c["duration"] for t, _ in TRACKS for c in self.tl.get(t, [])), default=60)
        self.set_zoom((self.view.viewport().width() - 20) / max(end, 1))

    def set_playhead(self, seconds: float) -> None:
        self.scene.playhead_s = seconds
        if self.playhead:
            self.playhead.setX(self.scene.x_of(seconds))
            self.view.ensureVisible(self.playhead, 60, 0)

    def _seek(self, seconds: float) -> None:
        self.set_playhead(seconds)
        self.seek.emit(seconds)

    def _changed(self) -> None:
        self.changed.emit()

    def _selection(self) -> None:
        items = [i for i in self.scene.selectedItems() if isinstance(i, ClipItem)]
        if not items:
            self.selected.emit(None)
            return
        it = items[0]
        self.selected.emit((TRACKS[it.track][0], it.data))
