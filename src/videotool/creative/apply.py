"""Merge an agent-authored `creative.yaml` into the deterministic job.yaml.

The agent does the judgement work locally (music_schedule, SFX cues, overlay, description,
chapters); this only applies it, copying the named SFX and overlay files from the local libraries
into the job folder. No LLM is involved.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from videotool.creative.prepare import apply_input_overrides, run_cli
from videotool.creative.rules import SFX_GAIN_DB, CreativeError, filter_sfx_cues, srt_cues, voice_end

SFX_LIBRARY = Path.home() / ".local/share/videotool/sfx"
OVERLAY_LIBRARY = Path.home() / ".local/share/videotool/overlays"

# Channel -> sfx pack: kiếm hiệp -> binh-thien, ma hài -> dao-si.
SFX_PACK_KEYWORDS = {
    "binh-thien": ("kiếm", "hiệp", "tiên", "tu", "đạo", "chưởng", "giang hồ"),
    "dao-si": ("ma", "hài", "quỷ", "yêu", "đạo sĩ", "bùa"),
}


def read_first(job_dir: Path, pattern: str) -> str:
    matches = sorted(Path(job_dir).glob(pattern))
    return matches[0].read_text(encoding="utf-8") if matches else ""


def infer_pack(job_dir: Path) -> str:
    text = (read_first(job_dir, "*_music_prompts.txt") + " " + read_first(job_dir, "*_vi_qa.txt")[:2000]).lower()
    best, score = "binh-thien", 0
    for pack, words in SFX_PACK_KEYWORDS.items():
        hits = sum(text.count(w) for w in words)
        if hits > score:
            best, score = pack, hits
    return best


def renumber_srt_chapters(job_dir: Path, mapping: dict) -> int:
    """Rewrite the chapter numbers in the staged outputs/captions.srt.

    Some episodes ship an SRT whose headings restart per source file ("Chương 1", "Chương 33")
    while the published episode numbers them absolutely (77-80). Renumbering the burn baseline
    BEFORE the render is the only way the burned subtitles carry the published numbers — the
    description can be corrected afterwards, the pixels cannot."""
    srt = Path(job_dir) / "outputs" / "captions.srt"
    if not srt.exists():
        raise CreativeError("captions.renumber needs outputs/captions.srt (provided SRT missing)")
    wanted = {int(k): int(v) for k, v in mapping.items()}
    seen: set[int] = set()

    def sub(match: "re.Match[str]") -> str:
        old_num = int(match.group(2))
        if old_num not in wanted:
            return match.group(0)
        seen.add(old_num)
        return f"{match.group(1)}{wanted[old_num]}{match.group(3)}"

    text, count = re.subn(r"(Chương\s+)(\d+)(\s*:)", sub, srt.read_text(encoding="utf-8"))
    missing = sorted(set(wanted) - seen)
    if missing:
        raise CreativeError(f"captions.renumber: no 'Chương N:' heading found for {missing}")
    srt.write_text(text, encoding="utf-8")
    return count


def write_chapters(job_dir: Path, chapters: list) -> None:
    """Final say over outputs/chapters.json. chapters-from-srt derives it from the SRT headings,
    which cannot express the extra story beats the description format lists between chapters."""
    entries = [{"start": float(c["start"]), "title": str(c["title"]).strip()} for c in chapters]
    out = Path(job_dir) / "outputs" / "chapters.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")


def apply_creative(
    job_dir: Path,
    data: dict,
    creative: dict,
    sfx_library: Path = SFX_LIBRARY,
    overlay_library: Path = OVERLAY_LIBRARY,
) -> None:
    """Merge `creative` into `data` (the loaded job.yaml). creative.yaml shape (all keys optional):

        audio: {music_schedule: [{track,start,end,gain_db?}, ...]}
        enhance:
            mood: cozy            # clean|melancholy|cozy|horror|action
            grain: false          # default false — grain eats the capped bitrate budget
            overlay: fireflies-gen-01.mp4   # filename in the overlay library -> copied into job
            parallax: true        # link Parallax/ clips (parallax_on_box: opt into depth on the box)
            sfx: {pack: dao-si, cues: [{time, file, gain_db?}, ...]}
        captions: {renumber: {1: 77, 33: 78}}   # fix chapter numbers in the BURNED subtitles
        render: {bitrate_cap: 2500k}             # read by the cloud runner / local prepare
        project:
            chapters: [{start: 0.0, title: "Chương 77: ..."}, ...]  # final say over chapters.json
            title / description / recap_previous / metadata
        inputs: {intro_image: "Ảnh bìa Thumbnail-Intro/15.jpg", ...}  # job-relative overrides
    """
    job_dir = Path(job_dir)
    # Renumber first, then re-derive, so chapters.json picks up the new numbers.
    renumber = (creative.get("captions") or {}).get("renumber")
    if renumber:
        replaced = renumber_srt_chapters(job_dir, renumber)
        print(f"director: renumbered {replaced} chapter heading(s) in outputs/captions.srt")
        run_cli(["chapters-from-srt", str(job_dir / "job.yaml")])

    chapters = (creative.get("project") or {}).get("chapters")
    if chapters:
        write_chapters(job_dir, chapters)
        print(f"director: wrote {len(chapters)} chapter marker(s) from creative.yaml")

    if creative.get("audio", {}).get("music_schedule"):
        data.setdefault("audio", {})["music_schedule"] = creative["audio"]["music_schedule"]

    # prepare_job already applied these before the storyboard; re-applying keeps a direct call
    # honouring them too.
    apply_input_overrides(job_dir, data, creative.get("inputs", {}))

    proj = creative.get("project", {})
    for key in ("title", "description", "recap_previous", "metadata"):  # `chapters` -> chapters.json
        if proj.get(key):
            data.setdefault("project", {})[key] = proj[key]

    enh = creative.get("enhance", {})
    denh = data.setdefault("enhance", {})
    if enh.get("mood"):
        denh["mood"] = enh["mood"]
        # Grain (auto-on for most moods) balloons a capped H264's size — off unless asked.
        denh["grain"] = enh.get("grain", False)
    for key in ("vignette", "glow", "flicker", "color_grade"):
        if key in enh:
            denh[key] = enh[key]
    if enh.get("parallax") is not None:
        denh["parallax"] = enh["parallax"]

    overlay = enh.get("overlay")
    if overlay:
        src = Path(overlay_library) / overlay
        if not src.exists():
            raise CreativeError(f"overlay '{overlay}' not found in library {overlay_library}")
        shutil.copy(src, job_dir / src.name)  # validation requires the overlay INSIDE the job
        data.setdefault("inputs", {})["particle_overlay"] = src.name
        denh["atmosphere"] = True

    sfx = enh.get("sfx")
    if sfx and sfx.get("cues"):
        _apply_sfx(job_dir, denh, sfx, Path(sfx_library))


def _apply_sfx(job_dir: Path, denh: dict, sfx: dict, sfx_library: Path) -> None:
    pack = sfx.get("pack") or infer_pack(job_dir)
    pack_dir = sfx_library / pack
    dest = job_dir / "sfx"
    dest.mkdir(exist_ok=True)
    raw = [{"time": c["time"], "file": Path(c["file"]).name, "gain_db": c.get("gain_db")} for c in sfx["cues"]]
    cues = srt_cues(job_dir)
    final = []
    for cue in filter_sfx_cues(raw, {p.name for p in pack_dir.glob("*")}, voice_end(cues) if cues else 1e9):
        src = pack_dir / cue["file"]
        if not src.exists():
            raise CreativeError(f"sfx cue '{cue['file']}' not found in pack {pack_dir}")
        shutil.copy(src, dest / cue["file"])
        gain = cue.get("gain_db")
        final.append({"time": round(cue["time"], 2), "file": f"sfx/{cue['file']}",
                      "gain_db": gain if gain is not None else SFX_GAIN_DB})
    if final:
        denh["sfx"] = {"enabled": True, "pack": pack, "cues": final}
