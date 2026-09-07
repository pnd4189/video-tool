"""Turn desired scene start times into durations a render can use.

Every tier of image timing ends here, which is the point: the minimum-hold rule and the
"storyboard must total exactly the narration length" rule are written once and cannot drift
apart between tiers.

The solver works on BOUNDARIES rather than durations. A scene's duration is the difference
between its own boundary and the next one, so with the first boundary pinned to the window
start and the last to the window end the durations always sum to exactly the window — there is
no rounding remainder to hand back to some arbitrary scene. A minimum hold is then enforced by
pushing boundaries right in one pass and pulling them back off the fixed end in a second,
which preserves both the order and the exact total.
"""
from __future__ import annotations

DEFAULT_MIN_HOLD_SECONDS = 9.0


def solve_durations(
    kinds: list[str],
    clip_durations: list[float],
    desired_starts: list[float | None],
    window: tuple[float, float],
    floor: float = DEFAULT_MIN_HOLD_SECONDS,
) -> list[float]:
    """Duration per position, totalling exactly the window.

    ``kinds`` marks each position ``"image"`` or ``"video"``. A video clip keeps its real
    length from ``clip_durations`` untouched — stretching a clip would desync its own motion —
    so clips act as fixed blocks and the images between them share what is left. ``desired_starts``
    carries the second each image wants to begin at (from its narration anchor), or ``None``
    where nothing is known; unknown positions are spaced evenly between their nearest known
    neighbours, which keeps one unlocatable anchor from disturbing the rest of the episode.
    """
    window_start, window_end = window
    durations = [0.0] * len(kinds)
    for run_start, run_end, positions in _image_runs(kinds, clip_durations, window):
        starts = _resolve_starts(
            [desired_starts[position] for position in positions], run_start, run_end
        )
        for position, duration in zip(positions, _hold(starts, run_start, run_end, floor)):
            durations[position] = duration
    for position, kind in enumerate(kinds):
        if kind == "video":
            durations[position] = clip_durations[position]
    return durations


def _image_runs(
    kinds: list[str], clip_durations: list[float], window: tuple[float, float]
) -> list[tuple[float, float, list[int]]]:
    """Split the timeline into the stretches of images that sit between the fixed clips.

    Clips consume their real length wherever they fall; the time left over is shared between
    the image stretches in proportion to how many images each holds, which is what the plain
    even split did before any anchoring existed.
    """
    window_start, window_end = window
    order: list[tuple[str, list[int] | int]] = []
    current: list[int] = []
    for position, kind in enumerate(kinds):
        if kind == "video":
            if current:
                order.append(("run", current))
                current = []
            order.append(("clip", position))
        else:
            current.append(position)
    if current:
        order.append(("run", current))

    image_total = sum(len(payload) for kind, payload in order if kind == "run")  # type: ignore[arg-type]
    free = (window_end - window_start) - sum(
        clip_durations[position] for position, kind in enumerate(kinds) if kind == "video"
    )
    if image_total and free <= 0:
        raise ValueError(
            f"Video clips leave {free:.0f}s for {image_total} still image(s) — use fewer or "
            "shorter clips, or a longer narration."
        )

    spans: list[tuple[float, float, list[int]]] = []
    cursor = window_start
    for kind, payload in order:
        if kind == "clip":
            cursor += clip_durations[payload]  # type: ignore[index]
            continue
        run = payload  # type: ignore[assignment]
        length = free * len(run) / image_total if image_total else 0.0
        spans.append((cursor, cursor + length, run))
        cursor += length
    return spans


def _resolve_starts(
    desired: list[float | None], run_start: float, run_end: float
) -> list[float]:
    """Fill in the unknown starts by spacing them evenly between the known ones.

    The run's own edges act as known points, so a gap at either end is spaced against the edge
    rather than left undefined. This is what confines an unlocatable anchor to its own
    neighbourhood: only the scenes between the same two located neighbours move.
    """
    count = len(desired)
    known = [
        (index, min(max(value, run_start), run_end))
        for index, value in enumerate(desired)
        if value is not None
    ]
    # (index, time) pairs the interpolation runs between. The first scene begins at the run's
    # start unless it carries a time of its own, and a virtual point past the last scene closes
    # the final gap — without it the tail would have nothing to interpolate towards.
    fixed: list[tuple[int, float]] = ([] if known and known[0][0] == 0 else [(0, run_start)])
    fixed += known
    fixed.append((count, run_end))

    starts: list[float] = []
    segment = 0
    for index in range(count):
        while fixed[segment + 1][0] < index:
            segment += 1
        low_index, low_time = fixed[segment]
        high_index, high_time = fixed[segment + 1]
        if index == high_index:
            starts.append(high_time)
            continue
        share = (index - low_index) / (high_index - low_index)
        starts.append(low_time + (high_time - low_time) * share)
    return starts


def _hold(starts: list[float], run_start: float, run_end: float, floor: float) -> list[float]:
    """Durations honouring the minimum hold, summing to exactly ``run_end - run_start``.

    Two passes over the boundaries. Forward: no scene may begin before the previous one has
    held for ``floor``, so a cluster of anchors closer together than the floor is spread out,
    borrowing from whichever later scene has slack. Backward off the pinned end: nothing may
    run past the window, which both undoes any overshoot the forward pass caused and proves the
    result stays ordered. When the window is too short to give every scene the floor, the floor
    shrinks to whatever the window can afford rather than the solver failing.
    """
    count = len(starts)
    if count == 0:
        return []
    length = run_end - run_start
    hold = min(floor, length / count) if count else floor

    boundaries = [run_start] + list(starts[1:]) + [run_end]
    for index in range(1, count):
        boundaries[index] = max(boundaries[index], boundaries[index - 1] + hold)
    boundaries[count] = run_end
    for index in range(count - 1, 0, -1):
        boundaries[index] = min(boundaries[index], boundaries[index + 1] - hold)
    # Round the interior boundaries only. Durations are differences between boundaries, so
    # rounding them here keeps the emitted YAML readable at millisecond precision while the
    # total stays exactly `run_end - run_start` — the two ends are never touched.
    for index in range(1, count):
        boundaries[index] = round(boundaries[index], 3)
    return [boundaries[index + 1] - boundaries[index] for index in range(count)]
