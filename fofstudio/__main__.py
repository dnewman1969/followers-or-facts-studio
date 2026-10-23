"""Command line. Everything the window does can also be done from here.

    python -m fofstudio app                      open the window (default)
    python -m fofstudio init                     create the data folder, settings and database
    python -m fofstudio doctor                   check Ollama, ComfyUI, ffmpeg, models
    python -m fofstudio download-models          fetch the Kokoro voice (~340 MB)
    python -m fofstudio import-research [DIR]    (re)import truth-vlog's research CSVs
    python -m fofstudio validate                 check the research database
    python -m fofstudio arcs                     arcs ranked by how well sourced they are
    python -m fofstudio new S01E01 "Title" --arc A-Y2K-FEAR-INDUSTRY
    python -m fofstudio status S01E01
    python -m fofstudio run S01E01 script        run one stage right here and wait
    python -m fofstudio queue S01E01 images      hand a stage to the background worker
    python -m fofstudio check|approve|skip|reject S01E01 <stage>
    python -m fofstudio worker                   run the background worker
"""

from __future__ import annotations

import argparse
import json
import sys

from . import APP_NAME, __version__


def _ep(pid: str):
    from .episode import Episode
    return Episode.load(pid)


def cmd_init(a) -> None:
    from . import db
    from .config import DEFAULTS, Paths, save_settings, settings_path
    from .db import importer
    paths = Paths().ensure()
    if not settings_path().exists():
        save_settings(DEFAULTS)
        print(f"Wrote settings: {settings_path()}")
    db.init()
    if db.is_empty():
        report = importer.import_research()
        print(f"Imported research from {report['source']}: {report['counts']}")
        for f in report["fixes"]:
            print("  fixed:", f)
    print(f"Data folder ready: {paths.root}")


def cmd_doctor(a) -> None:
    import shutil
    from .comfy import Comfy, load_workflow
    from .config import Paths, settings
    from .llm import Ollama
    ok = True

    def line(good: bool, text: str) -> None:
        nonlocal ok
        ok &= good
        print(("  OK   " if good else "  !!   ") + text)

    s = settings()
    print(f"{APP_NAME} {__version__}  data: {Paths().root}")
    line(Paths().db.exists(), f"database {Paths().db}")
    line(*Ollama().health())
    good, msg = Comfy().health()
    line(good, msg)
    line(bool(shutil.which(s["paths"]["ffmpeg"])), f"ffmpeg ({s['paths']['ffmpeg']})")
    for key in ("image_workflow", "video_workflow", "music_workflow"):
        try:
            load_workflow(key)
            line(True, f"workflow {s['comfyui'][key]}")
        except Exception as exc:  # noqa: BLE001
            line(False, str(exc))
    k = Paths().models / "kokoro" / "kokoro-v1.0.onnx"
    line(k.exists(), f"Kokoro voice model ({k})")
    try:
        import kokoro_onnx  # noqa: F401
        line(True, "kokoro-onnx installed")
    except ImportError:
        line(False, "kokoro-onnx not installed (pip install kokoro-onnx)")
    try:
        import faster_whisper  # noqa: F401
        line(True, "faster-whisper installed (exact caption timing)")
    except ImportError:
        print("  --   faster-whisper not installed (captions will be estimated)")
    from .media import encoder
    try:
        line(True, f"video encoder: {encoder(s['video']['encoder'])['name']}")
    except Exception as exc:  # noqa: BLE001
        line(False, str(exc))
    print("\nAll good." if ok else "\nFix the !! lines (see docs/SETUP.md).")


def cmd_download_models(a) -> None:
    import os
    from .engines.tts import download_kokoro
    for p in download_kokoro():
        print("  have", p)
    if os.name == "nt":
        from .owl import download_rhubarb
        try:
            print("  have", download_rhubarb())
        except Exception as exc:  # noqa: BLE001 - Owlbert still talks without it
            print("  Rhubarb Lip Sync couldn't be downloaded:", exc)


def cmd_import(a) -> None:
    from .db import importer
    report = importer.import_research(a.dir)
    print(json.dumps(report["counts"], indent=1))
    for f in report["fixes"]:
        print("fixed:", f)
    for w in report["warnings"]:
        print("warning:", w)


def cmd_validate(a) -> None:
    from .db.validate import validate
    result = validate()
    for e in result["errors"]:
        print("ERROR  ", e)
    for w in result["warnings"]:
        print("warning", w)
    print(f"{len(result['errors'])} errors, {len(result['warnings'])} warnings")
    sys.exit(1 if result["errors"] else 0)


