"""
TechSpecAgent — Layer 2
Translates architecture into exact file + asset plan → GeneratedSpec.txt.
Minimum 20 file entries in format "FILE: path | PURPOSE: ..."
"""

import json
import time
import openai
from pathlib import Path

from app.core.config import cfg
from app.core.logger import get_logger
from app.core.progress_tracker import update_progress
from app.flows.job_loader import load_job

logger = get_logger("tech_spec")


def _llm_call_with_retry(messages: list, max_retries: int = 3) -> str:
    """LLM call with exponential backoff."""
    client = openai.OpenAI(
        api_key=cfg.get("OPENAI_API_KEY", "sk-placeholder"),
        base_url=cfg.get("MODEL_BASE_URL", "https://api.openai.com/v1"),
    )
    model = cfg.get("MODEL_NAME", "gpt-4o")

    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.2,
                max_tokens=4096,
            )
            return response.choices[0].message.content
        except Exception as e:
            wait = 2 ** attempt
            logger.warning(f"LLM retry {attempt+1}/{max_retries}: {e}. Waiting {wait}s...")
            if attempt < max_retries - 1:
                time.sleep(wait)
            else:
                raise


class TechSpecAgent:
    """
    Layer 2 — Tech Spec.
    Converts architecture doc into a line-by-line file manifest.
    """

    def run(self, pack_name: str) -> dict:
        logger.info(f"[{pack_name}] TechSpecAgent starting.")

        job = load_job(pack_name)
        report_dir = Path(cfg.get("WORKSPACE_DIR", "workspace")) / pack_name / "Reports"
        report_dir.mkdir(parents=True, exist_ok=True)

        # Read architecture from previous stage
        arch_path = report_dir / "GeneratedArchitecture.txt"
        arch_text = arch_path.read_text(encoding="utf-8") if arch_path.exists() else "No architecture available."

        product_def = job.get("product_definition", {})
        scope = job.get("implementation_scope", {})
        plugin_title = product_def.get("title", pack_name)

        prompt_lib = _load_prompt_library()
        agent_prompts = prompt_lib.get("tech_spec", {})
        system_prompt = agent_prompts.get(
            "system_prompt",
            (
                "You are a UE5.5 plugin technical lead. "
                "Given an architecture document, produce an exact file manifest. "
                "Every .h, .cpp, .uplugin, .uasset, and .Build.cs file must be listed. "
                "Format each entry as: FILE: <relative_path> | PURPOSE: <one-line description>"
            ),
        )
        user_template = agent_prompts.get(
            "user_prompt_template",
            (
                "Plugin Name: {plugin_name}\n"
                "C++ Modules: {modules}\n"
                "Blueprint Assets: {blueprints}\n\n"
                "Architecture Document:\n{arch_text}\n\n"
                "List ALL files that must be created for this plugin. "
                "Include every .h, .cpp, .uplugin, .Build.cs, .uasset, and any config files. "
                "Minimum 20 files. Use exactly this format per line:\n"
                "FILE: Source/{plugin_name}/Public/MyClass.h | PURPOSE: Public header for MyClass\n"
                "FILE: Source/{plugin_name}/Private/MyClass.cpp | PURPOSE: Implementation of MyClass\n"
                "Do not include any other text — only FILE: lines."
            ),
        )

        user_prompt = user_template.format(
            plugin_name=plugin_title,
            modules=json.dumps(scope.get("c_plus_plus_modules", []), indent=2),
            blueprints=json.dumps(scope.get("blueprint_assets", []), indent=2),
            arch_text=arch_text[:4000],
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        logger.info(f"[{pack_name}] Calling LLM for file manifest...")
        raw = _llm_call_with_retry(messages)

        # Extract FILE: lines from response
        file_lines = _extract_file_lines(raw)

        # If fewer than 20 entries, request more
        if len(file_lines) < 20:
            logger.warning(f"[{pack_name}] Only {len(file_lines)} file entries. Requesting expansion...")
            expand_messages = messages + [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": f"Only {len(file_lines)} files listed. Add more — we need at least 20. Continue listing FILE: entries for helper utilities, subsystems, data assets, and editor tools."},
            ]
            additional_raw = _llm_call_with_retry(expand_messages)
            file_lines += _extract_file_lines(additional_raw)

        # Build spec content
        spec_content = "\n".join(file_lines)

        spec_path = report_dir / "GeneratedSpec.txt"
        spec_path.write_text(spec_content, encoding="utf-8")
        logger.info(f"[{pack_name}] GeneratedSpec.txt written with {len(file_lines)} entries.")

        update_progress(pack_name, stage="tech_spec", status="done")

        return {"spec_path": str(spec_path), "status": "done"}


def _extract_file_lines(text: str) -> list:
    """Extract all 'FILE: ... | PURPOSE: ...' lines from raw LLM output."""
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("FILE:") and "| PURPOSE:" in stripped:
            lines.append(stripped)
    return lines


def _load_prompt_library() -> dict:
    """Load config/prompt_library.json."""
    lib_path = Path("config") / "prompt_library.json"
    if lib_path.exists():
        return json.loads(lib_path.read_text(encoding="utf-8"))
    return {}
