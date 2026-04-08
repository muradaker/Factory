"""
validate_system.py — Full pre-flight check for Myth Studio UE5.5.

Usage:
    python -m app.tools.validate_system

Exit code 0 if all checks pass, 1 if any fail.
"""

import os
import sys
import json
import logging
from pathlib import Path

# ---------------------------------------------------------------------------
# Optional rich — fall back to plain print if not installed
# ---------------------------------------------------------------------------
try:
    from rich.console import Console
    from rich.table import Table

    console = Console()

    def _print_row(label: str, status: bool, detail: str = "") -> None:
        """Print a coloured PASS / FAIL row."""
        icon = "[bold green]PASS[/]" if status else "[bold red]FAIL[/]"
        msg = f"  {icon}  {label}"
        if detail:
            msg += f"  [dim]{detail}[/dim]"
        console.print(msg)

except ImportError:
    console = None  # type: ignore

    def _print_row(label: str, status: bool, detail: str = "") -> None:  # type: ignore
        """Plain-text fallback when rich is not available."""
        icon = "PASS" if status else "FAIL"
        suffix = f"  {detail}" if detail else ""
        print(f"  [{icon}]  {label}{suffix}")


logging.basicConfig(level=logging.WARNING)

# Project root — two levels above this file (app/tools/validate_system.py)
ROOT = Path(__file__).resolve().parents[2]

# Required .env keys
REQUIRED_ENV_KEYS = [
    "MODEL_BASE_URL",
    "MODEL_NAME",
    "BUILD_WITH_UNREAL",
]

# Optional UE keys (required only when BUILD_WITH_UNREAL=true)
UE_ENV_KEYS = [
    "UE_EDITOR_CMD",
    "UE_PROJECT_PATH",
]

# Expected job files
EXPECTED_JOBS = [
    "InteractionSystem",
    "InventorySystem",
    "QuestSystem",
    "CombatSystem",
    "DialogueSystem",
    "SaveSystem",
    "UISystem",
    "AudioSystem",
    "AnimationSystem",
    "PhysicsSystem",
    "NetworkSystem",
    "AISystem",
]

# Memory sub-directories that must exist
MEMORY_SUBDIRS = [
    "approved_plugins",
    "rejected_plugins",
    "error_patterns",
    "ue5_solutions",
    "style_rules",
    "review_feedback",
]

# Dataset sub-directories that must exist
DATASET_SUBDIRS = [
    "training_pairs",
    "review_outcomes",
    "error_corrections",
    "pipeline_traces",
]


def _load_dotenv() -> dict[str, str]:
    """Load .env file into a dict without requiring python-dotenv."""
    env: dict[str, str] = {}
    env_path = ROOT / ".env"
    if not env_path.exists():
        return env
    with env_path.open() as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def check_env_file(env: dict[str, str]) -> tuple[bool, str]:
    """Check .env exists and contains all required keys."""
    env_path = ROOT / ".env"
    if not env_path.exists():
        return False, ".env file not found"
    missing = [k for k in REQUIRED_ENV_KEYS if not env.get(k)]
    if missing:
        return False, f"missing keys: {', '.join(missing)}"
    return True, f"{len(REQUIRED_ENV_KEYS)} required keys present"


def check_job_files() -> tuple[bool, str]:
    """Verify all 12 job JSON files exist in input/jobs/."""
    jobs_dir = ROOT / "input" / "jobs"
    missing = []
    for job in EXPECTED_JOBS:
        p = jobs_dir / f"{job}.json"
        if not p.exists():
            missing.append(job)
    if missing:
        return False, f"missing jobs: {', '.join(missing)}"
    return True, f"{len(EXPECTED_JOBS)} job files found"


