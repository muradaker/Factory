"""
main.py — CLI entry point for Myth Studio UE5.5 Plugin Factory.
Commands: run-job, run-index, run-factory
"""

from __future__ import annotations

import signal
import sys
import time
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.table import Table
from rich.text import Text

from app.core.config import cfg
from app.core.json_loader import load_json_or_default, save_json
from app.core.logger import log_system, log_info, log_warn, log_stage_fail
from app.core.file_utils import safe_mkdir
from app.core.state_store import get_state, reset as reset_state, increment_run_count

console = Console()

# Default jobs file path
_DEFAULT_JOBS_FILE = Path(__file__).resolve().parents[1] / "input" / "jobs_index.json"

# Graceful shutdown flag for factory loop
_shutdown_requested = False


def _handle_sigint(sig, frame):
    global _shutdown_requested
    _shutdown_requested = True
    console.print(Text("\n[Factory] Ctrl+C received — finishing current job then shutting down...", style="bold yellow"))


signal.signal(signal.SIGINT, _handle_sigint)


# ── helpers ───────────────────────────────────────────────────────────────────


def _load_jobs(jobs_file: Path) -> list[dict]:
    """Load jobs list from JSON file. Returns empty list on error."""
    data = load_json_or_default(jobs_file, default=[])
    if not isinstance(data, list):
        log_system(f"jobs file {jobs_file} is not a list — treating as empty")
        return []
    return data


def _save_jobs(jobs_file: Path, jobs: list[dict]) -> None:
    save_json(jobs_file, jobs)


def _find_job(jobs: list[dict], pack_name: str) -> Optional[dict]:
    for job in jobs:
        if job.get("name") == pack_name:
            return job
    return None


def _print_job_table(jobs: list[dict]) -> None:
    """Print a rich table of all jobs and their statuses."""
    table = Table(title="Job Index", show_lines=True)
    table.add_column("Pack Name", style="cyan")
    table.add_column("Status", style="white")
    table.add_column("Retries", style="yellow")

    for job in jobs:
        status = job.get("status", "unknown")
        retries = str(job.get("retries", 0))
        color = "green" if status == "done" else "red" if status == "failed" else "cyan"
        table.add_row(job.get("name", "?"), Text(status, style=color), retries)

    console.print(table)


def _run_single_job(pack_name: str, force_reheal: bool = False) -> bool:
    """
    Execute the full pipeline for a single pack.
    Returns True on success, False on failure.
    This is a stub — real agent stages will be added in Parts 2-4.
    """
    console.print(Text(f"\n[Job] Starting: {pack_name}", style="bold cyan"))

    # Ensure workspace and reports dirs exist
    safe_mkdir(cfg.workspace_for(pack_name))
    safe_mkdir(cfg.reports_dir(pack_name))

    increment_run_count(pack_name)
    state = get_state(pack_name)
    console.print(Text(f"  Run #{state['run_count']} | force_reheal={force_reheal}", style="dim white"))

    # ── Placeholder pipeline ──────────────────────────────────────────────────
    # In Parts 2-4, real agent stage calls replace this block.
    console.print(Text(f"  [Pipeline] Foundation layer only — no agents yet.", style="dim yellow"))
    console.print(Text(f"  [Pipeline] Workspace ready at: {cfg.workspace_for(pack_name)}", style="dim white"))
    console.print(Text(f"  [Pipeline] Reports dir ready at: {cfg.reports_dir(pack_name)}", style="dim white"))
    # ─────────────────────────────────────────────────────────────────────────

    console.print(Text(f"[Job] Done: {pack_name}\n", style="bold green"))
    return True


# ── CLI commands ──────────────────────────────────────────────────────────────


@click.group()
def cli():
    """Myth Studio UE5.5 Autonomous Plugin Production Factory."""
    pass


@cli.command("run-job")
@click.argument("pack_name")
@click.option("--force-reheal", is_flag=True, default=False, help="Force a self-heal pass even if state looks clean.")
def run_job(pack_name: str, force_reheal: bool):
    """Run the full pipeline for a single pack by name."""
    console.print(Text(f"\n=== run-job: {pack_name} ===", style="bold white"))
    success = _run_single_job(pack_name, force_reheal=force_reheal)
    if not success:
        console.print(Text(f"[run-job] FAILED: {pack_name}", style="bold red"))
        sys.exit(1)
    console.print(Text(f"[run-job] SUCCESS: {pack_name}", style="bold green"))


@cli.command("run-index")
@click.option("--jobs-file", default=str(_DEFAULT_JOBS_FILE), show_default=True,
              help="Path to jobs_index.json")
