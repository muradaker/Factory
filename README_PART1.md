# Myth Studio UE5.5 — Part 1: Foundation Layer

## Prerequisites

- Python 3.11+
- Windows 10/11 (primary target; Linux works for non-UE operations)
- Unreal Engine 5.5 installed (optional for foundation layer)
- A running LLM endpoint (Ollama with qwen2.5-coder:32b recommended)

---

## Installation

### 1. Clone / extract the project

```
cd C:\MythStudio
```

### 2. Create and activate virtual environment

```bat
python -m venv .venv
.venv\Scripts\activate
```

### 3. Install dependencies

```bat
pip install -r requirements.txt
```

### 4. Configure environment

Copy `.env.example` to `.env` and edit values for your machine:

```bat
copy .env.example .env
notepad .env
```

Key values to set:
- `UNREAL_RUN_UAT` — path to your RunUAT.bat
- `UE_EDITOR_CMD` — path to your UnrealEditor-Cmd.exe
- `UE_PROJECT_PATH` — path to your .uproject file
- `MODEL_BASE_URL` — your Ollama or OpenAI-compatible endpoint
- `MODEL_NAME` — model to use (default: qwen2.5-coder:32b)

To test without Unreal Engine installed, set:
```
BUILD_WITH_UNREAL=false
ALLOW_BUILD_SKIP=true
```

---

## First Test Commands

### Verify the CLI loads correctly

```bat
python -m app.main --help
```

### Run a single job (foundation stub — no agents yet)

```bat
python -m app.main run-job InteractionSystem
```

### Run all jobs once (index pass)

```bat
python -m app.main run-index
```

### Start the factory loop

```bat
python -m app.main run-factory
```

### Start the factory loop indefinitely

```bat
python -m app.main run-factory --loop-forever
```

Press `Ctrl+C` for graceful shutdown.

---

## Directory Overview

```
app/
  core/           — All foundation modules (config, logger, state, memory, etc.)
  main.py         — CLI entry point
config/
  pack_registry.json  — All 12 plugin pack definitions
input/
  jobs_index.json     — Job queue (edit status to re-run)
memory/             — Persistent AI memory (per category)
datasets/           — Fine-tuning records
logs/               — Per-pack log files + raw UE output
state/              — Per-pack run state JSON files
workspace/          — Generated plugin source + reports (per pack)
```

---

## Verifying the Foundation

After `run-job InteractionSystem` succeeds you should see:

- `workspace/InteractionSystem/` directory created
- `workspace/InteractionSystem/Reports/` directory created
- `state/InteractionSystem.state.json` written with run_count=1
- Terminal output in cyan/green with no red errors

---

## Next Steps

- **Part 2**: Spec & Architecture agents (LLM-powered generation)
- **Part 3**: Code generation, build, and QA pipeline
- **Part 4**: Review, optimization, approval, and Fab packaging
