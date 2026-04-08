"""
FunctionDocsAgent — Layer 3
Reads generated .h files and inserts doxygen-style comment blocks above each function.
"""

import json
import time
import re
import openai
from pathlib import Path

from app.core.config import cfg
from app.core.logger import get_logger
from app.core.progress_tracker import update_progress

logger = get_logger("function_docs")


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
                max_tokens=2000,
            )
            return response.choices[0].message.content
        except Exception as e:
            wait = 2 ** attempt
            logger.warning(f"LLM retry {attempt+1}/{max_retries}: {e}. Waiting {wait}s...")
            if attempt < max_retries - 1:
                time.sleep(wait)
            else:
                raise


class FunctionDocsAgent:
    """
    Layer 3 — Function Docs.
    Parses .h files and inserts doxygen comments above each UFUNCTION/function declaration.
    """

    def run(self, pack_name: str) -> dict:
        logger.info(f"[{pack_name}] FunctionDocsAgent starting.")

        source_dir = Path(cfg.get("WORKSPACE_DIR", "workspace")) / pack_name / "PluginSource"
        if not source_dir.exists():
            logger.warning(f"[{pack_name}] PluginSource dir not found. Skipping function docs.")
            update_progress(pack_name, stage="function_docs", status="skipped")
            return {"files_updated": [], "status": "done"}

        # Find all .h files
        h_files = list(source_dir.rglob("*.h"))
        if not h_files:
            logger.warning(f"[{pack_name}] No .h files found in {source_dir}.")
            update_progress(pack_name, stage="function_docs", status="skipped")
            return {"files_updated": [], "status": "done"}

        files_updated = []

        for h_file in h_files:
            logger.info(f"[{pack_name}] Processing: {h_file.name}")
            original_content = h_file.read_text(encoding="utf-8")

            # Find UFUNCTION declarations and bare function declarations
            functions = _find_function_declarations(original_content)

            if not functions:
                logger.info(f"[{pack_name}] No functions found in {h_file.name}. Skipping.")
                continue

            # Ask LLM to produce doxygen blocks for all functions in this file
            user_prompt = (
                f"Header file: {h_file.name}\n"
                f"Content:\n```cpp\n{original_content[:4000]}\n```\n\n"
                "For each public function/UFUNCTION in this header, write a doxygen-style comment block. "
                "Format:\n"
                "/**\n"
                " * @brief One-line description.\n"
                " * @param ParamName Description.\n"
                " * @return Description.\n"
                " */\n"
                "Return ONLY a JSON array where each item is:\n"
                "{\"function_signature\": \"...\", \"doxygen_block\": \"/**\\n * @brief ...\\n */\"}\n"
                "Include every public function. No other text."
            )

            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are a C++ documentation expert specializing in Unreal Engine 5. "
                        "Write concise, accurate doxygen comments. Return only valid JSON."
                    ),
                },
                {"role": "user", "content": user_prompt},
            ]

            try:
                raw = _llm_call_with_retry(messages)
                doc_entries = _parse_doc_entries(raw)
                updated_content = _insert_doxygen_comments(original_content, doc_entries)
                h_file.write_text(updated_content, encoding="utf-8")
                files_updated.append(str(h_file))
                logger.info(f"[{pack_name}] Updated {h_file.name} with {len(doc_entries)} doxygen blocks.")
            except Exception as ex:
                logger.warning(f"[{pack_name}] Failed to document {h_file.name}: {ex}")

        update_progress(pack_name, stage="function_docs", status="done")

        return {"files_updated": files_updated, "status": "done"}


def _find_function_declarations(content: str) -> list:
    """Extract function declaration lines from a .h file."""
    # Match UFUNCTION macros and bare function declarations
    pattern = re.compile(
        r'(UFUNCTION\s*\([^)]*\)\s*\n\s*)?'
        r'(?:virtual\s+)?(?:static\s+)?(?:FORCEINLINE\s+)?'
        r'\w[\w\s\*&<>:,]*\s+\w+\s*\([^)]*\)\s*(?:const\s*)?(?:override\s*)?;',
        re.MULTILINE,
    )
    return pattern.findall(content)


def _parse_doc_entries(raw: str) -> list:
    """Extract JSON array of doxygen entries from LLM response."""
    # Strip markdown fences
    raw = re.sub(r"^```[\w]*\n", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"\n```$", "", raw, flags=re.MULTILINE)

    try:
        # Try to parse as JSON
        json_match = re.search(r"\[.*\]", raw, re.DOTALL)
        if json_match:
            return json.loads(json_match.group(0))
    except Exception:
        pass
    return []


def _insert_doxygen_comments(content: str, doc_entries: list) -> str:
    """Insert doxygen comment blocks above matching function signatures."""
    for entry in doc_entries:
        if not isinstance(entry, dict):
            continue
        sig = entry.get("function_signature", "").strip()
        doxygen = entry.get("doxygen_block", "").strip()

        if not sig or not doxygen:
            continue

        # Match function signature in content (simplified: match by function name)
        func_name_match = re.search(r'(\w+)\s*\(', sig)
        if not func_name_match:
            continue

        func_name = func_name_match.group(1)

        # Find the function in content and insert doxygen above it
        # Look for the function name not already preceded by doxygen
        pattern = re.compile(
            r'(?<!\*/\n)(\s*(?:UFUNCTION[^\n]*\n\s*)?(?:virtual\s+|static\s+|FORCEINLINE\s+)?'
            r'[^\n]*\b' + re.escape(func_name) + r'\s*\([^)]*\)[^{;]*;)',
            re.MULTILINE,
        )
        match = pattern.search(content)
        if match:
            original_decl = match.group(0)
            # Preserve leading whitespace
            leading_ws = re.match(r'^\s*', original_decl).group(0)
            commented_decl = f"\n{leading_ws}{doxygen}\n{original_decl}"
            content = content.replace(original_decl, commented_decl, 1)

    return content
