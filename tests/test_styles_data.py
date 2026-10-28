"""The style database, the style mixer, style fatigue, the prompt checks and caricature traditions."""

import json
from pathlib import Path

import pytest

from fofstudio import cast, promptcheck, styleengine, styles
from fofstudio.util import StageError
from tests.test_pipeline import episode  # noqa: F401 - the shared fixture

DATA = Path(styles.__file__).parent / "data"
HOUSE = ["documentary", "classroom", "cartoon", "satire", "newscast", "truecrime", "courtroom", "noir", "comic",
         "papercut", "infomercial", "heist"]


def test_the_house_styles_and_about_seventy_new_looks_load():
    assert all(k in styles.STYLES and styles.STYLES[k].status == "live" for k in HOUSE)
    new = [s for s in styles.STYLES.values() if s.status == "draft"]
    assert len(new) >= 60
    for s in styles.STYLES.values():
        assert s.name and s.look and s.tone and s.sample and s.wpm > 100 and s.shot_seconds > 2
        assert s.tier in ("A", "B", "C", "care")
    families = {s.group for s in new}
    assert {"animation", "puppet", "print", "fine_art", "storybook", "international"} <= families
    for s in new:   # Dave's format is all there
        assert s.info.get("visual_dna") and s.info.get("prompt_elements") and s.info.get("best_uses") is not None


def test_no_names_or_brands_ever_reach_a_prompt():
    for s in list(styles.STYLES.values()) + [styles.get(f"mix:{h['key']}") for h in styleengine.recipes()]:
        text = " ".join([s.look, s.motion, s.owl_look, " ".join(s.info.get("prompt_elements") or [])])
        assert not promptcheck.found(text), (s.key, promptcheck.found(text))
        assert "Avoid:" not in s.look and not s.look.lower().startswith("no ")
    # but the human-only note keeps where a look came from
    assert "Reiniger" in styles.get("backlit_shadow_puppet_fable").info["inspired_by"]
    assert "analog videotape" in styles.get("infomercial").look and "VHS" not in styles.get("infomercial").look


def test_prompt_check_strips_names_and_negations():
    text, hits = promptcheck.clean_prompt("A Muppet-style puppet in a Wes Anderson hallway, no people, "
                                          "never any text. Avoid: photograph, 3D")
    assert hits and "Muppet" not in text and "Anderson" not in text
    assert "no people" not in text and "Avoid" not in text and "photograph" not in text
    assert "puppet" in text and "hallway" in text


def test_keep_and_drop_change_the_pickers(data):
    key = "relief_print"
    assert any(k == key and "(untested)" in label for k, label in styles.choices())
    styles.rate(key, "kept")
    assert any(k == key and "(untested)" not in label for k, label in styles.choices())
    styles.rate(key, "dropped")
    assert key not in {k for k, _ in styles.choices()}
    assert styles.get(key).key == key          # an old video that used it still opens
    styles.rate(key, "draft")
    assert key in {k for k, _ in styles.choices()}


def test_careful_topics_only_get_sober_looks():
    keys = [k for k, _ in styles.choices(careful=True)]
    assert keys and all(styles.get(k).careful_ok for k in keys)
    assert "documentary" in keys and "satire" not in keys and "mix:spooky_clay" not in keys
    assert "mix:quiet_watercolor_memorial" in keys


def test_caricatures_only_in_drawn_cartoon_looks():
    for s in styles.STYLES.values():
        if s.caricature:
            assert s.cartoon and s.tier in ("A", "B")
            assert s.medium not in ("puppet", "felt", "clay", "latex", "film", "miniature")
    for h in styleengine.recipes():
        if h.get("caricature_ok"):
            assert h["medium"] in ("ink", "paint", "print", "cel", "drawing", "poster")
    assert not styles.get("mix:latex_caricature_workshop").caricature   # invented archetypes only


