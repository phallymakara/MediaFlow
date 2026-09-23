"""FFmpeg media processing and stream combination service."""

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

from app.config import get_config

logger = logging.getLogger(__name__)


class FFmpegError(Exception):
    """Raised when an FFmpeg processing operation fails."""

    pass


class FFmpegService:
    """Service interfacing with FFmpeg and FFprobe binaries."""

    def __init__(
        self,
        ffmpeg_path: Optional[str] = None,
        ffprobe_path: Optional[str] = None,
    ) -> None:
        """Initialize FFmpeg service and locate executables."""
        config = get_config()
        self._ffmpeg_path = self._resolve_binary(
            ffmpeg_path or config.ffmpeg_path,
            "ffmpeg",
        )
        self._ffprobe_path = self._resolve_binary(
            ffprobe_path or config.ffprobe_path,
            "ffprobe",
        )

        if self.is_available():
            logger.info("FFmpeg binary detected at: %s", self._ffmpeg_path)
        else:
            logger.warning("FFmpeg binary not detected on system PATH or configuration.")

    @staticmethod
    def _resolve_binary(custom_path: Optional[str], default_name: str) -> Optional[str]:
        """Resolve full path to executable from custom setting or system PATH."""
        if custom_path and custom_path.strip():
            candidate = Path(custom_path.strip()).resolve()
            return str(candidate) if candidate.is_file() else None

        # Look in system PATH when no custom path was provided
        return shutil.which(default_name)

    def is_available(self) -> bool:
        """Return True if FFmpeg executable is located and usable."""
        return self._ffmpeg_path is not None

    def is_probe_available(self) -> bool:
        """Return True if FFprobe executable is located and usable."""
        return self._ffprobe_path is not None

    def _get_subprocess_flags(self) -> Dict[str, Any]:
        """Configure subprocess flags to suppress console popups on Windows."""
        kwargs: Dict[str, Any] = {}
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        return kwargs

    def get_version(self) -> Optional[str]:
        """Retrieve the installed FFmpeg version string."""
        if not self.is_available():
            return None

        try:
            cmd = [str(self._ffmpeg_path), "-version"]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
                timeout=5,
                **self._get_subprocess_flags(),
            )
            first_line = result.stdout.splitlines()[0] if result.stdout else ""
            return first_line.strip()
        except (subprocess.SubprocessError, OSError) as exc:
            logger.error("Failed to query FFmpeg version: %s", exc)
            return None

    def mux_streams(
        self,
        video_path: Path,
        audio_path: Path,
        output_path: Path,
    ) -> bool:
        """Merge separate video and audio streams into single output file using stream copy.

        Args:
            video_path: Path to video stream file.
            audio_path: Path to audio stream file.
            output_path: Destination path for combined media file.

        Returns:
            True if muxing succeeded.

        Raises:
            FFmpegError: If FFmpeg is unavailable or command execution fails.
            FileNotFoundError: If input files do not exist.
        """
        if not self.is_available():
            raise FFmpegError("FFmpeg is not available on this system.")

        if not video_path.exists():
            raise FileNotFoundError(f"Video input file not found: {video_path}")
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio input file not found: {audio_path}")

        output_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            str(self._ffmpeg_path),
            "-y",
            "-i", str(video_path),
            "-i", str(audio_path),
            "-c", "copy",
            str(output_path),
        ]

        logger.debug("Executing FFmpeg mux: %s", " ".join(cmd))
        try:
            subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
                **self._get_subprocess_flags(),
            )
            logger.info("Successfully muxed streams into: %s", output_path)
            return True
        except subprocess.CalledProcessError as exc:
            logger.error("FFmpeg muxing failed: %s", exc.stderr)
            raise FFmpegError("Failed to combine audio and video streams.") from exc

    def extract_audio(
        self,
        input_path: Path,
        output_path: Path,
        audio_format: str = "mp3",
        bitrate: str = "192k",
    ) -> bool:
        """Extract audio track from video file into target audio format.

        Args:
            input_path: Source media file path.
            output_path: Destination audio file path.
            audio_format: Output audio format ('mp3', 'm4a', 'aac').
            bitrate: Audio bitrate (e.g. '192k', '320k').

        Returns:
            True if audio extraction succeeded.

        Raises:
            FFmpegError: If FFmpeg is unavailable or command fails.
            FileNotFoundError: If input file does not exist.
        """
        if not self.is_available():
            raise FFmpegError("FFmpeg is not available on this system.")

        if not input_path.exists():
            raise FileNotFoundError(f"Input file not found: {input_path}")

        output_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            str(self._ffmpeg_path),
            "-y",
            "-i", str(input_path),
            "-vn",
            "-b:a", bitrate,
            str(output_path),
        ]

        logger.debug("Executing FFmpeg audio extraction: %s", " ".join(cmd))
        try:
            subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
                **self._get_subprocess_flags(),
            )
            logger.info("Successfully extracted audio to: %s", output_path)
            return True
        except subprocess.CalledProcessError as exc:
            logger.error("FFmpeg audio extraction failed: %s", exc.stderr)
            raise FFmpegError("Failed to extract audio track from media.") from exc

    def probe_media(self, file_path: Path) -> Optional[Dict[str, Any]]:
        """Probe media file and extract format and stream metadata using FFprobe.

        Args:
            file_path: Target media file path.

        Returns:
            Dictionary containing probe output, or None if probe fails or is unavailable.
        """
        if not self.is_probe_available():
            logger.debug("FFprobe not available for media inspection.")
            return None

        if not file_path.exists():
            logger.warning("Target file for probing does not exist: %s", file_path)
            return None

        cmd = [
            str(self._ffprobe_path),
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            str(file_path),
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
                timeout=10,
                **self._get_subprocess_flags(),
            )
            return json.loads(result.stdout)
        except (subprocess.SubprocessError, json.JSONDecodeError, OSError) as exc:
            logger.error("Failed to probe media file %s: %s", file_path, exc)
            return None

