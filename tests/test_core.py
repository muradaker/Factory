"""
test_core.py — Real unit tests for Myth Studio core modules.

Run with:
    pytest tests/ -v
"""

import json
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure project root is on sys.path so imports resolve
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


# ───────────────────────────────────────────────────────────── helpers ──────

def _tmp() -> Path:
    """Return a fresh temporary directory as a Path."""
    d = tempfile.mkdtemp()
    return Path(d)


# ─────────────────────────────────────────────── 1. Config loads ────────────

def test_config_loads():
    """Config object must have a non-empty model_name after construction."""
    from app.core.config import Config  # type: ignore

    cfg = Config()
    assert isinstance(cfg.model_name, str)
    assert len(cfg.model_name) > 0, "model_name should not be empty"


# ───────────────────────────────────── 2. Approval policy — missing reports ──

def test_approval_policy_rejects_missing_reports():
    """check_approval on a pack with no report files must return 'rejected'."""
    from app.core.approval_policy import check_approval  # type: ignore

    # Use a pack name that definitely has no workspace files
    decision, reason = check_approval("__nonexistent_pack_xyz__")
    assert decision == "rejected", f"Expected 'rejected', got '{decision}'"


# ──────────────────────── 3. Approval policy — partial gates still rejected ──

def test_approval_policy_needs_all_gates():
    """Providing only 9 of 10 required report files must still be rejected."""
    from app.core.approval_policy import check_approval, REQUIRED_REPORTS  # type: ignore

    tmp = _tmp()
    pack_name = "__partial_test_pack__"

    # Patch workspace root so approval_policy looks in our temp dir
    import app.core.approval_policy as ap_mod  # type: ignore

    original_root = ap_mod.WORKSPACE_ROOT
    ap_mod.WORKSPACE_ROOT = tmp

    pack_dir = tmp / pack_name
    pack_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Write all but the last required report
        reports_to_write = list(REQUIRED_REPORTS)[:-1]  # leave one out
        for report_name in reports_to_write:
            content = json.dumps({"status": "pass", "approved": True})
            (pack_dir / report_name).write_text(content, encoding="utf-8")

        decision, reason = check_approval(pack_name)
        assert decision == "rejected", (
            f"Expected 'rejected' with incomplete reports, got '{decision}'. Reason: {reason}"
        )
    finally:
        ap_mod.WORKSPACE_ROOT = original_root


# ────────────────────────────────────── 4. Output parser — valid JSON block ──

def test_output_parser_json_block():
    """parse_json_block must extract JSON from a fenced code block."""
    from app.core.output_parser import parse_json_block  # type: ignore

    text = '```json\n{"key": "val"}\n```'
    result = parse_json_block(text)
    assert result == {"key": "val"}, f"Unexpected result: {result}"


# ────────────────────────────────────── 5. Output parser — invalid JSON ─────

def test_output_parser_invalid_json():
    """parse_json_block must return None for non-JSON text."""
    from app.core.output_parser import parse_json_block  # type: ignore

    result = parse_json_block("not json at all")
    assert result is None, f"Expected None, got {result}"


# ──────────────────────────────────────── 6. Retrieval engine — top matches ──

def test_retrieval_engine_returns_results():
    """Writing 3 memory entries and querying must return at least 1 result."""
    from app.core.retrieval_engine import RetrievalEngine  # type: ignore

    tmp = _tmp()
    engine = RetrievalEngine(memory_root=tmp)

    # Write three simple entries
    entries = [
        {"id": "e1", "summary": "Inventory system blueprint node", "category": "approved_plugins"},
        {"id": "e2", "summary": "Quest tracker component error fix", "category": "error_patterns"},
        {"id": "e3", "summary": "Combat system animation blend", "category": "approved_plugins"},
    ]
    for entry in entries:
        engine.store(entry, category=entry["category"])

    # Retrieve using a keyword present in the summaries
    results = engine.retrieve("blueprint", top_k=3)
    assert len(results) >= 1, "Expected at least one result for query 'blueprint'"


# ──────────────────────────────────────────── 7. State store — tracking ─────

def test_state_store_tracking():
    """mark_done/is_done and mark_failed/stages_failed must behave correctly."""
    from app.core.state_store import StateStore  # type: ignore

    tmp = _tmp()
    store = StateStore(state_dir=tmp, pack_name="test_pack")

    # Mark a stage done
    store.mark_done("stage_design")
    assert store.is_done("stage_design"), "stage_design should be done"
    assert not store.is_done("stage_review"), "stage_review should not be done"

    # Mark a stage failed
    store.mark_failed("stage_compile", reason="syntax error")
    failed = store.stages_failed()
    assert any(
        s == "stage_compile" or (isinstance(s, dict) and s.get("stage") == "stage_compile")
        for s in failed
    ), f"stage_compile not found in stages_failed: {failed}"


# ─────────────────────────────────────── 8. Dataset writer — file creation ──

def test_dataset_writer_creates_file():
    """write_record must create a file in the datasets/ directory."""
    from app.core.dataset_writer import DatasetWriter  # type: ignore

    tmp = _tmp()
    writer = DatasetWriter(datasets_root=tmp)

    record = {
        "pack_name": "TestPack",
        "stage": "design",
        "prompt": "Design an inventory system",
        "response": "Here is the design...",
    }
    writer.write_record(record, category="training_pairs")

    # At least one file must now exist under datasets_root
    all_files = list(tmp.rglob("*"))
    files_only = [f for f in all_files if f.is_file()]
    assert len(files_only) >= 1, "write_record should create at least one file"
