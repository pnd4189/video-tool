---
phase: 2
title: "Cloud core module"
status: done
effort: "M"
---

# Phase 2: Cloud core module (`videotool_cloud.py`)

## Overview
A single platform-agnostic module both notebooks import, so Kaggle/Colab differ only in I/O. Holds
install + job-resolve + GPU-whisper logic. No Drive/rclone code here (that is injected by the runners).

## Requirements
- Functional: `run_whisper(job_dir, model, device, compute_type)` produces
  `<job_dir>/outputs/captions.srt` (+ `chapters.json` when ≥3 chương) by shelling to the Phase-1 CLI.
- Non-functional: whisper-only — never reads `Image/`, `Video/`, `Parallax/`, `Music/`, overlays, sfx;
  only `voice.*` + `*_vi.txt`. Idempotent; safe to re-run.

## Architecture
`Colab/videotool_cloud.py` exposes:
<!-- Updated: Validation Session 1 - install via git+https primary (wheel fallback); model large-v3; no HF token -->
- `setup(repo_ref)` — `pip install` videotool + `[ai]` extra + faster-whisper; assert ffmpeg + report
  `torch.cuda.is_available()`. `repo_ref` default = `git+https://github.com/pnd4189/video-tool@<tag>`
  (PRIMARY, identical on Kaggle + Colab; requires public repo/release); accepts a Drive-staged wheel
  path as the private fallback. No HF token needed for `large-v3` (public model).
- `ensure_job_yaml(job_dir)` — if no `job.yaml`, run `videotool init-job` to synthesize a minimal one
  (voice auto-detected); else use the `_creative/job.yaml` seed Claude pushed. Set
  `inputs.script` to the detected `*_vi.txt` if unset. Whisper needs only voice + script + a valid job.
- `run_whisper(job_dir, model, device, compute_type)` — call
  `videotool transcribe <job.yaml> --model <model> --device <device> --compute-type <compute_type>
   --script <*_vi.txt>`; return `(captions_path, chapters_path|None)`.
- `detect_voice(job_dir)` / `detect_script(job_dir)` — mirror the CLI convention (`voice.*`, `*_vi.txt`).

## Related Code Files
- Create: `Colab/videotool_cloud.py`
- Reference (no edit): `src/videotool/cli/main.py` (transcribe surface from Phase 1), `AGENTS.md` (conventions)

## Implementation Steps
1. Write `setup()`: pip install (default `pip install "git+https://github.com/pnd4189/video-tool@<tag>"`,
   or a Drive-staged wheel when `repo_ref` is a path), `pip install faster-whisper`, print CUDA +
   ffmpeg versions; raise a clear error if no GPU when `device==cuda` requested.
2. `detect_voice`/`detect_script`: glob the job dir for `voice.*`/audio ext and `*_vi.txt`.
3. `ensure_job_yaml`: create via `videotool init-job` when absent; force `assets.policy:
   allow-missing-local` and `captions.mode: off` so `validate` (run inside transcribe) passes with no
   asset index; set `inputs.script`.
4. `run_whisper`: subprocess the Phase-1 CLI with GPU flags; stream logs; verify outputs exist; return paths.
5. Smoke-test locally on CPU: `run_whisper(test_job, "<local-base-path>", "cpu", "int8")` against a
   short voice clip → captions.srt present. (Proves the module before notebook wiring; cloud uses
   `large-v3` on `cuda`/`float16`.)

## Success Criteria
- [ ] `run_whisper` on a local job dir (voice + `*_vi.txt`) writes `outputs/captions.srt`
- [ ] Reads only voice + script (no image/video/parallax access)
- [ ] `ensure_job_yaml` makes `validate` pass without an asset index
- [ ] Module has zero platform-specific (Drive/rclone) code

## Risk Assessment
- `init-job` defaults to `licensed-only` + `captions: srt-only` (known pitfalls) → `ensure_job_yaml`
  must rewrite to `allow-missing-local` / `mode: off` or transcribe's internal validate fails.
- Private repo install → keep `repo_ref` pluggable so the runner can pass a Drive-staged wheel.
