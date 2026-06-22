import sys
from pathlib import Path

import numpy as np
import pytest

# scripts/ is an offline tools dir, not on the package path — add it for this test.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import gen_overlay  # noqa: E402

# Test at the real target resolution: density (sparseness of the glow) is what the
# black-background assertion checks, and density only reads true at the shipping size.
# One frame at 1080p is still milliseconds.
WIDTH, HEIGHT = 1920, 1080


def _field_and_sprite(preset_name: str):
    preset = gen_overlay.PRESETS[preset_name]
    rng = np.random.default_rng(7)
    fld = gen_overlay._make_field(preset, WIDTH, HEIGHT, rng)
    sprite = gen_overlay.glow_sprite(preset.glow_sigma)
    return preset, fld, sprite


@pytest.mark.parametrize("preset_name", sorted(gen_overlay.PRESETS))
def test_loop_is_seamless(preset_name: str) -> None:
    """frame(t=0) must equal frame(t=1): the clip closes its own loop. Lifecycle presets
    (embers) close because every particle's wrapping phase returns to its start."""
    preset, fld, sprite = _field_and_sprite(preset_name)
    first = gen_overlay.render_frame(preset, fld, sprite, 0.0, WIDTH, HEIGHT)
    wrap = gen_overlay.render_frame(preset, fld, sprite, 1.0, WIDTH, HEIGHT)
    assert np.array_equal(first, wrap), f"{preset_name}: loop seam, first and wrap frame differ"


@pytest.mark.parametrize("preset_name", sorted(gen_overlay.PRESETS))
def test_background_is_black(preset_name: str) -> None:
    """Glow on black: the vast majority of pixels stay at 0 so screen-blend is clean."""
    preset, fld, sprite = _field_and_sprite(preset_name)
    frame = gen_overlay.render_frame(preset, fld, sprite, 0.37, WIDTH, HEIGHT)
    assert int(np.median(frame)) == 0, f"{preset_name}: background is not pure black"
    lit_fraction = float((frame.max(axis=2) > 8).mean())
    assert lit_fraction < 0.25, f"{preset_name}: too much of the frame is lit ({lit_fraction:.2%})"
