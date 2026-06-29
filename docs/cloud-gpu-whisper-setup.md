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

Shared core: `Colab/videotool_cloud.py` (`setup` / `ensure_job_yaml` / `ensure_model_cache` / `run_whisper`). Re-upload it to `gdrive:_VIDEOTOOL_SHARED/` after editing (the runner copies it from there at cell 2): `rclone copy Colab/videotool_cloud.py gdrive:_VIDEOTOOL_SHARED/`.

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

No HF token is needed — `large-v3` (`Systran/faster-whisper-large-v3`) is a public model.
If anonymous HF rate-limits ever appear, add `HF_TOKEN` once per account (Kaggle Secret
/ Colab `userdata`) — deferred, not wired by default.

## Drive caches (model + wheels) — one-time, reused every later session

`run_whisper(model_cache_dir=...)` downloads the model ONCE to a Drive folder and passes
that local path as `--model`, so later sessions load it straight from Drive instead of
re-downloading ~3GB each run. `setup(wheelhouse=...)` does the same for the faster-whisper
pip wheels. Both live under `gdrive:_VIDEOTOOL_SHARED/`:

| Cache | Path | First run | Later runs |
|-------|------|-----------|------------|
| Model | `_VIDEOTOOL_SHARED/models/large-v3/` | `snapshot_download` ~3GB (real files, no symlinks — Drive FUSE can't create them) | `config.json` present → skip download, `--model <path>` |
| Wheels | `_VIDEOTOOL_SHARED/wheelhouse/` | install from network, `pip download` copies resolved wheels there | `pip install --find-links <wheelhouse>` (no PyPI re-fetch) |

The model download uses `huggingface_hub.snapshot_download(local_dir=...)`, NOT the HF blob
cache — the blob cache uses symlinks, which the Drive FUSE mount cannot create, so it would
break. `ensure_model_cache()` detects a completed download by `config.json`; a partial one
must be deleted (`rclone purge _VIDEOTOOL_SHARED/models/large-v3`) before re-running. `torch`
is NOT cached — Colab's GPU image ships a CUDA torch already and the `ai` extra doesn't pull
it (faster-whisper uses CTranslate2).

## One persistent Colab notebook (no scratchpad sprawl)

By default `open_colab_browser_connection` opens `colab.research.google.com/notebooks/empty.ipynb`
— Colab's unsaved **scratchpad** — so every new session spawns a fresh throwaway notebook. To
reuse ONE notebook and just re-point `JOB_DIR` each run, the live runner lives on Drive at
`gdrive:_VIDEOTOOL_SHARED/colab_runner.ipynb` (a copy of `Colab/colab_runner.ipynb`), and the
`colab-mcp` package is patched to open it instead of the scratchpad:

```bash
# File ID of gdrive:_VIDEOTOOL_SHARED/colab_runner.ipynb
ID=$(rclone lsjson gdrive:_VIDEOTOOL_SHARED/colab_runner.ipynb | python3 -c 'import sys,json;print(json.load(sys.stdin)[0]["ID"])')
F=/home/dung/.local/share/uv/tools/colab-mcp/lib/python3.14/site-packages/colab_mcp/websocket_server.py
sed -i -E 's|^SCRATCH_PATH = .*|SCRATCH_PATH = "/drive/'"$ID"'"  # VideoTool persistent whisper runner|' "$F"
```

Re-apply after `uv tool upgrade colab-mcp` (it overwrites site-packages) or if the notebook's
Drive file ID changes (re-upload → re-fetch ID → re-sed). The patch takes effect on the NEXT
`colab-mcp` server start (the running session already imported the old constant).

**Per-run workflow** (no new scratchpad): the user asks to run cloud whisper →
`open_colab_browser_connection` opens `colab_runner.ipynb` with the proxy token injected →
edit the `JOB_DIR` cell to the target folder → Run All (mount → install+GPU check → whisper →
confirm). The `large-v3` model + wheels load from the Drive caches; only `JOB_DIR` changes.

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
