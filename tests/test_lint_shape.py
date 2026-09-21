"""creative.yaml shape: unknown keys and input paths the render box cannot resolve."""

from __future__ import annotations

from pathlib import Path

import yaml

from videotool.creative.lint_shape import check_inputs, check_keys

EXAMPLES = Path(__file__).resolve().parents[1] / ".agents/skills/make-video/examples"


def test_real_creatives_that_rendered_have_no_unknown_keys() -> None:
    for path in sorted(EXAMPLES.glob("creative-*.yaml")):
        assert check_keys(yaml.safe_load(path.read_text(encoding="utf-8"))) == ([], []), path.name


def test_the_overlay_mistake_is_named_with_the_key_meant() -> None:
    errors, _ = check_keys({"enhance": {"atmosphere": "fireflies", "parallax": True}})
    assert errors == ["unknown creative key `enhance.atmosphere` — nothing reads it, so it has no effect; "
                      "did you mean `enhance.overlay`?"]


def test_typos_in_nested_known_sections_are_caught() -> None:
    errors, _ = check_keys({"project": {"metadata": {"chanel": "x"}}, "inputs": {"intro_imge": "a.jpg"},
                            "enhance": {"sfx": {"cue": []}}})
    assert len(errors) == 3
    assert any("project.metadata.channel" in e for e in errors)
    assert any("inputs.intro_image" in e for e in errors)
    assert any("enhance.sfx.cues" in e for e in errors)


def test_input_paths_must_be_inside_and_present() -> None:
    files = ["Music/01.mp3", "Ảnh bìa/22.jpg", "T_DESCRIPTION_TEMPLATE.txt"]
    ok = {"inputs": {"music": "Music", "intro_image": "Ảnh bìa/22.jpg", "description_template": "T_DESCRIPTION_TEMPLATE.txt"}}
    assert check_inputs(ok, files) == ([], [])
    errors, _ = check_inputs({"inputs": {"description_template": "/home/dung/x/T.txt", "ending_image": "../e.jpg",
                                         "outro_cta": "CTA voice/missing.mp4"}}, files)
    assert len(errors) == 3
    assert sum("inside the episode folder" in e for e in errors) == 2
    assert any("is not in the episode folder" in e for e in errors)


def test_a_hint_is_only_offered_when_it_is_valid_at_that_level() -> None:
    errors, _ = check_keys({"music": "Music"})   # `music_schedule` lives under `audio`, not at the top
    assert errors and "did you mean `music_schedule`" not in errors[0]
