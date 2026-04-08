"""
memory_browser.py — Browse persisted memory entries by category.

Usage:
    python -m app.tools.memory_browser
    python -m app.tools.memory_browser --category approved_plugins
    python -m app.tools.memory_browser --category all
"""

import sys
import json
from pathlib import Path

try:
    from rich.console import Console
    from rich.table import Table
    from rich import box

    _RICH = True
    console = Console()
except ImportError:
    _RICH = False
    console = None  # type: ignore

ROOT = Path(__file__).resolve().parents[2]
MEMORY_ROOT = ROOT / "memory"

# All known memory categories
ALL_CATEGORIES = [
    "approved_plugins",
    "rejected_plugins",
    "error_patterns",
    "ue5_solutions",
    "style_rules",
    "review_feedback",
]


def _load_entries(category_dir: Path) -> list[dict]:
    """Load all JSON / JSONL entries from a category directory."""
    entries: list[dict] = []

    # Individual JSON files
    for p in sorted(category_dir.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("_file", p.name)
                entries.append(data)
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        item.setdefault("_file", p.name)
                        entries.append(item)
        except (json.JSONDecodeError, OSError):
            pass

    # JSONL files
    for p in sorted(category_dir.glob("*.jsonl")):
        try:
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict):
                        obj.setdefault("_file", p.name)
                        entries.append(obj)
                except json.JSONDecodeError:
                    pass
        except OSError:
            pass

    return entries


def _print_category(category: str) -> int:
    """Print all entries for one category; return entry count."""
    cat_dir = MEMORY_ROOT / category
    if not cat_dir.is_dir():
        _info(f"Category '{category}' directory not found — skipping")
        return 0

    entries = _load_entries(cat_dir)

    if _RICH:
        tbl = Table(
            title=f"[bold cyan]{category}[/]  ({len(entries)} entries)",
            box=box.SIMPLE_HEAVY,
            show_lines=True,
        )
        tbl.add_column("#", style="dim", width=4, justify="right")
        tbl.add_column("File", style="dim", max_width=25)
        tbl.add_column("ID / Name", style="white", max_width=30)
        tbl.add_column("Summary", style="yellow", max_width=60)

        for idx, entry in enumerate(entries, start=1):
            ident = (
                entry.get("id")
                or entry.get("name")
                or entry.get("pack_name")
                or "—"
            )
            summary = entry.get("summary") or entry.get("description") or "—"
            # Truncate very long summaries
            if len(summary) > 120:
                summary = summary[:117] + "..."
            tbl.add_row(str(idx), entry.get("_file", ""), str(ident), summary)

        console.print(tbl)
    else:
        print(f"\n[{category}]  ({len(entries)} entries)")
        print("-" * 70)
        for idx, entry in enumerate(entries, start=1):
            ident = entry.get("id") or entry.get("name") or entry.get("pack_name") or "—"
            summary = entry.get("summary") or entry.get("description") or "—"
            if len(summary) > 100:
                summary = summary[:97] + "..."
            print(f"  {idx:3d}. [{entry.get('_file', '')}] {ident}: {summary}")

    return len(entries)


def _info(msg: str) -> None:
    if _RICH:
        console.print(f"  [dim]{msg}[/dim]")
    else:
        print(f"  {msg}")


def main() -> int:
    # Parse --category argument
    category_arg = "all"
    if "--category" in sys.argv:
        idx = sys.argv.index("--category")
        if idx + 1 < len(sys.argv):
            category_arg = sys.argv[idx + 1]
        else:
            print("Error: --category requires a value")
            return 1

    if _RICH:
        console.print("\n[bold cyan]Myth Studio — Memory Browser[/]\n")
    else:
        print("\nMyth Studio — Memory Browser\n")

    if category_arg == "all":
        categories = ALL_CATEGORIES
    else:
        if category_arg not in ALL_CATEGORIES:
            print(f"Unknown category '{category_arg}'.")
            print(f"Valid categories: {', '.join(ALL_CATEGORIES)} or 'all'")
            return 1
        categories = [category_arg]

    total_entries = 0
    counts: dict[str, int] = {}
    for cat in categories:
        count = _print_category(cat)
        counts[cat] = count
        total_entries += count

    # Summary table
    if _RICH:
        from rich.table import Table as _T
        from rich import box as _box

        summary = _T(title="Summary", box=_box.MINIMAL_DOUBLE_HEAD)
        summary.add_column("Category", style="cyan")
        summary.add_column("Entries", justify="right", style="white")
        for cat, cnt in counts.items():
            summary.add_row(cat, str(cnt))
        summary.add_row("[bold]TOTAL[/]", f"[bold]{total_entries}[/]")
        console.print(summary)
    else:
        print("\nSummary")
        print("-" * 30)
        for cat, cnt in counts.items():
            print(f"  {cat:<25} {cnt}")
        print(f"  {'TOTAL':<25} {total_entries}")

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
