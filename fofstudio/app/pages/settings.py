"""Settings: Sound (speakers, test, volume, mix) and YouTube (sign in) at the top, then every other
value in settings.toml as a form, plus connection tests."""

from __future__ import annotations

import threading

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QSlider, QSpinBox,
                               QVBoxLayout, QWidget)

from ... import youtube
from ...comfy import Comfy
from ...config import REPO, save_settings, settings, settings_path
from ...llm import Ollama
from ...util import StageError
from .. import sound
from ..common import GOLD, GREEN, MUTED, RED, button, error, info, label, row

HELP = {
    "truth_vlog_research": "Folder with truth-vlog's research CSVs (claims/, sources/...)",
    "writer_model": "Writes scripts and storyboards",
    "checker_model": "A different model, for checks",
    "image_workflow": "ComfyUI API-format workflow with {{PROMPT}} etc.",
    "video_workflow": "Wan 2.2 image-to-video workflow",
    "voice": "Kokoro voice id, e.g. bm_george, bm_fable, am_michael",
}
OWN_PANELS = {"sound", "youtube"}   # these sections have their own panels above the form
MIX = [("speech_db", "Speech", -24, 12), ("music_db", "Music", -40, 6), ("master_db", "Master", -24, 12)]


def _db_slider(lo: int, hi: int, value: float) -> tuple[QSlider, QLabel]:
    sl = QSlider(Qt.Horizontal)
    sl.setRange(lo * 2, hi * 2)
    sl.setValue(int(round(value * 2)))
    lab = QLabel(f"{value:+.1f} dB")
    lab.setMinimumWidth(70)
    sl.valueChanged.connect(lambda v: lab.setText(f"{v / 2:+.1f} dB"))
    return sl, lab


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
        self.tester = sound.Tester(self)
        self._sign_in_result: dict | None = None
        self.lay.addWidget(self._sound_panel())
        self.lay.addWidget(self._youtube_panel())
        self._build()

    # ------------------------------------------------------------ Sound
    def _sound_panel(self) -> QGroupBox:
        cfg = settings()["sound"]
        box = QGroupBox("Sound")
        form = QFormLayout(box)
        self.speaker = QComboBox()
        self.speaker.setMinimumWidth(380)
        refresh = button("Refresh", self._fill_speakers)
        form.addRow("Speakers", row(self.speaker, refresh))
        self.listen, listen_lab = QSlider(Qt.Horizontal), QLabel("")
        self.listen.setRange(0, 100)
        self.listen.setValue(int(cfg["listen_volume"]))
        self.listen.valueChanged.connect(lambda v: listen_lab.setText(f"{v}%"))
        listen_lab.setText(f"{self.listen.value()}%")
        self.listen.setMinimumWidth(260)
        form.addRow("Listening volume", row(self.listen, listen_lab))
        self.test_msg = QLabel("")
        self.test_msg.setWordWrap(True)
        form.addRow("Test", row(button("🔔  Play test sound", self._test_chime, "primary"),
                                button("🦉  Play Owlbert's voice", self._test_voice), self.test_msg))
        hint = label("The listening volume is only how loud things play on this PC. The mix below is baked into "
                     "every new video (each video's own mix is on the Production page).", "muted")
        form.addRow(hint)
        self.mix: dict[str, QSlider] = {}
        for key, name, lo, hi in MIX:
            sl, lab = _db_slider(lo, hi, float(cfg[key]))
            sl.setMinimumWidth(260)
            self.mix[key] = sl
            form.addRow(f"{name} level", row(sl, lab))
        self.normalize = QCheckBox("Make every video equally loud for YouTube")
        self.normalize.setChecked(bool(cfg["normalize_loudness"]))
        self.lufs = QDoubleSpinBox()
        self.lufs.setRange(-30, -6)
        self.lufs.setDecimals(1)
        self.lufs.setSuffix(" LUFS")
        self.lufs.setValue(float(cfg["loudness_lufs"]))
        self.lufs.setToolTip("-14 is what YouTube plays most videos at")
        form.addRow("Loudness", row(self.normalize, self.lufs))
        self.backend = QComboBox()
        for text, key in (("Automatic (recommended)", "auto"), ("FFmpeg", "ffmpeg"), ("Windows Media Foundation", "windows")):
            self.backend.addItem(text, key)
        self.backend.setCurrentIndex(max(0, self.backend.findData(cfg["media_backend"])))
        self.backend.setToolTip("Only change this if the preview still has no sound. Restart the Studio after.")
        form.addRow("Playback engine", self.backend)
        self._fill_speakers()
        sound.watch(self._fill_speakers)
        return box

    def _fill_speakers(self) -> None:
        want = settings()["sound"]["device"] if not self.speaker.count() else self.speaker.currentData()
        self.speaker.blockSignals(True)
        self.speaker.clear()
        default = sound.chosen_device("")
        self.speaker.addItem(f"Windows default ({default.description() or 'none found'})"
                             if sound.audio_enabled() else "Sound is switched off for this run", "")
        for dev in sound.outputs():
            self.speaker.addItem(dev.description(), sound.device_key(dev))
        i = self.speaker.findData(want)
        self.speaker.setCurrentIndex(i if i >= 0 else 0)
        self.speaker.blockSignals(False)
        if want and i < 0:
            self.test_msg.setText(f"<span style='color:{GOLD}'>The speaker you chose isn't plugged in; using "
                                  "Windows' default.</span>")

    def _test_chime(self) -> None:
        self._say(self.tester.play(sound.test_tone(), self.speaker.currentData(), self.listen.value()))

    def _test_voice(self) -> None:
        self._say("Owlbert is warming up his voice...")
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()
        try:
            from ...config import Paths
            from ...stages.narration import synth_line
            path = Paths().root / "sounds" / "owlbert-test.wav"
            if not path.exists():
                synth_line("Hello! I'm Professor Owlbert. If you can hear me, your sound is working. "
                           "Now, let's think this through.", path)
            self._say(self.tester.play(path, self.speaker.currentData(), self.listen.value()))
        except Exception as exc:  # noqa: BLE001 - show it, keep the window going
            self._say(f"<span style='color:{RED}'>Couldn't make Owlbert's voice: {exc}</span>")

    def _say(self, text: str) -> None:
        self.test_msg.setText(text if "<span" in text else f"<span style='color:{GREEN}'>{text}</span>")

    # ------------------------------------------------------------ YouTube
    def _youtube_panel(self) -> QGroupBox:
        cfg = settings()["youtube"]
        box = QGroupBox("YouTube")
        form = QFormLayout(box)
        form.addRow(label("One-time setup (free, about 10 minutes): make a Google Cloud project with the YouTube "
                          "Data API turned on and a 'Desktop app' sign-in client, then choose its file here and sign "
                          "in. The guide walks through every click.", "muted"))
        form.addRow("Guide", row(button("Open the setup guide", self._guide),
                                 button("Open Google Cloud", lambda: QDesktopServices.openUrl(
                                     QUrl("https://console.cloud.google.com/apis/library/youtube.googleapis.com")))))
        self.client_lab = QLabel("")
        form.addRow("1. Client file", row(button("Choose client file...", self._choose_client), self.client_lab))
        self.sign_btn = button("Sign in to YouTube", self._sign_in, "primary")
        self.out_btn = button("Sign out", self._sign_out)
        self.account_lab = QLabel("")
        self.account_lab.setWordWrap(True)
        form.addRow("2. Your channel", row(self.sign_btn, self.out_btn, self.account_lab))
        self.privacy = QComboBox()
        for text, key in (("Private (recommended: check it, then make it public in YouTube Studio)", "private"),
                          ("Unlisted", "unlisted"), ("Public", "public")):
            self.privacy.addItem(text, key)
        self.privacy.setCurrentIndex(max(0, self.privacy.findData(cfg["privacy"])))
        form.addRow("Upload as", self.privacy)
        self.kids = QCheckBox("Made for kids")
        self.kids.setChecked(bool(cfg["made_for_kids"]))
        form.addRow("", self.kids)
        self._show_account()
        return box

    def _guide(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(REPO / "docs" / "YOUTUBE.md")))

    def _choose_client(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose the client file you downloaded from Google Cloud",
                                              "", "Google client file (*.json)")
        if not path:
            return
        try:
            youtube.use_client_file(path)
        except StageError as exc:
            error(self, str(exc))
        self._show_account()

    def _sign_in(self) -> None:
        if not youtube.client_file():
            error(self, "Choose the client file first (step 1).")
            return
        self.sign_btn.setEnabled(False)
        self.sign_btn.setText("Finish signing in in your browser...")
        self.account_lab.setText(f"<span style='color:{GOLD}'>A browser tab opened. Pick the Google account that "
                                 "owns the channel, allow access, then come back here.</span>")
        self._sign_in_result = None

        def work() -> None:
            try:
                self._sign_in_result = {"ok": youtube.sign_in()}
            except Exception as exc:  # noqa: BLE001 - shown on the page
                self._sign_in_result = {"error": str(exc)}
        threading.Thread(target=work, daemon=True).start()
        self._poll = QTimer(self)
        self._poll.timeout.connect(self._sign_in_done)
        self._poll.start(500)

    def _sign_in_done(self) -> None:
        if self._sign_in_result is None:
            return
        self._poll.stop()
        self.sign_btn.setEnabled(True)
        res = self._sign_in_result
        if "error" in res:
            error(self, f"Signing in didn't work:\n{res['error']}")
        self._show_account()

    def _sign_out(self) -> None:
        youtube.sign_out()
        self._show_account()

    def _show_account(self) -> None:
        cf = youtube.client_file()
        self.client_lab.setText(f"<span style='color:{GREEN}'>✔ {cf.name}</span>" if cf else
                                f"<span style='color:{MUTED}'>not chosen yet</span>")
        acct = youtube.account()
        self.sign_btn.setText("Sign in again" if acct else "Sign in to YouTube")
        self.out_btn.setEnabled(bool(acct))
        self.account_lab.setText(f"<span style='color:{GREEN}'>✔ Signed in as <b>{acct['title']}</b></span>"
                                 if acct else f"<span style='color:{MUTED}'>not signed in</span>")

    # ------------------------------------------------------------ everything else
    def _build(self) -> None:
        for section, values in settings().items():
            if section in OWN_PANELS:
                continue
            box = QGroupBox(section)
            form = QFormLayout(box)
            for key, value in values.items():
                if isinstance(value, bool):
                    w = QCheckBox()
                    w.setChecked(value)
                elif isinstance(value, int):
                    w = QSpinBox()
                    w.setRange(-1_000_000, 10_000_000)
                    w.setValue(value)
                elif isinstance(value, float):
                    w = QDoubleSpinBox()
                    w.setDecimals(2)
                    w.setRange(-100000, 100000)
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
        snd = data["sound"]
        old_backend = snd["media_backend"]
        snd["device"] = self.speaker.currentData() or ""
        snd["listen_volume"] = self.listen.value()
        for key, sl in self.mix.items():
            snd[key] = sl.value() / 2
        snd["normalize_loudness"] = self.normalize.isChecked()
        snd["loudness_lufs"] = self.lufs.value()
        snd["media_backend"] = self.backend.currentData()
        data["youtube"]["privacy"] = self.privacy.currentData()
        data["youtube"]["made_for_kids"] = self.kids.isChecked()
        path = save_settings(data)
        # the preview player picks up the new speaker and volume straight away
        win = self.window()
        for page in getattr(win, "pages_and_tools", []):
            if hasattr(page, "player"):
                page.player.refresh_audio()
        extra = ("\n\nRestart the Studio to use the new playback engine." if old_backend != snd["media_backend"] else "")
        info(self, f"Saved {path}{extra}")

    def _ollama(self) -> None:
        info(self, Ollama().health()[1])

    def _comfy(self) -> None:
        info(self, Comfy().health()[1])
