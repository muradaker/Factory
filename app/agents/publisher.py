"""
publisher.py — PublisherAgent
Generates Fab marketplace listing materials from the plugin spec and review.
Writes all output files to workspace/{pack_name}/Publishing/.
"""

import json
import re
from pathlib import Path

from app.core import config, logger as log, llm_client


class PublisherAgent:
    def __init__(self):
        self.name = "PublisherAgent"

    # ------------------------------------------------------------------ #
    # Main entry point
    # ------------------------------------------------------------------ #
    def run(self, pack_name: str) -> dict:
        workspace = Path(config.WORKSPACE_ROOT) / pack_name
        publishing_dir = workspace / "Publishing"
        publishing_dir.mkdir(parents=True, exist_ok=True)
        reports_dir = workspace / "Reports"

        log.info(f"[{self.name}] Generating publishing materials for '{pack_name}'")

        # ---- 1. Gather source material ----
        product_spec = self._read_json(workspace / "ProductSpec.json")
        market_notes = self._read_text(workspace / "MarketNotes.md")
        review_report = self._read_json(reports_dir / "ReviewReport.json")

        # ---- 2. LLM call — generate all marketplace content in one shot ----
        marketplace_data = self._generate_marketplace_content(
            pack_name, product_spec, market_notes, review_report
        )

        files_written = []

        # ---- 3. Write FabDescription.md ----
        desc_path = publishing_dir / "FabDescription.md"
        description = marketplace_data.get("description", self._fallback_description(pack_name))
        desc_path.write_text(description, encoding="utf-8")
        files_written.append(str(desc_path))

        # ---- 4. Write FeatureBullets.json ----
        bullets_path = publishing_dir / "FeatureBullets.json"
        bullets = marketplace_data.get("feature_bullets", self._fallback_bullets(pack_name))
        # Ensure we have 5-8 bullets
        if not isinstance(bullets, list):
            bullets = self._fallback_bullets(pack_name)
        bullets = bullets[:8]
        bullets_path.write_text(json.dumps(bullets, indent=2), encoding="utf-8")
        files_written.append(str(bullets_path))

        # ---- 5. Write Tags.json ----
        tags_path = publishing_dir / "Tags.json"
        tags_data = marketplace_data.get("tags", self._fallback_tags(pack_name))
        tags_path.write_text(json.dumps(tags_data, indent=2), encoding="utf-8")
        files_written.append(str(tags_path))

        # ---- 6. Write ScreenshotPlan.md ----
        screenshot_path = publishing_dir / "ScreenshotPlan.md"
        screenshot_plan = marketplace_data.get("screenshot_plan", self._fallback_screenshot_plan(pack_name))
        screenshot_path.write_text(screenshot_plan, encoding="utf-8")
        files_written.append(str(screenshot_path))

        # ---- 7. Write ReleaseManifest.json ----
        manifest_path = publishing_dir / "ReleaseManifest.json"
        plugin_files = self._list_plugin_files(workspace / "PluginSource")
        manifest = {
            "pack_name": pack_name,
            "version": product_spec.get("version", "1.0.0"),
            "files_to_include": plugin_files,
            "ready_for_upload": False,   # Human must verify before upload
        }
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        files_written.append(str(manifest_path))

        log.info(f"[{self.name}] Wrote {len(files_written)} publishing files")
        return {"files_written": files_written, "status": "done"}

    # ------------------------------------------------------------------ #
    # LLM call to generate structured marketplace content
    # ------------------------------------------------------------------ #
    def _generate_marketplace_content(self, pack_name, product_spec, market_notes, review_report) -> dict:
        spec_text = json.dumps(product_spec, indent=2)[:2000]
        review_text = json.dumps(review_report, indent=2)[:1500]

        prompt = (
            f"Generate Fab Unreal Engine marketplace listing content for a plugin called '{pack_name}'.\n\n"
            f"=== Product Spec ===\n{spec_text}\n\n"
            f"=== Market Notes ===\n{market_notes[:1000]}\n\n"
            f"=== Review Report ===\n{review_text}\n\n"
            "Return ONLY valid JSON (no markdown fences) with these keys:\n"
            '{"description": "<300+ word markdown description>", '
            '"feature_bullets": ["<bullet 1>", ..., "<bullet 8>"], '
            '"tags": {"category": "...", "tags": ["..."], "ue_version": "5.5", "price_usd": 0.0}, '
            '"screenshot_plan": "<markdown list of recommended screenshot scenes>"}'
        )

        try:
            raw = llm_client.complete(prompt, max_tokens=2048)
            clean = re.sub(r"```[a-z]*", "", raw).strip().strip("`").strip()
            return json.loads(clean)
        except Exception as exc:
            log.warning(f"[{self.name}] LLM content generation failed: {exc}")
            return {}

    # ------------------------------------------------------------------ #
    # List plugin source files (relative paths, for the manifest)
    # ------------------------------------------------------------------ #
    def _list_plugin_files(self, plugin_source: Path) -> list:
        files = []
        if plugin_source.exists():
            for f in sorted(plugin_source.rglob("*")):
                if f.is_file():
                    files.append(str(f.relative_to(plugin_source.parent)))
        return files

    # ------------------------------------------------------------------ #
    # Helpers — read files safely
    # ------------------------------------------------------------------ #
    def _read_json(self, path: Path) -> dict:
        try:
            return json.loads(path.read_text()) if path.exists() else {}
        except Exception:
            return {}

    def _read_text(self, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8") if path.exists() else ""
        except Exception:
            return ""

    # ------------------------------------------------------------------ #
    # Fallback content (used when LLM call fails)
    # ------------------------------------------------------------------ #
    def _fallback_description(self, pack_name: str) -> str:
        return (
            f"# {pack_name}\n\n"
            f"A high-quality Unreal Engine 5.5 plugin providing production-ready functionality "
            f"for your game projects. This plugin was built with clean architecture, full "
            f"Blueprint support, and detailed documentation. It integrates seamlessly into "
            f"existing projects without modifying engine source code.\n\n"
            f"## Features\n"
            f"- Full Blueprint exposure for rapid prototyping\n"
            f"- Optimized for UE 5.5 Lumen and Nanite pipelines\n"
            f"- Comprehensive API documentation included\n"
            f"- Example demo map with pre-configured actors\n"
            f"- Multiplayer-ready architecture\n\n"
            f"## Support\n"
            f"Documentation and support available via the product page."
        )

    def _fallback_bullets(self, pack_name: str) -> list:
        return [
            f"Production-ready {pack_name} plugin for UE 5.5",
            "Full Blueprint API exposure — no C++ required",
            "Includes demo map with example setup",
            "Multiplayer-compatible architecture",
            "Detailed API_OVERVIEW.md and README included",
        ]

    def _fallback_tags(self, pack_name: str) -> dict:
        return {
            "category": "Code Plugins",
            "tags": [pack_name, "UE5", "Plugin", "Blueprint", "Gameplay"],
            "ue_version": "5.5",
            "price_usd": 0.0,
        }

    def _fallback_screenshot_plan(self, pack_name: str) -> str:
        return (
            f"# Screenshot Plan — {pack_name}\n\n"
            "1. **Hero shot** — Demo map overview showing the plugin in action\n"
            "2. **Blueprint nodes** — Key Blueprint functions exposed by the plugin\n"
            "3. **Editor integration** — Plugin panel/settings visible in UE Editor\n"
            "4. **Gameplay demonstration** — In-game result (PIE or packaged build)\n"
            "5. **Documentation screenshot** — API_OVERVIEW.md rendered in browser\n"
        )
