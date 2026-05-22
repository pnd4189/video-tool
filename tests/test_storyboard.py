from pathlib import Path

import yaml
from typer.testing import CliRunner

from videotool.cli.main import app
from videotool.core.job_spec import JobSpec
from videotool.core.storyboard import build_storyboard, select_effects


def test_parse_storyboard_prompts_and_select_effects(tmp_path: Path) -> None:
    image_prompts = tmp_path / "image_prompts.txt"
    video_prompts = tmp_path / "video_prompts.txt"
    image_prompts.write_text(
        """
# Image Prompts

[Scene 1 - establishing]
Subject: action clash

[Scene 2 - dialogue]
Subject: quiet room
""",
        encoding="utf-8",
    )
    video_prompts.write_text(
        """
# Video Prompts

[Scene 1 - 6s]
Camera: Quick zoom in on the clashing hands
Atmosphere: Explosive, fast-paced martial arts combat

[Scene 2 - 4s]
Camera: Static wide shot slowly panning right
Atmosphere: Serene and quiet
""",
        encoding="utf-8",
    )
    scenes = build_storyboard(image_prompts, video_prompts, tmp_path / "media")
    assert [scene.duration for scene in scenes] == [6.0, 4.0]
    assert scenes[0].motion == "zoom-in"
    assert scenes[0].transition == "crossfade"
    assert scenes[1].motion == "pan-right"
    assert scenes[1].transition == "fade"


def test_effect_selector_has_safe_defaults() -> None:
    assert select_effects("Camera: unknown") == ("ken-burns", "crossfade")


def test_storyboard_plan_command_writes_job(tmp_path: Path) -> None:
    image_prompts = tmp_path / "image_prompts.txt"
    video_prompts = tmp_path / "video_prompts.txt"
    image_prompts.write_text("[Scene 1 - establishing]\nSubject: hero\n", encoding="utf-8")
    video_prompts.write_text("[Scene 1 - 8s]\nCamera: Slow push in on hero\n", encoding="utf-8")
    output = tmp_path / "job.yaml"
    result = CliRunner().invoke(
        app,
        [
            "storyboard",
            "plan",
            "--image-prompts",
            str(image_prompts),
            "--video-prompts",
            str(video_prompts),
            "--media",
            "media",
            "--voice",
            "voice.wav",
            "--output",
            str(output),
        ],
    )
    assert result.exit_code == 0
    job = JobSpec.model_validate(yaml.safe_load(output.read_text(encoding="utf-8")))
    assert job.storyboard[0].image == Path("media/scene-001.png")
    assert job.storyboard[0].motion == "slow-push"
