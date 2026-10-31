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
    assert not sp.creative.style.isVisibleTo(sp) and sp.creative.writer.isVisibleTo(sp)   # style moved to Script
    scp = pages["ScriptPage"]
    scp.creative.style.setCurrentIndex(scp.creative.style.findData("cartoon"))
    assert ep.creative()["style"] == "cartoon" and scp.creative.style.isVisibleTo(scp)
    sp._use(1)
    assert sp.size_text.isVisible() and "work with" in sp.size_text.text()
    assert sp.book_btn.isEnabled() and not sp.book_open.isVisible()
    pipeline.run_now(ep, "book")
    sp.refresh()
    assert sp.book_open.isVisible() and "Draft" in sp.book_state.text()
    sp._book_approve()
    assert "Approved" in sp.book_state.text()

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


def test_write_up_has_lots_of_search_tags_and_upload_is_in_the_browser(app, episode, monkeypatch):
    """Dave (2026-10-30): no Google setup, open YouTube's page; lots of search terms so it's found."""
    from fofstudio.app import youtube_ui
    from fofstudio.youtube import tag_length
    ep = episode
    _finish(ep)
    pipeline.approve(ep, "production")
    pipeline.run_now(ep, "render")
    pipeline.approve(ep, "render")
    pipeline.run_now(ep, "package")
    meta = read_json(ep.path("publish", "metadata.json"))
    tags = meta["tags"]
    assert len(tags) >= 20 and tag_length(tags) <= 500
    assert "was y2k real" in tags and "fact check" in tags and "one" not in tags   # one-word AI junk dropped
    assert "#FactCheck" in meta["description"]
    pipeline.approve(ep, "package")
    with pytest.raises(Exception, match="Upload on YouTube"):
        pipeline.run_now(ep, "upload")
    opened = []
    monkeypatch.setattr(youtube_ui, "_open", lambda url: opened.append(url))
    monkeypatch.setattr(youtube_ui, "reveal", lambda p: opened.append(str(p)))
    k = youtube_ui.PublishKitDialog(ep)
    from PySide6.QtGui import QGuiApplication
    assert any("youtube.com/upload" in u for u in opened)
    assert QGuiApplication.clipboard().text() == meta["title"]          # the title is copied straight away
    k._copy("tags", "Tags")
    assert QGuiApplication.clipboard().text() == ", ".join(tags)
    assert not app.problems, app.problems


def test_tags_are_trimmed_to_youtubes_limit():
    from fofstudio.youtube import sanitize_tags
    assert sanitize_tags(["fact check", "Fact Check", " fact   check "]) == ["fact check"]
    assert sanitize_tags(["<b>owl</b>"]) == ["bowl/b"]
    tags = sanitize_tags(["x" * 120] + [f"tag number {i}" for i in range(60)])
    assert sum(len(t) + (2 if " " in t else 0) for t in tags) + len(tags) - 1 <= 500
    assert all(len(t) <= 100 for t in tags)


def test_long_progress_text_never_pushes_the_bar_off_the_window(app, episode):
    from fofstudio import db
    from fofstudio.app.main import MainWindow
    w = MainWindow()
    w.resize(1280, 800)
    w.show()
    jobs.enqueue(episode.project_id, "selftest")
    db.execute("UPDATE job SET status='running', started_at=?, progress=?, progress_pct=40 WHERE stage='selftest'",
               ("2026-10-24T12:00:00+00:00", "Searching: \"" + "a very long search phrase " * 40 + "\""))
    w.activity.refresh()
    for _ in range(5):
        app.processEvents()
    bar = w.activity.bar
    assert bar.isVisible()
    right = bar.mapTo(w, bar.rect().topRight()).x()
    assert right <= w.width(), (right, w.width())
    from PySide6.QtCore import QTimer
    for t in w.findChildren(QTimer):   # nothing may poll the test database after it's gone
        t.stop()
    w.close()


