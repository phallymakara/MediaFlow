"""File storage and path sanitization service."""

import logging
import os
import re
import shutil
import uuid
from pathlib import Path
from typing import Optional

from app.config import get_config

logger = logging.getLogger(__name__)

WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
}

ILLEGAL_CHARS_PATTERN = re.compile(r'[\\/*?:"<>|]')
CONTROL_CHARS_PATTERN = re.compile(r'[\x00-\x1f\x7f]')


class StorageService:
    """Manages file storage paths, safe filename sanitization, and temp directories."""

    def __init__(
        self,
        base_download_dir: Optional[Path] = None,
        temp_dir: Optional[Path] = None,
    ) -> None:
        """Initialize storage service with download and temporary directories."""
        config = get_config()
        self.base_download_dir = Path(base_download_dir or config.download_dir).resolve()
        self.temp_dir = Path(temp_dir or config.temp_dir).resolve()

        self._ensure_directories()

    def _ensure_directories(self) -> None:
        """Create storage directories if they do not exist."""
        try:
            self.base_download_dir.mkdir(parents=True, exist_ok=True)
            self.temp_dir.mkdir(parents=True, exist_ok=True)
            logger.debug(
                "Storage directories initialized: download=%s, temp=%s",
                self.base_download_dir,
                self.temp_dir,
            )
        except OSError as exc:
            logger.error("Failed to create storage directories: %s", exc)
            raise

    @staticmethod
    def sanitize_filename(name: str, max_length: int = 200) -> str:
        """Sanitize a filename by removing illegal characters and preventing collisions with system reserved names.

        Args:
            name: Original filename or title.
            max_length: Maximum allowed character length for the filename.

        Returns:
            A clean, safe filename string.
        """
        if not name or not name.strip():
            return "media_download"

        # Separate stem and extension without treating slashes as path separators
        stem, ext = os.path.splitext(name.strip())

        # Replace illegal filesystem characters and control characters with underscore
        clean_stem = ILLEGAL_CHARS_PATTERN.sub("_", stem)
        clean_stem = CONTROL_CHARS_PATTERN.sub("_", clean_stem)

        # Replace multiple spaces or underscores with a single character
        clean_stem = re.sub(r"[\s_]+", "_", clean_stem).strip(" ._")
        clean_ext = ILLEGAL_CHARS_PATTERN.sub("", ext).strip()

        # If stem is empty after sanitization, assign default stem
        if not clean_stem:
            clean_stem = "media_download"

        # Check for Windows reserved device names
        if clean_stem.upper() in WINDOWS_RESERVED_NAMES:
            clean_stem = f"_{clean_stem}"

        # Truncate length while preserving file extension
        max_stem_length = max_length - len(clean_ext)
        if max_stem_length < 1:
            clean_stem = clean_stem[:max_length]
            clean_ext = ""
        elif len(clean_stem) > max_stem_length:
            clean_stem = clean_stem[:max_stem_length].rstrip(" ._")

        return f"{clean_stem}{clean_ext}"

    def get_destination_path(self, filename: str, subfolder: Optional[str] = None) -> Path:
        """Resolve a destination file path within the base download directory.

        Ensures that path traversal attempts (e.g., using '../../') are strictly prevented.

        Args:
            filename: Target file name.
            subfolder: Optional subfolder inside base download directory.

        Returns:
            Resolved absolute destination path.

        Raises:
            ValueError: If path resolves outside the permitted download directory.
        """
        # Explicit check for path traversal patterns
        if ".." in filename or (subfolder and ".." in subfolder):
            logger.warning("Path traversal attempt blocked: filename=%s, subfolder=%s", filename, subfolder)
            raise ValueError("Path traversal attempt detected")

        clean_name = self.sanitize_filename(filename)

        if subfolder:
            clean_subfolder = self.sanitize_filename(subfolder)
            target_dir = (self.base_download_dir / clean_subfolder).resolve()
        else:
            target_dir = self.base_download_dir

        resolved_path = (target_dir / clean_name).resolve()

        # Verify path traversal containment
        if not resolved_path.is_relative_to(self.base_download_dir):
            logger.warning("Path traversal attempt blocked for filename: %s", filename)
            raise ValueError("Target path must be inside download directory")

        target_dir.mkdir(parents=True, exist_ok=True)
        return resolved_path

    def get_unique_destination_path(self, target_path: Path) -> Path:
        """Return a unique destination path by appending an incrementing suffix if the file exists.

        Args:
            target_path: Desired target file path.

        Returns:
            A unique Path that does not currently exist on disk.
        """
        if not target_path.exists():
            return target_path

        stem = target_path.stem
        ext = target_path.suffix
        parent = target_path.parent

        counter = 1
        while True:
            candidate = parent / f"{stem} ({counter}){ext}"
            if not candidate.exists():
                return candidate
            counter += 1

    def get_temp_path(self, prefix: str = "media", extension: str = ".tmp") -> Path:
        """Generate a unique temporary file path in the temp directory.

        Args:
            prefix: Prefix identifier for the temporary file.
            extension: File extension including the leading dot.

        Returns:
            Path to non-existent temporary file.
        """
        clean_prefix = re.sub(r"[^\w-]", "_", prefix)
        unique_token = uuid.uuid4().hex[:8]
        clean_ext = extension if extension.startswith(".") else f".{extension}"
        temp_name = f"{clean_prefix}_{unique_token}{clean_ext}"
        return self.temp_dir / temp_name

    def commit_temp_file(self, temp_path: Path, final_path: Path) -> Path:
        """Atomically move completed temporary file to its final destination.

        Args:
            temp_path: Source temporary file path.
            final_path: Final destination path.

        Returns:
            The final destination path.

        Raises:
            FileNotFoundError: If temp_path does not exist.
        """
        if not temp_path.exists():
            raise FileNotFoundError(f"Temporary file does not exist: {temp_path}")

        final_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(temp_path), str(final_path))
        logger.info("Committed temporary file %s to %s", temp_path.name, final_path)
        return final_path

