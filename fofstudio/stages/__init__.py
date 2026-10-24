"""The stages, in order. The window's pages group them:
  Database (choose) -> Research -> Stories -> Script -> Storyboard -> Video (instructions, clips)
  -> Production (speech, captions, music, timeline, render) -> Publish (package, upload)
"""

from __future__ import annotations

from . import (captions, lengthscan, music, narration, production, publish, render, research, script, stories,
               storyboard, video)
from .base import Stage

STAGES: list[Stage] = [
    Stage("research", "Research", "ollama", (), research.run, research.check,
          description="Agents gather the proof: database sources, web and archive searches, word-for-word quotes."),
    Stage("stories", "Stories", "ollama", ("research",), stories.run, stories.check,
          description="Three ways to tell it; you pick one or ask for a rewrite."),
    Stage("script", "Script", "ollama", ("stories",), script.run, script.check,
          description="Owlbert's narration, written from the chosen story."),
    Stage("storyboard", "Storyboard", "comfy", ("script",), storyboard.run, storyboard.check,
          description="Three pictures per scene; you pick the ones to use."),
    Stage("video_plan", "Scene instructions", "ollama", ("storyboard",), video.plan, video.check_plan,
          description="How each picture plays out and how it will be made."),
    Stage("video", "Clips", "comfy", ("video_plan",), video.run, video.check,
          description="Every picture becomes a moving clip."),
    Stage("narration", "Speech track", "cpu", ("script",), narration.run, narration.check,
          description="Owlbert reads the script."),
    Stage("captions", "Captions", "cpu", ("narration",), captions.run, captions.check,
          description="Word timings for subtitles."),
    Stage("music", "Music", "comfy", ("script",), music.run, music.check, optional=True,
          description="A quiet music bed (optional)."),
    Stage("production", "Timeline", "cpu", ("video", "narration", "captions", "music"),
          production.run, production.check,
          description="Everything lined up on the editing timeline."),
    Stage("render", "Final video", "ffmpeg", ("production",), render.run, render.check,
          description="The finished YouTube video."),
    Stage("package", "Write-up", "cpu", ("render",), publish.package, publish.check_package,
          description="Title, description with every proof link, chapters, thumbnail."),
    Stage("upload", "Upload", "network", ("package",), publish.upload, publish.check_upload,
          description="Upload to YouTube as private."),
]


def _preview(ctx):
    ctx.options["draft"] = True
    render.run(ctx)


STAGES.append(Stage("preview", "Preview", "ffmpeg", ("video", "narration"), _preview, lambda ep: [],
                    hidden=True, description="A quick low-resolution render to watch while editing."))

def _selftest(ctx):
    """A tiny job that proves the worker picks jobs up (Queue page → Test the worker)."""
    from ..util import utc_now, write_json
    ctx.progress("The worker picked up the test job.", 50)
    write_json(ctx.episode.path("worker-test.json"), {"ok": True, "at": utc_now()})
    ctx.progress("Worker test finished.", 100)


STAGES.append(Stage("selftest", "Worker test", "cpu", (), _selftest, lambda ep: [], hidden=True,
                    description="Checks that the background worker runs jobs."))

STAGES.append(Stage("autopublish", "Automatic upload", "network", (), publish.autopublish, lambda ep: [],
                    hidden=True, description="After a final render: write it up and upload it as private."))

STAGES.append(Stage("scan", "Story scan", "ollama", (), lengthscan.run, lambda ep: [], hidden=True,
                    description="Reads the story and evidence and works out how long the video should be."))

BY_NAME = {s.name: s for s in STAGES}
