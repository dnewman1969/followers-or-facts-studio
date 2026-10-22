import json
from pathlib import Path

from PIL import Image

from fofstudio import cards, comfy
from fofstudio.config import REPO
from fofstudio.engines.tts import respell
from fofstudio.stages.captions import _align, build_srt


def test_comfy_placeholders_fill_numbers_and_text():
    wf = {"1": {"inputs": {"text": "{{PROMPT}}", "seed": "{{SEED}}", "prefix": "fof/{{SEED}}"}}}
    out = comfy.fill(wf, {"PROMPT": "a desk", "SEED": "42"})
    assert out["1"]["inputs"] == {"text": "a desk", "seed": 42, "prefix": "fof/42"}


def test_workflow_templates_are_valid_and_have_their_placeholders():
    need = {"zimage_turbo_t2i.json": {"PROMPT", "SEED", "WIDTH", "HEIGHT", "FILENAME_PREFIX"},
            "wan22_i2v_lightning.json": {"IMAGE", "PROMPT", "SEED", "WIDTH", "HEIGHT", "FRAMES",
                                         "FPS", "FILENAME_PREFIX"},
            "acestep_music.json": {"TAGS", "LYRICS", "SECONDS", "SEED", "FILENAME_PREFIX"}}
    for name, keys in need.items():
        data = json.loads((REPO / "comfy_workflows" / name).read_text(encoding="utf-8"))
        data.pop("_about")
        assert comfy.placeholders(data) == keys, name
        for node in data.values():  # every link points at a node that exists
            for v in node["inputs"].values():
                if isinstance(v, list):
                    assert v[0] in data, (name, v)


def test_respell_brand_words():
    assert "Owl-bert" in respell("Professor Owlbert explains Y2K")
    assert "Y two K" in respell("Professor Owlbert explains Y2K")


def test_align_keeps_script_spelling():
    script = "Owlbert checks the Y2K claim today".split()
    heard = [{"word": w, "start": i * 0.5, "end": i * 0.5 + 0.4}
             for i, w in enumerate("Owl bert checks the why two k claim today".split())]
    timed = _align(script, heard, 4.5)
    assert [t["word"] for t in timed] == script
    assert all(a["start"] <= b["start"] for a, b in zip(timed, timed[1:]))


def test_srt_groups_sentences_and_offsets_scenes():
    timings = {"scenes": {"S1": {"words": [{"word": "Hello", "start": 0.0, "end": 0.4},
                                           {"word": "there.", "start": 0.4, "end": 0.9},
                                           {"word": "Next", "start": 1.0, "end": 1.3}]}}}
    srt = build_srt({"S1": 10.0}, timings, lead=0.5)
    assert "00:00:10,500 --> " in srt and "Hello there." in srt and "Next" in srt


def test_cards_draw(tmp_path):
    cards.quote_card("A sentence copied exactly from the source.", "Reuters, 1999", tmp_path / "q.png")
    cards.thumbnail("The Y2K fear machine", tmp_path / "t.png")
    assert Image.open(tmp_path / "t.png").size == (1280, 720)
    owl = cards.owl()
    assert owl is not None and owl.getpixel((0, 0))[3] == 0  # background keyed out
