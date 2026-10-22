"""Render Mode: free RAM and VRAM by pausing other programs while the GPU works."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QTableWidgetItem, QVBoxLayout, QWidget

from ... import rendermode
from ...config import save_settings, settings
from ..common import GOLD, button, error, info, label, row, table


class RenderModePage(QWidget):
    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.addWidget(label("Render Mode", "h1"))
        lay.addWidget(label("Pauses the programs you tick (they're suspended, not closed) so the "
                            "renders get the memory. Everything comes back exactly as it was when "
                            "you press Resume all, or automatically after each GPU job if the box "
                            "below is ticked.", "muted"))
        self.meters = label("", "h2")
        lay.addWidget(self.meters)
        self.auto = QCheckBox("Pause the suggested programs automatically during every GPU job")
        self.auto.setChecked(bool(settings()["rendermode"]["auto_for_gpu_stages"]))
        self.auto.toggled.connect(self._auto)
        lay.addWidget(self.auto)
        lay.addWidget(row(button("Scan", self.refresh), button("Pause ticked", self._suspend, "primary"),
                          button("Resume all", self._resume)))
        self.table = table(["Pause?", "Program", "Memory", "Processes", "State"])
        lay.addWidget(self.table, 1)
        self._names: list[str] = []

    def refresh(self) -> None:
        gpu = rendermode.gpu_memory()
        ram = rendermode.ram()
        text = f"RAM {ram['used_gb']} / {ram['total_gb']} GB"
        if gpu:
            text += f"    ·    {gpu['name']}: {gpu['used_mb'] / 1024:.1f} / {gpu['total_mb'] / 1024:.1f} GB VRAM, {gpu['util']}% busy"
        self.meters.setText(text)
        groups = rendermode.scan()
        self._names = [g["name"] for g in groups]
        self.table.setRowCount(len(groups))
        for r, g in enumerate(groups):
            box = QTableWidgetItem()
            box.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            box.setCheckState(Qt.Checked if g["suggested"] and not g["suspended"] else Qt.Unchecked)
            self.table.setItem(r, 0, box)
            for c, v in enumerate([g["name"], f"{g['mb']:,} MB", len(g["pids"]),
                                   "paused" if g["suspended"] else ""], 1):
                self.table.setItem(r, c, QTableWidgetItem(str(v)))
        self.table.resizeColumnsToContents()

    def _suspend(self) -> None:
        names = [self._names[r] for r in range(self.table.rowCount())
                 if self.table.item(r, 0).checkState() == Qt.Checked]
        if not names:
            return
        try:
            done = rendermode.suspend(names)
        except Exception as exc:  # noqa: BLE001
            error(self, str(exc))
            return
        info(self, f"Paused {len(done)} processes. Press Resume all when the render is done.")
        self.refresh()

    def _resume(self) -> None:
        done = rendermode.resume_all()
        info(self, f"Resumed {len(done)} processes.")
        self.refresh()

    def _auto(self, on: bool) -> None:
        s = settings()
        s["rendermode"]["auto_for_gpu_stages"] = on
        save_settings(s)
