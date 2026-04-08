"""
BlueprintBuilderAgent — Layer 2
Generates Unreal Python automation script for Blueprint creation.
Runs it via ue_runner. Produces BlueprintAutomationReport.json.
"""

import json
import time
import openai
from pathlib import Path

from app.core.config import cfg
from app.core.logger import get_logger
from app.core.progress_tracker import update_progress
from app.core.ue_runner import run_editor_cmd
from app.flows.job_loader import load_job

logger = get_logger("blueprint_builder")


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
                max_tokens=3000,
            )
            return response.choices[0].message.content
        except Exception as e:
            wait = 2 ** attempt
            logger.warning(f"LLM retry {attempt+1}/{max_retries}: {e}. Waiting {wait}s...")
            if attempt < max_retries - 1:
                time.sleep(wait)
            else:
                raise


class BlueprintBuilderAgent:
    """
    Layer 2 — Blueprint Builder.
    Generates and runs Unreal Python script to create Blueprint assets.
    """

    def run(self, pack_name: str) -> dict:
        logger.info(f"[{pack_name}] BlueprintBuilderAgent starting.")

        job = load_job(pack_name)
        product_def = job.get("product_definition", {})
        scope = job.get("implementation_scope", {})
        plugin_title = product_def.get("title", pack_name)

        report_dir = Path(cfg.get("WORKSPACE_DIR", "workspace")) / pack_name / "Reports"
        scripts_dir = Path(cfg.get("WORKSPACE_DIR", "workspace")) / pack_name / "Scripts"
        report_dir.mkdir(parents=True, exist_ok=True)
        scripts_dir.mkdir(parents=True, exist_ok=True)

        report_path = report_dir / "BlueprintAutomationReport.json"

        # Check if Unreal build is enabled
        build_with_unreal = cfg.get("BUILD_WITH_UNREAL", "false").lower() == "true"

        if not build_with_unreal:
            # Skip execution — mark as skipped
            report = {
                "pack_name": pack_name,
                "script_path": str(scripts_dir / f"CreateBlueprints_{pack_name}.py"),
                "executed": False,
                "success": False,
                "stdout_excerpt": "",
                "error": "BUILD_SKIPPED",
                "note": "BUILD_WITH_UNREAL=false in environment. Script generated but not run.",
            }
            # Still generate the script for reference
            script_path = self._generate_bp_script(pack_name, plugin_title, scope, scripts_dir)
            report["script_path"] = str(script_path)
            report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
            logger.info(f"[{pack_name}] Build skipped. Report: {report_path}")
            update_progress(pack_name, stage="blueprint_builder", status="skipped")
            return {"report_path": str(report_path), "status": "done"}

        # Generate Blueprint automation script
        script_path = self._generate_bp_script(pack_name, plugin_title, scope, scripts_dir)

        # Execute via Unreal editor command
        logger.info(f"[{pack_name}] Running Blueprint automation script via UE editor...")
        try:
            result = run_editor_cmd(
                exec_class="PythonScriptPlugin",
                script=str(script_path),
            )
            stdout = result.get("stdout", "")
            success = "SUCCESS" in stdout or result.get("returncode", 1) == 0
            error = "" if success else result.get("stderr", "Execution failed")
        except Exception as ex:
            stdout = ""
            success = False
            error = str(ex)

        report = {
            "pack_name": pack_name,
            "script_path": str(script_path),
            "executed": True,
            "success": success,
            "stdout_excerpt": stdout[:1000],
            "error": error,
        }

        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        logger.info(f"[{pack_name}] BlueprintAutomationReport.json written. Success={success}")

        update_progress(pack_name, stage="blueprint_builder", status="done" if success else "failed")

        return {"report_path": str(report_path), "status": "done" if success else "failed"}

    def _generate_bp_script(self, pack_name: str, plugin_title: str, scope: dict, scripts_dir: Path) -> Path:
        """Generate the Unreal Python script for Blueprint creation."""
        blueprint_assets = scope.get("blueprint_assets", [])

        prompt_lib = _load_prompt_library()
        agent_prompts = prompt_lib.get("blueprint_builder", {})
        system_prompt = agent_prompts.get(
            "system_prompt",
            (
                "You are an Unreal Engine 5.5 Python automation expert. "
                "Write Unreal Python scripts using unreal.EditorAssetLibrary, unreal.AssetToolsHelpers, "
                "and unreal.BlueprintGeneratedClass. Write complete executable scripts with error handling."
            ),
        )
        user_template = agent_prompts.get(
            "user_prompt_template",
            (
                "Plugin: {plugin_name}\n"
                "Blueprint assets to create:\n{assets}\n\n"
                "Write an Unreal Python script that:\n"
                "1. Creates a Blueprint asset for each item in the list under /Game/Plugins/{plugin_name}/Blueprints/\n"
                "2. Sets the parent class to the appropriate C++ class from the plugin\n"
                "3. Saves all created assets\n"
                "4. Prints 'SUCCESS: Blueprint created: <asset_path>' for each success\n"
                "5. Prints 'ERROR: <message>' for any failure\n"
                "Use unreal.EditorAssetLibrary and unreal.AssetToolsHelpers. "
                "Include import statements. No placeholders."
            ),
        )

        user_prompt = user_template.format(
            plugin_name=plugin_title,
            assets=json.dumps(blueprint_assets, indent=2),
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        logger.info(f"[{pack_name}] Generating Blueprint automation script via LLM...")
        raw = _llm_call_with_retry(messages)

        # Strip code fences
        import re
        raw = re.sub(r"^```[\w]*\n", "", raw, flags=re.MULTILINE)
        raw = re.sub(r"\n```$", "", raw, flags=re.MULTILINE)

        script_path = scripts_dir / f"CreateBlueprints_{pack_name}.py"
        script_path.write_text(raw.strip(), encoding="utf-8")
        logger.info(f"[{pack_name}] Blueprint script written: {script_path}")
        return script_path


def _load_prompt_library() -> dict:
    """Load config/prompt_library.json."""
    lib_path = Path("config") / "prompt_library.json"
    if lib_path.exists():
        return json.loads(lib_path.read_text(encoding="utf-8"))
    return {}
