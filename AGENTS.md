# Notes for AI assistants working on this repo

- Read `PROJECT-LOG.md` first; add a dated entry when you finish.
- The editorial rules in `docs/EDITORIAL-RULES.md` outrank everything. Never weaken a check
  to make something pass; if a check is wrong, fix the check and add a test.
- Never add a model or library without checking its licence allows monetized YouTube use in
  the US. Add it to `docs/MODELS.md`.
- Never commit media, models or the data folder. Paths in episode JSON are relative to the
  episode folder.
- A failure must be visible: raise `StageError` with a message Dave can act on. No silent
  fallbacks that pretend to succeed.
- Run `python -m pytest` before committing. Tests fake Ollama, ComfyUI and the voice, and
  use real ffmpeg.
- Dave writes casually. Don't comment on spelling. Explain things in plain words.
