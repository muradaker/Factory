# Myth Studio UE5.5 — Technical Architecture

---

## System Overview

Myth Studio is a fully autonomous pipeline that takes a plain-language plugin specification and produces a packaged, tested, approved Unreal Engine 5.5 plugin — with no human involvement except a single approval gate.

The system is composed of four layers:

```
┌─────────────────────────────────────────────────────┐
│                   INPUT LAYER                       │
│   input/jobs/<PackName>.json  ←  human spec         │
└─────────────────────────┬───────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────┐
│                  PIPELINE LAYER                     │
│   app/flows/pipeline.py — 17 sequential stages      │
│   Self-heal loop: up to 3 retries per stage         │
└─────────────────────────┬───────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────┐
│                   AGENT LAYER                       │
│   17 specialised agents — one per stage             │
│   Each agent: LLM call → parse → validate → write   │
└─────────────────────────┬───────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────┐
│                 FOUNDATION LAYER                    │
│   config, state_store, retrieval_engine,            │
│   approval_policy, dataset_writer, json_loader,     │
│   output_parser, file_utils                         │
└─────────────────────────────────────────────────────┘
```

Key architectural decisions:

- **Stateless agents** — every agent reads its inputs from disk and writes its outputs to disk; no shared mutable state between agents
- **Resumable pipeline** — `StateStore` tracks which stages completed; a resumed run skips completed stages
- **Self-heal loop** — each stage is retried up to 3 times with error context injected back into the LLM prompt
- **Memory-augmented generation** — `RetrievalEngine` injects relevant past solutions into every LLM prompt
- **Strict output parsers** — all LLM output is parsed and validated before use; invalid output triggers a retry

---

## Agent Responsibility Table

| # | Agent | Layer | Input | Output | Memory Reads | Memory Writes |
|---|---|---|---|---|---|---|
| 1 | `SpecAnalystAgent` | Design | job JSON | `spec_analysis.json` | `approved_plugins`, `style_rules` | — |
| 2 | `ArchitectAgent` | Design | spec analysis | `architecture.json` | `approved_plugins`, `ue5_solutions` | — |
| 3 | `FileListAgent` | Design | architecture | `file_list.json` | `approved_plugins` | — |
| 4 | `CodeGenAgent` | Generation | file list + architecture | `generated/` directory | `ue5_solutions`, `error_patterns` | — |
| 5 | `HeaderGenAgent` | Generation | code gen output | `.h` header files | `style_rules` | — |
| 6 | `BlueprintExportAgent` | Generation | architecture | `blueprints/` directory | `approved_plugins` | — |
| 7 | `StaticAnalysisAgent` | Validation | generated code | `static_analysis.json` | `error_patterns` | `error_patterns` |
| 8 | `UECompileAgent` | Validation | generated code + `.uproject` | `compile_report.json` | `ue5_solutions` | `ue5_solutions` |
| 9 | `TestGenAgent` | Validation | architecture + code | `tests/` directory | `approved_plugins` | — |
| 10 | `TestRunAgent` | Validation | tests + compiled plugin | `test_results.json` | `error_patterns` | `error_patterns` |
| 11 | `ReviewAgent` | Review | all reports | `review_report.json` | `review_feedback`, `style_rules` | `review_feedback` |
| 12 | `PatchAgent` | Repair | review report | patch bundle JSON | `ue5_solutions` | — |
| 13 | `ApplyPatchAgent` | Repair | patch bundle | updated source files | — | — |
| 14 | `DocumentationAgent` | Packaging | architecture + code | `docs/` directory | `approved_plugins` | — |
| 15 | `PackageAgent` | Packaging | compiled plugin | `.zip` archive | — | — |
| 16 | `ApprovalGateAgent` | Gate | all 10 required reports | `gate_decision.json` | `review_feedback` | `approved_plugins` or `rejected_plugins` |
| 17 | `DatasetRecorderAgent` | Learning | full pipeline trace | `datasets/` records | — | `training_pairs`, `pipeline_traces` |

