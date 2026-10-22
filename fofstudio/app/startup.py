"""The window you see first: starts Ollama and ComfyUI, waits until both answer, then opens the Studio."""

from __future__ import annotations

import threading
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QVBoxLayout

from .. import APP_NAME, services
from ..config import REPO, settings
from .common import GOLD, GREEN, MUTED, RED, button, label, row


class Startup(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        owl = QLabel()
        pix = QPixmap(str(REPO / "brand" / "owlbert-profile.png"))
        if not pix.isNull():
            owl.setPixmap(pix.scaled(120, 120, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        top.addWidget(owl)
        title = QVBoxLayout()
        title.addWidget(label(APP_NAME, "h1"))
        title.addWidget(label("Getting the local AI ready...", "muted"))
        top.addLayout(title, 1)
        lay.addLayout(top)
        self.rows = {"ollama": label("Ollama (writes scripts)"), "comfyui": label("ComfyUI (makes pictures)")}
        for w in self.rows.values():
            lay.addWidget(w)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setVisible(False)
        self.detail.setMinimumHeight(160)
        lay.addWidget(self.detail)
        self.open_btn = button("Open anyway", self.accept)
        self.log_btn = button("Show ComfyUI messages", self._show_log)
        self.log_btn.setVisible(False)
        lay.addWidget(row(self.open_btn, self.log_btn))
        self.state = {"ollama": ("wait", "Checking..."), "comfyui": ("wait", "Checking..."), "done": False}
        self.started = time.time()
        threading.Thread(target=self._work, daemon=True).start()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(500)

    # runs in a background thread so the window never freezes
    def _work(self) -> None:
        svc = settings()["services"]
        want_ollama, want_comfy = svc["start_ollama"], svc["start_comfyui"]

        if services.ollama_up():
            self.state["ollama"] = ("ok", "Running")
        elif want_ollama:
            self.state["ollama"] = ("wait", services.start_ollama())
        else:
            self.state["ollama"] = ("off", "Not running (auto-start is off in Settings)")

        url = services.comfy_url_up()
        if url:
            services.remember_comfy_url(url)
            self.state["comfyui"] = ("ok", f"Running at {url}")
        elif want_comfy:
            msg = services.start_comfyui()
            failed = not msg.startswith("Starting")
            self.state["comfyui"] = ("fail" if failed else "wait", msg)
        else:
            self.state["comfyui"] = ("off", "Not running (auto-start is off in Settings)")

        limit = {"ollama": 60, "comfyui": float(svc["comfyui_wait_seconds"])}
        while True:
            busy = False
            if self.state["ollama"][0] == "wait":
                if services.ollama_up():
                    self.state["ollama"] = ("ok", "Running")
                elif time.time() - self.started > limit["ollama"]:
                    self.state["ollama"] = ("fail", "Didn't start within a minute. Start Ollama from the Start menu.")
                else:
                    busy = True
            if self.state["comfyui"][0] == "wait":
                url = services.comfy_url_up()
                if url:
                    services.remember_comfy_url(url)
                    self.state["comfyui"] = ("ok", f"Running at {url}")
                elif time.time() - self.started > limit["comfyui"]:
                    self.state["comfyui"] = ("fail", "Didn't answer in time. Press 'Show ComfyUI messages' to see why.")
                else:
                    secs = int(time.time() - self.started)
                    self.state["comfyui"] = ("wait", f"Starting... {secs} s (the first start can take a minute or two)")
                    busy = True
            if not busy:
                break
            time.sleep(1.5)
        self.state["done"] = True

    def _tick(self) -> None:
        colors = {"ok": GREEN, "wait": GOLD, "fail": RED, "off": MUTED}
        icons = {"ok": "✔", "wait": "…", "fail": "✖", "off": "–"}
        names = {"ollama": "Ollama (writes scripts)", "comfyui": "ComfyUI (makes pictures)"}
        for key, lab in self.rows.items():
            kind, text = self.state[key]
            lab.setText(f"<span style='color:{colors[kind]}'>{icons[kind]}</span>  "
                        f"<b>{names[key]}</b>: {text}")
        if not self.state["done"]:
            return
        self.timer.stop()
        if all(self.state[k][0] in ("ok", "off") for k in ("ollama", "comfyui")):
            self.accept()
            return
        self.open_btn.setText("Open the Studio")
        self.log_btn.setVisible(self.state["comfyui"][0] == "fail")

    def _show_log(self) -> None:
        self.detail.setVisible(True)
        text = services.log_tail("comfyui.log", 40)
        self.detail.setPlainText(text or "No messages from ComfyUI. Check Settings -> services -> "
                                         "comfyui_command.")
