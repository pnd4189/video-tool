"""job.yaml assembler for the cloud render path — turns a staged asset folder into a validated,
pinned `job.yaml` for the Kaggle/Colab render box.

Architecture (revised 2026-07-11): **Claude Code CLI is the director.** Claude (Opus) reads the
folder and authors a small `creative.yaml` (music_schedule, SFX cues, mood, atmosphere overlay,
description/recap) locally — the same intelligent work it does for the local `/make-video`,
including confirming the overlay with the user. The render box just runs the DETERMINISTIC
pre-steps (init/storyboard/SRT/chapters/parallax/CTA-detection) and `apply_creative()` — **no LLM
runs on the render box.** Then it hard-gates the result (`videotool validate` + encoder/SFX/overlay
pre-render checks the CLI does NOT cover) BEFORE any GPU time.

The on-box LLM tasks (music_schedule/SFX/description via the Kaggle Model Proxy or a direct key)
survive as an `autonomous=True` FALLBACK for running the notebook without Claude in the loop — but
they author lower-quality output (the probe showed only `google/gemini-3.5-flash` even works on the
Kaggle proxy), so the Claude-authored `creative.yaml` path is the default.

Design decisions (see plan 260707-0855):
- `render.max_inline_scenes: 1` forces the resumable segmented render path. The plan wrote
  "0" but the schema (`job_spec.py:264`) requires `> 0`; `1` sends every job with >=2 scenes
  down the segmented path, same intent, no shared-code change.
- Idempotent (red-team H4): a pinned, already-validated job.yaml makes `run()` a NO-OP, so a
  resume never re-calls the LLM. The pin marker lives at `<job>/.videotool/.cloud_director.pinned`;
  the runner restores it (with job.yaml) from the Drive checkpoint before resuming.
- Providers: on Kaggle (primary) the LLM credit is the Benchmarks **Model Proxy** — an OpenAI-
  compatible endpoint provisioned by `kaggle benchmarks init` (no personal key). Probing this
  account (2026-07-11) showed the Anthropic/GLM/Qwen slugs 503 and only `google/gemini-3.5-flash`
  up + correct on the Vietnamese homograph test, so that is the proxy default. Direct-key
  providers (gemini / anthropic / glm) remain for Colab or as fallback.
- Keys are read from platform Secrets, kept in memory, never written to disk/Drive, redacted
  from every log line (M11).
- LLM output is never trusted: JSON-schema shaped + code-side post-filters cap SFX density /
  spacing / CTA-skip regions and verify music-cue coverage; a hallucinated encoder or an
  escaping SFX path aborts before render (H8).

No dependency beyond the stdlib + `yaml` (already a videotool dep); LLM calls use urllib.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

import yaml

# Reuse the whisper runner's install-agnostic CLI shim + asset detectors (DRY).
import videotool_cloud as vc

FORCE_SEGMENTED_INLINE_CAP = 1  # schema forbids 0; 1 forces segmented for any >=2-scene job.
PIN_MARKER = Path(".videotool") / ".cloud_director.pinned"

# Kaggle's Benchmarks Model Proxy: `kaggle benchmarks init` writes a `.env` with an OpenAI-compatible
# endpoint (MODEL_PROXY_URL) + a short-lived key (MODEL_PROXY_API_KEY), funded by the account's LLM
# credit. This is the PRIMARY provider on Kaggle — no personal API key needed. Empirically (probe
# 2026-07-11 on this account) the Anthropic/GLM/Qwen slugs 503 and only google/gemini-3.5-flash is
# reliably up AND passes the Vietnamese homograph SFX test, so it is the default proxy model.
KAGGLE_PROXY_DEFAULT_MODEL = "google/gemini-3.5-flash"

# SFX density / placement rules (AGENTS.md audio-story defaults).
SFX_MAX_CUES = 15
SFX_MIN_SPACING_S = 30.0  # >= 30-60s between clustered cues
SFX_SKIP_HEAD_S = 30.0    # skip the first 30s (intro / CTA region)
SFX_SKIP_TAIL_S = 25.0    # skip the last 25s (outro / CTA region)
SFX_GAIN_DB = -11.0       # point-SFX sit -8..-15 dB under the un-ducked voice

# Channel -> sfx pack (AGENTS.md): kiếm hiệp -> binh-thien, ma hài -> dao-si.
SFX_PACK_KEYWORDS = {
    "binh-thien": ("kiếm", "hiệp", "tiên", "tu", "đạo", "chưởng", "giang hồ"),
    "dao-si": ("ma", "hài", "quỷ", "yêu", "đạo sĩ", "bùa"),
}

_REDACT_KEYS = ("GLM_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY")


# -- Secrets + LLM providers -------------------------------------------------------------


class DirectorError(RuntimeError):
    """Fatal cloud_director error — raised with a message safe to print (no secrets)."""


def get_secret(name: str) -> str | None:
    """Read a Secret from Colab userdata, then Kaggle secrets, then the environment.

    Returns None when absent so the caller can pick another provider. The value is never
    logged; callers keep it in memory only.
    """
    try:  # Colab
        from google.colab import userdata  # noqa: PLC0415

        value = userdata.get(name)
        if value:
            return value
    except Exception:  # not on Colab, or secret not granted
        pass
    try:  # Kaggle
        from kaggle_secrets import UserSecretsClient  # noqa: PLC0415

        value = UserSecretsClient().get_secret(name)
        if value:
            return value
    except Exception:  # not on Kaggle, or secret missing
        pass
    return os.environ.get(name) or None


def _kaggle_proxy() -> tuple[str, str] | None:
    """Return (base_url, key) for the Kaggle Model Proxy, or None when it isn't provisioned.

    Reads MODEL_PROXY_URL / MODEL_PROXY_API_KEY from the environment first, then from a `.env` in
    the cwd (what `kaggle benchmarks init` writes). No personal key — the account's credit funds it.
    """
    url, key = os.environ.get("MODEL_PROXY_URL"), os.environ.get("MODEL_PROXY_API_KEY")
    if not (url and key):
        env = Path(".env")
        if env.exists():
            values = dict(
                line.split("=", 1)
                for line in env.read_text().splitlines()
                if "=" in line and not line.lstrip().startswith("#")
            )
            url = url or values.get("MODEL_PROXY_URL", "").strip()
            key = key or values.get("MODEL_PROXY_API_KEY", "").strip()
    return (url.rstrip("/"), key) if url and key else None


def _provider_available(provider: str) -> bool:
    if provider == "kaggle":
        return _kaggle_proxy() is not None
    key_for = {"glm": "GLM_API_KEY", "gemini": "GEMINI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}
    return bool(get_secret(key_for.get(provider, "")))


def choose_provider(preferred: str | None = None) -> str:
    """Pick an available provider. Kaggle's Model Proxy wins by default (its credit funds a strong
    model — google/gemini-3.5-flash — with no personal key); then direct keys, best-quality-first.
    `preferred` overrides. Raises with an actionable message when nothing is available."""
    order = [preferred] if preferred else []
    order += ["kaggle", "anthropic", "gemini", "glm"]
    for provider in order:
        if provider and _provider_available(provider):
            return provider
    raise DirectorError(
        "No LLM available. On Kaggle run `kaggle benchmarks init -y` first (Model Proxy), or add a "
        "GEMINI_API_KEY / ANTHROPIC_API_KEY / GLM_API_KEY Secret (Colab userdata / Kaggle Secrets)."
    )


def _redact(text: str) -> str:
    """Strip any live key value out of a string before it reaches a log/exception."""
    values = [get_secret(name) for name in _REDACT_KEYS]
    proxy = _kaggle_proxy()
    if proxy:
        values.append(proxy[1])  # the short-lived Model Proxy key
    for value in values:
        if value and value in text:
            text = text.replace(value, "***REDACTED***")
    return text


def _http_json(url: str, payload: dict, headers: dict, timeout: int = 120) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = _redact(exc.read().decode("utf-8", errors="replace"))
        raise DirectorError(f"LLM HTTP {exc.code}: {detail[:400]}") from None
    except urllib.error.URLError as exc:
        raise DirectorError(f"LLM request failed: {_redact(str(exc.reason))}") from None


def call_llm(provider: str, system: str, user: str) -> str:
    """Return the raw text response from the chosen provider, asking for JSON output.

    Providers share this signature so the caller stays provider-agnostic; JSON parsing +
    schema checks happen in `_ask_json`.
    """
    if provider == "kaggle":
        proxy = _kaggle_proxy()
        if not proxy:
            raise DirectorError("Kaggle Model Proxy not provisioned; run `kaggle benchmarks init -y` first.")
        base, key = proxy
        model = os.environ.get("KAGGLE_PROXY_MODEL", KAGGLE_PROXY_DEFAULT_MODEL)
        data = _http_json(
            f"{base}/openapi/v1/chat/completions",
            {
                "model": model,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "temperature": 0.3,
            },
            {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        )
        return data["choices"][0]["message"]["content"]
    if provider == "glm":
        key = get_secret("GLM_API_KEY")
        data = _http_json(
            "https://open.bigmodel.cn/api/paas/v4/chat/completions",
            {
                "model": "glm-4-flash",
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "response_format": {"type": "json_object"},
                "temperature": 0.3,
            },
            {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        )
        return data["choices"][0]["message"]["content"]
    if provider == "gemini":
        key = get_secret("GEMINI_API_KEY")
        # gemini-2.5-flash: the 2.0 line was retired June 2026. 2.5-flash keeps JSON mode + a free tier.
        data = _http_json(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={key}",
            {
                "contents": [{"parts": [{"text": user}]}],
                "systemInstruction": {"parts": [{"text": system}]},
                "generationConfig": {"responseMimeType": "application/json", "temperature": 0.3},
            },
            {"Content-Type": "application/json"},
        )
        return data["candidates"][0]["content"]["parts"][0]["text"]
    if provider == "anthropic":
        key = get_secret("ANTHROPIC_API_KEY")
        data = _http_json(
            "https://api.anthropic.com/v1/messages",
            {
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 4096,
                "system": system + "\nRespond with ONLY a JSON object, no prose.",
                "messages": [{"role": "user", "content": user}],
                "temperature": 0.3,
            },
            {"x-api-key": key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"},
        )
        return data["content"][0]["text"]
    raise DirectorError(f"Unknown provider '{provider}'.")


def _ask_json(provider: str, system: str, user: str, required: tuple[str, ...], retries: int = 2) -> dict:
    """Call the LLM, parse JSON, and confirm the required top-level keys exist. Retries on
    malformed JSON / missing keys by feeding the fault back, then raises."""
    last_error = ""
    prompt = user
    for _ in range(retries + 1):
        raw = call_llm(provider, system, prompt)
        try:
            obj = json.loads(_strip_fences(raw))
            missing = [k for k in required if k not in obj]
            if missing:
                raise ValueError(f"missing keys: {missing}")
            return obj
        except (json.JSONDecodeError, ValueError) as exc:
            last_error = str(exc)
            prompt = f"{user}\n\nYour previous reply was invalid ({last_error}). Return valid JSON with keys {list(required)}."
    raise DirectorError(f"LLM did not return valid JSON after retries: {last_error}")


# A homograph the pipeline must get right: literal "kiếm" (sword → SFX) vs "kiếm" (to seek → no SFX).
_PROBE_SYSTEM = (
    "You add one-shot sound effects to a Vietnamese audiobook. Only PHYSICAL actions get a cue; "
    "skip metaphors/homographs. Return JSON {\"cues\":[{\"time\":sec,\"file\":\"name\"}]} using ONLY "
    "the given files."
)
_PROBE_USER = (
    "Available SFX files: [\"sword-clash.wav\", \"thunder.wav\"]\n"
    "Timestamped narration:\n"
    "[12.0] Hắn rút kiếm, hai thanh kiếm chạm nhau chan chát.\n"   # literal sword clash -> cue
    "[40.0] Suốt đời hắn chỉ kiếm tiền, chưa từng thấy vui.\n"      # 'kiếm tiền' = earn money -> NO cue
    "[70.0] Một tiếng sấm nổ vang trời."                            # thunder -> cue
)


def probe_providers(providers: tuple[str, ...] = ("kaggle", "anthropic", "gemini", "glm")) -> list[dict]:
    """Empirically test each available provider against a real pipeline task (Vietnamese homograph
    SFX selection). Prints a table + a recommendation. Run this in the Kaggle/Colab notebook (after
    `kaggle benchmarks init` for the proxy, or with your Secrets loaded) — it uses YOUR credit and
    answers 'which LLM is best for this pipeline' with evidence, not guesswork. On this account
    (probe 2026-07-11) kaggle=google/gemini-3.5-flash was the only one up + correct."""
    import time  # noqa: PLC0415

    results = []
    for provider in providers:
        if not _provider_available(provider):
            print(f"  {provider:10} — not available, skipped")
            continue
        row: dict = {"provider": provider}
        try:
            t0 = time.monotonic()
            obj = _ask_json(provider, _PROBE_SYSTEM, _PROBE_USER, ("cues",))
            row["latency_s"] = round(time.monotonic() - t0, 2)
            times = sorted(round(float(c["time"])) for c in obj.get("cues", []) if "time" in c)
            # Quality = picked the two literal actions (12 sword, 70 thunder) and skipped 40 (earn money).
            row["cue_times"] = times
            row["homograph_ok"] = (12 in times and 70 in times and 40 not in times)
            row["json_ok"] = True
            print(f"  {provider:10} — {row['latency_s']:>5}s  cues@{times}  homograph_ok={row['homograph_ok']}")
        except Exception as exc:  # noqa: BLE001 — probe reports failures, never raises
            row.update(json_ok=False, error=_redact(str(exc))[:120])
            print(f"  {provider:10} — FAILED: {row['error']}")
        results.append(row)

    passed = [r for r in results if r.get("homograph_ok")]
    order = {"kaggle": 0, "anthropic": 1, "gemini": 2, "glm": 3}
    best = min(passed, key=lambda r: (order.get(r["provider"], 9), r["latency_s"]), default=None)
    if best:
        print(f"\nRecommended provider for this pipeline: {best['provider']} "
              f"(passed the VN homograph test, {best['latency_s']}s).")
    else:
        print("\nNo provider passed the homograph test — check keys, or inspect cue_times above.")
    return results


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return text.strip()


# -- Deterministic pre-steps (NO LLM) ----------------------------------------------------


def _run_cli(args: list[str]) -> None:
    vc._run_cli(args)  # list-form subprocess; safe with VN folder names (L12)


def prepare_job(job_dir: Path) -> dict:
    """Run the deterministic AGENTS.md pre-steps and return the loaded job.yaml dict.

    init-job -> harden (allow-missing-local, captions off, script) -> storyboard auto with
    Image/ + Video/ -> copy provided SRT -> chapters-from-srt -> detect intro/ending/CTA ->
    seed audio-story enhance + audio + NVENC encoder + forced-segmented cap.
    """
    job_dir = Path(job_dir)
    job_yaml = vc.ensure_job_yaml(job_dir)  # init-job + policy/captions/script harden

    images = job_dir / "Image"
    videos = job_dir / "Video"
    args = ["storyboard", "auto", str(job_yaml), "--images-dir", str(images if images.exists() else job_dir / "media")]
    if videos.exists():
        args += ["--videos-dir", str(videos)]
    _run_cli(args)

    _copy_provided_srt(job_dir)
    _run_cli(["chapters-from-srt", str(job_yaml)])

    data = yaml.safe_load(job_yaml.read_text(encoding="utf-8")) or {}
    _detect_intro_ending_cta(job_dir, data)
    _seed_audio_story_defaults(job_dir, data)
    _write_job(job_yaml, data)
    return data


def _copy_provided_srt(job_dir: Path) -> None:
    """Copy the user-provided QA SRT to outputs/captions.srt (the burn baseline). No whisper."""
    srts = [p for p in sorted(job_dir.glob("*_vi_qa.srt"))] or [p for p in sorted(job_dir.glob("*.srt"))]
    if not srts:
        return
    out = job_dir / "outputs"
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy(srts[0], out / "captions.srt")


def _detect_intro_ending_cta(job_dir: Path, data: dict) -> None:
    """Filename/subfolder heuristics from AGENTS.md; only set what is unambiguous."""
    inputs = data.setdefault("inputs", {})
    thumbs, ends = [], []
    for p in job_dir.rglob("*"):
        if p.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
            continue
        name = (p.parent.name + " " + p.name).lower()
        if "thumb" in name:
            thumbs.append(p)
        if "end" in name or "outro" in name or "ảnh end" in name:
            ends.append(p)
    if len(thumbs) == 1 and not inputs.get("intro_image"):
        inputs["intro_image"] = str(thumbs[0].relative_to(job_dir))
    if len(ends) == 1 and not inputs.get("ending_image"):
        inputs["ending_image"] = str(ends[0].relative_to(job_dir))

    cta = job_dir / "CTA voice"
    if cta.exists():
        _set_if_present(inputs, "intro_cta", _first_match(cta, ("intro cta - with voice", "intro cta", "cta-intro")))
        _set_if_present(inputs, "outro_cta", _first_match(cta, ("outro cta - with voice", "outro cta", "cta-outro")))


def _first_match(folder: Path, stems: tuple[str, ...]) -> Path | None:
    """Find a CTA clip by stem, preferring an animated video (voice baked, e.g. ĐẠO SĨ's
    `cta-intro.mp4`) over a bare audio file — a plain `sorted()` would pick `cta-intro-voice.mp3`
    first because '-' < '.'. Video across all stems wins, then audio."""
    video = sorted(p for p in folder.iterdir() if p.suffix.lower() in (".mp4", ".mov"))
    audio = sorted(p for p in folder.iterdir() if p.suffix.lower() in (".wav", ".mp3", ".m4a"))
    for group in (video, audio):
        for stem in stems:
            for p in group:
                if stem in p.name.lower():
                    return p
    return None


def _set_if_present(inputs: dict, key: str, path: Path | None) -> None:
    if path is not None and not inputs.get(key):
        inputs[key] = str(path)


def _seed_audio_story_defaults(job_dir: Path, data: dict) -> None:
    """Audio-story channel defaults + cloud render knobs. Does not enable mood FX (default off)."""
    enhance = data.setdefault("enhance", {})
    enhance.setdefault("visualizer", True)
    enhance.setdefault("subtitles", True)
    enhance.setdefault("subtitle_color", "yellow")

    inputs = data.setdefault("inputs", {})
    # `init-job` runs without --music here, so point at the track folder explicitly — without
    # `inputs.music` the whole music bed (and any music_schedule) is silently dropped at render.
    if not inputs.get("music"):
        music_dir = next((d for d in (job_dir / "Music", job_dir / "music") if d.is_dir()), None)
        if music_dir is not None:
            inputs["music"] = music_dir.name
    if not inputs.get("script"):
        script = vc.detect_script(job_dir)
        if script is not None:
            inputs["script"] = script.name
    template = next(iter(sorted(job_dir.glob("*_DESCRIPTION_TEMPLATE.txt"))), None)
    if template and not inputs.get("description_template"):
        inputs["description_template"] = template.name

    render = data.setdefault("render", {})
    render["encoder"] = "h264_nvenc-capped"
    render["max_inline_scenes"] = FORCE_SEGMENTED_INLINE_CAP


# -- LLM tasks ---------------------------------------------------------------------------


def _read(job_dir: Path, pattern: str) -> str:
    matches = sorted(job_dir.glob(pattern))
    return matches[0].read_text(encoding="utf-8") if matches else ""


def _srt_lines(job_dir: Path) -> list[tuple[float, str]]:
    """Parse outputs/captions.srt into (start_seconds, text) pairs for the SFX/chapter prompts."""
    srt = job_dir / "outputs" / "captions.srt"
    if not srt.exists():
        return []
    out: list[tuple[float, str]] = []
    blocks = re.split(r"\n\s*\n", srt.read_text(encoding="utf-8").strip())
    for block in blocks:
        m = re.search(r"(\d\d):(\d\d):(\d\d)[,.](\d\d\d)\s*-->", block)
        if not m:
            continue
        h, mi, s, ms = (int(x) for x in m.groups())
        text = " ".join(block.splitlines()[2:]).strip()
        out.append((h * 3600 + mi * 60 + s + ms / 1000.0, text))
    return out


def _chapter_seconds(data: dict) -> list[tuple[float, str]]:
    return [(c["start"], c["title"]) for c in data.get("project", {}).get("chapters", [])]


def author_music_schedule(provider: str, job_dir: Path, data: dict) -> None:
    """Map each music track to the chapter range whose mood fits; write audio.music_schedule."""
    tracks = sorted((job_dir / "Music").glob("*")) if (job_dir / "Music").exists() else []
    prompts = _read(job_dir, "*_music_prompts.txt") or _read(job_dir, "*music_prompt*.txt")
    chapters = _chapter_seconds(data)
    if len(tracks) < 2 or not prompts or not chapters:
        return  # unset -> concat + loop (schema default)

    voice_end = max((t for t, _ in _srt_lines(job_dir)), default=0.0) or chapters[-1][0] + 60
    system = (
        "You place background-music tracks over an audiobook timeline. Block i of the music "
        "prompts maps to track i (1-based). Return JSON {\"cues\":[{\"track\":int,\"start\":sec,"
        "\"end\":sec}]} covering the whole narration, time-ordered and NON-overlapping. Calm/"
        "scenery scenes get gentle tracks, action/climax get faster ones."
    )
    user = (
        f"Tracks (1..{len(tracks)}): {[t.name for t in tracks]}\n"
        f"Music prompt blocks:\n{prompts[:4000]}\n"
        f"Chapter markers (sec,title): {chapters}\n"
        f"Narration ends at ~{voice_end:.0f}s. Emit {len(tracks)} cues, one per track, in story order."
    )
    obj = _ask_json(provider, system, user, ("cues",))
    cues = _clean_music_cues(obj["cues"], len(tracks), voice_end)
    if cues:
        data.setdefault("audio", {})["music_schedule"] = cues


def _clean_music_cues(raw: list, ntracks: int, voice_end: float) -> list[dict]:
    """Sort, clamp, and drop overlaps so the schedule satisfies job_spec's disjoint validator."""
    cues = []
    for c in raw:
        try:
            track, start, end = int(c["track"]), float(c["start"]), float(c["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if not 1 <= track <= ntracks or end <= start:
            continue
        cues.append({"track": track, "start": max(0.0, start), "end": min(end, voice_end)})
    cues.sort(key=lambda c: c["start"])
    disjoint: list[dict] = []
    for c in cues:
        if disjoint and c["start"] < disjoint[-1]["end"]:
            c["start"] = disjoint[-1]["end"]
        if c["end"] > c["start"]:
            disjoint.append(c)
    return disjoint


def author_sfx_cues(provider: str, job_dir: Path, data: dict, sfx_library: Path, pack: str | None) -> None:
    """Pick unambiguous action SFX from the pack, pin by SRT time, copy into <job>/sfx/."""
    lines = _srt_lines(job_dir)
    pack = pack or _infer_pack(job_dir)
    pack_dir = Path(sfx_library) / pack
    if not lines or not pack_dir.exists():
        return
    available = [p.name for p in sorted(pack_dir.glob("*")) if p.suffix.lower() in (".wav", ".mp3", ".m4a", ".ogg")]
    if not available:
        return

    voice_end = max((t for t, _ in lines), default=0.0)
    transcript = "\n".join(f"[{t:.1f}] {txt}" for t, txt in lines if txt)
    system = (
        "You add one-shot sound effects to an audiobook. Choose ONLY unambiguous physical-action "
        "moments (a sword clash, a door slam, thunder) — skip metaphors and homographs. Return JSON "
        "{\"cues\":[{\"time\":sec,\"file\":\"name.wav\"}]}. Use ONLY files from the provided list. "
        "Be conservative: prefer clarity over quantity."
    )
    user = (
        f"Available SFX files: {available}\n"
        f"Narration ends at ~{voice_end:.0f}s.\n"
        f"Timestamped narration:\n{transcript[:8000]}"
    )
    obj = _ask_json(provider, system, user, ("cues",))
    cues = _filter_sfx_cues(obj["cues"], set(available), voice_end)
    if not cues:
        return
    dest = job_dir / "sfx"
    dest.mkdir(exist_ok=True)
    final = []
    for cue in cues:
        shutil.copy(pack_dir / cue["file"], dest / cue["file"])
        final.append({"time": round(cue["time"], 2), "file": f"sfx/{cue['file']}", "gain_db": SFX_GAIN_DB})
    data.setdefault("enhance", {})["sfx"] = {"enabled": True, "pack": pack, "cues": final}


def _infer_pack(job_dir: Path) -> str:
    text = (_read(job_dir, "*_music_prompts.txt") + " " + _read(job_dir, "*_vi_qa.txt")[:2000]).lower()
    best, score = "binh-thien", 0
    for pack, words in SFX_PACK_KEYWORDS.items():
        hits = sum(text.count(w) for w in words)
        if hits > score:
            best, score = pack, hits
    return best


def _filter_sfx_cues(raw: list, available: set[str], voice_end: float) -> list[dict]:
    """Enforce AGENTS.md density: known files only, skip head/tail CTA regions, min spacing,
    hard cap on count. The model's placement is a suggestion; these caps are the contract."""
    picked: list[dict] = []
    for c in sorted(raw, key=lambda c: c.get("time", 0)):
        try:
            time, name = float(c["time"]), str(c["file"])
        except (KeyError, TypeError, ValueError):
            continue
        if name not in available:
            continue
        if time < SFX_SKIP_HEAD_S or time > voice_end - SFX_SKIP_TAIL_S:
            continue
        if picked and time - picked[-1]["time"] < SFX_MIN_SPACING_S:
            continue
        picked.append({"time": time, "file": name})
        if len(picked) >= SFX_MAX_CUES:
            break
    return picked


def author_description(provider: str, job_dir: Path, data: dict) -> None:
    """Author project.description + project.recap_previous from the vi.txt script."""
    script = _read(job_dir, "*_vi_qa.txt") or _read(job_dir, "*_vi.txt")
    if not script:
        return
    system = (
        "You write YouTube descriptions for a Vietnamese audiobook channel. Return JSON "
        "{\"description\":str,\"recap_previous\":str}. `description` = an engaging 2-3 sentence "
        "summary of THIS episode. `recap_previous` = 1-2 sentences recapping the prior episode "
        "(leave \"\" if unknown). Vietnamese, no spoilers of the ending."
    )
    user = f"Episode script (first part):\n{script[:6000]}"
    obj = _ask_json(provider, system, user, ("description",))
    project = data.setdefault("project", {})
    if obj.get("description"):
        project["description"] = obj["description"].strip()
    if obj.get("recap_previous"):
        project["recap_previous"] = obj["recap_previous"].strip()


def author_chapters_fallback(provider: str, job_dir: Path, data: dict) -> None:
    """Only when chapters-from-srt found <3 markers: derive chapter titles from the narration."""
    if len(data.get("project", {}).get("chapters", [])) >= 3:
        return
    lines = _srt_lines(job_dir)
    if not lines:
        return
    transcript = "\n".join(f"[{t:.1f}] {txt}" for t, txt in lines if txt)
    system = (
        "Split an audiobook into 3-8 chapters. Return JSON {\"chapters\":[{\"start\":sec,"
        "\"title\":str}]}. First chapter starts at 0. Titles in Vietnamese, short."
    )
    obj = _ask_json(provider, system, f"Timestamped narration:\n{transcript[:8000]}", ("chapters",))
    chapters = [
        {"start": max(0.0, float(c["start"])), "title": str(c["title"]).strip()}
        for c in obj["chapters"]
        if str(c.get("title", "")).strip()
    ]
    if len(chapters) >= 3:
        data.setdefault("project", {})["chapters"] = sorted(chapters, key=lambda c: c["start"])


# -- Pre-render gate ---------------------------------------------------------------------


def pre_render_checks(job_dir: Path, job_yaml: Path) -> None:
    """`videotool validate` PLUS the checks it omits (H8): encoder must be a real profile,
    every SFX cue file must exist inside the job folder, and the music bed must be wired.
    Abort BEFORE any GPU time."""
    _run_cli(["validate", str(job_yaml)])  # raises on schema / path errors

    data = yaml.safe_load(job_yaml.read_text(encoding="utf-8")) or {}
    check_music_wiring(Path(job_dir), data)
    encoder = data.get("render", {}).get("encoder", "libx264-balanced")
    valid = _known_profiles()
    if encoder not in valid:
        raise DirectorError(f"render.encoder '{encoder}' is not a known profile ({sorted(valid)}).")

    job_dir = Path(job_dir).resolve()
    for cue in data.get("enhance", {}).get("sfx", {}).get("cues", []):
        path = (job_dir / cue["file"]).resolve()
        if not path.is_relative_to(job_dir):
            raise DirectorError(f"SFX cue escapes job folder: {cue['file']}")
        if not path.exists():
            raise DirectorError(f"SFX cue file missing: {cue['file']}")

    overlay = data.get("inputs", {}).get("particle_overlay")
    if overlay:
        path = (job_dir / overlay).resolve()
        if not path.is_relative_to(job_dir):
            raise DirectorError(f"particle_overlay escapes job folder: {overlay}")
        if not path.exists():
            raise DirectorError(f"particle_overlay file missing: {overlay}")


MUSIC_SUFFIXES = (".mp3", ".wav", ".m4a", ".flac", ".ogg")


def check_music_wiring(job_dir: Path, data: dict) -> None:
    """Abort when the folder ships music tracks but the job would render silent.

    `services._stage_music` drops the whole bed (and any `audio.music_schedule`) unless
    `inputs.music` points at the tracks, so a missing key is a silent quality loss, not an
    error — it has to be caught here, before the GPU time is spent.
    """
    music = data.get("inputs", {}).get("music")
    if music:
        path = job_dir / music
        if not path.exists():
            raise DirectorError(f"inputs.music '{music}' does not exist in the job folder.")
        return

    if data.get("audio", {}).get("music_schedule"):
        raise DirectorError("audio.music_schedule is set but inputs.music is not — the bed would be dropped.")
    for name in ("Music", "music"):
        folder = job_dir / name
        if folder.is_dir() and any(p.suffix.lower() in MUSIC_SUFFIXES for p in folder.iterdir()):
            raise DirectorError(f"'{name}/' holds music tracks but inputs.music is unset — the bed would be dropped.")


def _known_profiles() -> set[str]:
    """The render profiles the installed videotool accepts (import if available, else the
    known set). Kept in sync with `render/profiles.py`."""
    try:
        from videotool.render.profiles import PROFILES  # noqa: PLC0415

        return set(PROFILES)
    except Exception:
        return {"libx264-balanced", "libx264-fast", "libx264-balanced-capped", "h264_nvenc-capped"}


# -- Claude-authored creative merge (DEFAULT path — no on-Kaggle LLM) --------------------


DEFAULT_OVERLAY_LIBRARY = Path.home() / ".local/share/videotool/overlays"


def apply_creative(
    job_dir: Path,
    data: dict,
    creative: dict,
    sfx_library: Path,
    overlay_library: Path,
) -> None:
    """Merge a Claude Code CLI-authored `creative.yaml` into the deterministic job.yaml — the
    DEFAULT authoring path. Claude (Opus) does the intelligent work locally (music_schedule, SFX
    cue selection with VN homograph filtering, mood + atmosphere overlay, description/recap) and
    this just applies it, copying the NAMED sfx + overlay files from the staged libraries into the
    job folder. No LLM runs on the render box.

    creative.yaml shape (all keys optional):
        audio: {music_schedule: [{track,start,end,gain_db?}, ...]}
        enhance:
            mood: cozy            # clean|melancholy|cozy|horror|action
            grain: false          # default false — grain eats the capped bitrate budget
            overlay: fireflies-gen-01.mp4   # filename in the overlay library -> copied into job
            sfx: {pack: dao-si, cues: [{time, file, gain_db?}, ...]}
        project: {description: "...", recap_previous: "..."}
    """
    if creative.get("audio", {}).get("music_schedule"):
        data.setdefault("audio", {})["music_schedule"] = creative["audio"]["music_schedule"]

    proj = creative.get("project", {})
    if proj.get("description"):
        data.setdefault("project", {})["description"] = proj["description"]
    if proj.get("recap_previous"):
        data.setdefault("project", {})["recap_previous"] = proj["recap_previous"]

    enh = creative.get("enhance", {})
    denh = data.setdefault("enhance", {})
    if enh.get("mood"):
        denh["mood"] = enh["mood"]
        # Grain (auto-on for most moods) balloons a capped H264's quality/size — keep it off unless
        # explicitly asked (memory: melancholy-grain-bitrate-blowup).
        denh["grain"] = enh.get("grain", False)
    for key in ("vignette", "glow", "flicker", "color_grade"):
        if key in enh:
            denh[key] = enh[key]

    overlay = enh.get("overlay")
    if overlay:
        src = Path(overlay_library) / overlay
        if not src.exists():
            raise DirectorError(f"overlay '{overlay}' not found in library {overlay_library}")
        shutil.copy(src, job_dir / src.name)  # validation requires the overlay INSIDE the job
        data.setdefault("inputs", {})["particle_overlay"] = src.name
        denh["atmosphere"] = True

    sfx = enh.get("sfx")
    if sfx and sfx.get("cues"):
        pack = sfx.get("pack") or _infer_pack(job_dir)
        pack_dir = Path(sfx_library) / pack
        dest = job_dir / "sfx"
        dest.mkdir(exist_ok=True)
        final = []
        for cue in _filter_sfx_cues(
            [{"time": c["time"], "file": Path(c["file"]).name} for c in sfx["cues"]],
            {p.name for p in pack_dir.glob("*")},
            max((t for t, _ in _srt_lines(job_dir)), default=1e9),
        ):
            src = pack_dir / cue["file"]
            if not src.exists():
                raise DirectorError(f"sfx cue '{cue['file']}' not found in pack {pack_dir}")
            shutil.copy(src, dest / cue["file"])
            gain = next((c.get("gain_db") for c in sfx["cues"] if Path(c["file"]).name == cue["file"]), None)
            final.append({"time": round(cue["time"], 2), "file": f"sfx/{cue['file']}", "gain_db": gain if gain is not None else SFX_GAIN_DB})
        if final:
            denh["sfx"] = {"enabled": True, "pack": pack, "cues": final}


# -- Orchestrator ------------------------------------------------------------------------


def _write_job(job_yaml: Path, data: dict) -> None:
    job_yaml.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def run(
    job_dir: str | Path,
    creative_path: str | Path | None = None,
    provider: str | None = None,
    sfx_library: str | Path = Path.home() / ".local/share/videotool/sfx",
    overlay_library: str | Path = DEFAULT_OVERLAY_LIBRARY,
    sfx_pack: str | None = None,
    autonomous: bool = False,
) -> Path:
    """Author + validate a complete job.yaml, then pin it. Idempotent: a pinned job.yaml
    short-circuits (resume makes no work).

    Three authoring modes, in priority order:
    1. `creative_path` present  -> DEFAULT: apply the Claude Code CLI-authored creative.yaml (no LLM).
    2. `autonomous=True`        -> FALLBACK: the on-box LLM authors it (Kaggle Model Proxy / a key).
       Use only when running the notebook WITHOUT Claude in the loop.
    3. neither                  -> deterministic job.yaml only (no music_schedule / sfx / FX).
    """
    job_dir = Path(job_dir)
    job_yaml = job_dir / "job.yaml"
    if (job_dir / PIN_MARKER).exists() and job_yaml.exists():
        print("cloud_director: pinned job.yaml present -> NO-OP (resume run).")
        return job_yaml

    data = prepare_job(job_dir)

    creative = None
    if creative_path and Path(creative_path).exists():
        creative = yaml.safe_load(Path(creative_path).read_text(encoding="utf-8")) or {}

    if creative is not None:
        print(f"cloud_director: applying Claude-authored creative from {creative_path} (no LLM).")
        apply_creative(job_dir, data, creative, Path(sfx_library), Path(overlay_library))
    elif autonomous:
        provider = choose_provider(provider)
        print(f"cloud_director: AUTONOMOUS fallback, on-box LLM provider={provider}")
        author_music_schedule(provider, job_dir, data)
        author_sfx_cues(provider, job_dir, data, Path(sfx_library), sfx_pack)
        author_description(provider, job_dir, data)
        author_chapters_fallback(provider, job_dir, data)
    else:
        print("cloud_director: deterministic job.yaml only (no creative.yaml, not autonomous).")

    _write_job(job_yaml, data)
    pre_render_checks(job_dir, job_yaml)

    (job_dir / PIN_MARKER).parent.mkdir(parents=True, exist_ok=True)
    (job_dir / PIN_MARKER).write_text("pinned by cloud_director\n", encoding="utf-8")
    print(f"cloud_director: job.yaml authored + validated + pinned -> {job_yaml}")
    return job_yaml


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Assemble a cloud-render job.yaml.")
    parser.add_argument("job_dir")
    parser.add_argument("--creative", default=None, help="path to a Claude-authored creative.yaml (default path)")
    parser.add_argument("--autonomous", action="store_true", help="fallback: let the on-box LLM author it")
    parser.add_argument("--provider", choices=["kaggle", "glm", "gemini", "anthropic"], default=None)
    parser.add_argument("--sfx-library", default=str(Path.home() / ".local/share/videotool/sfx"))
    parser.add_argument("--overlay-library", default=str(DEFAULT_OVERLAY_LIBRARY))
    parser.add_argument("--sfx-pack", default=None)
    args = parser.parse_args()
    run(args.job_dir, args.creative, args.provider, args.sfx_library, args.overlay_library, args.sfx_pack, args.autonomous)
