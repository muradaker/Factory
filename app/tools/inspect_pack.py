"""
inspect_pack.py — Inspect the current state of a single pack run.

Usage:
    python -m app.tools.inspect_pack <pack_name>
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
    console = None

ROOT = Path(__file__).resolve().parents[2]


def _load_json_safe(path: Path) -> dict | list | None:
    """Load JSON file; return None on any error."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _print_section(title: str) -> None:
    if _RICH:
        console.print(f"\n[bold yellow]{title}[/]")
    else:
        print(f"\n{'='*60}")
        print(f"  {title}")
        print(f"{'='*60}")


def inspect_pack(pack_name: str) -> None:
    """Print a full inspection report for the given pack."""

    # ------------------------------------------------------------------ paths
    state_file = ROOT / "state" / f"{pack_name}.state.json"
    workspace_dir = ROOT / "workspace" / pack_name
    progress_file = workspace_dir / "LiveProgress.json"
    events_file = workspace_dir / "LiveEvents.jsonl"

    # ------------------------------------------------------------------ state
    _print_section(f"Pack: {pack_name} — State")
    state = _load_json_safe(state_file)
    if state is None:
        _warn(f"State file not found: {state_file}")
        state = {}
    else:
        _kv("State file", str(state_file))
        _kv("Current stage", state.get("current_stage", "—"))
        _kv("Status", state.get("status", "—"))
        _kv("Started at", state.get("started_at", "—"))
        _kv("Updated at", state.get("updated_at", "—"))

    # --------------------------------------------------------- stages done/failed
    _print_section("Pipeline Stages")
    stages_done: list[str] = state.get("stages_done", [])
    stages_failed: list[str] = state.get("stages_failed", [])

    if _RICH:
        tbl = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="bold cyan")
        tbl.add_column("Stage", style="white")
        tbl.add_column("Status", justify="center")
        for stage in stages_done:
            tbl.add_row(stage, "[green]✓ done[/]")
        for stage in stages_failed:
            if stage not in stages_done:
                tbl.add_row(stage, "[red]✗ failed[/]")
        console.print(tbl)
    else:
        for s in stages_done:
            print(f"  [DONE]   {s}")
        for s in stages_failed:
            if s not in stages_done:
                print(f"  [FAILED] {s}")

    if not stages_done and not stages_failed:
        print("  (no stages recorded)")

    # --------------------------------------------------- report files in workspace
    _print_section("Report Files in Workspace")
    report_files = sorted(workspace_dir.glob("*.json")) + sorted(workspace_dir.glob("*.jsonl"))
    if report_files:
        for rf in report_files:
            size = rf.stat().st_size if rf.exists() else 0
            _kv(rf.name, f"{size} bytes")
    else:
        print("  (no report files found)")

    # --------------------------------------------------- approval gate status
    _print_section("Approval Gate Status")
    try:
        # Dynamically import approval_policy to avoid hard dependency at module level
        sys.path.insert(0, str(ROOT))
        from app.core.approval_policy import check_approval  # type: ignore

        decision, reason = check_approval(pack_name)
        _kv("Decision", decision)
        _kv("Reason", reason)
    except ImportError:
        _warn("approval_policy module not available — skipping gate check")
    except Exception as exc:
        _warn(f"Error calling check_approval: {exc}")

    # --------------------------------------------------- LiveProgress summary
    _print_section("LiveProgress Summary")
    progress = _load_json_safe(progress_file)
    if progress and isinstance(progress, dict):
        for key, val in progress.items():
            _kv(key, str(val))
    else:
        print("  (LiveProgress.json not found or empty)")

    # --------------------------------------------------- last 10 LiveEvents
    _print_section("Last 10 LiveEvents")
    if events_file.exists():
        lines = events_file.read_text(encoding="utf-8").splitlines()
        tail = lines[-10:] if len(lines) > 10 else lines
        for line in tail:
            try:
                evt = json.loads(line)
                ts = evt.get("ts", evt.get("timestamp", ""))
                msg = evt.get("message", evt.get("msg", line))
                print(f"  [{ts}] {msg}")
            except json.JSONDecodeError:
                print(f"  {line}")
    else:
        print("  (LiveEvents.jsonl not found)")

    print()


def _kv(key: str, value: str) -> None:
    """Print a key/value pair."""
    if _RICH:
        console.print(f"  [cyan]{key}:[/] {value}")
    else:
        print(f"  {key}: {value}")


def _warn(msg: str) -> None:
    if _RICH:
        console.print(f"  [red]WARNING:[/] {msg}")
    else:
        print(f"  WARNING: {msg}")


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python -m app.tools.inspect_pack <pack_name>")
        return 1
    pack_name = sys.argv[1]
    inspect_pack(pack_name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