---

## Pipeline Stage Order

```
Stage 01 — spec_analysis          SpecAnalystAgent
Stage 02 — architecture           ArchitectAgent
Stage 03 — file_list              FileListAgent
Stage 04 — code_gen               CodeGenAgent
Stage 05 — header_gen             HeaderGenAgent
Stage 06 — blueprint_export       BlueprintExportAgent
Stage 07 — static_analysis        StaticAnalysisAgent
Stage 08 — ue_compile             UECompileAgent            ← requires BUILD_WITH_UNREAL=true
Stage 09 — test_gen               TestGenAgent
Stage 10 — test_run               TestRunAgent
Stage 11 — review                 ReviewAgent
Stage 12 — patch                  PatchAgent                ← only runs if review found issues
Stage 13 — apply_patch            ApplyPatchAgent           ← only runs if patch was generated
Stage 14 — documentation          DocumentationAgent
Stage 15 — package                PackageAgent
Stage 16 — approval_gate          ApprovalGateAgent         ── HUMAN GATE ──
Stage 17 — dataset_record         DatasetRecorderAgent
```

**Gate conditions:**

- Stage 08 (`ue_compile`) is skipped entirely when `BUILD_WITH_UNREAL=false`
- Stage 12 (`patch`) runs only if `review_report.json` contains `"issues_found": true`
- Stage 13 (`apply_patch`) runs only if Stage 12 produced a non-empty patch bundle
- Stage 16 blocks progress until all 10 approval gates pass (see table below)
- Stage 17 always runs, even if Stage 16 rejected the pack (captures learning from failures)

---

## Self-Heal Loop

Every stage is executed inside a retry wrapper:

```
attempt 1 — run stage normally
    ↓ if fails
attempt 2 — inject error message into LLM prompt context ("Previous attempt failed: ...")
    ↓ if fails
attempt 3 — inject full traceback + last output into LLM prompt
    ↓ if fails
mark stage as FAILED — move to next stage
log error to LiveEvents.jsonl
write error pattern to memory/error_patterns/
```

The retry wrapper lives in `app/flows/pipeline.py` and wraps every agent's `run()` method. Retry count is configurable via `MAX_RETRIES` in `.env` (default: 3).

---

## Approval Gate Table

All 10 gates must pass for `ApprovalGateAgent` to approve the pack. A single failure causes immediate rejection with a reason code.

| # | Gate | File Checked | Field Checked | Pass Condition |
|---|---|---|---|---|
| 1 | Spec coverage | `spec_analysis.json` | `coverage_score` | `>= 0.85` |
| 2 | Architecture valid | `architecture.json` | `valid` | `true` |
| 3 | Static analysis | `static_analysis.json` | `errors` | empty list `[]` |
| 4 | Compilation | `compile_report.json` | `success` | `true` |
| 5 | Test pass rate | `test_results.json` | `pass_rate` | `>= 0.90` |
| 6 | Review decision | `review_report.json` | `decision` | `"approved"` |
| 7 | No critical issues | `review_report.json` | `critical_issues` | empty list `[]` |
| 8 | Documentation | `docs/README.md` | file exists and non-empty | — |
| 9 | Package artifact | `<PackName>.zip` | file exists and non-empty | — |
| 10 | Style compliance | `static_analysis.json` | `style_score` | `>= 0.80` |

If `BUILD_WITH_UNREAL=false`, Gate 4 (compilation) is automatically marked as passed.

---

## Memory Category Descriptions

