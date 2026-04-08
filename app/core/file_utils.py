"""
<<<<<<< HEAD
file_utils.py — Safe mkdir, safe write, safe read, zip utilities.
All operations raise explicit errors on failure — no silent swallowing.
"""

import os
import shutil
import zipfile
from pathlib import Path
from typing import Optional


def safe_mkdir(path: Path | str) -> Path:
    """Create directory (and parents) if it doesn't exist. Returns Path."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def safe_write(path: Path | str, content: str, encoding: str = "utf-8") -> Path:
    """Write text to file, creating parent dirs automatically."""
    p = Path(path)
    safe_mkdir(p.parent)
    p.write_text(content, encoding=encoding)
    return p


def safe_read(path: Path | str, encoding: str = "utf-8") -> Optional[str]:
    """Read text file. Returns None if file does not exist."""
    p = Path(path)
    if not p.exists():
        return None
    return p.read_text(encoding=encoding)


def safe_append(path: Path | str, line: str, encoding: str = "utf-8") -> None:
    """Append a single line to a file, creating it if needed."""
    p = Path(path)
    safe_mkdir(p.parent)
    with p.open("a", encoding=encoding) as f:
        f.write(line + "\n")


def safe_copy(src: Path | str, dst: Path | str) -> Path:
    """Copy a file to dst (creates parent dirs)."""
    s, d = Path(src), Path(dst)
    safe_mkdir(d.parent)
    shutil.copy2(s, d)
    return d


def zip_directory(source_dir: Path | str, output_zip: Path | str) -> Path:
    """
    Zip all files inside source_dir into output_zip.
    Paths inside the archive are relative to source_dir.
    """
    src = Path(source_dir)
    out = Path(output_zip)
    safe_mkdir(out.parent)

    if not src.exists():
        raise FileNotFoundError(f"Source dir does not exist: {src}")

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in src.rglob("*"):
            if file_path.is_file():
                arcname = file_path.relative_to(src)
                zf.write(file_path, arcname)

    return out


def zip_files(file_paths: list[Path | str], output_zip: Path | str, arcroot: Optional[Path] = None) -> Path:
    """
    Zip an explicit list of files.
    If arcroot is provided, arc names are relative to arcroot.
    """
    out = Path(output_zip)
    safe_mkdir(out.parent)

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for fp in file_paths:
            p = Path(fp)
            if not p.exists():
                raise FileNotFoundError(f"File to zip not found: {p}")
            arcname = p.relative_to(arcroot) if arcroot else p.name
            zf.write(p, arcname)

    return out


def list_files(directory: Path | str, pattern: str = "*") -> list[Path]:
    """List all files matching glob pattern in directory (non-recursive)."""
    d = Path(directory)
    if not d.exists():
        return []
    return sorted([f for f in d.glob(pattern) if f.is_file()])


def list_files_recursive(directory: Path | str, pattern: str = "*") -> list[Path]:
    """List all files matching glob pattern recursively."""
    d = Path(directory)
    if not d.exists():
        return []
    return sorted([f for f in d.rglob(pattern) if f.is_file()])
=======
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
>>>>>>> V4
