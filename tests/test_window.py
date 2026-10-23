"""Open the whole window on a finished test episode and press things on every page, so mistakes in the
window code show up here instead of on Dave's PC."""

import os
import sys

import pytest

from fofstudio import jobs, pipeline
from fofstudio.stages import production, storyboard, video
from fofstudio.util import read_json
from tests.test_pipeline import episode, research_and_story  # noqa: F401 - shared fixture


@pytest.fixture()
def app(monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("FOF_NO_AUDIO", "1")
    from PySide6.QtWidgets import QApplication, QMessageBox
    a = QApplication.instance() or QApplication(sys.argv)
    # answer every "are you sure?" with Yes and swallow info boxes, so nothing waits for a click
    problems = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: problems.append(a[2] if len(a) > 2 else a))
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: problems.append(a[2] if len(a) > 2 else a))
    # errors raised inside Qt signal handlers go to sys.excepthook instead of failing the test
    monkeypatch.setattr(sys, "excepthook", lambda kind, value, tb: problems.append(f"{kind.__name__}: {value}"))
    monkeypatch.setattr(jobs, "start_worker", lambda force=False: 0)   # jobs are run by hand below
    a.problems = problems
    return a


def _finish(ep):
    research_and_story(ep)
    for st in ("script",):
        pipeline.run_now(ep, st)
        pipeline.approve(ep, st)
    pipeline.run_now(ep, "storyboard")
    pipeline.approve(ep, "storyboard")
    pipeline.run_now(ep, "video_plan")
    pipeline.approve(ep, "video_plan")
    for s in video.load_plan(ep)["shots"]:
        video.update_shot(ep, s["shot_id"], method="camera_move")
    pipeline.run_now(ep, "video")
    for s in video.load_plan(ep)["shots"]:
        video.update_shot(ep, s["shot_id"], approved=True)
    pipeline.approve(ep, "video")
    for st in ("narration", "captions"):
        pipeline.run_now(ep, st)
        pipeline.approve(ep, st)
    pipeline.skip(ep, "music")
    pipeline.run_now(ep, "production")


def test_every_page_opens_and_reacts(app, episode):
    ep = episode
    _finish(ep)
    from fofstudio.app.main import MainWindow
    w = MainWindow()
    w.show()
    w._fill_picker(ep.project_id)
    for row in range(w.nav.count()):
        w.nav.setCurrentRow(row)
        app.processEvents()
        page = w.stack.currentWidget()
        if hasattr(page, "poll"):
            page.poll()
    pages = {type(p).__name__: p for p in w.pages_and_tools}

    db_page = pages["DatabasePage"]
    for kind in ("story", "conspiracy", "person", "org", "researched"):
        db_page.set_kind(kind)
        db_page.table.selectRow(0)
        app.processEvents()

    rp = pages["ResearchPage"]
    w.nav.setCurrentRow(1)
    rp.search.setText("y2k")
    rp.show_what.setCurrentIndex(2)
    rp.table.selectRow(0)
    rp.show_what.setCurrentIndex(0)
    rp.search.setText("")

    sp = pages["StoriesPage"]
    w.nav.setCurrentRow(2)
    sp.creative.style.setCurrentIndex(sp.creative.style.findData("cartoon"))
    assert ep.creative()["style"] == "cartoon"
    sp._use(1)

    sb = pages["StoryboardPage"]
    w.nav.setCurrentRow(4)
    first = ep.storyboard()["scenes"][0]["shots"][0]
    storyboard.set_pick(ep, first["shot_id"], 1)
    sb.force_refresh()
    app.processEvents()

    pp = pages["ProductionPage"]
    w.nav.setCurrentRow(6)
    pp.refresh()
    pp.editor.set_zoom(50)
    pp.editor.slider.setValue(800)
    pp.editor.fit()
    sl, _ = pp.mix_sliders["music_db"]
    sl.setValue(-40)
    pp._mix_changed()
    pp._save()
    assert production.load(ep)["mix"]["music_db"] == -20.0

    # Clear on the Storyboard page starts pictures over and leaves the script alone
    w.nav.setCurrentRow(4)
    sb._clear_clicked()
    assert not ep.storyboard() and ep.path("script.md").exists()
    assert ep.stage_status("storyboard")["status"] == "not_started"
    for row in range(w.nav.count()):   # every page still opens after a clear
        w.nav.setCurrentRow(row)
        app.processEvents()
    w.close()
    assert not app.problems, app.problems


def test_queue_page_and_worker_test_button(app, episode):
    from fofstudio.app.pages.queue import QueuePage
    q = QueuePage()
    q.refresh()
    q._selftest()
    assert any(j["stage"] == "selftest" and j["status"] == "queued" for j in jobs.jobs())
    jobs.worker_loop(once=True, in_app=True)
    q.refresh()
    assert any(j["stage"] == "selftest" and j["status"] == "done" for j in jobs.jobs())
    assert not app.problems, app.problems


def test_render_is_uploaded_privately_with_a_studio_link(app, episode, monkeypatch):
    """Google's uploader idea, our way: after a final render, write it up and upload it PRIVATE."""
    from fofstudio import youtube
    from fofstudio.stages import publish
    ep = episode
    _finish(ep)
    pipeline.approve(ep, "production")
    pipeline.run_now(ep, "render")
    sent = {}

    class Req:
        def __init__(self, result):
            self.result = result

        def next_chunk(self):
            return None, self.result

        def execute(self):
            return {}

    class Fake:
        def videos(self):
            return self

        def insert(self, part, body, media_body, notifySubscribers):  # noqa: N803 - YouTube's name
            sent.update(body=body, notify=notifySubscribers)
            return Req({"id": "abc123"})

        def thumbnails(self):
            return self

        def set(self, videoId, media_body):  # noqa: N803
            sent["thumb"] = True
            return Req({})

        def captions(self):
            return self
    monkeypatch.setattr(publish, "_youtube", lambda: Fake())
    monkeypatch.setattr(youtube, "account", lambda: {"title": "Followers or Facts", "channel_id": "UC1"})
    pipeline.run_now(ep, "autopublish")
    body = sent["body"]
    assert body["status"]["privacyStatus"] == "private" and body["status"]["containsSyntheticMedia"]
    assert sent["notify"] is False and sent["thumb"]
    tags = body["snippet"]["tags"]
    assert "critical thinking" in tags and sum(len(t) for t in tags) + len(tags) <= 500
    up = read_json(ep.path("publish", "upload.json"))
    assert up["studio_url"] == "https://studio.youtube.com/video/abc123/edit" and up["privacy"] == "private"
    assert ep.stage_status("upload")["status"] == "awaiting_approval"


def test_tags_are_trimmed_to_youtubes_limit():
    from fofstudio.youtube import sanitize_tags
    assert sanitize_tags(["fact check", "Fact Check", " fact   check "]) == ["fact check"]
    assert sanitize_tags(["<b>owl</b>"]) == ["bowl/b"]
    tags = sanitize_tags(["x" * 120] + [f"tag number {i}" for i in range(60)])
    assert sum(len(t) + (2 if " " in t else 0) for t in tags) + len(tags) - 1 <= 500
    assert all(len(t) <= 100 for t in tags)
