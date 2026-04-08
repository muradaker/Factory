"""
file_utils.py — Safe filesystem helpers used across all agents and tools.
All functions swallow common OS errors and log them instead of raising.
"""

import logging
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)


def safe_mkdir(path: Path) -> None:
    """Create directory (and parents); silent if it already exists."""
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.error("safe_mkdir failed for %s: %s", path, exc)


def safe_write(path: Path, content: str, encoding: str = "utf-8") -> None:
    """Write text to path, creating parent directories as needed."""
    try:
        safe_mkdir(path.parent)
        path.write_text(content, encoding=encoding)
    except OSError as exc:
        logger.error("safe_write failed for %s: %s", path, exc)


def safe_read(path: Path, default: str = "") -> str:
    """Read text from path; return default string if file is missing or unreadable."""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        logger.debug("safe_read: returning default for %s (%s)", path, exc)
        return default


def zip_directory(source_dir: Path, output_zip: Path) -> bool:
    """Zip all files inside source_dir into output_zip.

    Preserves relative directory structure inside the archive.
    Returns True on success, False on any error.
    """
    try:
        safe_mkdir(output_zip.parent)
        with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_path in source_dir.rglob("*"):
                if file_path.is_file():
                    arcname = file_path.relative_to(source_dir)
                    zf.write(file_path, arcname)
        logger.info("zip_directory: wrote %s", output_zip)
        return True
    except OSError as exc:
        logger.error("zip_directory failed: %s", exc)
        return False


def find_files(directory: Path, extension: str) -> list[Path]:
    """Recursively find all files with the given extension under directory.

    Extension should be passed with or without leading dot, e.g. '.py' or 'py'.
    Returns empty list if directory does not exist.
    """
    if not directory.exists():
        return []
    # Normalise extension
    ext = extension if extension.startswith(".") else f".{extension}"
    return sorted(directory.rglob(f"*{ext}"))


def file_exists_and_nonempty(path: Path) -> bool:
    """Return True only if path exists, is a file, and has at least one byte."""
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False
