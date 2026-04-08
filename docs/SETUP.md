# Myth Studio UE5.5 — Setup Guide

Complete setup guide for the Myth Studio Autonomous Plugin Production Organization system.

---

## 1. Prerequisites

| Requirement | Minimum Version | Notes |
|---|---|---|
| **Python** | 3.11+ | Must be on PATH |
| **pip** | 23+ | Bundled with Python |
| **LLM API** | — | Ollama (local) or any OpenAI-compatible endpoint |
| **Unreal Engine** | 5.5 | Only required if `BUILD_WITH_UNREAL=true` |
| **OS** | Windows 10/11 | Linux supported for headless mode (no UE build) |
| **RAM** | 16 GB+ | 32 GB recommended when running local LLM |
| **Disk** | 10 GB free | For datasets, workspaces, and model weights |

### LLM Options

**Option A — Ollama (local, free):**
```
winget install Ollama.Ollama
ollama pull llama3:8b
# or for better results:
ollama pull llama3:70b
```

**Option B — OpenAI-compatible cloud API:**
Any endpoint that implements `/v1/chat/completions` works (OpenAI, Together, Groq, etc.).

---

## 2. Clone / Download the Project

```bash
git clone https://github.com/your-org/myth-studio-ue55.git
cd myth-studio-ue55
```

Or download and extract the ZIP archive, then `cd` into the extracted folder.

---

## 3. Install Python Dependencies

```bash
pip install -r requirements.txt
```

This installs all required packages including `rich`, `httpx`, `pytest`, and others.

If you are on Windows and see build errors, ensure you have the Visual C++ Build Tools installed, or use pre-built wheels:

```bash
pip install --prefer-binary -r requirements.txt
```

---

## 4. Configure the Environment

Copy the example environment file and fill in your values:

```bash
copy .env.example .env        # Windows
# cp .env.example .env        # Linux / macOS
```

Open `.env` in any text editor and set:

```env
# ── LLM Configuration ──────────────────────────────────────────────────────
MODEL_BASE_URL=http://localhost:11434       # Ollama default
# MODEL_BASE_URL=https://api.openai.com    # OpenAI
MODEL_NAME=llama3:8b                       # Model to use
# API_KEY=sk-...                           # Required for cloud APIs

# ── Unreal Engine (only needed if BUILD_WITH_UNREAL=true) ──────────────────
BUILD_WITH_UNREAL=false
UE_EDITOR_CMD=C:\Program Files\Epic Games\UE_5.5\Engine\Binaries\Win64\UnrealEditor-Cmd.exe
UE_PROJECT_PATH=C:\Projects\MyGame\MyGame.uproject

# ── Output ─────────────────────────────────────────────────────────────────
OUTPUT_DIR=output
LOG_LEVEL=INFO
```

**Key settings explained:**

- `MODEL_BASE_URL` — Base URL of your LLM API (no trailing slash, no `/v1`)
- `MODEL_NAME` — Exact model identifier your API accepts
- `BUILD_WITH_UNREAL` — Set to `true` to enable real UE compilation and packaging
- `UE_EDITOR_CMD` — Full path to `UnrealEditor-Cmd.exe` (required if BUILD_WITH_UNREAL=true)
- `UE_PROJECT_PATH` — Full path to your `.uproject` file

---

## 5. Validate the Installation

Run the system validator to confirm everything is configured correctly:

```bash
python -m app.tools.validate_system
```

You should see output like:

```
Myth Studio UE5.5 — System Validation

  PASS  1. .env file & required keys        3 required keys present
  PASS  2. Job files (12 expected)          12 job files found
  PASS  3. pack_registry.json (12 entries)  12 entries
  PASS  4. prompt_library.json             17 agent keys present
  PASS  5. memory/ subdirectories          6 subdirs present
  PASS  6. datasets/ subdirectories        4 subdirs present
  PASS  7. LLM reachability test           model replied: 'ok'

All 7 checks passed ✓
```

**If any check fails**, fix it before proceeding. Common fixes:

