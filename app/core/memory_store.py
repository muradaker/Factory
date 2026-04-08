"""
memory_store.py — Persistent JSON memory per category.
Writes records to memory/{category}/{pack_name}_{ts}.json.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.core.json_loader import load_json_or_default, save_json
from app.core.file_utils import safe_mkdir, list_files

# Root memory directory (relative to project root)
_MEMORY_ROOT = Path(__file__).resolve().parents[2] / "memory"

VALID_CATEGORIES = {
    "approved_plugins",
    "rejected_plugins",
    "build_failures",
    "runtime_failures",
    "map_failures",
    "multiplayer_failures",
    "patches",
    "review_decisions",
    "architecture_patterns",
    "code_patterns",
    "docs_patterns",
    "optimization_patterns",
    "market_notes",
}


def _category_dir(category: str) -> Path:
    if category not in VALID_CATEGORIES:
        raise ValueError(f"Unknown memory category: {category!r}. Valid: {VALID_CATEGORIES}")
    return _MEMORY_ROOT / category


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")


def write_memory(category: str, pack_name: str, data_dict: dict) -> Path:
    """
    Save data_dict as JSON to memory/{category}/{pack_name}_{ts}.json.
    Injects pack_name and written_at into the record automatically.
    Returns the path written.
    """
    cat_dir = _category_dir(category)
    safe_mkdir(cat_dir)

    record = {
        "pack_name": pack_name,
        "category": category,
        "written_at": datetime.now(timezone.utc).isoformat(),
        **data_dict,
    }

    filename = f"{pack_name}_{_ts()}.json"
    out_path = cat_dir / filename
    save_json(out_path, record)
    return out_path


def list_memory(category: str) -> list[dict]:
    """
    Return a list of all memory records (dicts) from memory/{category}/.
    Silently skips files that cannot be parsed.
    Returns empty list if category dir is empty or missing.
    """
    cat_dir = _category_dir(category)
    if not cat_dir.exists():
        return []

    records: list[dict] = []
    for json_file in list_files(cat_dir, pattern="*.json"):
        data = load_json_or_default(json_file, default=None)
        if isinstance(data, dict):
            records.append(data)

    return records


def get_latest_memory(category: str, pack_name: str) -> Optional[dict]:
    """
    Return the most recent memory record for a specific pack in a category.
    Returns None if no record exists.
    """
    cat_dir = _category_dir(category)
    if not cat_dir.exists():
        return None

    # Filter by pack prefix, sort by filename (timestamp suffix guarantees order)
    matching = sorted(cat_dir.glob(f"{pack_name}_*.json"))
    if not matching:
        return None

    return load_json_or_default(matching[-1], default=None)


def delete_memory_file(path: Path) -> bool:
    """Delete a specific memory file. Returns True on success."""
    try:
        path.unlink()
        return True
    except OSError:
        return False


def count_memory(category: str) -> int:
    """Return number of records in a category."""
    cat_dir = _category_dir(category)
    if not cat_dir.exists():
        return 0
    return len(list(cat_dir.glob("*.json")))
