"""
DocsAgent — Layer 3
Generates plugin documentation: README.md, QUICKSTART.md, API_OVERVIEW.md.
"""

import json
import time
import openai
from pathlib import Path

from app.core.config import cfg
from app.core.logger import get_logger
from app.core.progress_tracker import update_progress
from app.flows.job_loader import load_job

logger = get_logger("docs_agent")


def _llm_call_with_retry(messages: list, max_retries: int = 3, max_tokens: int = 3000) -> str:
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
                temperature=0.4,
                max_tokens=max_tokens,
            )
            return response.choices[0].message.content
        except Exception as e:
            wait = 2 ** attempt
            logger.warning(f"LLM retry {attempt+1}/{max_retries}: {e}. Waiting {wait}s...")
            if attempt < max_retries - 1:
                time.sleep(wait)
            else:
                raise


class DocsAgent:
    """
    Layer 3 — Documentation.
    Produces README.md, QUICKSTART.md, API_OVERVIEW.md for the plugin.
    """

    def run(self, pack_name: str) -> dict:
        logger.info(f"[{pack_name}] DocsAgent starting.")

        job = load_job(pack_name)
        product_def = job.get("product_definition", {})
        scope = job.get("implementation_scope", {})
        plugin_title = product_def.get("title", pack_name)
        multiplayer = product_def.get("multiplayer_aware", False)
        ue_version = product_def.get("ue_version", "5.5")

        report_dir = Path(cfg.get("WORKSPACE_DIR", "workspace")) / pack_name / "Reports"
        docs_dir = Path(cfg.get("WORKSPACE_DIR", "workspace")) / pack_name / "docs" / pack_name
        docs_dir.mkdir(parents=True, exist_ok=True)

        # Read architecture for context
        arch_path = report_dir / "GeneratedArchitecture.txt"
        arch_text = arch_path.read_text(encoding="utf-8") if arch_path.exists() else ""

        # Read spec for API info
        spec_path = report_dir / "GeneratedSpec.txt"
        spec_text = spec_path.read_text(encoding="utf-8") if spec_path.exists() else ""

        prompt_lib = _load_prompt_library()
        agent_prompts = prompt_lib.get("docs", {})
        system_prompt = agent_prompts.get(
            "system_prompt",
            (
                "You are a technical writer for Unreal Engine 5.5 plugins. "
                "Write clear, professional documentation targeting indie and AA game developers. "
                "Use Markdown. Be concise but complete."
            ),
        )

        docs_written = []

        # ── README.md ─────────────────────────────────────────────────────
        readme_prompt = (
            f"Plugin: {plugin_title}\n"
            f"UE Version: {ue_version}\n"
            f"Description: {product_def.get('description', '')}\n"
            f"Target Audience: {product_def.get('target_audience', '')}\n"
            f"Core Features: {json.dumps(scope.get('core_features', []), indent=2)}\n"
            f"Multiplayer Aware: {multiplayer}\n"
            f"Architecture Summary:\n{arch_text[:2000]}\n\n"
            "Write a complete README.md for this UE5 plugin. Include:\n"
            "- Header with plugin name and UE version badge\n"
            "- Overview section\n"
            "- Features list\n"
            "- Requirements (UE5.5+, C++17, GAS if needed)\n"
            "- Installation instructions\n"
            "- Basic Usage example with Blueprint node names\n"
            "- Multiplayer Notes section (if multiplayer_aware=true)\n"
            "- License section\n"
        )
        readme_content = _llm_call_with_retry([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": readme_prompt},
        ])
        readme_path = docs_dir / "README.md"
        readme_path.write_text(readme_content, encoding="utf-8")
        docs_written.append(str(readme_path))
        logger.info(f"[{pack_name}] README.md written.")

        # ── QUICKSTART.md ─────────────────────────────────────────────────
        quickstart_prompt = (
            f"Plugin: {plugin_title}\n"
            f"Core Features: {json.dumps(scope.get('core_features', []), indent=2)}\n\n"
            "Write a QUICKSTART.md that helps a developer get this plugin working in under 15 minutes. Include:\n"
            "- Step 1: Enable plugin in .uproject\n"
            "- Step 2: Add required module dependencies in Build.cs\n"
            "- Step 3: First implementation (code snippet)\n"
            "- Step 4: Blueprint setup\n"
            "- Step 5: Test in Play-In-Editor\n"
            "- Common pitfalls / FAQ (3-5 items)\n"
        )
        qs_content = _llm_call_with_retry([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": quickstart_prompt},
        ])
        qs_path = docs_dir / "QUICKSTART.md"
        qs_path.write_text(qs_content, encoding="utf-8")
        docs_written.append(str(qs_path))
        logger.info(f"[{pack_name}] QUICKSTART.md written.")

        # ── API_OVERVIEW.md ───────────────────────────────────────────────
        api_prompt = (
            f"Plugin: {plugin_title}\n"
            f"File Manifest:\n{spec_text[:3000]}\n\n"
            "Write an API_OVERVIEW.md documenting the public API. Include:\n"
            "- Public Classes table (class name | responsibility | Blueprint exposed)\n"
            "- Key Functions section with function signatures and descriptions\n"
            "- Delegates/Events section\n"
            "- Configuration Properties section\n"
            "- Notes on thread safety and performance\n"
        )
        api_content = _llm_call_with_retry([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": api_prompt},
        ])
        api_path = docs_dir / "API_OVERVIEW.md"
        api_path.write_text(api_content, encoding="utf-8")
        docs_written.append(str(api_path))
        logger.info(f"[{pack_name}] API_OVERVIEW.md written.")

        update_progress(pack_name, stage="docs", status="done")

        return {"docs_written": docs_written, "status": "done"}


def _load_prompt_library() -> dict:
    """Load config/prompt_library.json."""
    lib_path = Path("config") / "prompt_library.json"
    if lib_path.exists():
        return json.loads(lib_path.read_text(encoding="utf-8"))
    return {}
