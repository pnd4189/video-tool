from videotool.core.job_spec import EnhanceSpec


def test_mood_expands_to_group_a_effects() -> None:
    cozy = EnhanceSpec(mood="cozy")
    assert cozy.effect_on("vignette") is True
    assert cozy.effect_on("glow") is True
    assert cozy.effect_on("grain") is False
    assert cozy.resolved_color_grade() == "warm"


def test_no_mood_means_all_effects_off() -> None:
    spec = EnhanceSpec()
    assert all(spec.effect_on(n) is False for n in ("vignette", "grain", "glow", "flicker"))
    assert spec.resolved_color_grade() is None


def test_explicit_effect_overrides_mood() -> None:
    # action mood has grain on, flicker on; force them off and add glow.
    spec = EnhanceSpec(mood="action", grain=False, glow=True)
    assert spec.effect_on("grain") is False
    assert spec.effect_on("glow") is True
    assert spec.effect_on("flicker") is True  # still from mood


def test_color_grade_override_wins() -> None:
    assert EnhanceSpec(mood="cozy", color_grade="cold").resolved_color_grade() == "cold"


def test_tier_full_does_not_enable_group_a() -> None:
    # Group A is mood-driven, independent of tier; full must not turn it on.
    spec = EnhanceSpec(tier="full")
    assert spec.effect_on("vignette") is False
    assert spec.atmosphere is False


def test_progress_bar_key_accepted_but_inert() -> None:
    # Backward-compat: old job.yaml with progress_bar still validates; it renders nothing.
    spec = EnhanceSpec(progress_bar=True)
    assert spec.progress_bar is True  # accepted, but no timeline/overlay wiring consumes it
