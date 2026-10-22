"""The eleven stages, in order."""

from __future__ import annotations

from . import captions, images, music, narration, publish, render, research, script, storyboard, video
from .base import Stage

STAGES: list[Stage] = [
    Stage("research", "Research", "ollama", (), research.run, research.check,
          description="Pull claims and sources from the database, save source copies, find verified quotes."),
    Stage("script", "Script", "ollama", ("research",), script.run, script.check,
          description="Local AI drafts the script from the research only; you edit script.md."),
    Stage("storyboard", "Storyboard", "ollama", ("script",), storyboard.run, storyboard.check,
          description="Break every scene into shots: AI pictures, quote cards, titles, receipts."),
    Stage("narration", "Narration", "cpu", ("script",), narration.run, narration.check,
          description="Read every scene aloud with the chosen voice."),
    Stage("images", "Images", "comfy", ("storyboard",), images.run, images.check,
          description="Make every picture: ComfyUI for AI shots, cards drawn locally."),
    Stage("video", "Animation", "comfy", ("images",), video.run, video.check, optional=True,
          description="Animate the chosen shots with Wan 2.2 (slow; skip for stills only)."),
    Stage("captions", "Captions", "cpu", ("narration",), captions.run, captions.check,
          description="Time every word for subtitles."),
    Stage("music", "Music", "comfy", ("script",), music.run, music.check, optional=True,
          description="Make or pick a music bed (skip for voice only)."),
    Stage("render", "Render", "ffmpeg", ("images", "narration", "captions", "video", "music"),
          render.run, render.check,
          description="Assemble everything into the finished video."),
    Stage("package", "Package", "cpu", ("render",), publish.package, publish.check_package,
          description="Title, description with sources and credit, chapters, thumbnail."),
    Stage("upload", "Upload", "network", ("package",), publish.upload, publish.check_upload,
          description="Upload to YouTube as private."),
]

BY_NAME = {s.name: s for s in STAGES}
