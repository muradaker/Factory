"""
DemoMapBuilderAgent — Layer 2
Creates a real demo map in Unreal via Python script automation.
Produces DemoMapAutomationReport.json and DemoMapVerifyReport.json.
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

logger = get_logger("demo_map_builder")


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


class DemoMapBuilderAgent:
    """
    Layer 2 — Demo Map Builder.
    Generates, executes, and verifies a demo map via Unreal Python automation.
    """

    def run(self, pack_name: str) -> dict:
        logger.info(f"[{pack_name}] DemoMapBuilderAgent starting.")

        job = load_job(pack_name)
        product_def = job.get("product_definition", {})
        plugin_title = product_def.get("title", pack_name)
        demo_reqs = job.get("implementation_scope", {}).get("demo_map_requirements", {})

        workspace = Path(cfg.get("WORKSPACE_DIR", "workspace"))
        scripts_dir = workspace / pack_name / "Scripts"
        markers_dir = workspace / pack_name / "markers"
        report_dir = workspace / pack_name / "Reports"
        for d in [scripts_dir, markers_dir, report_dir]:
            d.mkdir(parents=True, exist_ok=True)

        build_with_unreal = cfg.get("BUILD_WITH_UNREAL", "false").lower() == "true"
        map_path = f"/Game/PluginDemos/{pack_name}/Maps/Demo_{pack_name}"

        # ── STEP 1: Create map ──────────────────────────────────────────────
        create_script_path = self._generate_create_script(
            pack_name, plugin_title, map_path, markers_dir, scripts_dir, demo_reqs
        )

        auto_report = {
            "map_path": map_path,
            "script_run": False,
            "map_created": False,
            "marker_found": False,
            "error": "",
        }

        if build_with_unreal:
            logger.info(f"[{pack_name}] Running map creation script...")
            try:
                result = run_editor_cmd(
                    exec_class="PythonScriptPlugin",
                    script=str(create_script_path),
                )
                auto_report["script_run"] = True
                stdout = result.get("stdout", "")
                auto_report["map_created"] = "MAP_CREATED" in stdout or result.get("returncode", 1) == 0
                auto_report["error"] = "" if auto_report["map_created"] else result.get("stderr", "Unknown error")
            except Exception as ex:
                auto_report["script_run"] = True
                auto_report["error"] = str(ex)
        else:
            auto_report["error"] = "BUILD_SKIPPED"
            logger.info(f"[{pack_name}] Build skipped. Map creation script generated but not run.")

        # Check for filesystem marker
        map_marker = markers_dir / "map_created.marker"
        auto_report["marker_found"] = map_marker.exists()

        auto_report_path = report_dir / "DemoMapAutomationReport.json"
        auto_report_path.write_text(json.dumps(auto_report, indent=2), encoding="utf-8")

        # ── STEP 2: Verify map ──────────────────────────────────────────────
        verify_script_path = self._generate_verify_script(
            pack_name, map_path, markers_dir, scripts_dir
        )

        verify_report = {
            "map_path": map_path,
            "verified": False,
            "actor_count": 0,
            "has_player_start": False,
            "has_directional_light": False,
            "error": "",
        }

        if build_with_unreal and auto_report["map_created"]:
            logger.info(f"[{pack_name}] Running map verification script...")
            try:
                result = run_editor_cmd(
                    exec_class="PythonScriptPlugin",
                    script=str(verify_script_path),
                )
                stdout = result.get("stdout", "")
                verify_report = _parse_verify_stdout(stdout, map_path, markers_dir)
            except Exception as ex:
                verify_report["error"] = str(ex)
        else:
            verify_report["error"] = "BUILD_SKIPPED or map not created"

        # NEVER fake verification — check marker file
        verify_marker = markers_dir / "map_verified.marker"
        if verify_marker.exists():
            try:
                marker_data = json.loads(verify_marker.read_text(encoding="utf-8"))
                actor_count = marker_data.get("actor_count", 0)
                verify_report["actor_count"] = actor_count
                verify_report["verified"] = actor_count > 0
                verify_report["has_player_start"] = marker_data.get("has_player_start", False)
                verify_report["has_directional_light"] = marker_data.get("has_directional_light", False)
            except Exception as ex:
                verify_report["error"] = f"Marker parse error: {ex}"
        else:
            # Marker missing — not verified
            verify_report["verified"] = False
            if not verify_report["error"]:
                verify_report["error"] = "map_verified.marker not found"

        verify_report_path = report_dir / "DemoMapVerifyReport.json"
        verify_report_path.write_text(json.dumps(verify_report, indent=2), encoding="utf-8")

        logger.info(f"[{pack_name}] DemoMapVerifyReport.json written. verified={verify_report['verified']}")

        status = "done" if auto_report.get("script_run") or not build_with_unreal else "failed"
        update_progress(pack_name, stage="demo_map_builder", status=status)

        return {
            "auto_report": str(auto_report_path),
            "verify_report": str(verify_report_path),
            "status": status,
        }

    def _generate_create_script(
        self, pack_name: str, plugin_title: str, map_path: str,
        markers_dir: Path, scripts_dir: Path, demo_reqs: dict
    ) -> Path:
        """Generate the Unreal Python script that creates the demo map."""
        marker_abs = str((markers_dir / "map_created.marker").resolve()).replace("\\", "/")

        prompt_lib = _load_prompt_library()
        agent_prompts = prompt_lib.get("demo_map_builder", {})
        system_prompt = agent_prompts.get(
            "system_prompt",
            (
                "You are an Unreal Engine 5.5 Python automation expert. "
                "Write Unreal Python using unreal.EditorLevelLibrary, unreal.EditorAssetLibrary. "
                "Always include error handling and print markers for parsing."
            ),
        )
        user_prompt = (
            f"Plugin: {plugin_title}\n"
            f"Map UE path: {map_path}\n"
            f"Demo requirements: {json.dumps(demo_reqs, indent=2)}\n"
            f"Filesystem marker path: {marker_abs}\n\n"
            "Write an Unreal Python script that:\n"
            "1. Creates a new level at the given map UE path using unreal.EditorLevelLibrary.new_level()\n"
            "2. Spawns a PlayerStart actor\n"
            "3. Spawns a DirectionalLight actor\n"
            "4. Spawns a SkyLight actor\n"
            "5. Saves the level with unreal.EditorLevelLibrary.save_current_level()\n"
            "6. Writes a JSON file to the filesystem marker path: {\"created\": true, \"map_path\": \"<path>\"}\n"
            "7. Prints 'MAP_CREATED: <map_path>' on success\n"
            "8. Prints 'MAP_ERROR: <message>' on failure\n"
            "Include all imports. No placeholders."
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        raw = _llm_call_with_retry(messages)
        import re
        raw = re.sub(r"^```[\w]*\n", "", raw, flags=re.MULTILINE)
        raw = re.sub(r"\n```$", "", raw, flags=re.MULTILINE)

        script_path = scripts_dir / f"CreateDemoMap_{pack_name}.py"
        script_path.write_text(raw.strip(), encoding="utf-8")
        logger.info(f"[{pack_name}] Map creation script written: {script_path}")
        return script_path

    def _generate_verify_script(
        self, pack_name: str, map_path: str, markers_dir: Path, scripts_dir: Path
    ) -> Path:
        """Generate the Unreal Python script that verifies the demo map."""
        marker_abs = str((markers_dir / "map_verified.marker").resolve()).replace("\\", "/")

        user_prompt = (
            f"Map UE path: {map_path}\n"
            f"Filesystem marker path: {marker_abs}\n\n"
            "Write an Unreal Python script that:\n"
            "1. Loads the level at the given UE path with unreal.EditorLevelLibrary.load_level()\n"
            "2. Gets all actors in the level with unreal.EditorLevelLibrary.get_all_level_actors()\n"
            "3. Counts total actors\n"
            "4. Checks if PlayerStart is present\n"
            "5. Checks if DirectionalLight is present\n"
            "6. Writes a JSON marker file to the filesystem path:\n"
            "   {\"actor_count\": N, \"has_player_start\": bool, \"has_directional_light\": bool}\n"
            "7. Prints 'MAP_VERIFIED: actor_count=N' on success\n"
            "Include all imports. No placeholders."
        )

        messages = [
            {"role": "system", "content": "You are an Unreal Engine 5.5 Python automation expert."},
            {"role": "user", "content": user_prompt},
        ]

        raw = _llm_call_with_retry(messages)
        import re
        raw = re.sub(r"^```[\w]*\n", "", raw, flags=re.MULTILINE)
        raw = re.sub(r"\n```$", "", raw, flags=re.MULTILINE)

        script_path = scripts_dir / f"VerifyDemoMap_{pack_name}.py"
        script_path.write_text(raw.strip(), encoding="utf-8")
        logger.info(f"[{pack_name}] Verify script written: {script_path}")
        return script_path


def _parse_verify_stdout(stdout: str, map_path: str, markers_dir: Path) -> dict:
    """Parse stdout from verify script for actor count and flags."""
    import re
    report = {
        "map_path": map_path,
        "verified": False,
        "actor_count": 0,
        "has_player_start": False,
        "has_directional_light": False,
        "error": "",
    }
    match = re.search(r"MAP_VERIFIED: actor_count=(\d+)", stdout)
    if match:
        report["actor_count"] = int(match.group(1))
        report["verified"] = report["actor_count"] > 0
    return report


def _load_prompt_library() -> dict:
    """Load config/prompt_library.json."""
    lib_path = Path("config") / "prompt_library.json"
    if lib_path.exists():
        return json.loads(lib_path.read_text(encoding="utf-8"))
    return {}
