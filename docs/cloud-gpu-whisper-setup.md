# Cloud GPU whisper pre-compute — setup

Offload **only** Vietnamese transcription at `large-v3` quality to a free Kaggle/Colab T4
GPU, driven from a Google Drive job-folder path. The notebook is LLM-free and whisper-only:
it reads just the narration `voice.*` + the polished `*_vi.txt` script and writes
`captions.srt` (+ `chapters.json` when the script has ≥3 `Chương` markers) back to the same
Drive folder. The local machine still runs `videotool render` (CPU render is faster than cloud
CPU). Creative decisions (mood/overlay/SFX/description) stay with Claude locally.

Two interchangeable runners — pick whichever has GPU quota left, both on the same Drive folder:

| Runner | File | I/O | When |
|--------|------|-----|------|
| Kaggle (primary) | `Colab/kaggle_runner.ipynb` | rclone (no Drive mount) | 30h/week T4 |
| Colab (backup)   | `Colab/colab_runner.ipynb` | `drive.mount` | Kaggle quota spent |

Shared core: `Colab/videotool_cloud.py` (`setup` / `ensure_job_yaml` / `run_whisper`).

## One-time install model

Default install is the **public git repo** — identical one-liner on both platforms, no wheel
rebuild per change:

```python
vc.setup()  # repo_ref = "git+https://github.com/pnd4189/video-tool@main"
```

This requires the repo (or a tagged release) be **PUBLIC**. To pin a reproducible build, tag a
release and pass `vc.setup("git+https://github.com/pnd4189/video-tool@v0.1")`.

**If the repo must stay private:** build a wheel locally and stage it on Drive, then point
`setup()` at it:

```bash
python -m build                       # produces dist/videotool-*.whl
rclone copy dist/videotool-*.whl gdrive:_VIDEOTOOL_SHARED/
```
```python
vc.setup("/content/drive/MyDrive/_VIDEOTOOL_SHARED/videotool-0.1-py3-none-any.whl")
```

No HF token is needed — `large-v3` (`Systran/faster-whisper-large-v3`) is a public model,
downloaded from HuggingFace at runtime each session (no Drive model cache; rclone-down isn't
faster). If anonymous HF rate-limits ever appear, add `HF_TOKEN` once per account (Kaggle Secret
/ Colab `userdata`) — deferred, not wired by default.

## Drive layout: `_VIDEOTOOL_SHARED/`

Create `gdrive:_VIDEOTOOL_SHARED/` once and upload the cloud core:

```bash
rclone copy Colab/videotool_cloud.py gdrive:_VIDEOTOOL_SHARED/
# (+ the wheel above ONLY if the repo is private)
```

Deferred (NOT needed for whisper-only; add when render moves to cloud): `overlays/`,
`sfx/{dao-si,binh-thien}/`, `fonts/`.

## Kaggle runner

1. **Secret:** Add-ons → Secrets → create `RCLONE_CONF` = the full text of your local
   `~/.config/rclone/rclone.conf` (including the `[gdrive]` block with its `token`). Set once per
   Kaggle account. Refresh the secret if the token expires (the notebook fails fast at
   `rclone listremotes`).
2. **Notebook settings:** Accelerator → **GPU T4**, Internet → **On**. (`kernel-metadata.json`
   already encodes `enable_gpu` + `enable_internet` if you push via the Kaggle API.)
3. Edit `JOB_REMOTE` to your Drive folder, e.g.
   `JOB_REMOTE = "gdrive:1. YOUTUBE AUDIO/<series>/CHAP N"`.
4. Run all cells. Only audio + `*_vi.txt` (+ job.yaml / `_creative/`) are transferred — no
   Image/Video/Parallax/Music, so there is no 50-file gdown cap.

## Colab runner

1. Runtime → Change runtime type → **T4 GPU**.
2. Run the mount cell, authorize Drive.
3. Edit `JOB_DIR` to the mounted folder, e.g.
   `JOB_DIR = "/content/drive/MyDrive/1. YOUTUBE AUDIO/<series>/CHAP N"`.
   For a shared drive use `/content/drive/Shareddrives/...` instead of `MyDrive`.
4. Run all cells; whisper reads the voice in place and writes outputs back to `JOB_DIR/outputs/`.

## Back on the local machine

The returned `captions.srt` / `chapters.json` drop into the job's `outputs/` on Drive. Pull the
folder locally (rclone/stage as usual) and run the normal render step — `videotool render` picks
up the existing `outputs/captions.srt`; paste `chapters.json` timings into the YouTube description
via `package`. No local `transcribe` re-run needed.

## job.yaml resolution

`ensure_job_yaml` prefers a Claude-pushed `_creative/job.yaml` seed, else the folder's own
`job.yaml`, else synthesizes one via `videotool init-job`. It always forces
`assets.policy: allow-missing-local` + `captions.mode: off` (init-job's `licensed-only` /
`srt-only` defaults would fail the validate run inside `transcribe`), points `inputs.script` at
the detected `*_vi.txt`, and creates an empty `media/` dir so validation passes for the
image-less whisper-only job.

## Notes

- No tokens/secrets are committed to the repo — `RCLONE_CONF` lives only in the Kaggle Secret.
- `large-v3` on a 49-min clip finishes in minutes on a T4, well under the session limit.
- Parallax keeps its existing separate Kaggle flow; this notebook does not touch it.
