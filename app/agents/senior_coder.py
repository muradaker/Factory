"""
SeniorCoderAgent — Layer 2
Generates real C++ plugin source files from GeneratedSpec.txt.
Writes to workspace/{pack_name}/PluginSource/
Also generates .uplugin and .Build.cs.
"""

import json
import time
import re
import openai
from pathlib import Path

from app.core.config import cfg
from app.core.logger import get_logger
from app.core.memory_store import write_memory
from app.core.retrieval_engine import retrieve
from app.core.progress_tracker import update_progress
from app.flows.job_loader import load_job

logger = get_logger("senior_coder")


def _llm_call_with_retry(messages: list, max_retries: int = 3, max_tokens: int = 4096) -> str:
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


class SeniorCoderAgent:
    """
    Layer 2 — Senior Coder.
    Generates C++ source for every .h and .cpp in GeneratedSpec.txt.
    """

    def run(self, pack_name: str) -> dict:
        logger.info(f"[{pack_name}] SeniorCoderAgent starting.")

        job = load_job(pack_name)
        product_def = job.get("product_definition", {})
        plugin_title = product_def.get("title", pack_name)
        multiplayer = product_def.get("multiplayer_aware", False)
        ue_version = product_def.get("ue_version", "5.5")

        report_dir = Path(cfg.get("WORKSPACE_DIR", "workspace")) / pack_name / "Reports"
        source_dir = Path(cfg.get("WORKSPACE_DIR", "workspace")) / pack_name / "PluginSource"
        source_dir.mkdir(parents=True, exist_ok=True)

        # Read file manifest from TechSpecAgent
        spec_path = report_dir / "GeneratedSpec.txt"
        spec_content = spec_path.read_text(encoding="utf-8") if spec_path.exists() else ""

        # Read architecture for context
        arch_path = report_dir / "GeneratedArchitecture.txt"
        arch_text = arch_path.read_text(encoding="utf-8") if arch_path.exists() else ""

        # Parse file entries from spec
        file_entries = _parse_spec_entries(spec_content)
        cpp_files = [(path, purpose) for path, purpose in file_entries if path.endswith((".h", ".cpp"))]

        # Retrieve code patterns from memory
        retrieved = retrieve(category="code_patterns", query=pack_name, top_k=3)
        code_context = "\n".join(
            r.get("value", {}).get("summary", "") if isinstance(r.get("value"), dict) else ""
            for r in retrieved
            if isinstance(r, dict)
        )

        prompt_lib = _load_prompt_library()
        agent_prompts = prompt_lib.get("senior_coder", {})
        system_prompt = agent_prompts.get(
            "system_prompt",
            (
                "You are a senior Unreal Engine 5.5 C++ plugin developer. "
                "Write complete, compilable C++ code. "
                "Use UE5.5 macros (UCLASS, UPROPERTY, UFUNCTION, GENERATED_BODY). "
                "Include copyright header. Use proper module API macros. "
                "Never write placeholder comments like '// TODO implement'. Write real code."
            ),
        )

        files_written = []

        # Generate each .h and .cpp file
        for rel_path, purpose in cpp_files:
            logger.info(f"[{pack_name}] Generating: {rel_path}")
            out_path = source_dir / rel_path
            out_path.parent.mkdir(parents=True, exist_ok=True)

            user_prompt = (
                f"Plugin: {plugin_title} (UE {ue_version})\n"
                f"Multiplayer: {multiplayer}\n"
                f"File to generate: {rel_path}\n"
                f"Purpose: {purpose}\n\n"
                f"Architecture context:\n{arch_text[:2000]}\n\n"
                f"Prior code patterns:\n{code_context[:500]}\n\n"
                f"Write the complete file contents. Include all includes, class declarations, "
                f"method implementations, and UE5 macros. No placeholders."
            )

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]

            code = _llm_call_with_retry(messages)
            # Strip markdown code fences if present
            code = _strip_code_fences(code)

            out_path.write_text(code, encoding="utf-8")
            files_written.append(str(out_path))
            logger.info(f"[{pack_name}] Written: {out_path}")

        # Generate .uplugin file
        uplugin_path = _generate_uplugin(source_dir, pack_name, plugin_title, ue_version, job)
        files_written.append(str(uplugin_path))

        # Generate Build.cs
        build_cs_path = _generate_build_cs(source_dir, pack_name, plugin_title, multiplayer)
        files_written.append(str(build_cs_path))

        # Store code patterns in memory
        write_memory(
            category="code_patterns",
            key=f"{pack_name}_code_patterns",
            value={
                "pack_name": pack_name,
                "summary": f"Generated {len(files_written)} files for {plugin_title}. Multiplayer={multiplayer}.",
                "files_count": len(files_written),
                "ue_version": ue_version,
            },
        )

        update_progress(pack_name, stage="senior_coder", status="done")

        return {"files_written": files_written, "status": "done"}


