"""LLM orchestrator for the cloud render path — the notebook-side replacement for the
Claude-authored steps of `/make-video`.

Given a staged job folder (voice, Image/, Video/, Music/, `*_vi_qa.{txt,srt}`,
`*_music_prompts.txt`, description template, CTA folder) this authors a complete
audio-story `job.yaml` — deterministic pre-steps (init/storyboard/SRT/chapters/CTA
detection) plus four LLM tasks (music_schedule, SFX cues, description+recap, chapters
fallback) — then hard-gates it (`videotool validate` + encoder/SFX pre-render checks the
CLI does NOT cover) BEFORE any GPU time is spent.

Design decisions (see plan 260707-0855):
- `render.max_inline_scenes: 1` forces the resumable segmented render path. The plan wrote
  "0" but the schema (`job_spec.py:264`) requires `> 0`; `1` sends every job with >=2 scenes
  down the segmented path, same intent, no shared-code change.
- Idempotent (red-team H4): a pinned, already-validated job.yaml makes `run()` a NO-OP, so a
  resume never re-calls the LLM. The pin marker lives at `<job>/.videotool/.cloud_director.pinned`;
  the runner restores it (with job.yaml) from the Drive checkpoint before resuming.
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


def choose_provider(preferred: str | None = None) -> str:
    """Pick an LLM provider whose key is present. Colab defaults to glm, Kaggle to gemini;
    `preferred` overrides. Raises with an actionable message when no key is available."""
    order = [preferred] if preferred else []
    order += ["glm", "gemini", "anthropic"]
    key_for = {"glm": "GLM_API_KEY", "gemini": "GEMINI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}
    for provider in order:
        if provider and get_secret(key_for[provider]):
            return provider
    raise DirectorError(
        "No LLM key found. Add one of GLM_API_KEY / GEMINI_API_KEY / ANTHROPIC_API_KEY to "
        "Colab (userdata) or Kaggle (Add-ons -> Secrets)."
    )


def _redact(text: str) -> str:
    """Strip any live key value out of a string before it reaches a log/exception."""
    for name in _REDACT_KEYS:
        value = get_secret(name)
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
        data = _http_json(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={key}",
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
    files = [p for p in folder.iterdir() if p.suffix.lower() in (".mp4", ".mov", ".wav", ".mp3", ".m4a")]
    for stem in stems:
        for p in files:
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
    """`videotool validate` PLUS the two checks it omits (H8): encoder must be a real profile,
    and every SFX cue file must exist inside the job folder. Abort BEFORE any GPU time."""
    _run_cli(["validate", str(job_yaml)])  # raises on schema / path errors

    data = yaml.safe_load(job_yaml.read_text(encoding="utf-8")) or {}
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


def _known_profiles() -> set[str]:
    """The render profiles the installed videotool accepts (import if available, else the
    known set). Kept in sync with `render/profiles.py`."""
    try:
        from videotool.render.profiles import PROFILES  # noqa: PLC0415

        return set(PROFILES)
    except Exception:
        return {"libx264-balanced", "libx264-fast", "libx264-balanced-capped", "h264_nvenc-capped"}


# -- Orchestrator ------------------------------------------------------------------------


def _write_job(job_yaml: Path, data: dict) -> None:
    job_yaml.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def run(
    job_dir: str | Path,
    provider: str | None = None,
    sfx_library: str | Path = Path.home() / ".local/share/videotool/sfx",
    sfx_pack: str | None = None,
    no_llm: bool = False,
) -> Path:
    """Author + validate a complete job.yaml. Idempotent: a pinned job.yaml short-circuits.

    Returns the job.yaml path. On the first run it pins the validated job.yaml so a resume
    (which restores the pin from the Drive checkpoint) becomes a NO-OP — no LLM, no network.
    """
    job_dir = Path(job_dir)
    job_yaml = job_dir / "job.yaml"
    if (job_dir / PIN_MARKER).exists() and job_yaml.exists():
        print("cloud_director: pinned job.yaml present -> NO-OP (resume run).")
        return job_yaml

    data = prepare_job(job_dir)

    if not no_llm:
        provider = choose_provider(provider)
        print(f"cloud_director: provider={provider}")
        author_music_schedule(provider, job_dir, data)
        author_sfx_cues(provider, job_dir, data, Path(sfx_library), sfx_pack)
        author_description(provider, job_dir, data)
        author_chapters_fallback(provider, job_dir, data)
    else:
        print("cloud_director: --no-llm, deterministic job.yaml only (no music_schedule/sfx/description).")

    _write_job(job_yaml, data)
    pre_render_checks(job_dir, job_yaml)

    (job_dir / PIN_MARKER).parent.mkdir(parents=True, exist_ok=True)
    (job_dir / PIN_MARKER).write_text("pinned by cloud_director\n", encoding="utf-8")
    print(f"cloud_director: job.yaml authored + validated + pinned -> {job_yaml}")
    return job_yaml


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Author a cloud-render job.yaml with an LLM.")
    parser.add_argument("job_dir")
    parser.add_argument("--provider", choices=["glm", "gemini", "anthropic"], default=None)
    parser.add_argument("--sfx-library", default=str(Path.home() / ".local/share/videotool/sfx"))
    parser.add_argument("--sfx-pack", default=None)
    parser.add_argument("--no-llm", action="store_true", help="deterministic pipeline only (testable without keys)")
    args = parser.parse_args()
    run(args.job_dir, args.provider, args.sfx_library, args.sfx_pack, args.no_llm)