def check_pack_registry() -> tuple[bool, str]:
    """Check config/pack_registry.json exists and has 12 entries."""
    reg_path = ROOT / "config" / "pack_registry.json"
    if not reg_path.exists():
        return False, "pack_registry.json not found"
    try:
        data = json.loads(reg_path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        return False, f"parse error: {exc}"
    count = len(data) if isinstance(data, (dict, list)) else 0
    if count < 12:
        return False, f"expected 12 entries, found {count}"
    return True, f"{count} entries"


def check_prompt_library() -> tuple[bool, str]:
    """Check config/prompt_library.json exists and has all agent keys."""
    lib_path = ROOT / "config" / "prompt_library.json"
    if not lib_path.exists():
        return False, "prompt_library.json not found"
    try:
        data = json.loads(lib_path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        return False, f"parse error: {exc}"
    if not isinstance(data, dict):
        return False, "expected a dict at top level"
    count = len(data)
    if count < 17:
        return False, f"expected ≥17 agent keys, found {count}"
    return True, f"{count} agent keys present"


def check_memory_dirs() -> tuple[bool, str]:
    """Verify all required memory/ subdirectories exist."""
    base = ROOT / "memory"
    missing = [d for d in MEMORY_SUBDIRS if not (base / d).is_dir()]
    if missing:
        return False, f"missing dirs: {', '.join(missing)}"
    return True, f"{len(MEMORY_SUBDIRS)} subdirs present"


def check_dataset_dirs() -> tuple[bool, str]:
    """Verify all required dataset/ subdirectories exist."""
    base = ROOT / "datasets"
    missing = [d for d in DATASET_SUBDIRS if not (base / d).is_dir()]
    if missing:
        return False, f"missing dirs: {', '.join(missing)}"
    return True, f"{len(DATASET_SUBDIRS)} subdirs present"


def check_llm_reachability(env: dict[str, str]) -> tuple[bool, str]:
    """Make a real test call to the configured LLM endpoint."""
    import urllib.request
    import urllib.error

    base_url = env.get("MODEL_BASE_URL", "").rstrip("/")
    model_name = env.get("MODEL_NAME", "")
    if not base_url or not model_name:
        return False, "MODEL_BASE_URL or MODEL_NAME not set"

    endpoint = f"{base_url}/v1/chat/completions"
    payload = json.dumps(
        {
            "model": model_name,
            "messages": [{"role": "user", "content": "reply with: ok"}],
            "max_tokens": 10,
        }
    ).encode()

    req = urllib.request.Request(
        endpoint,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    # Add API key header if available
    api_key = env.get("OPENAI_API_KEY") or env.get("API_KEY")
    if api_key:
        req.add_header("Authorization", f"Bearer {api_key}")

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read())
            content = (
                body.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
                .lower()
            )
            if "ok" in content:
                return True, f"model replied: '{content}'"
            return True, f"reachable; reply: '{content}'"
    except urllib.error.URLError as exc:
        return False, f"connection error: {exc.reason}"
    except (json.JSONDecodeError, KeyError, IndexError) as exc:
        return False, f"unexpected response: {exc}"
    except Exception as exc:  # noqa: BLE001
        return False, f"error: {exc}"


def check_ue_editor_cmd(env: dict[str, str]) -> tuple[bool, str]:
    """Check UE_EDITOR_CMD path exists on disk."""
    cmd = env.get("UE_EDITOR_CMD", "")
    if not cmd:
        return False, "UE_EDITOR_CMD not set"
    p = Path(cmd)
    if not p.exists():
        return False, f"not found: {cmd}"
    return True, f"found: {cmd}"


def check_ue_project_path(env: dict[str, str]) -> tuple[bool, str]:
    """Check UE_PROJECT_PATH file exists on disk."""
    proj = env.get("UE_PROJECT_PATH", "")
    if not proj:
        return False, "UE_PROJECT_PATH not set"
    p = Path(proj)
    if not p.exists():
        return False, f"not found: {proj}"
    return True, f"found: {proj}"


def main() -> int:
    """Run all validation checks; return exit code."""
    env = _load_dotenv()
    # Merge with actual OS environment
    env = {**env, **{k: v for k, v in os.environ.items() if k in REQUIRED_ENV_KEYS + UE_ENV_KEYS}}

    build_with_ue = env.get("BUILD_WITH_UNREAL", "false").lower() == "true"

    if console:
        console.print("\n[bold cyan]Myth Studio UE5.5 — System Validation[/]\n")
    else:
        print("\nMyth Studio UE5.5 — System Validation\n")

    results: list[tuple[str, bool, str]] = []

    def run(label: str, fn, *args) -> bool:
        ok, detail = fn(*args)
        results.append((label, ok, detail))
        _print_row(label, ok, detail)
        return ok

    run("1. .env file & required keys", check_env_file, env)
    run("2. Job files (12 expected)", check_job_files)
    run("3. pack_registry.json (12 entries)", check_pack_registry)
    run("4. prompt_library.json (17 agent keys)", check_prompt_library)
    run("5. memory/ subdirectories", check_memory_dirs)
    run("6. datasets/ subdirectories", check_dataset_dirs)
    run("7. LLM reachability test", check_llm_reachability, env)

    if build_with_ue:
        run("8. UE_EDITOR_CMD path exists", check_ue_editor_cmd, env)
        run("9. UE_PROJECT_PATH exists", check_ue_project_path, env)
    else:
        _print_row("8. UE checks", True, "skipped (BUILD_WITH_UNREAL=false)")
        _print_row("9. UE project path", True, "skipped")

    total = len(results)
    passed = sum(1 for _, ok, _ in results if ok)
    failed = total - passed

    print()
    if failed == 0:
        _print_row(f"All {total} checks passed ✓", True)
        return 0
    else:
        _print_row(f"{passed}/{total} passed — {failed} FAILED", False)
        return 1


if __name__ == "__main__":
    sys.exit(main())
