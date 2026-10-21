"""Free this machine once an episode is published: delete its local stage under ~/.cache/videotool.

Every lane that works in a local stage (Colab CLI, VPS, Kaggle CPU, Modal, local) ends here, so a published episode
leaves behind only its run log and its review folder (contact sheet + loudness, a few MB), moved to
`<stage>-review/`. Nothing is deleted unless every file in STAGE/outputs is at the publish path at the
same size; a refusal deletes nothing. User decision 2026-10-15: clean up automatically, no question.

    .venv/bin/python .agents/skills/make-video/scripts/purge_stage.py STAGE --published-to "gdrive:…/Chap NN/outputs"
"""
from __future__ import annotations

import argparse
import fnmatch
import os
import shutil
import subprocess
import sys
from pathlib import Path

CACHE_ROOT = Path.home() / ".cache/videotool"
SIBLING_SUFFIXES = ("-dl", "-kcpu", "-colab", "-vps")  # the downloaded render and the Kaggle CPU / Colab / VPS bundle
REVIEW_SUFFIX = "-review"
UNPUBLISHED = "thumbnail-candidate-*.jpg"  # never published, so never checked


class PurgeError(RuntimeError):
    """A refused purge; nothing was deleted."""


def parse_lsl(listing: str) -> dict[str, int]:
    sizes = {}
    for line in listing.splitlines():
        parts = line.split(maxsplit=3)  # size, date, time, name (names keep their spaces)
        if len(parts) == 4 and parts[0].isdigit():
            sizes[parts[3]] = int(parts[0])
    return sizes


def remote_sizes(dest: str) -> dict[str, int]:
    proc = subprocess.run(["rclone", "lsl", dest, "--max-depth", "1"], capture_output=True, text=True,
                          errors="replace")
    if proc.returncode != 0:
        raise PurgeError(f"cannot list {dest}: {(proc.stdout + proc.stderr).strip()[-500:]}")
    return parse_lsl(proc.stdout)


def check_stage(stage: Path, cache_root: Path) -> Path:
    if stage.is_symlink():
        raise PurgeError(f"{stage} is a symlink; only a real stage folder is purged")
    stage, root = stage.resolve(), cache_root.resolve()
    if stage.parent != root or stage.name.startswith(("_", ".")):
        raise PurgeError(f"{stage} is not an episode stage directly under {root}")
    if not (stage / "job.yaml").is_file():
        raise PurgeError(f"{stage} has no job.yaml, so it is not an episode stage")
    return stage


def check_published(stage: Path, dest: str) -> None:
    outputs = stage / "outputs"
    local = {p.name: p.stat().st_size for p in outputs.iterdir()
             if p.is_file() and not fnmatch.fnmatch(p.name, UNPUBLISHED)} if outputs.is_dir() else {}
    if not any(name.endswith(".mp4") for name in local):
        raise PurgeError(f"{outputs} holds no mp4, so nothing was published from this stage")
    remote = remote_sizes(dest)
    differ = {name: (size, remote.get(name)) for name, size in local.items() if remote.get(name) != size}
    if differ:
        raise PurgeError(f"not at {dest} with the same size (local, remote): {differ}")


def tree_bytes(path: Path) -> int:
    # os.walk never descends into a linked folder, and lstat sizes a link as the link itself.
    return sum(os.lstat(os.path.join(top, name)).st_size for top, _, files in os.walk(path) for name in files)


def purge(stage: Path, published_to: str, cache_root: Path = CACHE_ROOT) -> tuple[list[Path], int, Path | None]:
    """Delete the stage and its -dl/-kcpu/-colab/-vps siblings once its outputs are published.
    Returns the deleted folders, the bytes freed and where the review folder was kept."""
    stage = check_stage(stage, cache_root)
    check_published(stage, published_to)
    review, kept = stage / ".videotool/review", stage.parent / f"{stage.name}{REVIEW_SUFFIX}"
    if kept.is_symlink():
        raise PurgeError(f"{kept} is a symlink; the review folder would be moved through it")
    if review.is_dir():
        if kept.is_dir():
            shutil.rmtree(kept)  # an earlier render of the same episode
        shutil.move(str(review), str(kept))
    targets = [stage, *(stage.parent / f"{stage.name}{suffix}" for suffix in SIBLING_SUFFIXES)]
    targets = [t for t in targets if t.is_dir() and not t.is_symlink()]
    freed = sum(tree_bytes(t) for t in targets)
    for target in targets:
        shutil.rmtree(target)  # unlinks symlinks inside the tree, never follows them
    return targets, freed, kept if kept.is_dir() else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("stage", type=Path, help="the episode stage, ~/.cache/videotool/<name>")
    parser.add_argument("--published-to", required=True,
                        help="where STAGE/outputs was published, e.g. gdrive:…/Chap 71/outputs")
    args = parser.parse_args(argv)
    try:
        removed, freed, kept = purge(args.stage.expanduser(), args.published_to, CACHE_ROOT)
    except PurgeError as exc:
        print(f"FAILED: {exc}; nothing deleted")
        return 1
    print(f"freed {freed / 1e9:.2f} GB: deleted {', '.join(p.name for p in removed)}"
          + (f"; review kept in {kept}" if kept else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
