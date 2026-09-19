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

The deterministic pre-steps and the creative merge live in the `videotool.creative` package (shared
with the local path and `videotool creative lint`), so this module needs videotool installed and must
be imported only after `videotool_cloud.setup()`. LLM calls use urllib.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import urllib.error
import urllib.request
from pathlib import Path

import yaml

# The deterministic rules live in the installed package (one copy for local, cloud and lint).
# Importing it here is safe: the runner imports this module only after `vc.setup()` installed it.
from videotool.creative.apply import OVERLAY_LIBRARY as DEFAULT_OVERLAY_LIBRARY
from videotool.creative.apply import SFX_LIBRARY, apply_creative, infer_pack, read_first
from videotool.creative.checks import check_music_wiring, pre_render_checks  # noqa: F401 (re-export)
from videotool.creative.prepare import prepare_job, write_job
from videotool.creative.rules import (
    SFX_GAIN_DB,
    CreativeError,
    clean_music_cues,
    filter_sfx_cues,
    srt_cues,
    voice_end,
)

PIN_MARKER = Path(".videotool") / ".cloud_director.pinned"

# Kaggle's Benchmarks Model Proxy: `kaggle benchmarks init` writes a `.env` with an OpenAI-compatible
# endpoint (MODEL_PROXY_URL) + a short-lived key (MODEL_PROXY_API_KEY), funded by the account's LLM
# credit. This is the PRIMARY provider on Kaggle — no personal API key needed. Empirically (probe
# 2026-07-11 on this account) the Anthropic/GLM/Qwen slugs 503 and only google/gemini-3.5-flash is
# reliably up AND passes the Vietnamese homograph SFX test, so it is the default proxy model.
KAGGLE_PROXY_DEFAULT_MODEL = "google/gemini-3.5-flash"


# Kept under its old name: callers and tests catch `cloud_director.DirectorError`.
DirectorError = CreativeError

_REDACT_KEYS = ("GLM_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY")


# -- Secrets + LLM providers -------------------------------------------------------------


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


# -- LLM tasks ---------------------------------------------------------------------------


def _chapter_seconds(data: dict) -> list[tuple[float, str]]:
    return [(c["start"], c["title"]) for c in data.get("project", {}).get("chapters", [])]


def author_music_schedule(provider: str, job_dir: Path, data: dict) -> None:
    """Map each music track to the chapter range whose mood fits; write audio.music_schedule."""
    tracks = sorted((job_dir / "Music").glob("*")) if (job_dir / "Music").exists() else []
    prompts = read_first(job_dir, "*_music_prompts.txt") or read_first(job_dir, "*music_prompt*.txt")
    chapters = _chapter_seconds(data)
    if len(tracks) < 2 or not prompts or not chapters:
        return  # unset -> concat + loop (schema default)

    end_s = voice_end(srt_cues(job_dir)) or chapters[-1][0] + 60
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
        f"Narration ends at ~{end_s:.0f}s. Emit {len(tracks)} cues, one per track, in story order."
    )
    obj = _ask_json(provider, system, user, ("cues",))
    cues = clean_music_cues(obj["cues"], len(tracks), end_s)
    if cues:
        data.setdefault("audio", {})["music_schedule"] = cues


def author_sfx_cues(provider: str, job_dir: Path, data: dict, sfx_library: Path, pack: str | None) -> None:
    """Pick unambiguous action SFX from the pack, pin by SRT time, copy into <job>/sfx/."""
    lines = srt_cues(job_dir)
    pack = pack or infer_pack(job_dir)
    pack_dir = Path(sfx_library) / pack
    if not lines or not pack_dir.exists():
        return
    available = [p.name for p in sorted(pack_dir.glob("*")) if p.suffix.lower() in (".wav", ".mp3", ".m4a", ".ogg")]
    if not available:
        return

    end_s = voice_end(lines)
    transcript = "\n".join(f"[{t:.1f}] {txt}" for t, _, txt in lines if txt)
    system = (
        "You add one-shot sound effects to an audiobook. Choose ONLY unambiguous physical-action "
        "moments (a sword clash, a door slam, thunder) — skip metaphors and homographs. Return JSON "
        "{\"cues\":[{\"time\":sec,\"file\":\"name.wav\"}]}. Use ONLY files from the provided list. "
        "Be conservative: prefer clarity over quantity."
    )
    user = (
        f"Available SFX files: {available}\n"
        f"Narration ends at ~{end_s:.0f}s.\n"
        f"Timestamped narration:\n{transcript[:8000]}"
    )
    obj = _ask_json(provider, system, user, ("cues",))
    cues = filter_sfx_cues(obj["cues"], set(available), end_s)
    if not cues:
        return
    dest = job_dir / "sfx"
    dest.mkdir(exist_ok=True)
    final = []
    for cue in cues:
        shutil.copy(pack_dir / cue["file"], dest / cue["file"])
        final.append({"time": round(cue["time"], 2), "file": f"sfx/{cue['file']}", "gain_db": SFX_GAIN_DB})
    data.setdefault("enhance", {})["sfx"] = {"enabled": True, "pack": pack, "cues": final}


def author_description(provider: str, job_dir: Path, data: dict) -> None:
    """Author project.description + project.recap_previous from the vi.txt script."""
    script = read_first(job_dir, "*_vi_qa.txt") or read_first(job_dir, "*_vi.txt")
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
    lines = srt_cues(job_dir)
    if not lines:
        return
    transcript = "\n".join(f"[{t:.1f}] {txt}" for t, _, txt in lines if txt)
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


# -- Orchestrator ------------------------------------------------------------------------


def run(
    job_dir: str | Path,
    creative_path: str | Path | None = None,
    provider: str | None = None,
    sfx_library: str | Path = SFX_LIBRARY,
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

    creative = None
    if creative_path and Path(creative_path).exists():
        creative = yaml.safe_load(Path(creative_path).read_text(encoding="utf-8")) or {}

    # creative.yaml's input overrides (e.g. which thumbnail is the intro card) must be in place
    # before prepare_job builds the storyboard.
    data = prepare_job(job_dir, (creative or {}).get("inputs"))

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

    write_job(job_yaml, data)
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
