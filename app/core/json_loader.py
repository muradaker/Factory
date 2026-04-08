"""
json_loader.py — Load/save JSON with error handling and atomic writes.
Never silently returns bad data. Raises on parse failure.
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Optional

from app.core.file_utils import safe_mkdir


def load_json(path: Path | str) -> Optional[dict | list]:
    """
    Load JSON from path. Returns None if file does not exist.
    Raises ValueError on parse error with file path in message.
    """
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in {p}: {e}") from e


def save_json(path: Path | str, data: Any, indent: int = 2) -> Path:
    """
    Save data as JSON to path using an atomic write (temp file + rename).
    Creates parent dirs. Returns the final Path.
    """
    p = Path(path)
    safe_mkdir(p.parent)

    serialized = json.dumps(data, indent=indent, ensure_ascii=False, default=str)

    # Write to temp then rename for atomicity on Windows too
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=p.parent, prefix=".tmp_", suffix=".json"
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(serialized)
        # On Windows, target must not exist for os.rename → use replace
        Path(tmp_path).replace(p)
    except Exception:
        # Clean up temp file on failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    return p


def load_json_or_default(path: Path | str, default: Any) -> Any:
    """Load JSON; return default if file missing or parse error."""
    try:
        result = load_json(path)
        return result if result is not None else default
    except ValueError:
        return default


def append_jsonl(path: Path | str, record: dict) -> None:
    """Append a single JSON object as a line to a .jsonl file."""
    p = Path(path)
    safe_mkdir(p.parent)
    line = json.dumps(record, ensure_ascii=False, default=str)
    with p.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_jsonl(path: Path | str) -> list[dict]:
    """Load all lines from a .jsonl file. Returns empty list if missing."""
    p = Path(path)
    if not p.exists():
        return []
    records = []
    for i, line in enumerate(p.read_text(encoding="utf-8").splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as e:
            raise ValueError(f"Bad JSON on line {i+1} in {p}: {e}") from e
    return records
