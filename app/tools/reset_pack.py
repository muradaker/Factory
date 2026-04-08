"""
reset_pack.py — Delete pack state and workspace so it can be re-run.
Memory entries are preserved so learned knowledge is retained.

Usage:
    python -m app.tools.reset_pack <pack_name> [--confirm]
"""

import sys
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _rmfile(path: Path) -> bool:
    """Delete a single file; return True if deleted."""
    if path.exists() and path.is_file():
        path.unlink()
        return True
    return False


def _rmdir(path: Path) -> bool:
    """Delete a directory and all its contents; return True if deleted."""
    if path.exists() and path.is_dir():
        shutil.rmtree(path)
        return True
    return False


def reset_pack(pack_name: str, confirmed: bool) -> int:
    """Perform the reset; return exit code."""
    state_file = ROOT / "state" / f"{pack_name}.state.json"
    workspace_dir = ROOT / "workspace" / pack_name

    # Collect what would be deleted
    targets: list[tuple[str, Path]] = [
        ("state file", state_file),
        ("workspace dir", workspace_dir),
    ]

    # Dry-run output
    print(f"\nReset plan for pack: {pack_name}")
    print("-" * 50)
    for label, path in targets:
        exists = path.exists()
        mark = "→ WILL DELETE" if exists else "  (not found, skip)"
        print(f"  {label}: {path}  {mark}")
    print()

    if not confirmed:
        print("Add --confirm to proceed with deletion.")
        print("Note: memory entries are NOT deleted (learning is preserved).\n")
        return 0

    # Perform deletions
    deleted: list[str] = []

    if _rmfile(state_file):
        deleted.append(str(state_file))
        print(f"  Deleted state file: {state_file}")
    else:
        print(f"  State file not found, skipped: {state_file}")

    if _rmdir(workspace_dir):
        deleted.append(str(workspace_dir))
        print(f"  Deleted workspace dir: {workspace_dir}")
    else:
        print(f"  Workspace dir not found, skipped: {workspace_dir}")

    if deleted:
        print(f"\nReset complete. {len(deleted)} item(s) deleted.")
        print("Memory entries preserved — learned knowledge retained.\n")
    else:
        print("\nNothing to delete — pack was already clean.\n")

    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python -m app.tools.reset_pack <pack_name> [--confirm]")
        return 1

    pack_name = sys.argv[1]
    confirmed = "--confirm" in sys.argv
    return reset_pack(pack_name, confirmed)


if __name__ == "__main__":
    sys.exit(main())