- `FAIL  .env file & required keys` → Edit `.env` and ensure all keys have values
- `FAIL  LLM reachability` → Check that Ollama is running (`ollama serve`) or your API key is valid
- `FAIL  Job files` → Run `python -m app.tools.scaffold` to regenerate missing files
- `FAIL  UE_EDITOR_CMD` → Update the path in `.env` to your actual UE installation

---

## 6. Run Your First Job

Process a single pack through all 17 pipeline stages:

```bash
python -m app.main run-job InteractionSystem
```

The system will:
1. Load the job definition from `input/jobs/InteractionSystem.json`
2. Run all 17 agents in sequence (design → code → review → package → ...)
3. Apply self-heal loops if any stage fails
4. Stop at the approval gate — a human reviewer must approve or reject
5. If approved, produce final output in `output/InteractionSystem/`

Progress is streamed live to the terminal. You can also inspect progress in another terminal:

```bash
python -m app.tools.inspect_pack InteractionSystem
```

---

## 7. Inspect Results

After a job completes (or while it is running):

```bash
python -m app.tools.inspect_pack InteractionSystem
```

This shows:
- Current pipeline stage and status
- Which stages completed successfully
- Which stages failed and why
- Approval gate status
- Last 10 live events

To view the generated files:

```
output/
  InteractionSystem/
    InteractionSystem.zip        ← Final packaged plugin (if approved)
    reports/                     ← All agent reports
    workspace/                   ← Intermediate generated code
```

---

## 8. Factory Mode (Process All Jobs Automatically)

Run the autonomous factory loop to process all 12 jobs one after another, restarting endlessly:

```bash
python -m app.main run-factory --loop-forever
```

The factory:
- Picks the next unprocessed job from `input/jobs/`
- Runs it through the full pipeline
- Waits for human approval at the gate
- Moves to the next job
- Loops back to the beginning when all jobs are done

To run without looping (process each job once and exit):

```bash
python -m app.main run-factory
```

To run only specific jobs:

```bash
python -m app.main run-factory --jobs InteractionSystem QuestSystem
```

---

## 9. Troubleshooting

### LLM returns empty responses

- Check that your model is loaded: `ollama list` or test your API directly
- Increase `max_tokens` in `.env` if responses are being cut off
- Try a larger model: `ollama pull llama3:70b`

### Pipeline stage keeps failing and retrying

- Check `workspace/<pack_name>/LiveEvents.jsonl` for the exact error
- The self-heal loop will retry up to 3 times before marking the stage as failed
- Run `python -m app.tools.inspect_pack <pack_name>` for a summary

### Approval gate always rejects

- Open `workspace/<pack_name>/` and check which report files are missing
- Each required report must exist and contain `"approved": true`
- Re-run failed stages: `python -m app.main run-job <pack_name> --resume`

### UE compilation fails

- Verify `UE_EDITOR_CMD` path is correct and the file exists
- Check that the `.uproject` compiles successfully when opened manually in UE
- Run `make validate` to re-check all paths

### Out of memory errors

- Reduce concurrent workers in `.env`: `MAX_WORKERS=1`
- Use a smaller model: `ollama pull llama3:8b`
- Close other applications before running

### Reset and start over

If a pack is in a broken state, reset it:

```bash
python -m app.tools.reset_pack InteractionSystem --confirm
python -m app.main run-job InteractionSystem
```

Note: memory entries are preserved — the system retains what it learned.

---

## 10. Browse the Memory Store

The system learns from every pack it processes. Browse accumulated knowledge:

```bash
# Show all categories
python -m app.tools.memory_browser

# Show only approved plugins
python -m app.tools.memory_browser --category approved_plugins

# Available categories:
#   approved_plugins
#   rejected_plugins
#   error_patterns
#   ue5_solutions
#   style_rules
#   review_feedback
```

Memory entries are used by agents to improve future generations — the longer the system runs, the better its outputs become.

---

## Quick Reference

| Command | Purpose |
|---|---|
| `make install` | Install Python dependencies |
| `make validate` | Check full system configuration |
| `make test` | Run unit tests |
| `make run-job` | Process InteractionSystem |
| `make run-factory` | Run all 12 jobs in factory mode |
| `make inspect` | Inspect InteractionSystem state |
| `make reset` | Reset InteractionSystem for re-run |
| `python -m app.tools.memory_browser` | Browse learning memory |
