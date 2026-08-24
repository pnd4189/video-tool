"""Publisher metadata for the finished mp4: channel credits, tags, and the publish filename.

FFmpeg writes a handful of iTunes-style atoms at mux time (title/comment/artist). The fields
Windows Explorer lists under "Origin" — Directors, Producers, Publisher, Author URL, Promotion
URL, Tags — live in a separate `Xtra` box that only ExifTool can write, so the finished file
gets one metadata pass here. The pass rewrites the container only: streams, duration and the
faststart layout come through untouched (~4s on a 2.5 GB render).

Runs AFTER `package`, because the tags and genre are read back out of the rendered
description.txt — the file then carries exactly what gets pasted into YouTube.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from datetime import date
from pathlib import Path

from videotool.core.errors import DependencyError, RenderError
from videotool.core.job_spec import JobSpec, load_job
from videotool.package.manifest import write_package_manifest

# ExifTool is pure Perl and is not vendored: PATH first, then the durable data dir the SFX and
# overlay libraries already live in (unpack the release tarball there — no root needed).
EXIFTOOL_HOME = Path.home() / ".local" / "share" / "videotool" / "exiftool" / "exiftool"
INSTALL_HINT = (
    "ExifTool was not found. Install it (apt install libimage-exiftool-perl) or unpack the "
    f"release tarball so that {EXIFTOOL_HOME} exists."
)
# Windows star rating -> the 0-99 scale WM/SharedUserRating uses.
RATING_SCALE = {0: 0, 1: 1, 2: 25, 3: 50, 4: 75, 5: 99}
GENRE_MARKER = "• Thể loại:"
TAGS_MARKER = "TAGS"
MAX_FILENAME_CHARS = 150
SUBPROCESS_TIMEOUT_SECONDS = 1800


def find_exiftool() -> str | None:
    found = shutil.which("exiftool")
    if found:
        return found
    return str(EXIFTOOL_HOME) if EXIFTOOL_HOME.exists() else None


def parse_description(path: Path) -> tuple[list[str], str]:
    """Return (tags, genre) read out of a rendered description.txt. Both are optional: a missing
    file or a template without the markers yields ([], "") and those fields stay unwritten."""
    if not path.exists():
        return [], ""
    lines = path.read_text(encoding="utf-8").splitlines()
    tags: list[str] = []
    genre = ""
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not genre and stripped.startswith(GENRE_MARKER):
            genre = stripped[len(GENRE_MARKER):].strip()
        if not tags and stripped.startswith("=") and TAGS_MARKER in stripped:
            for candidate in lines[index + 1:]:
                if candidate.strip():
                    tags = [tag.strip() for tag in candidate.split(",") if tag.strip()]
                    break
    return tags, genre


def safe_filename(title: str) -> str:
    """A publish name Windows, Drive and ext4 all accept. Separators the title uses for reading
    (`|`, `:`) become dashes rather than vanishing, so the name still reads like the title."""
    name = title.replace("|", "-").replace("/", "-").replace("\\", "-").replace(":", " -")
    name = re.sub(r'[<>"?*\x00-\x1f]', "", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name[:MAX_FILENAME_CHARS].strip(" .") or "video"


def build_metadata_args(job: JobSpec, tags: list[str], genre: str) -> list[str]:
    """ExifTool tag assignments for one output. `ItemList:` tags are the ones ffprobe and every
    player read; `Microsoft:` tags land in the Xtra box Windows Explorer reads."""
    project = job.project
    meta = project.metadata
    channel = meta.channel or project.author
    args: list[str] = []
    if project.title:
        args.append(f"-ItemList:Title={project.title}")
    if project.description:
        args.append(f"-ItemList:Comment={project.description}")
        args.append(f"-ItemList:Description={project.description}")
    if genre:
        args.append(f"-ItemList:Genre={genre}")
    if meta.copyright:
        args.append(f"-ItemList:Copyright={meta.copyright}")
    if channel:
        args.append(f"-ItemList:Artist={channel}")
        for tag in ("Director", "Producer", "Publisher", "ContentDistributor", "EncodedBy"):
            args.append(f"-Microsoft:{tag}={channel}")
    if meta.channel_url:
        args.append(f"-Microsoft:AuthorURL={meta.channel_url}")
        args.append(f"-Microsoft:PromotionURL={meta.channel_url}")
    if meta.original_author:
        args.append(f"-Microsoft:Writer={meta.original_author}")
    if meta.subtitle:
        args.append(f"-Microsoft:Subtitle={meta.subtitle}")
    if meta.rating:
        args.append(f"-Microsoft:SharedUserRating={RATING_SCALE[meta.rating]}")
    for tag in tags:
        args.append(f"-Microsoft:Category={tag}")
    stamp = (meta.release_date or date.today().isoformat()).replace("-", ":")
    args.append(f"-ItemList:ContentCreateDate={stamp} 00:00:00")
    args.append(f"-QuickTime:CreateDate={stamp} 00:00:00")
    return args


def write_metadata(video: Path, tag_args: list[str], exiftool: str) -> None:
    command = [
        exiftool, "-charset", "UTF8", "-P", "-overwrite_original",
        "-api", "LargeFileSupport=1", *tag_args, str(video),
    ]
    try:
        # errors="replace": ExifTool echoes the Vietnamese values back on warnings, and a split
        # multi-byte char on a read boundary would otherwise raise in strict-UTF-8 mode.
        result = subprocess.run(
            command, capture_output=True, text=True, errors="replace",
            check=False, timeout=SUBPROCESS_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        raise DependencyError(INSTALL_HINT) from exc
    except subprocess.TimeoutExpired as exc:
        raise RenderError(f"ExifTool timed out writing metadata to {video.name}.") from exc
    if result.returncode != 0:
        raise RenderError(
            f"ExifTool failed on {video.name} (exit {result.returncode}):\n{result.stderr}"
        )


def publish_name(job: JobSpec) -> str:
    return job.project.metadata.filename or safe_filename(job.project.title)


def _resolve_outputs(job: JobSpec, output_dir: Path) -> list[Path]:
    """Rendered mp4s to tag. A re-run finds the already-renamed file, so tagging twice is safe."""
    resolved: list[Path] = []
    renamed = output_dir / f"{publish_name(job)}.mp4"
    for output in job.outputs:
        video = output_dir / f"{output.preset}.mp4"
        if video.exists():
            resolved.append(video)
        elif renamed.exists() and renamed not in resolved:
            resolved.append(renamed)
    return resolved


def run_metadata(job_path: Path, *, rename: bool = True) -> tuple[list[Path], Path | None]:
    """Tag every rendered output and, unless disabled, rename the single long-form mp4 to the
    publish title. Returns (tagged files, renamed path). Run after `package`; the publish step
    then copies whatever names outputs/ holds."""
    job = load_job(job_path)
    output_dir = job_path.parent.resolve() / "outputs"
    videos = _resolve_outputs(job, output_dir)
    if not videos:
        raise RenderError(f"No rendered output found in {output_dir}; run render first.")
    exiftool = find_exiftool()
    if exiftool is None:
        raise DependencyError(INSTALL_HINT)

    parsed_tags, parsed_genre = parse_description(output_dir / "description.txt")
    tags = job.project.tags or parsed_tags
    args = build_metadata_args(job, tags=tags, genre=job.project.metadata.genre or parsed_genre)
    for video in videos:
        write_metadata(video, args, exiftool)

    published: Path | None = None
    # Renaming only makes sense for a single long-form output; a multi-preset job keeps the
    # preset names so nothing downstream has to guess which file is which.
    if rename and len(videos) == 1 and job.project.title:
        dest = videos[0].with_name(f"{publish_name(job)}.mp4")
        if dest != videos[0]:
            videos[0].replace(dest)
        published = dest

    manifest_path = output_dir / "package-manifest.json"
    if manifest_path.exists():
        files = sorted(
            path for path in output_dir.iterdir() if path.is_file() and path != manifest_path
        )
        write_package_manifest(files, job_path, manifest_path)
    return videos, published