def test_caricature_box_offers_the_satire_style(app, episode):
    from fofstudio.app.creative import CreativePanel
    episode.set_creative(style="newscast")           # a look that doesn't carry caricatures
    p = CreativePanel()
    p.set_episode(episode)
    assert p.caric.isEnabled() and not p.caric.isChecked()
    p.caric.setChecked(True)          # the test's message boxes answer Yes
    c = episode.creative()
    assert c["style"] == "satire" and c["caricatures"] and p.caric.isChecked()
    assert not app.problems, app.problems
    # the drawn house styles carry caricatures themselves now (Dave: caricatures in the Comic book storyboard)
    episode.set_creative(style="comic", caricatures=True)
    p.set_episode(episode)
    assert episode.creative()["style"] == "comic" and p.caric.isChecked()


def test_a_new_project_starts_with_clean_pages(app, episode):
    """Dave: starting a new project from the Database should clear steps 2 to 8."""
    from fofstudio import subjects
    from fofstudio.app.main import MainWindow
    from fofstudio.episode import Episode, next_id
    from fofstudio.util import write_json
    ep = episode
    research_and_story(ep)
    pipeline.run_now(ep, "script")
    write_json(ep.path("publish", "metadata.json"), {"title": "OLD TITLE", "description": "OLD DESCRIPTION",
                                                     "made_at": "x"})
    write_json(ep.path("publish", "upload.json"), {"youtube_id": "OLDVIDEO", "privacy": "private"})
    w = MainWindow()
    w.show()
    w._fill_picker(ep.project_id)
    pages = {type(p).__name__: p for p in w.pages_and_tools}
    for row in range(1, 8):
        w.nav.setCurrentRow(row)
        app.processEvents()
    pages["ScriptPage"].direction.setText("old notes for the writer")
    assert "OLD TITLE" in pages["PublishPage"].title_edit.text()
    # a new project from the Database page
    b = subjects.breakdown("story", "A-Y2K-FEAR-INDUSTRY")
    new = Episode.create(next_id(), "A brand new job", "A-Y2K-FEAR-INDUSTRY", b["claim_ids"][:1])
    w._chosen(new.project_id, 1)
    for row in range(1, 8):
        w.nav.setCurrentRow(row)
        app.processEvents()
    pub, scr = pages["PublishPage"], pages["ScriptPage"]
    assert pub.title_edit.text() == "" and pub.desc.toPlainText() == "" and "OLDVIDEO" not in pub.uploaded.text()
    assert scr.direction.text() == "" and scr.editor.toPlainText() == ""
    assert pages["StoryboardPage"].summary.text() == "" and pages["VideoPage"].summary.text() == ""
    for k in range(2, 8):   # no step after Research shows as done or waiting for the old job
        assert w.ep.stage_status(["stories", "script", "storyboard", "video", "render", "upload"][k - 2])["status"] \
            == "not_started"
    w.close()
    assert not app.problems, app.problems


def test_browser_upload_window(app, episode, monkeypatch):
    from fofstudio.app import youtube_ui
    from fofstudio.util import read_json, write_json
    opened = []
    monkeypatch.setattr(youtube_ui, "_open", lambda url: opened.append(url))
    monkeypatch.setattr(youtube_ui, "reveal", lambda p: opened.append(str(p)))
    ep = episode
    ep.path("render", "final.mp4").write_bytes(b"x")
    write_json(ep.path("publish", "metadata.json"), {"title": "My title", "description": "My description",
                                                     "tags": ["y2k"], "video": "render/final.mp4", "made_at": "x"})
    k = youtube_ui.PublishKitDialog(ep)
    assert any("youtube.com/upload" in u for u in opened)
    k._copy("title", "Title")
    from PySide6.QtGui import QGuiApplication
    assert QGuiApplication.clipboard().text() == "My title"
    k.link.setText("https://youtu.be/abcDEF12345")
    k._done()
    assert read_json(ep.path("publish", "upload.json"))["youtube_id"] == "abcDEF12345"
    assert not app.problems, app.problems


def test_cast_window_shows_a_kept_caricature(app, episode):
    from PIL import Image

    from fofstudio import cast
    from fofstudio.app.creative import CaricatureLibraryDialog, CastDialog
    ep = episode
    research_and_story(ep)
    ep.set_creative(style="satire", caricatures=True)
    person = cast.eligible(ep)[0]
    Image.new("RGB", (64, 36), "orange").save(ep.path("pick.png"))
    cast.save(person["person_id"], "a stocky man shouting into a huge radio microphone", True,
              tradition="classic_newspaper_editorial_cartoon", ep=ep, picture=ep.path("pick.png"))
    d = CastDialog(ep)
    from PySide6.QtWidgets import QLabel
    texts = " ".join(lab.text() for lab in d.findChildren(QLabel))
    assert "Already approved" in texts
    d._save()                                    # saving unchanged keeps the original approval
    assert cast.record(person["person_id"])["approved_in"] == ep.project_id
    lib = CaricatureLibraryDialog()
    assert "1 approved caricature" in " ".join(lab.text() for lab in lib.findChildren(QLabel))
    assert not app.problems, app.problems