def _parse_spec_entries(spec_content: str) -> list:
    """Parse 'FILE: path | PURPOSE: desc' lines into (path, purpose) tuples."""
    entries = []
    for line in spec_content.splitlines():
        line = line.strip()
        if line.startswith("FILE:") and "| PURPOSE:" in line:
            parts = line.split("| PURPOSE:", 1)
            path = parts[0].replace("FILE:", "").strip()
            purpose = parts[1].strip() if len(parts) > 1 else ""
            entries.append((path, purpose))
    return entries


def _strip_code_fences(text: str) -> str:
    """Remove markdown code block fences from LLM output."""
    text = re.sub(r"^```[\w]*\n", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n```$", "", text, flags=re.MULTILINE)
    return text.strip()


def _generate_uplugin(source_dir: Path, pack_name: str, plugin_title: str, ue_version: str, job: dict) -> Path:
    """Generate a valid .uplugin JSON file."""
    scope = job.get("implementation_scope", {})
    modules = scope.get("c_plus_plus_modules", [pack_name])

    uplugin = {
        "FileVersion": 3,
        "Version": 1,
        "VersionName": "1.0",
        "FriendlyName": plugin_title,
        "Description": job.get("product_definition", {}).get("description", ""),
        "Category": "Game Systems",
        "CreatedBy": "Myth Studio",
        "CreatedByURL": "",
        "DocsURL": "",
        "MarketplaceURL": "",
        "SupportURL": "",
        "CanContainContent": True,
        "IsBetaVersion": False,
        "IsExperimentalVersion": False,
        "Installed": False,
        "Modules": [
            {
                "Name": mod,
                "Type": "Runtime",
                "LoadingPhase": "Default",
            }
            for mod in modules
        ],
    }

    uplugin_path = source_dir / f"{pack_name}.uplugin"
    uplugin_path.parent.mkdir(parents=True, exist_ok=True)
    uplugin_path.write_text(json.dumps(uplugin, indent="\t"), encoding="utf-8")
    logger.info(f"Generated .uplugin: {uplugin_path}")
    return uplugin_path


def _generate_build_cs(source_dir: Path, pack_name: str, plugin_title: str, multiplayer: bool) -> Path:
    """Generate a Source/{PackName}/{PackName}.Build.cs file."""
    multiplayer_deps = ""
    if multiplayer:
        multiplayer_deps = """
            "OnlineSubsystem",
            "OnlineSubsystemUtils",
            "NetCore","""

    build_cs = f"""// Copyright Myth Studio. All Rights Reserved.

using UnrealBuildTool;

public class {pack_name} : ModuleRules
{{
    public {pack_name}(ReadOnlyTargetRules Target) : base(Target)
    {{
        PCHUsage = ModuleRules.PCHUsageMode.UseExplicitOrSharedPCHs;

        PublicDependencyModuleNames.AddRange(new string[]
        {{
            "Core",
            "CoreUObject",
            "Engine",
            "InputCore",
            "GameplayAbilities",
            "GameplayTags",
            "GameplayTasks",{multiplayer_deps}
        }});

        PrivateDependencyModuleNames.AddRange(new string[]
        {{
            "Slate",
            "SlateCore",
            "UMG",
            "EnhancedInput",
        }});

        PublicIncludePaths.AddRange(new string[]
        {{
            "Runtime/Launch/Resources",
        }});
    }}
}}
"""
    build_path = source_dir / "Source" / pack_name / f"{pack_name}.Build.cs"
    build_path.parent.mkdir(parents=True, exist_ok=True)
    build_path.write_text(build_cs, encoding="utf-8")
    logger.info(f"Generated Build.cs: {build_path}")
    return build_path


def _load_prompt_library() -> dict:
    """Load config/prompt_library.json."""
    lib_path = Path("config") / "prompt_library.json"
    if lib_path.exists():
        return json.loads(lib_path.read_text(encoding="utf-8"))
    return {}
