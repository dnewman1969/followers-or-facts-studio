from fofstudio import db, sources
from fofstudio.db.validate import validate


def test_import_counts_and_fixes(data):
    assert db.one("SELECT COUNT(*) n FROM claim")["n"] == 487
    assert db.one("SELECT COUNT(*) n FROM source")["n"] == 388
    assert db.one("SELECT COUNT(*) n FROM arc")["n"] == 54
    # the shifted arc rows are repaired
    assert db.one("SELECT status FROM arc WHERE arc_id='A-SETH-RICH'")["status"] == "backlog"
    assert db.one("SELECT first_known_origin FROM arc WHERE arc_id='A-SETH-RICH'")[
        "first_known_origin"].startswith("2017")
    # Flynn has one ID now, and the alias is recorded
    assert db.one("SELECT 1 FROM person WHERE person_id='P-MIKE-FLYNN'") is None
    assert db.one("SELECT canonical_id FROM entity_alias WHERE alias_id='P-MIKE-FLYNN'")[
        "canonical_id"] == "P-MICHAEL-FLYNN"


def test_readiness_and_careful_topics(data):
    y2k = db.one("SELECT * FROM arc_strength WHERE arc_id='A-Y2K-FEAR-INDUSTRY'")
    assert y2k["claims"] == y2k["sourced_claims"] == 6
    rules = {r["rule"] for r in db.rows(
        "SELECT rule FROM content_restriction WHERE subject_id='A-SH-COURT-ARRIVES'")}
    assert {"courts_only", "no_names", "no_footage"} <= rules


def test_reimport_keeps_projects(data):
    from fofstudio.db import importer
    from fofstudio.episode import Episode
    Episode.create("T1", "Test", "A-Y2K-FEAR-INDUSTRY")
    importer.import_research(importer.SEED)
    assert len(Episode.load("T1").claim_ids) == 6


def test_validator_has_no_errors(data):
    assert validate()["errors"] == []


def test_quotes_only_verified_when_word_for_word(data, tmp_path):
    text_file = tmp_path / "s.txt"
    text_file.write_text("The plant shut down as a precaution. Officials said there was "
                         "no danger to the public at any time.", encoding="utf-8")
    sid = db.one("SELECT source_id FROM source WHERE is_primary=1 LIMIT 1")["source_id"]
    db.execute("UPDATE source SET text_path=? WHERE source_id=?", (str(text_file), sid))
    _, ok = sources.add_excerpt(sid, "Officials said there was no danger to the public at any time.")
    assert ok
    _, bad = sources.add_excerpt(sid, "Officials admitted there was great danger to the public.")
    assert not bad


def test_html_to_text_drops_scripts():
    html = "<html><head><title>T</title><script>var x=1</script></head><body><p>Hello</p><p>World</p></body></html>"
    text = sources.html_to_text(html)
    assert "var x" not in text and "Hello" in text and "World" in text


def test_quotes_are_copied_by_sentence_number():
    """The AI picks sentence numbers; the program copies the exact words, so a quote can't come out wrong."""
    from fofstudio.stages.research import copy_sentences, numbered_sentences
    text = ('The court finds that the defendant sold survival supplies. He told listeners "the grid would fail." '
            'Sales rose 40% in 1999!\n\nDr. Smith (an expert) disagreed. U.S. officials said no. See No. 5 on p. 12.')
    s = numbered_sentences(text)
    assert [x["text"] for x in s] == ["The court finds that the defendant sold survival supplies.",
                                      'He told listeners "the grid would fail."', "Sales rose 40% in 1999!",
                                      "Dr. Smith (an expert) disagreed.", "U.S. officials said no.",
                                      "See No. 5 on p. 12."]
    assert copy_sentences(s, 1, 3) in text and copy_sentences(s, 1, 3).endswith("1999!")
    assert copy_sentences(s, 3, 5) == "Sales rose 40% in 1999!"      # never across paragraphs
    assert copy_sentences(s, 1, 9) == copy_sentences(s, 1, 3)       # at most 3 in a row
