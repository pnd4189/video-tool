"""Platform-agnostic cloud GPU pre-compute core for VideoTool (whisper-only).

Both the Kaggle and Colab runner notebooks import this module so they differ only in
their Drive I/O shim. It holds install + job-resolve + GPU-whisper logic and never reads
Image/, Video/, Parallax/, Music/, overlays or sfx — only the narration voice and the
polished `*_vi.txt` script. No Drive/rclone code lives here; the runners inject that.

Model default on cloud is `large-v3` on `cuda`/`float16`; downloaded from public
HuggingFace at runtime (no HF token, no Drive model cache).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_REPO_REF = "git+https://github.com/pnd4189/video-tool@main"
AUDIO_EXTS = (".wav", ".mp3", ".m4a")


def setup(repo_ref: str = DEFAULT_REPO_REF) -> None:
    """Install videotool + AI extras and report the GPU/ffmpeg environment.

    `repo_ref` defaults to a public git install (identical on Kaggle + Colab). Pass a
    Drive-staged wheel path instead when the repo must stay private.
    """
    if repo_ref.endswith(".whl") or Path(repo_ref).suffix == ".whl":
        spec = f"{repo_ref}[ai]"
    else:
        # git+https refs need the extras suffix appended to the spec, not the URL.
        spec = f"videotool[ai] @ {repo_ref}" if repo_ref.startswith("git+") else f"{repo_ref}[ai]"
    _pip_install(spec)
    _pip_install("faster-whisper")

    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg not found after install; the cloud image is missing it.")
    print("ffmpeg:", shutil.which("ffmpeg"))
    try:
        import torch  # noqa: PLC0415

        print("torch:", torch.__version__, "cuda available:", torch.cuda.is_available())
    except ImportError:
        print("torch not importable (CPU-only smoke test is fine; GPU runs need it).")


def detect_voice(job_dir: Path) -> Path:
    """Find the narration audio the same way the CLI convention expects (`voice.*`)."""
    job_dir = Path(job_dir)
    for ext in AUDIO_EXTS:
        candidate = job_dir / f"voice{ext}"
        if candidate.exists():
            return candidate
    matches = [p for p in sorted(job_dir.iterdir()) if p.suffix.lower() in AUDIO_EXTS]
    if not matches:
        raise FileNotFoundError(f"No voice audio ({', '.join(AUDIO_EXTS)}) found in {job_dir}")
    return matches[0]


def detect_script(job_dir: Path) -> Path | None:
    """Find the polished Vietnamese narration script; returns None when absent.

    Real chapter folders name it `*_vi_qa.txt` (QA-finalised) or plain `*_vi.txt`, and
    also carry `*_vi_image_prompts.txt` / `*_vi_music_prompts.txt` that are NOT scripts.
    Match `*_vi*.txt`, drop the prompt files, then prefer the QA script.
    """
    candidates = [p for p in sorted(Path(job_dir).glob("*_vi*.txt")) if "prompt" not in p.name.lower()]
    if not candidates:
        return None
    for suffix in ("_vi_qa.txt", "_vi.txt"):
        for p in candidates:
            if p.name.endswith(suffix):
                return p
    return candidates[0]


def ensure_job_yaml(job_dir: Path) -> Path:
    """Return a valid `job.yaml` for the job dir.

    Prefer a Claude-pushed `_creative/job.yaml` seed, else the job dir's own job.yaml,
    else synthesize one via `videotool init-job`. Always force whisper-safe settings:
    `assets.policy: allow-missing-local` and `captions.mode: off` (init-job's defaults of
    licensed-only / srt-only would fail the validate run inside transcribe), and point
    `inputs.script` at the detected `*_vi.txt`.
    """
    job_dir = Path(job_dir)
    job_yaml = job_dir / "job.yaml"
    seed = job_dir / "_creative" / "job.yaml"
    if seed.exists() and not job_yaml.exists():
        shutil.copy(seed, job_yaml)

    if not job_yaml.exists():
        voice = detect_voice(job_dir)
        _run_cli(["init-job", str(job_dir), "--voice", voice.name, "--media", "media"])

    _harden_job_yaml(job_yaml, job_dir)
    return job_yaml


def run_whisper(
    job_dir: Path,
    model: str = "large-v3",
    device: str = "cuda",
    compute_type: str = "float16",
) -> tuple[Path, Path | None]:
    """Run GPU whisper via the Phase-1 CLI; return (captions_path, chapters_path|None)."""
    job_dir = Path(job_dir)
    job_yaml = ensure_job_yaml(job_dir)
    script = detect_script(job_dir)

    cmd = ["transcribe", str(job_yaml), "--model", model, "--device", device, "--compute-type", compute_type]
    if script is not None:
        cmd += ["--script", str(script)]
    _run_cli(cmd)

    captions = job_dir / "outputs" / "captions.srt"
    if not captions.exists():
        raise RuntimeError(f"transcribe finished but {captions} is missing.")
    chapters = job_dir / "outputs" / "chapters.json"
    return captions, (chapters if chapters.exists() else None)


# -- internals ---------------------------------------------------------------------------


def _pip_install(spec: str) -> None:
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", spec], check=True)


def _run_cli(args: list[str]) -> None:
    """Invoke the installed `videotool` console script, streaming its logs."""
    exe = shutil.which("videotool") or "videotool"
    subprocess.run([exe, *args], check=True)


def _harden_job_yaml(job_yaml: Path, job_dir: Path) -> None:
    import yaml  # noqa: PLC0415

    data = yaml.safe_load(job_yaml.read_text(encoding="utf-8")) or {}
    data.setdefault("assets", {})["policy"] = "allow-missing-local"
    data.setdefault("captions", {})["mode"] = "off"

    inputs = data.setdefault("inputs", {})
    if not inputs.get("script"):
        script = detect_script(job_dir)
        if script is not None:
            inputs["script"] = script.name
    job_yaml.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")

    # Whisper-only jobs ship no images, but validate (run inside transcribe) checks that
    # the referenced media dir exists. Create it empty so validation passes.
    media_dir = inputs.get("media_dir", "media")
    (job_dir / media_dir).mkdir(parents=True, exist_ok=True)