def test_stories_page_scans_and_creates(app, episode, monkeypatch):
    """Dave (2026-10-30): Scan data for stories at the top, pick an idea, choose what to make, Create."""
    from fofstudio.stages import ideas
    from tests.test_pipeline import tick_all
    ep = episode
    pipeline.run_now(ep, "research", {"depth": "quick"})
    tick_all(ep)
    pipeline.approve(ep, "research")
    pipeline.run_now(ep, "ideas")
    from fofstudio.app.main import MainWindow
    w = MainWindow()
    w.show()
    w._fill_picker(ep.project_id)
    page = {type(p).__name__: p for p in w.pages_and_tools}["StoriesPage"]
    page.set_episode(ep)
    page.refresh()
    assert page.scan_btn.isEnabled()
    assert page.ideas.rowCount() == len(ideas.load(ep)) and page.ideas_box.isVisibleTo(page)
    page.ideas.selectRow(0)
    assert page.make_as.currentData() == "clip"          # an info-clip idea defaults to 2 info clips
    started = []
    monkeypatch.setattr(page, "run_stage", lambda stage, opts, label: started.append((stage, opts)))
    page._create_from_idea()
    assert started[0][0] == "stories" and started[0][1]["make"] == "clip"
    page.make_as.setCurrentIndex(page.make_as.findData("book"))
    page._create_from_idea()
    assert started[1][0] == "book" and started[1][1]["idea"]["id"] == "I01"
    w.close()
    assert not app.problems, app.problems


def test_clear_all_and_delete_buttons(app, episode, monkeypatch):
    """Dave (2026-10-30): Clear all on Research; delete a research project on Database → Researched."""
    from fofstudio import cleanup, researched
    from fofstudio.app import common
    ep = episode
    research_and_story(ep)
    from fofstudio.app.main import MainWindow
    w = MainWindow()
    w.show()
    w._fill_picker(ep.project_id)
    pages = {type(p).__name__: p for p in w.pages_and_tools}
    rp = pages["ResearchPage"]
    rp.set_episode(ep)
    monkeypatch.setattr(common, "ask_with_box", lambda *a, **k: (True, True))
    rp._clear_all()
    packet = read_json(ep.path("research.json")) or {}       # the page lists what's on file again, unticked
    assert not packet.get("researched_at") and not any(e["include"] for e in packet.get("evidence", []))
    assert cleanup.agent_finds(ep.claim_ids) == [] and not ep.path("stories.json").exists()
    research_and_story(ep)
    researched.new_video_from(ep.project_id, "evidence")
    dbp = pages["DatabasePage"]
    dbp.set_kind("researched")
    dbp.table.selectRow(0)
    app.processEvents()
    assert dbp.del_project_btn.isEnabled()
    dbp._delete_project()
    assert dbp.table.rowCount() == 0 and w.ep is None
    w.close()
    assert not app.problems, app.problems


def test_style_test_window_starts_over_and_rates(app, episode, monkeypatch):
    from fofstudio import styles
    from fofstudio.app.styletest_ui import StyleTestDialog
    from fofstudio.stages import styletest

    class Page:
        def run_stage(self, *a):
            self.ran = a
    styles.rate("relief_print", "kept")
    d = StyleTestDialog(Page())
    d.group.setCurrentIndex(d.group.findData("all"))
    d._rate("noir", "maybe")
    assert styles.status_of(styles.get("noir")) == "maybe"
    d.group.setCurrentIndex(d.group.findData("maybe"))
    assert [k for _, k in d.boxes] == ["noir"]
    monkeypatch.setattr(styletest, "showcase", lambda k: "x")
    d._reset()
    assert styles.ratings() == {}
    d.boxes[0][0].setChecked(True)
    d._go()
    assert d.page.ran[0] == "styletest"
    assert not app.problems, app.problems
