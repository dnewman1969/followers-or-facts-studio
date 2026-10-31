"""Starting over (Dave, 2026-10-30): Clear all on the Research page, Delete on Database → Researched."""

import pytest

from fofstudio import cleanup, db, pipeline, researched
from fofstudio.stages import research as rs
from fofstudio.util import StageError, read_json
from tests.test_pipeline import episode, research_and_story  # noqa: F401 - shared fixture


def _db_sources(claim_ids):
    marks = ",".join("?" * len(claim_ids))
    return {r["source_id"] for r in db.rows(f"""SELECT s.source_id FROM source s JOIN claim_source cs
        ON cs.source_id = s.source_id WHERE cs.claim_id IN ({marks}) AND COALESCE(s.found_by,'') != 'agent'""",
                                             tuple(claim_ids))}


def test_clear_all_starts_the_research_over(episode):
    ep = episode
    research_and_story(ep)
    finds = cleanup.agent_finds(ep.claim_ids)
    original = _db_sources(ep.claim_ids)
    assert finds and original and cleanup.research_quotes(ep.claim_ids)
    out = cleanup.clear_research(ep, agent_finds_too=True)
    assert not ep.path("research.json").exists() and not ep.path("stories.json").exists()
    assert ep.stage_status("research")["status"] != "approved" and "Stories" in out["steps"]
    assert out["sources"] == len(finds) and cleanup.agent_finds(ep.claim_ids) == []
    assert cleanup.research_quotes(ep.claim_ids) == 0          # every quote a research run picked is gone too
    assert _db_sources(ep.claim_ids) == original                    # the original database is never touched
    assert rs.build_packet(ep)["evidence"] == []                      # the list starts empty again


def test_each_video_lists_only_its_own_research(episode):
    """Dave (2026-10-31): a new subject's Research page has no old search data in it."""
    from fofstudio.episode import Episode
    ep = episode
    assert rs.prepare(ep)["evidence"] == []                          # nothing before Start research
    research_and_story(ep)
    mine = {e["id"] for e in read_json(ep.path("research.json"))["evidence"]}
    finds = set(cleanup.agent_finds(ep.claim_ids))
    assert finds <= mine and _db_sources(ep.claim_ids) <= mine       # what it found, and the sources on file it read
    other = Episode.create("S01E05", "Another subject on the same claims", None, ep.claim_ids)
    assert rs.prepare(other)["evidence"] == []                       # the first video's finds don't leak in
    pipeline.run_now(other, "research", {"depth": "files"})          # reading only the sources on file
    listed = {e["id"] for e in read_json(other.path("research.json"))["evidence"]}
    assert _db_sources(other.claim_ids) <= listed and not (finds & listed)


def test_clear_all_can_keep_the_agents_finds(episode):
    ep = episode
    research_and_story(ep)
    finds = cleanup.agent_finds(ep.claim_ids)
    cleanup.clear_research(ep, agent_finds_too=False)
    assert cleanup.agent_finds(ep.claim_ids) == finds and not ep.path("research.json").exists()


def test_delete_a_research_project_and_start_over(episode):
    ep = episode
    research_and_story(ep)
    second = researched.new_video_from(ep.project_id, "evidence")
    kind, sid = researched.subject_of(db.one("SELECT * FROM project WHERE project_id=?", (ep.project_id,)))
    assert len(researched.videos_for(kind, sid)) == 2
    folders = [ep.folder, second.folder]
    db.execute("INSERT INTO job(project_id, stage, status, created_at) VALUES (?, 'stories', 'running', 'now')",
               (second.project_id,))
    with pytest.raises(StageError, match="busy"):
        cleanup.delete_research_project(kind, sid)                 # a working video has to be stopped first
    db.execute("UPDATE job SET status='cancelled' WHERE project_id=?", (second.project_id,))
    out = cleanup.delete_research_project(kind, sid, agent_finds_too=True)
    assert sorted(out["videos"]) == sorted([ep.project_id, second.project_id])
    assert not any(f.exists() for f in folders)
    assert researched.listing() == [] and not db.rows("SELECT * FROM project")
    from fofstudio import subjects
    assert subjects.breakdown(kind, sid)["claims"]                  # the subject is still there to research again


def test_delete_one_video(episode):
    ep = episode
    research_and_story(ep)
    second = researched.new_video_from(ep.project_id, "story")
    cleanup.delete_video(second.project_id)
    assert not second.folder.exists() and read_json(ep.path("research.json"))
    assert [r["project_id"] for r in db.rows("SELECT project_id FROM project")] == [ep.project_id]
