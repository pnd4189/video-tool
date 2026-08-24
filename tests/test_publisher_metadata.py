import shutil
from pathlib import Path

import pytest

from videotool.core.errors import RenderError
from videotool.core.job_spec import load_job
from videotool.package.metadata import (
    build_metadata_args,
    find_exiftool,
    parse_description,
    run_metadata,
    safe_filename,
)

DESCRIPTION = """Bình Thiên Sách - Tập 39

Tóm tắt tập này.

📖 THÔNG TIN TRUYỆN
• Tác giả: Vô Tội (无罪)
• Thể loại: Tiên hiệp, Tu tiên, Huyền huyễn

==================== TAGS (dán vào ô Tags YouTube) ====================
chính dịch đường, truyện audio, bình thiên sách tập 39
"""


def _write_job(tmp_path: Path, extra: str = "") -> Path:
    job_path = tmp_path / "job.yaml"
    job_path.write_text(
        "version: 1\n"
        'project:\n  title: "Ma Tông Song Sát | Tập 39"\n  description: "Tóm tắt."\n'
        f"{extra}"
        "inputs:\n  voice: voice.wav\n  media_dir: media\n"
        "outputs:\n  - preset: youtube-16x9\n",
        encoding="utf-8",
    )
    return job_path


METADATA_BLOCK = (
    "  metadata:\n"
    '    channel: "Chính Dịch Đường"\n'
    '    channel_url: "https://www.youtube.com/@ChinhDichDuongVN"\n'
    '    original_author: "Vô Tội"\n'
    '    copyright: "Bản dịch: Chính Dịch Đường."\n'
    '    subtitle: "Chương 421-435"\n'
    '    release_date: "2026-08-23"\n'
)


def test_parse_description_reads_tags_and_genre(tmp_path: Path) -> None:
    path = tmp_path / "description.txt"
    path.write_text(DESCRIPTION, encoding="utf-8")
    tags, genre = parse_description(path)
    assert tags == ["chính dịch đường", "truyện audio", "bình thiên sách tập 39"]
    assert genre == "Tiên hiệp, Tu tiên, Huyền huyễn"


def test_parse_description_missing_file_is_empty(tmp_path: Path) -> None:
    assert parse_description(tmp_path / "nope.txt") == ([], "")


def test_safe_filename_replaces_separators_windows_rejects() -> None:
    name = safe_filename('Douban (MXH sách/phim TQ): Siêu trộm | Đạo sĩ sợ ma - Tập 28')
    assert name == "Douban (MXH sách-phim TQ) - Siêu trộm - Đạo sĩ sợ ma - Tập 28"
    assert not set(name) & set('<>:"/\\|?*')


def test_safe_filename_caps_length_and_never_empty() -> None:
    assert len(safe_filename("x" * 400)) == 150
    assert safe_filename("???") == "video"  # a title of only stripped chars still names a file


def test_build_metadata_args_maps_channel_to_every_credit(tmp_path: Path) -> None:
    job = load_job(_write_job(tmp_path, METADATA_BLOCK))
    args = build_metadata_args(job, tags=["a", "b"], genre="Tiên hiệp")
    joined = "\n".join(args)
    for tag in ("Director", "Producer", "Publisher", "ContentDistributor", "EncodedBy"):
        assert f"-Microsoft:{tag}=Chính Dịch Đường" in args
    assert "-Microsoft:AuthorURL=https://www.youtube.com/@ChinhDichDuongVN" in args
    assert "-Microsoft:PromotionURL=https://www.youtube.com/@ChinhDichDuongVN" in args
    assert "-Microsoft:Writer=Vô Tội" in args
    assert "-Microsoft:Category=a" in args and "-Microsoft:Category=b" in args
    assert "-Microsoft:SharedUserRating=99" in args  # 5 stars
    assert "-ItemList:Genre=Tiên hiệp" in args
    assert "-ItemList:Title=Ma Tông Song Sát | Tập 39" in args
    assert "2026:08:23" in joined


def test_build_metadata_args_without_metadata_block_stays_minimal(tmp_path: Path) -> None:
    job = load_job(_write_job(tmp_path))
    args = build_metadata_args(job, tags=[], genre="")
    assert not [arg for arg in args if arg.startswith("-Microsoft:") and "Rating" not in arg]
    assert "-ItemList:Title=Ma Tông Song Sát | Tập 39" in args


def test_run_metadata_without_render_fails(tmp_path: Path) -> None:
    job_path = _write_job(tmp_path)
    (tmp_path / "outputs").mkdir()
    with pytest.raises(RenderError):
        run_metadata(job_path)


@pytest.mark.skipif(
    find_exiftool() is None or shutil.which("ffmpeg") is None, reason="needs exiftool + ffmpeg"
)
def test_run_metadata_tags_and_renames(tmp_path: Path) -> None:
    import subprocess

    job_path = _write_job(tmp_path, METADATA_BLOCK)
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    (outputs / "description.txt").write_text(DESCRIPTION, encoding="utf-8")
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=64x64:r=5:d=1",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
         str(outputs / "youtube-16x9.mp4")],
        check=True,
    )

    tagged, published = run_metadata(job_path)

    assert len(tagged) == 1
    assert published is not None and published.name == "Ma Tông Song Sát - Tập 39.mp4"
    assert published.exists() and not (outputs / "youtube-16x9.mp4").exists()
    read = subprocess.run(
        [find_exiftool(), "-charset", "UTF8", "-Microsoft:all", "-ItemList:all", str(published)],
        capture_output=True, text=True, errors="replace", check=True,
    ).stdout
    assert "Chính Dịch Đường" in read
    assert "bình thiên sách tập 39" in read  # tags came out of description.txt
    assert "Tiên hiệp, Tu tiên, Huyền huyễn" in read

    # Re-running finds the already-renamed file instead of failing on the missing preset name.
    tagged_again, published_again = run_metadata(job_path)
    assert tagged_again == [published] and published_again == published
