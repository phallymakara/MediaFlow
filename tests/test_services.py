"""Tests for application services."""

import pytest
from pathlib import Path

from app.services.storage import StorageService
from app.services.metadata import MetadataService
from app.services.ffmpeg import FFmpegService, FFmpegError


# ============================================================================
# StorageService Tests
# ============================================================================

def test_storage_service_initialization(tmp_path: Path) -> None:
    """Verify StorageService initializes and creates target directories."""
    dl_dir = tmp_path / "downloads"
    temp_dir = tmp_path / "temp"

    service = StorageService(base_download_dir=dl_dir, temp_dir=temp_dir)
    assert service.base_download_dir.exists()
    assert service.temp_dir.exists()


def test_sanitize_filename_illegal_chars() -> None:
    """Verify illegal filesystem characters are replaced with underscores."""
    raw_name = 'Video: Episode "1" <Final>? /Test\\ |Part*'
    sanitized = StorageService.sanitize_filename(raw_name)
    for illegal_char in ['\\', '/', ':', '*', '?', '"', '<', '>', '|']:
        assert illegal_char not in sanitized


def test_sanitize_filename_windows_reserved() -> None:
    """Verify Windows reserved device names are prefixed safely."""
    assert StorageService.sanitize_filename("CON.mp4") == "_CON.mp4"
    assert StorageService.sanitize_filename("aux.mkv") == "_aux.mkv"
    assert StorageService.sanitize_filename("NUL.webm") == "_NUL.webm"


def test_sanitize_filename_length_truncation() -> None:
    """Verify long filenames are truncated to max length while preserving extension."""
    long_title = "a" * 250 + ".mp4"
    sanitized = StorageService.sanitize_filename(long_title, max_length=100)
    assert len(sanitized) <= 100
    assert sanitized.endswith(".mp4")


def test_sanitize_filename_empty_fallback() -> None:
    """Verify empty or invalid inputs fall back to default filename."""
    assert StorageService.sanitize_filename("") == "media_download"
    assert StorageService.sanitize_filename("   ") == "media_download"
    assert StorageService.sanitize_filename("???") == "media_download"


def test_get_destination_path_normal(tmp_path: Path) -> None:
    """Verify normal destination path resolution inside download directory."""
    service = StorageService(base_download_dir=tmp_path)
    dest = service.get_destination_path("my_video.mp4")
    assert dest == tmp_path / "my_video.mp4"


def test_get_destination_path_traversal_blocked(tmp_path: Path) -> None:
    """Verify path traversal attempts are detected and blocked."""
    service = StorageService(base_download_dir=tmp_path)
    # Even if someone attempts to pass a traversal in subfolder, it gets sanitized or blocked
    with pytest.raises(ValueError):
        service.get_destination_path("../../secret.txt")


def test_get_unique_destination_path(tmp_path: Path) -> None:
    """Verify conflicting files automatically receive incremented names."""
    service = StorageService(base_download_dir=tmp_path)
    target = tmp_path / "video.mp4"

    # File does not exist initially
    assert service.get_unique_destination_path(target) == target

    # Create file
    target.touch()
    unique1 = service.get_unique_destination_path(target)
    assert unique1 == tmp_path / "video (1).mp4"

    # Create second file
    unique1.touch()
    unique2 = service.get_unique_destination_path(target)
    assert unique2 == tmp_path / "video (2).mp4"


def test_temp_path_and_commit(tmp_path: Path) -> None:
    """Verify temporary file creation and atomic commit."""
    dl_dir = tmp_path / "downloads"
    temp_dir = tmp_path / "temp"
    service = StorageService(base_download_dir=dl_dir, temp_dir=temp_dir)

    temp_file = service.get_temp_path(prefix="download", extension=".tmp")
    assert temp_file.parent == temp_dir
    assert not temp_file.exists()

    # Write content to temporary file
    temp_file.write_text("sample media data")
    assert temp_file.exists()

    # Commit to final destination
    final_dest = dl_dir / "final_media.mp4"
    committed = service.commit_temp_file(temp_file, final_dest)

    assert committed == final_dest
    assert final_dest.exists()
    assert not temp_file.exists()
    assert final_dest.read_text() == "sample media data"


# ============================================================================
# MetadataService Tests
# ============================================================================

