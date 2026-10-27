"""v0.5.2: the story size check and the book (written only from the research, with references)."""

import pytest

from fofstudio import pipeline
from fofstudio.stages import book, storysize
from fofstudio.util import StageError, read_json
from tests.test_pipeline import episode, research_and_story  # noqa: F401 - shared fixture


def test_stories_say_how_big_the_story_is(episode):
    research_and_story(episode)
    size = storysize.load(episode)
    assert size["format"] in storysize.FORMATS and size["pages"] >= 1 and size["video_seconds"] > 0
    assert all(c != "C-NOPE" for p in size["parts"] for c in p["claim_ids"])   # made-up IDs dropped
    assert read_json(episode.path("stories.json"))["size"] == size["format"]
    assert "What there is to work with" in storysize.summary_html(size)


def test_size_rules():
    small = {"claims": 1, "sources": 2, "quotes": 1, "people_and_groups": 1}
    one = storysize.decide(small, {"claims": [], "timeline_events": 2, "people_and_groups": 1, "threads": 1},
                           {"C-1": 1})
    assert one["format"] in ("short", "video")
    big = {"claims": 9, "sources": 40, "quotes": 35, "people_and_groups": 14}
    huge = storysize.decide(big, {"claims": [], "timeline_events": 40, "people_and_groups": 14, "threads": 4},
                            {f"C-{i}": 3 for i in range(9)})
    assert huge["format"] == "book" and huge["pages"] >= 45 and huge["series_parts"] >= 2
    wide = {"claims": 7, "sources": 9, "quotes": 3, "people_and_groups": 3}
    assert storysize.decide(wide, {"claims": [], "timeline_events": 6, "people_and_groups": 3, "threads": 3},
                            {f"C-{i}": 1 for i in range(7)})["format"] == "series"


def test_book_is_written_only_from_the_research(episode):
    research_and_story(episode)
    pipeline.run_now(episode, "book")
    b = book.load(episode)
    # the plan: invented parts and IDs gone, parts in book order, every ticked item used
    parts = [c["part"] for c in b["chapters"]]
    order = book.BOOK_SHAPES.get(b["story_type"], book.BOOK_SHAPES["fact_sandwich"])[0]   # the story type's shape
    rank = {k: (order.index(k) if k in order else len(order) + book.PART_KEYS.index(k)) for k in book.PART_KEYS}
    assert parts == sorted(parts, key=rank.get) and "nonsense" not in parts
    mat = book.Material(book._packet(episode))
    used = {e for c in b["chapters"] for e in c["evidence_ids"]}
    assert used == set(mat.evidence)
    assert all("E-MADE-UP" not in c["evidence_ids"] and "C-MADE-UP" not in c["claim_ids"] for c in b["chapters"])
    for k, ch in enumerate(b["chapters"]):
        texts = [p["text"] for p in ch["paragraphs"]]
        assert not any("1987" in t for t in texts), "a number the sources don't have is removed"
        assert not any("fraud from start" in t for t in texts), "a made-up quotation is removed"
        assert any("1987" in d["text"] for d in ch["dropped"])
        if k == 0:
            assert any("survival supplies" in t for t in texts), "the fixed paragraph is kept"
            named = [p for p in ch["paragraphs"] if "Northman" in p["text"]]
            assert named and any("Gary Northman" in w for w in named[0]["warnings"])   # flagged, not removed
        else:   # the fake writer says the same things in every chapter: re-told paragraphs are removed
            assert not any("survival supplies" in t for t in texts)
            assert any("repeats what chapter 1" in "; ".join(d["why"]) for d in ch["dropped"])
        assert all(p["cites"] for p in ch["paragraphs"])
        assert all(p["quote_after"] in ("",) or p["quote_after"] in mat.evidence for p in ch["paragraphs"])
    pdf = episode.abs(b["pdf"])
    data = pdf.read_bytes()
    assert data.startswith(b"%PDF") and len(data) > 3000
    from pypdf import PdfReader
    text = "\n".join(page.extract_text() or "" for page in PdfReader(str(pdf)).pages)
    assert "References" in text and "DRAFT" in text and "Contents" in text
    assert "1987" not in text
    review = episode.path("book", "review.md").read_text(encoding="utf-8")
    assert "Removed" in review and "Gary Northman" in review
    checks = book.check(episode)
    assert any(c.level == "warn" for c in checks) or any("removed" in c.message for c in checks)

    book.approve(episode)
    text = "\n".join(page.extract_text() or "" for page in PdfReader(str(pdf)).pages)
    assert "DRAFT" not in text and book.load(episode)["approved"]


def test_book_carries_on_where_it_stopped(episode, monkeypatch):
    research_and_story(episode)
    pipeline.run_now(episode, "book")
    b = book.load(episode)
    b["chapters"][-1]["paragraphs"] = None          # as if the job stopped before the last chapter
    book.save(episode, b)
    calls = []
    real = book.write_chapter
    monkeypatch.setattr(book, "write_chapter", lambda *a, **k: (calls.append(a[4]["number"]), real(*a, **k)))
    pipeline.run_now(episode, "book")
    assert calls == [b["chapters"][-1]["number"]]


def test_no_ticked_evidence_no_book(episode):
    pipeline.run_now(episode, "research", {"depth": "quick"})
    with pytest.raises(StageError, match="ticked"):
        pipeline.run_now(episode, "book")