def test_mixes_take_the_body_from_one_and_the_world_from_the_other():
    m = styleengine.mix("fingerprint_clay_stop_motion", "noir")
    assert m.key == "mix:fingerprint_clay_stop_motion+noir" and m.look.startswith("plasticine")
    assert "venetian blind" in m.look and m.motion_class == "stepped"
    assert styles.get(m.key).look == m.look                     # a saved mix rebuilds itself
    r = styles.get("mix:felt_starfarers")
    assert "Felt" in r.name and "foam puppets" in r.look.lower() and "starfield" in r.look
    assert "Henson" not in r.look and "Henson" in r.info["inspired_by"]   # Dave's label stays human-only
    assert "rim light" in styles.get("mix:neon_marionette").look


def test_mixes_that_cannot_work_are_refused():
    with pytest.raises(StageError, match="proportions"):
        styleengine.mix("super_deformed_chibi_explainer", "traced_footage_rotoscope")
    with pytest.raises(StageError, match="politically coded"):
        styleengine.mix("relief_print", "constructivist_agitprop_poster")
    with pytest.raises(StageError, match="careful topic"):
        styleengine.mix("fingerprint_clay_stop_motion", "noir", careful=True)
    with pytest.raises(StageError, match="needs your OK"):
        styleengine.mix("relief_print", "court_miniature")


def test_fatigue_and_fresh_suggestions(data):
    recent = ["satire", "comic", "satire", "cartoon"]
    assert styleengine.fatigue("satire", recent) >= styleengine.FATIGUE_LIMIT
    assert styleengine.fatigue("ink_wash", recent) < 0.4
    assert styleengine.fatigue("satire", []) == 0
    due = styleengine.due(recent)
    assert "woodcut" in due and "marionettes" in due
    assert "woodcut" not in styleengine.due(["relief_print"])
    picks = [k for k, _, _ in styleengine.recommend(recent, n=6)]
    assert picks and "satire" not in picks and all(styleengine.fatigue(k, recent) < 0.6 for k in picks)
    styles.rate(picks[0], "dropped")
    assert picks[0] not in [k for k, _, _ in styleengine.recommend(recent, n=6)]


def test_caricature_traditions_are_tiered_for_a_kind_channel():
    all_ = cast.traditions(include_excluded=True)
    offered = cast.traditions()
    assert len(all_) >= 16 and len(offered) < len(all_)
    assert all(t["tier"] != "exclude" for t in offered)
    assert cast.DEFAULT_TRADITION in {t["key"] for t in offered}
    house = {t["key"] for t in offered if t["tier"] == "A"}
    assert "urbane_magazine_editorial_illustration" in house and "theme_park_live_caricature" in house
    excluded = {t["key"] for t in all_ if t["tier"] == "exclude"}
    assert any("latex" in k for k in excluded) and any("crude" in k for k in excluded)
    json.loads((DATA / "visual_language.json").read_text(encoding="utf-8"))["metaphors"]


def test_caricature_design_is_kind_and_pushes_only_a_few_features():
    face, votes = cast.vote([
        {"is_portrait": True, "head_shape": "long", "hair_volume": "voluminous", "nose": "long", "glasses": "none",
         "eye_spacing": "close-set", "chin": "average"},
        {"is_portrait": True, "head_shape": "long", "hair_volume": "voluminous", "nose": "average",
         "eye_spacing": "close-set", "chin": "average"},
        {"is_portrait": True, "head_shape": "oval", "hair_volume": "voluminous", "nose": "long",
         "eye_spacing": "close-set", "chin": "square"},
        {"is_portrait": False, "head_shape": "round"},
    ])
    assert face["head_shape"] == "long" and face["hair_volume"] == "voluminous" and face["nose"] == "long"
    assert votes["head_shape"] == {"long": 2, "oval": 1}
    design, push = cast.compose_design(face)
    assert 1 <= len(push) <= 3 and "head_shape" in push
    assert "big head" in design and "(exaggerated)" in design
    for word in ("skin", "weight", "fat", "race", "ethnic", "religio"):
        assert word not in design.lower()
    assert not any(f in cast.FACE_FIELDS for f in ("skin", "weight", "ethnicity", "build"))