def cmd_arcs(a) -> None:
    from . import db
    for r in db.rows("SELECT * FROM arc_strength ORDER BY sourced_claims DESC, claims DESC LIMIT ?",
                     (a.limit,)):
        careful = "  [careful]" if r["careful"] else ""
        print(f"{r['arc_id']:<32} {r['sourced_claims']:>3}/{r['claims']:<3} sourced  "
              f"{r['title']}{careful}")


def cmd_new(a) -> None:
    from .episode import Episode
    ep = Episode.create(a.id, a.title, a.arc, a.claims.split(",") if a.claims else None)
    print(f"Created {ep.project_id} with {len(ep.claim_ids)} claims at {ep.folder}")


def cmd_status(a) -> None:
    from . import pipeline
    ep = _ep(a.id)
    print(f"{ep.project_id}  {ep.title}\n{ep.folder}")
    for s in pipeline.overview(ep):
        extra = " (skipped)" if s["skipped"] else ""
        print(f"  {s['label']:<12} {s['status']}{extra}  {s['note'][:80]}")


def cmd_run(a) -> None:
    from . import pipeline
    ep = _ep(a.id)
    opts = json.loads(a.options) if a.options else {}
    results = pipeline.run_now(ep, a.stage, opts, progress=lambda t, p=None: print("  ..", t, f"({p:.0f}%)" if p is not None else ""))
    for c in results:
        print(f"  [{c.level}] {c.message}")


def cmd_queue(a) -> None:
    from . import jobs
    job = jobs.enqueue(a.id, a.stage, json.loads(a.options) if a.options else {})
    pid = jobs.start_worker()
    print(f"Queued job {job}; worker pid {pid}")


def cmd_check(a) -> None:
    from . import pipeline
    for c in pipeline.checks(_ep(a.id), a.stage):
        print(f"  [{c.level}] {c.message}")


def cmd_approve(a) -> None:
    from . import pipeline
    pipeline.approve(_ep(a.id), a.stage, a.note or "")
    print(f"Approved {a.stage}.")


def cmd_skip(a) -> None:
    from . import pipeline
    pipeline.skip(_ep(a.id), a.stage, a.note or "")
    print(f"Skipped {a.stage}.")


def cmd_reject(a) -> None:
    from . import pipeline
    pipeline.reject(_ep(a.id), a.stage, a.note or "")
    print(f"Rejected {a.stage}.")


def cmd_worker(a) -> None:
    from .jobs import worker_loop
    worker_loop(once=a.once)


def cmd_app(a) -> None:
    from .app.main import main
    main()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="fofstudio", description=APP_NAME)
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("app").set_defaults(fn=cmd_app)
    sub.add_parser("init").set_defaults(fn=cmd_init)
    sub.add_parser("doctor").set_defaults(fn=cmd_doctor)
    sub.add_parser("download-models").set_defaults(fn=cmd_download_models)
    s = sub.add_parser("import-research")
    s.add_argument("dir", nargs="?")
    s.set_defaults(fn=cmd_import)
    sub.add_parser("validate").set_defaults(fn=cmd_validate)
    s = sub.add_parser("arcs")
    s.add_argument("--limit", type=int, default=25)
    s.set_defaults(fn=cmd_arcs)
    s = sub.add_parser("new")
    s.add_argument("id")
    s.add_argument("title")
    s.add_argument("--arc")
    s.add_argument("--claims", help="comma-separated claim IDs (default: all claims in the arc)")
    s.set_defaults(fn=cmd_new)
    s = sub.add_parser("status")
    s.add_argument("id")
    s.set_defaults(fn=cmd_status)
    for name, fn in (("run", cmd_run), ("queue", cmd_queue)):
        s = sub.add_parser(name)
        s.add_argument("id")
        s.add_argument("stage")
        s.add_argument("--options", help='JSON, e.g. {"minutes": 8}')
        s.set_defaults(fn=fn)
    for name, fn in (("check", cmd_check), ("approve", cmd_approve), ("skip", cmd_skip),
                     ("reject", cmd_reject)):
        s = sub.add_parser(name)
        s.add_argument("id")
        s.add_argument("stage")
        s.add_argument("--note")
        s.set_defaults(fn=fn)
    s = sub.add_parser("worker")
    s.add_argument("--once", action="store_true")
    s.set_defaults(fn=cmd_worker)
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    fn = getattr(args, "fn", cmd_app)
    from .util import StageError
    try:
        fn(args)
    except (StageError, KeyError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
