"""A whole episode, Database choice to packaged video, with fake AI services (ffmpeg is real)."""

import pytest

from fofstudio import media, pipeline, researched, scriptfmt, subjects
from fofstudio.agents import search, web
from fofstudio.episode import Episode
from fofstudio.llm import Ollama
from fofstudio.stages import production, research as rs, script as script_stage, stories, storyboard, video
from fofstudio.util import StageError, read_json

FOUND_URL = "https://www.courtlistener.com/opinion/123/test-v-jones/"
FOUND_TEXT = ("Background. The court finds that the defendant sold survival supplies while telling "
              "listeners the grid would fail. The jury awarded damages to the families.")


def fake_llm(get_packet):
    def chat_json(self, messages, schema, model=None, **kw):
        props = schema["properties"]
        if "summary" in props and len(props) == 1:
            return {"summary": "A court ruling. It says the defendant sold survival supplies."}
        if "queries" in props:
            return {"queries": ["survival supplies court ruling", "y2k radio fear"]}
        if "excerpts" in props:
            text = messages[-1]["content"]
            if "survival supplies" in text:
                return {"excerpts": [{"quote": "The court finds that the defendant sold survival supplies "
                                               "while telling listeners the grid would fail.",
                                      "supports": "who profited"},
                                     {"quote": "The court found he was a great man.", "supports": "made up"}]}
            return {"excerpts": []}
        if "beats" in props:
            ev = [e["id"] for e in get_packet()["evidence"]][:2]
            return {"title": "The Y2K Fear Machine", "logline": "A real bug, sold as doom.", "angle": "money",
                    "opening_hook": "Midnight, 1999.", "owl_moments": ["opens at his desk"],
                    "techniques": ["fear", "not-a-real-trick"], "thumbnail_words": "fear for sale, folks",
                    "beats": [{"role": r, "beat": f"The {r} beat.", "evidence_ids": ev + ["E-MADE-UP"]}
                              for r in ("intro", "claim", "record", "benefit", "harm", "verdict")]}
        if "central_question" in props:   # the script outline
            claims = get_packet()["claims"]
            scenes = []
            for role, c in zip(["intro", "claim", "record", "benefit", "harm", "tell", "toolkit", "verdict"],
                               (claims * 8)[:8]):
                facts = role not in ("intro", "verdict", "toolkit", "tell")
                prim = [x["source_id"] for x in c["sources"] if x["is_primary"]][:2]
                scenes.append({"role": role, "purpose": f"the {role}", "link": "therefore",
                               "claim_ids": [c["claim_id"]] if facts else [], "source_ids": prim if facts else [],
                               "excerpt_ids": [], "owl_on_camera": role == "intro",
                               "visual_idea": "An old desk with a newspaper and a clock"})
            return {"title": "The Y2K Fear Machine", "central_question": "Who sold the fear?", "scenes": scenes}
        if "narration" in props and "visual" in props:   # one scene
            text = messages[-1]["content"]
            import json as _j
            import re as _re
            m = _re.search(r"about (\d+) words", text)
            target = int(m.group(1)) if m else 40
            facts = text.split("Facts for this scene:\n", 1)[-1] if "Facts for this scene:" in text else \
                text.split("Facts:\n", 1)[-1]
            try:
                fl = _j.loads(facts)
            except ValueError:
                fl = []
            cids = [fl[0]["claim_id"]] if fl else []
            sids = [x["source_id"] for x in fl[0]["sources"]][:2] if fl else []
            sentence = "People were scared, and someone sold that fear for money. "
            words = (sentence * (target // 10 + 1)).split()[:target]
            role_m = _re.search(r"Role: (\w+)\.", text)
            role = role_m.group(1) if role_m else "record"
            # the writer directs the music and Owlbert too (some of it breaks the rules on purpose)
            music = {"intro": ("curious", 4, "crossfade"), "claim": ("tense", 5, "crossfade"),
                     "record": ("investigative", 2, "crossfade"), "benefit": ("investigative", 2, "continue"),
                     "harm": ("playful", 2, "crossfade"), "tell": ("playful", 4, "sting"),
                     "toolkit": ("encouraging", 3, "crossfade"), "verdict": ("resolved", 3, "crossfade")}
            mood, energy, change = music.get(role, ("investigative", 2, "continue"))
            moves = {"intro": [{"move": "fly_in", "prop": "", "at": ""}],
                     "record": [{"move": "hat_trick", "prop": "document", "at": "someone sold that fear"},
                                {"move": "point", "prop": "", "at": "not in the narration at all"}],
                     "harm": [{"move": "surprised", "prop": "", "at": "People were scared"},
                              {"move": "solemn", "prop": "", "at": "People were scared"}],
                     "tell": [{"move": "hat_trick", "prop": "card", "at": "sold that fear"}],
                     "verdict": [{"move": "stamp", "prop": "", "at": "for money"},
                                 {"move": "fly_in", "prop": "", "at": ""}]}.get(role, [])
            return {"narration": "This part is short and plain. " + " ".join(words),
                    "visual": "An old desk with a newspaper and a clock",
                    "on_screen_text": "December 31, 1999" if not cids else "",
                    "claim_ids": cids, "source_ids": sids, "excerpt_ids": [],
                    "music": {"mood": mood, "energy": energy, "change": change, "drop_before": "",
                              "sting_at": "sold that fear" if change == "sting" else ""},
                    "owlbert": moves}
        if "shots" in props:   # storyboard shot ideas
            n = props["shots"].get("minItems", 3)
            kinds = props["shots"]["items"]["properties"]["kind"]["enum"]
            return {"shots": [{"kind": kinds[i % len(kinds)], "idea": f"shot idea {i} {messages[-1]['content'][-30:]}",
                               "person_id": ""} for i in range(n)]}
        if "tricks_taught" in props:   # the length scan
            claims = get_packet()["claims"]
            return {"claims": [{"claim_id": c["claim_id"], "complexity": "some explaining", "why": "a timeline"}
                               for c in claims],
                    "timeline_events_explained": 4, "timeline_events_mentioned": 6, "people_introduced": 3,
                    "tricks_taught": 1, "steelman": False, "pad_risk": "low", "split_risk": "low",
                    "reasons": ["three claims with court records"], "if_shorter": ["drop the 1997 radio show"],
                    "if_longer": ["the 2000 follow-up broadcast"]}
        if "threads" in props:   # the story size check
            claims = get_packet()["claims"]
            return {"claims": [{"claim_id": c["claim_id"], "complexity": "some explaining"} for c in claims],
                    "timeline_events": 5, "people_and_groups": 2, "threads": 1,
                    "reasons": ["one claim with a court record"], "parts": [{"title": "All of it", "claim_ids":
                                                                            [c["claim_id"] for c in claims] + ["C-NOPE"]}]}
        if "subtitle" in props:   # the book's chapter plan
            ev = props["chapters"]["items"]["properties"]["evidence_ids"]["items"]["enum"]
            cl = props["chapters"]["items"]["properties"]["claim_ids"]["items"]["enum"]
            return {"title": "The Y2K Fear Machine", "subtitle": "How a real bug was sold as doom",
                    "chapters": [{"part": "verdict", "title": "What we know", "purpose": "the verdict",
                                  "claim_ids": cl, "evidence_ids": ev[:1]},
                                 {"part": "origin", "title": "A real bug", "purpose": "where it started",
                                  "claim_ids": cl + ["C-MADE-UP"], "evidence_ids": ["E-MADE-UP"]},
                                 {"part": "nonsense", "title": "Bad part", "purpose": "", "claim_ids": [],
                                  "evidence_ids": []},
                                 {"part": "damage", "title": "Who paid", "purpose": "the damage", "claim_ids": cl,
                                  "evidence_ids": ev[:2]}]}
        if "paragraphs" in props:   # one book chapter
            item = props["paragraphs"]["items"]["properties"]
            cites = [c for c in item["cites"]["items"]["enum"] if not c.startswith("T-")]
            quotes = [q for q in item["quote_after"]["enum"] if q]
            fixing = "found problems" in messages[-1]["content"]
            return {"paragraphs": [
                {"heading": "The court", "text": "A court looked at what was sold and why.", "cites": cites[:1],
                 "quote_after": quotes[0] if quotes else ""},
                {"heading": "", "text": "In 1987 he sold 4,000 radios.", "cites": cites[:1], "quote_after": ""},
                {"heading": "", "text": ("The court said he sold survival supplies to scared people."
                                         if fixing else "The court called it \"a fraud from start to finish\"."),
                 "cites": cites[:1], "quote_after": ""},
                {"heading": "", "text": "Listeners trusted Gary Northman and his radio show.", "cites": cites[:1],
                 "quote_after": "E-MADE-UP"},
            ]}
        if "how_it_plays" in props:
            return {"how_it_plays": "The camera drifts toward the clock.", "motion_prompt": "slow push in",
                    "camera": "zoom_in", "seconds": 4}
        raise AssertionError(schema)
    return chat_json


@pytest.fixture()
def episode(data, fakes):
    b = subjects.breakdown("story", "A-Y2K-FEAR-INDUSTRY")
    ep = Episode.create("S01E01", b["title"], "A-Y2K-FEAR-INDUSTRY", b["claim_ids"])
    ep.set_creative(minutes=1.5)   # short, so the tests run fast
    fakes.setattr(Ollama, "chat_json", fake_llm(lambda: read_json(ep.path("research.json"))))
    fakes.setattr(search, "search_all", lambda q: [{"title": "Test v. Jones", "url": FOUND_URL, "snippet": "",
                                                     "finder": "courtlistener"}])
    fakes.setattr(web, "fetch", lambda url, timeout=40: (
        web._store(url, url, 200, "text/html", f"<html><body><p>{FOUND_TEXT}</p></body></html>".encode(), "web")
        if url == FOUND_URL else {"ok": False, "url": url, "error": "offline in tests"}))
    fakes.setattr(web, "fetch_via_wayback", lambda url: {"ok": False, "url": url, "error": "offline"})
    fakes.setattr(web, "save_page_now", lambda url: "https://web.archive.org/web/2026/" + url)
    fakes.setattr(web, "wayback_closest", lambda url, timestamp=None: None)
    from fofstudio import sources
    fakes.setattr(sources, "fetch_source", lambda sid, refresh=False: {"source_id": sid, "ok": False,
                                                                        "error": "offline in tests"})
    return ep


def tick_all(ep):
    rs.set_include(ep, [e["id"] for e in read_json(ep.path("research.json"))["evidence"]], True)


def research_and_story(ep):
    pipeline.run_now(ep, "research", {"depth": "quick"})
    with pytest.raises(StageError, match="Nothing is ticked"):
        pipeline.approve(ep, "research")
    tick_all(ep)
    pipeline.approve(ep, "research")
    pipeline.run_now(ep, "stories")
    with pytest.raises(StageError, match="Pick one"):
        pipeline.approve(ep, "stories")
    stories.choose(ep, 1)
    pipeline.approve(ep, "stories")


def test_full_episode(episode):
    ep = episode
    research_and_story(ep)
    packet = read_json(ep.path("research.json"))
    found = [e for e in packet["evidence"] if e.get("found_by") == "agent"]
    assert found and found[0]["type"] == "court" and found[0]["archive_url"].startswith("https://web.archive.org")
    # the agent's made-up quote was thrown away; the real one kept
    quotes = [e["quote"] for e in packet["evidence"] if e["kind"] == "quote"]
    assert any("survival supplies" in q for q in quotes) and not any("great man" in q for q in quotes)
    # a made-up evidence ID in a story beat is dropped
    assert all("E-MADE-UP" not in b["evidence_ids"] for b in stories.chosen(ep)["beats"])

    pipeline.run_now(ep, "script")
    pipeline.approve(ep, "script")
    pipeline.run_now(ep, "storyboard")
    board = ep.storyboard()
    assert board["version"] == 2
    for s in board["scenes"]:
        # enough shots to cover the narration at the style's shot length, two versions of each
        from fofstudio import styles
        st = styles.get(board["style"])
        assert len(s["shots"]) >= max(1, int((s["seconds"] - 6) / st.shot_seconds))
        assert all(len([c for c in sh["candidates"] if c]) == 2 for sh in s["shots"])
    tell = [c for s in board["scenes"] for c in s["cards"] if c["type"] == "technique_card"]
    assert tell, "the 'tell' scene gets Owlbert's Tell card"
    first = board["scenes"][1]["shots"][0]["shot_id"]
    storyboard.set_pick(ep, first, 1)
    pipeline.approve(ep, "storyboard")
    assert any(sh["image"]["path"].endswith("-c1.png") for sh in storyboard.shots(ep) if sh["shot_id"] == first)

    pipeline.run_now(ep, "video_plan")
    pipeline.approve(ep, "video_plan")
    pipeline.run_now(ep, "video")
    with pytest.raises(StageError, match="not approved"):
        pipeline.approve(ep, "video")
    plan = video.load_plan(ep)
    assert {"animate", "camera_move"} <= {s["method"] for s in plan["shots"]}
    for s in plan["shots"]:
        video.update_shot(ep, s["shot_id"], approved=True)
    pipeline.approve(ep, "video")

    pipeline.run_now(ep, "narration")
    pipeline.approve(ep, "narration")
    pipeline.run_now(ep, "captions")
    pipeline.approve(ep, "captions")
    pipeline.run_now(ep, "music")
    pipeline.approve(ep, "music")
    pipeline.run_now(ep, "production")
    tl = production.load(ep)
    assert tl["video"][0]["kind"] == "bumper" and tl["video"][-1]["kind"] == "bumper"
    assert len(tl["speech"]) == 8 and len(tl["owl"]) == 8 and tl["music"]
    srcs = [c["src"] for c in tl["video"]]
    assert len(srcs) == len(set(srcs)), "no clip is used twice"
    assert any(c.get("still") for c in tl["video"]), "camera moves are redrawn at their exact length"
    pipeline.approve(ep, "production")

    pipeline.run_now(ep, "preview")  # works any time, no approval needed
    prev = read_json(ep.path("render", "preview.json"))
    assert ep.abs(prev["output"]).exists() and prev["draft"]

    pipeline.run_now(ep, "render")
    pipeline.approve(ep, "render")
    info = read_json(ep.path("render", "timeline.json"))
    out = ep.abs(info["output"])
    assert media.has_audio(out)
    assert abs(media.duration(out) - production.timeline_end(tl)) < 1.0
    srt = ep.abs(info["srt"]).read_text(encoding="utf-8")
    assert "-->" in srt and "fear" in srt

    pipeline.run_now(ep, "package")
    meta = read_json(ep.path("publish", "metadata.json"))
    assert FOUND_URL in meta["description"] and "web.archive.org" in meta["description"]
    assert "Knowledge Fight" in meta["description"]
    pipeline.approve(ep, "package")


def test_editing_the_timeline_needs_a_new_render(episode):
    ep = episode
    research_and_story(ep)
    for st in ("script",):
        pipeline.run_now(ep, st)
        pipeline.approve(ep, st)
    pipeline.run_now(ep, "storyboard")
    for s in ep.storyboard()["scenes"]:
        storyboard.set_picks(ep, s["scene_id"], [0])
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
    pipeline.approve(ep, "production")
    pipeline.run_now(ep, "render")
    pipeline.approve(ep, "render")
    tl = production.load(ep)
    tl["speech"][0]["start"] += 0.5
    production.save(ep, tl)
    assert any("changed the timeline" in c.message for c in pipeline.checks(ep, "render"))


def test_invented_source_is_blocked(episode):
    ep = episode
    research_and_story(ep)
    pipeline.run_now(ep, "script")
    text = ep.path("script.md").read_text(encoding="utf-8")
    ep.path("script.md").write_text(text.replace("sources: S-", "sources: S-MADE-UP-123, S-", 1), encoding="utf-8")
    with pytest.raises(StageError, match="doesn't exist"):
        pipeline.approve(ep, "script")


def test_unverified_quote_is_blocked(episode):
    ep = episode
    research_and_story(ep)
    pipeline.run_now(ep, "script")
    text = ep.path("script.md").read_text(encoding="utf-8")
    ep.path("script.md").write_text(text.replace(
        "This part is short and plain.", 'The report said "the grid will fail on New Year\'s Day".', 1),
        encoding="utf-8")
    with pytest.raises(StageError, match="verified quote"):
        pipeline.approve(ep, "script")


def test_real_person_in_picture_idea_is_blocked(episode):
    ep = episode
    research_and_story(ep)
    pipeline.run_now(ep, "script")
    pipeline.approve(ep, "script")
    pipeline.run_now(ep, "storyboard")
    board = ep.storyboard()
    shot = board["scenes"][0]["shots"][0]
    shot["candidates"][0]["prompt"] = shot["candidates"][0]["full_prompt"] = "Alex Jones shouting into a microphone"
    ep.save_storyboard(board)
    with pytest.raises(StageError, match="real person"):
        pipeline.approve(ep, "storyboard")


def test_redo_resets_later_approvals(episode):
    ep = episode
    research_and_story(ep)
    pipeline.run_now(ep, "research", {"depth": "quick"})
    assert ep.stage_status("stories")["status"] == "reset"


def test_database_page_lists_and_breakdowns(data):
    for kind in subjects.KINDS:
        rows = subjects.listing(kind)
        assert rows, kind
        b = subjects.breakdown(kind, rows[0]["id"])
        assert b["claims"] and "What the video will cover" in subjects.breakdown_html(b)


def test_script_roundtrip():
    scenes = [{"scene_id": "SCENE_001", "role": "claim", "est_seconds": 30, "visual": "v",
               "narration": "Hello there.", "on_screen_text": "1999", "claim_ids": ["C-A"],
               "source_ids": ["S-B", "S-C"], "excerpt_ids": [12]}]
    parsed = scriptfmt.parse(scriptfmt.render("T", scenes))
    sc = parsed["scenes"][0]
    assert parsed["title"] == "T" and sc["role"] == "claim" and sc["source_ids"] == ["S-B", "S-C"]
    assert sc["excerpt_ids"] == ["12"] and sc["narration"] == "Hello there."


def test_research_lists_what_is_on_file_without_starting(episode):
    ep = episode
    packet = rs.prepare(ep)  # what the Research page does when it opens: no agents, no internet
    assert packet["evidence"] and not any(e["include"] for e in packet["evidence"])
    assert not packet.get("researched_at")
    rs.set_include(ep, [packet["evidence"][0]["id"]], True)
    again = rs.prepare(ep)  # opening the page again keeps your ticks
    assert [e["id"] for e in again["evidence"] if e["include"]] == [packet["evidence"][0]["id"]]


def test_research_saves_summaries_and_flags_new_finds(episode):
    ep = episode
    before = {e["id"] for e in rs.prepare(ep)["evidence"]}
    pipeline.run_now(ep, "research", {"depth": "quick"})
    packet = read_json(ep.path("research.json"))
    new = [e for e in packet["evidence"] if e["new"]]
    assert new and {e["id"] for e in new}.isdisjoint(before)
    found = next(e for e in packet["evidence"] if e.get("found_by") == "agent")
    assert "survival supplies" in found["summary"]
    # the database keeps it: a brand-new video on the same subject sees it straight away
    other = Episode.create("S01E09", "Same subject", "A-Y2K-FEAR-INDUSTRY", ep.claim_ids)
    assert any(e["source_id"] == found["source_id"] for e in rs.prepare(other)["evidence"])


def test_dig_deeper_on_ticked_evidence(episode, monkeypatch):
    ep = episode
    packet = rs.prepare(ep)
    target = next(e for e in packet["evidence"] if e["kind"] == "link")
    asked = []
    real = Ollama.chat_json

    def spy(self, messages, schema, **kw):
        if "queries" in schema["properties"]:
            asked.append(messages[-1]["content"])
        return real(self, messages, schema, **kw)
    monkeypatch.setattr(Ollama, "chat_json", spy)
    pipeline.run_now(ep, "research", {"depth": "quick", "focus": [target["id"]], "notes": "look for the court case"})
    assert asked and target["title"] in asked[0] and "court case" in asked[0]
    packet = read_json(ep.path("research.json"))
    assert next(e for e in packet["evidence"] if e["id"] == target["id"])["include"]
    assert any(e["new"] and e["found_by"] == "agent" for e in packet["evidence"])
    assert packet["runs"][-1]["focus"] == [target["id"]]


def test_only_ticked_evidence_reaches_the_script(episode):
    ep = episode
    pipeline.run_now(ep, "research", {"depth": "files"})
    packet = read_json(ep.path("research.json"))
    keep = packet["claims"][0]["claim_id"]
    rs.set_include(ep, [e["id"] for e in packet["evidence"] if e["claim_id"] == keep], True)
    sel = rs.selected(read_json(ep.path("research.json")))
    assert [c["claim_id"] for c in sel["claims"]] == [keep]
    checks = pipeline.checks(ep, "research")
    assert any("leaves it out" in c.message for c in checks)


def test_quote_numbers_in_the_sources_line_are_understood(episode):
    """Dave's S01E02: the writer put E-numbers (quote IDs) where source IDs go."""
    ep = episode
    research_and_story(ep)
    pipeline.run_now(ep, "script")
    sel = script_stage.selected_packet(ep)
    quote = next(x for c in sel["claims"] for x in c["excerpts"])
    sc = {"scene_id": "SCENE_002", "claim_ids": [], "source_ids": [f"E{quote['excerpt_id']}"], "excerpt_ids": []}
    script_stage.fix_refs(sc, sel)
    assert sc["source_ids"] == [quote["source_id"]] and sc["excerpt_ids"] == [str(quote["excerpt_id"])]
    assert sc["claim_ids"]  # filled in from the source
    # and in a hand-edited script, the check reads E-numbers the same way
    text = ep.path("script.md").read_text(encoding="utf-8")
    first = text.index("sources: S-")
    end = text.index(" |", first)
    text = text[:first] + f"sources: E{quote['excerpt_id']}" + text[end:]
    ep.path("script.md").write_text(text, encoding="utf-8")
    msgs = [c.message for c in pipeline.checks(ep, "script")]
    assert not any("doesn't exist" in m for m in msgs), msgs


def test_scene_without_sources_gets_the_ticked_ones(episode):
    ep = episode
    research_and_story(ep)
    sel = script_stage.selected_packet(ep)
    cid = sel["claims"][0]["claim_id"]
    sc = {"scene_id": "SCENE_002", "claim_ids": [cid], "source_ids": [], "excerpt_ids": []}
    notes = script_stage.fix_refs(sc, sel)
    assert sc["source_ids"] and notes


def test_researched_projects_and_another_video(episode):
    ep = episode
    research_and_story(ep)
    rows = researched.listing()
    assert [(r["kind"], r["id"]) for r in rows] == [("story", "A-Y2K-FEAR-INDUSTRY")]
    assert "S01E01" in researched.detail_html("story", "A-Y2K-FEAR-INDUSTRY")

    fresh = researched.new_video_from("S01E01", "evidence")
    p = read_json(fresh.path("research.json"))
    assert p["evidence"] and not any(e["include"] for e in p["evidence"])
    assert fresh.info["based_on"] == "S01E01"

    other = researched.new_video_from("S01E01", "story")
    assert other.stage_status("research")["status"] == "approved"
    assert read_json(other.path("stories.json")).get("chosen") is None
    assert stories.used_by(other) == {1: ["S01E01"]}
    stories.choose(other, 0)
    pipeline.approve(other, "stories")
    assert stories.used_by(ep) == {0: [other.project_id]}
    assert len(researched.videos_for("story", "A-Y2K-FEAR-INDUSTRY")) == 3


def test_research_file_from_v02_still_works(episode):
    ep = episode
    research_and_story(ep)
    p = read_json(ep.path("research.json"))
    for e in p["evidence"]:  # what v0.2 saved: no excerpt_id, summary, claim or new
        for k in ("excerpt_id", "summary", "claim", "new"):
            e.pop(k, None)
    from fofstudio.util import write_json
    write_json(ep.path("research.json"), p)
    sel = rs.selected(p)
    assert any(c["excerpts"] for c in sel["claims"])


def test_script_points_at_unticked_evidence_it_uses(episode):
    """Dave's S01E02: the story leaned on the Senate report, which wasn't ticked."""
    ep = episode
    research_and_story(ep)
    pipeline.run_now(ep, "script")
    assert script_stage.wanted_unticked(ep) == {}
    cited = next(s for sc in scriptfmt.parse(ep.path("script.md").read_text(encoding="utf-8"))["scenes"]
                 for s in sc["source_ids"])
    rows = [e["id"] for e in read_json(ep.path("research.json"))["evidence"] if e["source_id"] == cited]
    rs.set_include(ep, rows, False)
    wanted = script_stage.wanted_unticked(ep)
    assert set(wanted) & set(rows) and all(v[0].startswith("SCENE_") for v in wanted.values())
    msgs = [c.message for c in pipeline.checks(ep, "script")]
    assert any("isn't ticked" in m and "Tick what the script needs" in m for m in msgs), msgs
    rs.set_include(ep, list(wanted), True)  # what the "Tick what the script needs" button does
    assert script_stage.wanted_unticked(ep) == {}
    assert not any("isn't ticked" in c.message for c in pipeline.checks(ep, "script"))


def test_ollama_streams_progress(data):
    """The local AI's answer arrives a bit at a time, so the page can show words written so far."""
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from fofstudio import config

    class Fake(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.end_headers()
            for part in ['{"title": "A', ' real bug", ', '"scenes": []}']:
                self.wfile.write((json.dumps({"message": {"content": part}, "done": False}) + "\n").encode())
            self.wfile.write((json.dumps({"message": {"content": ""}, "done": True, "done_reason": "stop"}) + "\n").encode())

        def log_message(self, *a):
            pass
    srv = HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    cfg = dict(config.settings()["ollama"], url=f"http://127.0.0.1:{srv.server_address[1]}")
    seen = []
    import fofstudio.llm as llm
    real = llm.Ollama.chat_json  # the test fixtures may have replaced it; use the real one
    out = real(llm.Ollama(cfg), [{"role": "user", "content": "hi"}], {"type": "object", "properties": {}},
               on_text=seen.append)
    srv.shutdown()
    assert out == {"title": "A real bug", "scenes": []} and seen


def test_made_up_ids_never_reach_the_script(episode, monkeypatch):
    """Dave's S01E02: a scene came back citing claim C-10 and sources S-5, S-7, which don't exist."""
    ep = episode
    research_and_story(ep)
    real = Ollama.chat_json
    seen = {}

    def inventive(self, messages, schema, **kw):
        out = real(self, messages, schema, **kw)
        props = schema["properties"]
        if "narration" in props and "visual" in props:
            seen["enum"] = props["source_ids"]["items"].get("enum")
            out["claim_ids"] = out.get("claim_ids", []) + ["C-10"]
            out["source_ids"] = out.get("source_ids", []) + ["S-5", "S-7"]
        return out
    monkeypatch.setattr(Ollama, "chat_json", inventive)
    pipeline.run_now(ep, "script")
    assert seen["enum"], "the writer is only offered the real source IDs"
    msgs = [c.message for c in pipeline.checks(ep, "script")]
    assert not any("may have invented" in m for m in msgs), msgs
    text = ep.path("script.md").read_text(encoding="utf-8")
    assert "S-5" not in text and "C-10" not in text


def test_repair_removes_made_up_ids_from_an_existing_script(episode):
    ep = episode
    research_and_story(ep)
    pipeline.run_now(ep, "script")
    text = ep.path("script.md").read_text(encoding="utf-8")
    text = text.replace("sources: S-", "sources: S-5, S-7, S-", 1).replace("claims: C-", "claims: C-10, C-", 1)
    ep.path("script.md").write_text(text, encoding="utf-8")
    assert any("may have invented" in c.message for c in pipeline.checks(ep, "script"))
    notes = script_stage.repair(ep)
    assert notes and not any("may have invented" in c.message for c in pipeline.checks(ep, "script"))