def test_metadata_format_bytes() -> None:
    """Verify byte formatting handles various ranges cleanly."""
    assert MetadataService.format_bytes(None) == "0 B"
    assert MetadataService.format_bytes(-10) == "0 B"
    assert MetadataService.format_bytes(0) == "0 B"
    assert MetadataService.format_bytes(500) == "500 B"
    assert MetadataService.format_bytes(1024) == "1.00 KB"
    assert MetadataService.format_bytes(1536) == "1.50 KB"
    assert MetadataService.format_bytes(1048576) == "1.00 MB"
    assert MetadataService.format_bytes(1073741824) == "1.00 GB"


def test_metadata_format_duration() -> None:
    """Verify duration formatting across seconds, minutes, and hours."""
    assert MetadataService.format_duration(None) == "--:--"
    assert MetadataService.format_duration(-1) == "--:--"
    assert MetadataService.format_duration(0) == "00:00"
    assert MetadataService.format_duration(45) == "00:45"
    assert MetadataService.format_duration(125) == "02:05"
    assert MetadataService.format_duration(3665) == "01:01:05"


def test_metadata_format_speed() -> None:
    """Verify download speed formatting."""
    assert MetadataService.format_speed(None) == "0 KB/s"
    assert MetadataService.format_speed(0) == "0 KB/s"
    assert MetadataService.format_speed(512) == "512 B/s"
    assert MetadataService.format_speed(2048) == "2.00 KB/s"
    assert MetadataService.format_speed(2097152) == "2.00 MB/s"


def test_metadata_clean_title() -> None:
    """Verify title cleaning decodes HTML entities and normalizes whitespace."""
    assert MetadataService.clean_title("") == "Untitled Media"
    assert MetadataService.clean_title(None) == "Untitled Media"  # type: ignore[arg-type]
    assert MetadataService.clean_title("Tom &amp; Jerry Episode &quot;1&quot;") == 'Tom & Jerry Episode "1"'
    assert MetadataService.clean_title("  Drama   Episode   5   ") == "Drama Episode 5"


# ============================================================================
# FFmpegService Tests
# ============================================================================

def test_ffmpeg_initialization_with_missing_binary() -> None:
    """Verify FFmpegService handles non-existent binary paths gracefully."""
    service = FFmpegService(ffmpeg_path="/non/existent/path/ffmpeg.exe")
    assert service.is_available() is False
    assert service.get_version() is None


def test_ffmpeg_mux_streams_missing_binary(tmp_path: Path) -> None:
    """Verify mux_streams raises FFmpegError if binary is unavailable."""
    service = FFmpegService(ffmpeg_path="/non/existent/path/ffmpeg.exe")
    video = tmp_path / "v.mp4"
    audio = tmp_path / "a.mp3"
    out = tmp_path / "out.mp4"

    video.touch()
    audio.touch()

    with pytest.raises(FFmpegError):
        service.mux_streams(video, audio, out)


def test_ffmpeg_mux_streams_missing_input_file(tmp_path: Path) -> None:
    """Verify mux_streams raises FileNotFoundError if input files do not exist."""
    service = FFmpegService()
    service._ffmpeg_path = "mock_ffmpeg"

    video = tmp_path / "missing_v.mp4"
    audio = tmp_path / "missing_a.mp3"
    out = tmp_path / "out.mp4"

    with pytest.raises(FileNotFoundError):
        service.mux_streams(video, audio, out)


def test_ffmpeg_extract_audio_missing_binary(tmp_path: Path) -> None:
    """Verify extract_audio raises FFmpegError if binary is unavailable."""
    service = FFmpegService(ffmpeg_path="/non/existent/ffmpeg.exe")
    video = tmp_path / "video.mp4"
    video.touch()
    out = tmp_path / "out.mp3"

    with pytest.raises(FFmpegError):
        service.extract_audio(video, out)


def test_ffmpeg_extract_audio_missing_input_file(tmp_path: Path) -> None:
    """Verify extract_audio raises FileNotFoundError if input file does not exist."""
    service = FFmpegService()
    service._ffmpeg_path = "mock_ffmpeg"

    video = tmp_path / "missing_video.mp4"
    out = tmp_path / "out.mp3"

    with pytest.raises(FileNotFoundError):
        service.extract_audio(video, out)


def test_ffmpeg_probe_media_when_missing(tmp_path: Path) -> None:
    """Verify probe_media returns None when ffprobe binary is unavailable or target file missing."""
    service = FFmpegService(ffprobe_path="/non/existent/ffprobe.exe")
    dummy_file = tmp_path / "media.mp4"
    dummy_file.touch()

    assert service.probe_media(dummy_file) is None
    assert service.probe_media(tmp_path / "non_existent.mp4") is None