def test_caricature_research_needs_three_free_photos_and_never_names_the_person(data, monkeypatch, tmp_path):
    from PIL import Image

    from fofstudio import mediafinder
    from fofstudio.llm import Ollama
    person = {"person_id": "P-1", "name": "Gary Northman"}
    few = [mediafinder.Candidate("Gary Northman 2019.jpg", f"https://x/{i}.jpg", f"https://c/{i}", "CC BY 4.0",
                                 "", "A", "Wikimedia Commons", 1200, 900) for i in range(2)]
    monkeypatch.setattr(cast, "find_references", lambda name, limit=6: few)
    with pytest.raises(StageError, match="3 are"):
        cast.research_design(person)
    many = few + [mediafinder.Candidate("Gary Northman portrait.jpg", "https://x/9.jpg", "https://c/9", "Public domain",
                                        "", "B", "Wikimedia Commons", 1200, 900)]
    monkeypatch.setattr(cast, "find_references", lambda name, limit=6: many)

    def fake_download(c, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        path = dest.with_suffix(".jpg")
        Image.new("RGB", (64, 64)).save(path)
        return {"path": str(path)}
    monkeypatch.setattr(mediafinder, "download", fake_download)
    seen = []

    def fake_chat_json(self, messages, schema, model=None, **kw):
        seen.append((model, messages[-1].get("images")))
        return {"is_portrait": True, "head_shape": "square", "hair_volume": "bald", "jaw": "wide",
                "glasses": "thick dark frames", "expression": "smug", **{f: "can't tell" for f in ("nose", "chin")}}
    monkeypatch.setattr(Ollama, "chat_json", fake_chat_json)
    res = cast.research_design(person)
    assert len(seen) == 3 and all(images for _, images in seen) and seen[0][0] == "qwen3-vl:8b"
    assert "Northman" not in res["design"] and "bald head" in res["design"] and "glasses" in res["design"]
    assert {r["licence"] for r in res["references"]} <= {"CC BY 4.0", "Public domain"}
    assert "nose" in res["unsure"]


def test_pictures_go_to_the_vision_model_on_either_route():
    from fofstudio.llm import _as_generate
    out = _as_generate({"model": "m", "messages": [{"role": "system", "content": "s"},
                                                   {"role": "user", "content": "u", "images": ["abc"]}]})
    assert out["images"] == ["abc"] and out["prompt"] == "u"


def test_picture_prompts_lead_with_the_medium_and_never_say_no(episode):
    from fofstudio import pipeline
    from tests.test_pipeline import research_and_story
    ep = episode
    research_and_story(ep)
    pipeline.run_now(ep, "script")
    pipeline.approve(ep, "script")
    pipeline.run_now(ep, "storyboard")
    style = styles.get(ep.creative()["style"])
    prompts = [c["full_prompt"] for s in ep.storyboard()["scenes"] for sh in s["shots"] for c in sh["candidates"]
               if c and c.get("full_prompt")]
    assert prompts
    for p in prompts:
        assert p.startswith(style.look.split(",")[0]), p[:80]
        assert "Avoid:" not in p and " no " not in f" {p.lower()} " and "never" not in p.lower()
        assert not promptcheck.found(p)


def test_the_style_test_paints_each_look_and_makes_a_contact_sheet(episode):
    from fofstudio import pipeline
    from fofstudio.stages import styletest
    pipeline.run_now(episode, "styletest", {"styles": ["fog_layer_glass_fable", "mix:felt_starfarers", "satire"]})
    res = styletest.results()
    assert set(res) >= {"fog_layer_glass_fable", "mix:felt_starfarers", "satire"}
    assert len(res["fog_layer_glass_fable"]["pictures"]) == 2 and len(res["satire"]["pictures"]) == 3   # + the salesman
    assert all(Path(p["path"]).exists() for p in res["satire"]["pictures"])
    assert list(styletest.folder().glob("contact-sheet-*.png"))
    assert all(not promptcheck.found(p["prompt"]) for v in res.values() for p in v["pictures"])


def test_titles_and_tags_never_name_a_brand(episode):
    from fofstudio.stages import publish
    from fofstudio.util import write_json
    write_json(episode.path("publish", "metadata.json"), {
        "title": "The Muppet-style fear machine", "description": "THE PROOF ... Knowledge Fight", "tags": ["y2k"],
        "chapters": [1, 2, 3], "video": "x.mp4"})
    msgs = [c.message for c in publish.check_package(episode) if c.level == "block"]
    assert any("brand, show or artist" in m for m in msgs)
