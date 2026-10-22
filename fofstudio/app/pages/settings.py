"""Settings: every value in settings.toml as a form, plus connection tests."""

from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QDoubleSpinBox, QFormLayout, QGroupBox, QLineEdit,
                               QScrollArea, QSpinBox, QVBoxLayout, QWidget)

from ...comfy import Comfy
from ...config import save_settings, settings, settings_path
from ...llm import Ollama
from ..common import button, info, label, row

HELP = {
    "truth_vlog_research": "Folder with truth-vlog's research CSVs (claims/, sources/...)",
    "writer_model": "Writes scripts and storyboards",
    "checker_model": "A different model, for checks",
    "image_workflow": "ComfyUI API-format workflow with {{PROMPT}} etc.",
    "video_workflow": "Wan 2.2 image-to-video workflow",
    "voice": "Kokoro voice id, e.g. bm_george, bm_fable, am_michael",
    "client_secrets": "OAuth client JSON from Google Cloud (see docs/YOUTUBE.md)",
    "privacy": "private, unlisted or public",
}


class SettingsPage(QWidget):
    def __init__(self):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.addWidget(label("Settings", "h1"))
        outer.addWidget(label(f"Saved to {settings_path()}", "muted"))
        outer.addWidget(row(button("Save", self._save, "primary"), button("Test Ollama", self._ollama),
                            button("Test ComfyUI", self._comfy)))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        self.lay = QVBoxLayout(body)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        self.fields: dict[tuple[str, str], QWidget] = {}
        self._build()

    def _build(self) -> None:
        for section, values in settings().items():
            box = QGroupBox(section)
            form = QFormLayout(box)
            for key, value in values.items():
                if isinstance(value, bool):
                    w = QCheckBox()
                    w.setChecked(value)
                elif isinstance(value, int):
                    w = QSpinBox()
                    w.setRange(0, 10_000_000)
                    w.setValue(value)
                elif isinstance(value, float):
                    w = QDoubleSpinBox()
                    w.setDecimals(2)
                    w.setRange(0, 100000)
                    w.setValue(value)
                elif isinstance(value, list):
                    w = QLineEdit(", ".join(value))
                else:
                    w = QLineEdit(str(value))
                if key in HELP:
                    w.setToolTip(HELP[key])
                self.fields[(section, key)] = w
                form.addRow(key, w)
            self.lay.addWidget(box)
        self.lay.addStretch(1)

    def _save(self) -> None:
        data = settings()
        for (section, key), w in self.fields.items():
            old = data[section][key]
            if isinstance(w, QCheckBox):
                data[section][key] = w.isChecked()
            elif isinstance(w, (QSpinBox, QDoubleSpinBox)):
                data[section][key] = type(old)(w.value())
            elif isinstance(old, list):
                data[section][key] = [x.strip() for x in w.text().split(",") if x.strip()]
            else:
                data[section][key] = w.text()
        path = save_settings(data)
        info(self, f"Saved {path}")

    def _ollama(self) -> None:
        info(self, Ollama().health()[1])

    def _comfy(self) -> None:
        info(self, Comfy().health()[1])