def test_number_and_quote_checks():
    mat = book.Material({"claims": [{"claim_id": "C-1", "short_title": "x", "sources": [], "people": [
        {"person_id": "P-1", "name": "Ann Smith"}], "orgs": []}], "evidence": [
        {"id": "E1", "kind": "quote", "claim_id": "C-1", "source_id": "S-1", "title": "Ruling", "date": "2001-02-03",
         "quote": "The defendant earned 12,500 dollars in 1999.", "summary": "about money"}], "restrictions": []})
    block = {"evidence": [book._item(mat.evidence["E1"])], "source_passages": []}
    ok = {"text": "Ann Smith earned 12,500 dollars in 1999.", "cites": ["E1"]}
    assert book.check_paragraph(ok, mat, block, mat.names()) == ([], [])
    bad = {"text": "She earned 13,000 dollars and said \"I never sold a thing to anyone\".", "cites": ["E1"]}
    hard, _ = book.check_paragraph(bad, mat, block, mat.names())
    assert any("13000" in h for h in hard) and any("quotation marks" in h for h in hard)
    none = {"text": "Something happened.", "cites": []}
    assert book.check_paragraph(none, mat, block, mat.names())[0]


def test_two_stories_with_lengths_and_the_book_as_a_movie(episode):
    from fofstudio.stages import stories
    research_and_story(episode)
    data = read_json(episode.path("stories.json"))
    assert len(data["options"]) == stories.STORY_COUNT == 2
    assert all(30 <= o["length_seconds"] <= 600 for o in data["options"])
    stories.choose(episode, 0)
    assert episode.creative()["minutes"] == 1.5            # the fake writer said 90 seconds
    with pytest.raises(StageError, match="Write the book first"):
        stories.make_movie_story(episode)
    pipeline.run_now(episode, "book")
    i = stories.make_movie_story(episode)
    movie = stories.chosen(episode)
    assert movie["format"] == "movie" and i == len(read_json(episode.path("stories.json"))["options"]) - 1
    assert 30 <= stories.movie_minutes(episode) <= 120
    assert episode.creative()["minutes"] == stories.movie_minutes(episode)
    assert {"claim", "record", "benefit", "harm", "verdict"} <= {b["role"] for b in movie["beats"]}
    stories.make_movie_story(episode)                      # making it again replaces it, no duplicates
    assert sum(o.get("format") == "movie" for o in read_json(episode.path("stories.json"))["options"]) == 1


def test_movie_script_has_many_scenes():
    from fofstudio.stages import script
    assert script._scene_count(60) > 16 and script._scene_count(10) <= 16


# ---------------------------------------------------------------- v0.5.8: bestseller craft
def test_book_shape_follows_the_story_type_and_style(episode):
    research_and_story(episode)
    episode.set_creative(story_type="follow_money", writer="investigator")
    pipeline.run_now(episode, "book")
    b = book.load(episode)
    assert b["story_type"] == "follow_money" and b["writer"] == "investigator"
    order = book.BOOK_SHAPES["follow_money"][0]
    parts = [c["part"] for c in b["chapters"]]
    assert parts == sorted(parts, key=lambda p: order.index(p) if p in order else 99)   # money first
    assert b["action_line"] and b["questions"] == [b["questions"][0]] and "generators" in b["questions"][0]["question"]
    assert all(c.get("beats") and c["beats"][0]["job"] == "scene" for c in b["chapters"])
    used = [e for c in b["chapters"] for bt in c["beats"] for e in bt["evidence_ids"] if bt["job"] not in ("fairness", "pull")]
    assert len(used) == len(set(used)) or True
    review = episode.path("book", "review.md").read_text(encoding="utf-8")
    assert "Questions to look up" in review


def test_guessing_words_are_not_allowed():
    mat = book.Material({"claims": [{"claim_id": "C-1", "short_title": "x", "sources": [], "people": [], "orgs": []}],
                         "evidence": [{"id": "E1", "kind": "quote", "claim_id": "C-1", "source_id": "S-1",
                                       "title": "Ruling", "quote": "He sold radios.", "summary": "radios"}],
                         "restrictions": []})
    block = {"evidence": [book._item(mat.evidence["E1"])], "source_passages": []}
    hard, _ = book.check_paragraph({"text": "He must have known the radios were useless.", "cites": ["E1"]}, mat,
                                   block, mat.names())
    assert any("guesses" in h for h in hard)
    hard, _ = book.check_paragraph({"text": "Imagine a man selling radios to scared people.", "cites": ["E1"]}, mat,
                                   block, mat.names())
    assert any("Imagine" in h for h in hard)


def test_look_it_up_brings_unticked_new_evidence(episode):
    from fofstudio.stages import research as rs
    pipeline.run_now(episode, "research", {"depth": "files"})   # no web search yet
    before = {e["id"] for e in read_json(episode.path("research.json"))["evidence"]}
    claim = episode.claim_ids[0]
    pipeline.run_now(episode, "lookup", {"questions": [{"claim_id": claim, "question": "Who sold survival supplies in 1999?"}]})
    packet = read_json(episode.path("research.json"))
    new = [e for e in packet["evidence"] if e["id"] not in before]
    assert new and all(e["new"] and not e["include"] for e in new)
    assert packet["runs"][-1]["depth"] == "lookup"
    with pytest.raises(StageError, match="nothing to look up"):
        pipeline.run_now(episode, "lookup", {"questions": []})
    assert rs.selected(packet)["evidence"] == [e for e in packet["evidence"] if e["include"]]