| Category | Purpose | Written By | Read By |
|---|---|---|---|
| `approved_plugins` | Full records of packs that passed all gates | `ApprovalGateAgent` | `SpecAnalystAgent`, `ArchitectAgent`, `FileListAgent`, `BlueprintExportAgent`, `ReviewAgent`, `DocumentationAgent` |
| `rejected_plugins` | Records of rejected packs with rejection reasons | `ApprovalGateAgent` | `ReviewAgent` |
| `error_patterns` | LLM errors, compile errors, test failures with solutions | `StaticAnalysisAgent`, `TestRunAgent` | `CodeGenAgent`, `UECompileAgent` |
| `ue5_solutions` | Specific UE5.5 API usage patterns that worked | `UECompileAgent` | `ArchitectAgent`, `CodeGenAgent` |
| `style_rules` | C++ and Blueprint style guidelines enforced by review | `ReviewAgent` | `SpecAnalystAgent`, `HeaderGenAgent` |
| `review_feedback` | Reviewer decisions and comments per pack | `ReviewAgent` | `ApprovalGateAgent`, `ReviewAgent` |

Memory entries are stored as `.json` files (one per entry) or `.jsonl` files (append-only logs) inside their respective subdirectories. The `RetrievalEngine` performs keyword and embedding-based retrieval to inject the most relevant entries into each LLM prompt.

---

## Dataset Output Format

All dataset records are written to `datasets/` by `DatasetRecorderAgent`. Each record is a dict written as a JSONL line.

### `training_pairs/`

```json
{
  "pack_name": "InteractionSystem",
  "stage": "code_gen",
  "prompt": "<full prompt sent to LLM>",
  "response": "<full LLM response>",
  "outcome": "pass",
  "timestamp": "2025-01-15T10:23:45Z"
}
```

### `review_outcomes/`

```json
{
  "pack_name": "InteractionSystem",
  "review_decision": "approved",
  "issues_found": [],
  "style_score": 0.92,
  "timestamp": "2025-01-15T10:45:00Z"
}
```

### `error_corrections/`

```json
{
  "pack_name": "InteractionSystem",
  "stage": "ue_compile",
  "error": "LNK2019 unresolved external symbol",
  "fix_applied": "Added missing module dependency in .Build.cs",
  "attempt": 2,
  "timestamp": "2025-01-15T10:30:00Z"
}
```

### `pipeline_traces/`

```json
{
  "pack_name": "InteractionSystem",
  "stages_done": ["spec_analysis", "architecture", "..."],
  "stages_failed": [],
  "total_duration_seconds": 847,
  "final_decision": "approved",
  "timestamp": "2025-01-15T11:00:00Z"
}
```

---

## How to Add a New Agent

Follow these steps to add a new agent to the system:

**1. Create the agent file:**

```
app/agents/my_new_agent.py
```

Implement the standard interface:

```python
class MyNewAgent:
    def __init__(self, config, retrieval_engine):
        self.config = config
        self.retrieval = retrieval_engine

    def run(self, pack_name: str, workspace: Path, context: dict) -> dict:
        # 1. Build prompt (inject relevant memory via self.retrieval.retrieve())
        # 2. Call LLM via self.config.llm_client
        # 3. Parse response via app.core.output_parser
        # 4. Validate output
        # 5. Write output file to workspace/
        # 6. Return {"status": "pass", "output_file": "..."}
        ...
```

**2. Register the stage in the pipeline:**

In `app/flows/pipeline.py`, add a new entry to `STAGES`:

```python
STAGES = [
    ...
    Stage(
        name="my_new_stage",
        agent_class=MyNewAgent,
        depends_on=["previous_stage"],
        required_for_gate=False,   # set True if it feeds the approval gate
    ),
]
```

**3. Add a prompt to the prompt library:**

In `config/prompt_library.json`, add a key matching your agent name:

```json
{
  "my_new_agent": {
    "system": "You are a specialist in ...",
    "user_template": "Given {context}, produce {output_format}."
  }
}
```

**4. Write a test:**

In `tests/test_core.py`, add a test that exercises your agent in isolation with a temp directory.

**5. Run validation:**

```bash
make validate
make test
```

Both must pass before the new agent is considered production-ready.