def run_index(jobs_file: str):
    """Run all pending jobs in the jobs index (single pass, no loop)."""
    jobs_path = Path(jobs_file)
    if not jobs_path.exists():
        console.print(Text(f"[run-index] Jobs file not found: {jobs_path}", style="bold red"))
        sys.exit(1)

    jobs = _load_jobs(jobs_path)
    if not jobs:
        console.print(Text("[run-index] No jobs found.", style="yellow"))
        return

    _print_job_table(jobs)

    pending = [j for j in jobs if j.get("status") in ("pending", "failed")]
    console.print(Text(f"\n[run-index] {len(pending)} pending/failed jobs to process.", style="cyan"))

    for job in pending:
        if _shutdown_requested:
            break
        pack_name = job.get("name", "")
        if not pack_name:
            continue

        success = _run_single_job(pack_name)
        job["retries"] = job.get("retries", 0) + (0 if success else 1)
        job["status"] = "done" if success else "failed"
        _save_jobs(jobs_path, jobs)

    _print_job_table(jobs)
    console.print(Text("\n[run-index] Complete.", style="bold green"))


@cli.command("run-factory")
@click.option("--jobs-file", default=str(_DEFAULT_JOBS_FILE), show_default=True,
              help="Path to jobs_index.json")
@click.option("--loop-forever", is_flag=True, default=False,
              help="Keep looping until all jobs are done or Ctrl+C.")
def run_factory(jobs_file: str, loop_forever: bool):
    """
    Factory loop: process jobs continuously.
    Retries failed jobs up to FACTORY_MAX_JOB_RETRIES times.
    Sleeps FACTORY_LOOP_SLEEP_SECONDS between rounds.
    """
    global _shutdown_requested
    jobs_path = Path(jobs_file)

    if not jobs_path.exists():
        console.print(Text(f"[run-factory] Jobs file not found: {jobs_path}", style="bold red"))
        sys.exit(1)

    console.print(Text("\n=== Myth Studio Factory — Starting ===", style="bold cyan"))
    console.print(Text(f"  Jobs file    : {jobs_path}", style="dim white"))
    console.print(Text(f"  Max retries  : {cfg.factory_max_job_retries}", style="dim white"))
    console.print(Text(f"  Loop sleep   : {cfg.factory_loop_sleep_seconds}s", style="dim white"))
    console.print(Text(f"  Loop forever : {loop_forever}", style="dim white"))
    console.print(Text("  Press Ctrl+C to exit gracefully.\n", style="dim yellow"))

    round_number = 0

    while not _shutdown_requested:
        round_number += 1
        jobs = _load_jobs(jobs_path)

        # Select jobs eligible for processing
        eligible = [
            j for j in jobs
            if j.get("status") in ("pending", "failed")
            and j.get("retries", 0) < cfg.factory_max_job_retries
        ]

        if not eligible:
            if not loop_forever:
                console.print(Text("[Factory] No eligible jobs remaining. Exiting.", style="bold green"))
                break
            console.print(Text(
                f"[Factory] Round {round_number}: No eligible jobs. "
                f"Sleeping {cfg.factory_loop_sleep_seconds}s...",
                style="dim white"
            ))
            _interruptible_sleep(cfg.factory_loop_sleep_seconds)
            continue

        console.print(Text(
            f"\n[Factory] Round {round_number} — {len(eligible)} job(s) eligible",
            style="bold cyan"
        ))

        for job in eligible:
            if _shutdown_requested:
                break

            pack_name = job.get("name", "")
            if not pack_name:
                continue

            success = _run_single_job(pack_name)
            job["retries"] = job.get("retries", 0) + (0 if success else 1)
            job["status"] = "done" if success else "failed"
            _save_jobs(jobs_path, jobs)

            # Sleep between jobs based on outcome
            if success:
                cooldown = cfg.factory_success_cooldown_seconds
            else:
                cooldown = cfg.factory_fail_cooldown_seconds

            if not _shutdown_requested:
                console.print(Text(f"  [Factory] Cooling down {cooldown}s before next job...", style="dim white"))
                _interruptible_sleep(cooldown)

        if not loop_forever:
            # Check if all done
            jobs = _load_jobs(jobs_path)
            remaining = [j for j in jobs if j.get("status") not in ("done",)]
            if not remaining:
                console.print(Text("[Factory] All jobs complete.", style="bold green"))
                break
            # Still have retryable failures — sleep and continue
            console.print(Text(
                f"[Factory] Round {round_number} done. "
                f"{len(remaining)} job(s) remain. Sleeping {cfg.factory_loop_sleep_seconds}s...",
                style="dim white"
            ))
            _interruptible_sleep(cfg.factory_loop_sleep_seconds)

    console.print(Text("\n=== Myth Studio Factory — Shutdown ===", style="bold yellow"))
    _print_job_table(_load_jobs(jobs_path))


def _interruptible_sleep(seconds: float) -> None:
    """Sleep in 1-second increments so Ctrl+C is responsive."""
    elapsed = 0.0
    while elapsed < seconds and not _shutdown_requested:
        time.sleep(min(1.0, seconds - elapsed))
        elapsed += 1.0


if __name__ == "__main__":
    cli()
