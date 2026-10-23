
import numpy as np

from fofstudio import media, owl
from fofstudio.agents import search
from fofstudio.stages.publish import fit_description

from .conftest import tone


def test_mouth_shapes_and_blinks_change_the_picture():
    closed = np.asarray(owl.mouth_frame("X"))
    open_wide = np.asarray(owl.mouth_frame("D"))
    blink = np.asarray(owl.mouth_frame("X", 1.0))
    l, t, r, b = owl.BEAK_BOX
    assert (closed[t:b + 30, l:r] != open_wide[t:b + 30, l:r]).any()   # the beak moved
    cx, cy = owl.EYES[0]
    assert (closed[cy - 20:cy + 20, cx - 20:cx + 20] != blink[cy - 20:cy + 20, cx - 20:cx + 20]).any()
    assert closed[2, 2, 3] == 0  # background removed


def test_loudness_cues_open_the_beak_when_he_talks(tmp_path):
    wav = tmp_path / "a.wav"
    tone(wav, 1.0)
    cues = owl.loudness_cues(wav)
    assert any(shape != "X" for _, shape in cues)


def test_presenter_track_and_bumper(data, tmp_path):
    wav = tmp_path / "line.wav"
    tone(wav, 1.5)
    listing = owl.presenter_track([(0.5, wav, "Hello there")], 3.0, tmp_path / "owl", height=120, fps=15)
    text = listing.read_text()
    assert text.startswith("ffconcat") and ".png" in text
    out = owl.bumper("intro", "Test title", tmp_path / "intro.mp4", 320, 180, 15, seconds=2)
    assert abs(media.duration(out) - 2) < 0.3 and media.has_audio(out)


def test_link_types():
    assert search.source_type("https://www.courtlistener.com/opinion/1/x/") == "court"
    assert search.source_type("https://www.govinfo.gov/app/details/CREC") == "gov"
    assert search.source_type("https://apnews.com/article/x") == "wire"
    assert search.source_type("https://www.nytimes.com/1999/12/31/x.html") == "journalism"
    assert search.source_type("https://someblog.example.com/post") == "other"
    assert search.skip("https://www.facebook.com/x") and search.skip("https://infowars.com/x")


def test_description_always_keeps_credit_lines():
    proof = [{"source_id": f"S-{i}", "line": "A long source title " * 4, "url": "https://example.com/" + "x" * 80,
              "archive_url": "https://web.archive.org/web/2026/https://example.com/" + "x" * 80} for i in range(60)]
    text, left = fit_description(["Hook."], proof, ["Research trail: Knowledge Fight.", "Spotted a mistake?"])
    assert len(text) <= 4900 and "Knowledge Fight" in text and "Spotted a mistake?" in text
    assert left > 0 and "more sources in the pinned comment" in text
