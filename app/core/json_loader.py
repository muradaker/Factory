"""
json_loader.py — Safe JSON I/O helpers.
All functions log warnings on error and return safe sentinel values.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def load_json(path: Path) -> dict | list | None:
    """Load a JSON file and return the parsed object.

    Returns None if file is missing, unreadable, or contains invalid JSON.
    """
    try:
        text = path.read_text(encoding="utf-8")
        return json.loads(text)
    except FileNotFoundError:
        logger.warning("load_json: file not found: %s", path)
        return None
    except json.JSONDecodeError as exc:
        logger.warning("load_json: invalid JSON in %s: %s", path, exc)
        return None
    except OSError as exc:
        logger.warning("load_json: OS error reading %s: %s", path, exc)
        return None


def save_json(path: Path, data, indent: int = 2) -> bool:
    """Serialize data as JSON and write to path (creates parent dirs).

    Returns True on success, False on any error.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(data, indent=indent, ensure_ascii=False)
        path.write_text(text, encoding="utf-8")
        return True
    except (OSError, TypeError, ValueError) as exc:
        logger.error("save_json: failed to write %s: %s", path, exc)
        return False


def load_json_lines(path: Path) -> list[dict]:
    """Parse a .jsonl file and return a list of dicts.

    Skips blank lines and lines that fail to parse (logs each skip).
    Returns empty list if file is missing.
    """
    records: list[dict] = []
    if not path.exists():
        logger.debug("load_json_lines: file not found: %s", path)
        return records

    try:
        with path.open(encoding="utf-8") as fh:
            for lineno, raw_line in enumerate(fh, start=1):
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict):
                        records.append(obj)
                    else:
                        logger.debug(
                            "load_json_lines: line %d in %s is not a dict, skipped",
                            lineno,
                            path,
                        )
                except json.JSONDecodeError as exc:
                    logger.warning(
                        "load_json_lines: parse error at %s line %d: %s", path, lineno, exc
                    )
    except OSError as exc:
        logger.warning("load_json_lines: OS error reading %s: %s", path, exc)

    return records


def append_jsonl(path: Path, record: dict) -> None:
    """Append one JSON record as a single line to a .jsonl file.

    Creates parent directories and the file if they do not exist.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except (OSError, TypeError, ValueError) as exc:
        logger.error("append_jsonl: failed to append to %s: %s", path, exc)
