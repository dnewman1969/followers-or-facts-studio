import os
import sys

from fofstudio import config, services


def _set(**paths):
    s = config.settings()
    for key, value in paths.items():
        section, name = key.split("__")
        s[section][name] = value


def test_finds_git_install_with_venv(data, tmp_path):
    comfy = tmp_path / "ComfyUI"
    (comfy / "venv" / "Scripts").mkdir(parents=True)
    (comfy / "venv" / "bin").mkdir(parents=True)
    (comfy / "main.py").write_text("")
    (comfy / "venv" / "Scripts" / "python.exe").write_text("")
    (comfy / "venv" / "bin" / "python").write_text("")
    _set(paths__comfyui_dir=str(comfy), services__comfyui_command="")
    cmd, where = services.find_comfyui()
    assert cmd[1].endswith("main.py") and "--port" in cmd and "--disable-auto-launch" in cmd
    assert where == comfy


def test_finds_portable_build(data, tmp_path):
    root = tmp_path / "ComfyUI_windows_portable"
    (root / "ComfyUI").mkdir(parents=True)
    (root / "python_embeded").mkdir()
    (root / "ComfyUI" / "main.py").write_text("")
    (root / "python_embeded" / "python.exe").write_text("")
    _set(paths__comfyui_dir=str(root / "ComfyUI"), services__comfyui_command="")
    cmd, _ = services.find_comfyui()
    assert "python_embeded" in cmd[0]


def test_custom_command_wins(data, tmp_path):
    _set(services__comfyui_command='"F:/AI/ComfyUI/run_nvidia_gpu.bat"')
    cmd, _ = services.find_comfyui()
    assert cmd == ["F:/AI/ComfyUI/run_nvidia_gpu.bat"]


def test_missing_comfyui_says_what_to_do(data, tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(services.shutil, "which", lambda name: None)
    _set(paths__comfyui_dir=str(tmp_path / "nowhere"), services__comfyui_command="")
    cmd, reason = services.find_comfyui()
    assert cmd is None and "comfyui_command" in reason


def test_startup_window_opens_studio_when_both_are_running(data, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    monkeypatch.setattr(services, "ollama_up", lambda: True)
    monkeypatch.setattr(services, "comfy_url_up", lambda: "http://127.0.0.1:8188")
    from fofstudio.app.startup import Startup
    dlg = Startup()
    assert dlg.exec() == 1  # accepted on its own, no click needed


def test_data_dir_file_written_by_powershell(tmp_path, monkeypatch):
    """Windows PowerShell 5 writes UTF-8 with a BOM; the path must still be read cleanly."""
    monkeypatch.delenv("FOF_DATA", raising=False)
    pointer = tmp_path / "config" / "data-dir.txt"
    pointer.parent.mkdir()
    pointer.write_bytes("\ufeffF:\\AI\\fof-data\r\n".encode("utf-8"))
    monkeypatch.setattr(config, "REPO", tmp_path)
    assert str(config.data_dir()) == "F:\\AI\\fof-data"
