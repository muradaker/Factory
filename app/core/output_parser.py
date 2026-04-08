"""
<<<<<<< HEAD
output_parser.py — Parse raw LLM text output into structured dicts.
Handles: JSON blocks, code fences, key:value patterns, fallback plain text.
"""

import json
import re
from typing import Any, Optional


def parse_json_block(text: str) -> Optional[dict | list]:
    """
    Extract and parse the first JSON object or array from text.
    Looks inside ```json ... ``` fences first, then bare braces/brackets.
    Returns None if nothing parseable found.
    """
    # Try fenced JSON block first
    fence_pattern = re.compile(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", re.DOTALL)
    m = fence_pattern.search(text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # Try first { ... } block
    brace_pattern = re.compile(r"(\{.*\})", re.DOTALL)
    m = brace_pattern.search(text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # Try first [ ... ] block
    bracket_pattern = re.compile(r"(\[.*\])", re.DOTALL)
    m = bracket_pattern.search(text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    return None


def parse_code_block(text: str, language: str = "") -> Optional[str]:
    """
    Extract the first code block matching language (or any fenced block).
    Returns the raw content string, or None.
    """
    pattern = re.compile(
        rf"```{re.escape(language)}\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE
    )
    m = pattern.search(text)
    if m:
        return m.group(1).strip()
    # Fallback: any fence
    fallback = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)
    m = fallback.search(text)
    if m:
        return m.group(1).strip()
    return None


def parse_key_value(text: str) -> dict[str, str]:
    """
    Parse simple key: value pairs from text (one per line).
    Strips surrounding whitespace from both key and value.
    """
    result: dict[str, str] = {}
    for line in text.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            if key:
                result[key] = value
    return result


def parse_section(text: str, heading: str) -> Optional[str]:
    """
    Extract the text content under a specific markdown heading.
    Returns everything between that heading and the next ## heading.
    """
    pattern = re.compile(
        rf"#+\s*{re.escape(heading)}\s*\n(.*?)(?=\n#+\s|\Z)", re.DOTALL | re.IGNORECASE
    )
    m = pattern.search(text)
    if m:
        return m.group(1).strip()
    return None


def parse_llm_response(text: str) -> dict[str, Any]:
    """
    Master parser. Returns a structured dict with best-effort extraction:
    {
        "raw": full text,
        "json": parsed JSON block (or None),
        "code_blocks": list of extracted code strings,
        "kv": key-value pairs parsed from text,
        "summary": first non-empty paragraph,
    }
    """
    result: dict[str, Any] = {
        "raw": text,
        "json": None,
        "code_blocks": [],
        "kv": {},
        "summary": "",
    }

    # JSON block
    result["json"] = parse_json_block(text)

    # All code blocks
    code_blocks = re.findall(r"```[^\n]*\n(.*?)```", text, re.DOTALL)
    result["code_blocks"] = [b.strip() for b in code_blocks if b.strip()]

    # Key-value pairs (only outside code fences)
    clean_text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    result["kv"] = parse_key_value(clean_text)

    # First paragraph as summary
    paragraphs = [p.strip() for p in clean_text.split("\n\n") if p.strip()]
    if paragraphs:
        result["summary"] = paragraphs[0]

    return result


def extract_bool_answer(text: str) -> Optional[bool]:
    """
    Parse a yes/no or true/false answer from LLM output.
    Returns True, False, or None if unclear.
    """
    lower = text.strip().lower()
    if lower.startswith(("yes", "true", "approved", "pass")):
        return True
    if lower.startswith(("no", "false", "rejected", "fail")):
        return False
    # Search inside text
    if re.search(r"\b(yes|true|approved|passed)\b", lower):
        return True
    if re.search(r"\b(no|false|rejected|failed)\b", lower):
        return False
    return None
=======
output_parser.py — Parse structured data from raw LLM text output.
All parsers are strict: return None / safe defaults on any ambiguity.
"""

import re
import json
import logging

logger = logging.getLogger(__name__)


def parse_json_block(text: str) -> dict | None:
    """Extract the first valid JSON object from LLM text.

    Handles both raw JSON and ```json ... ``` fenced blocks.
    Returns None if no valid JSON object found.
    """
    if not text:
        return None

    # Try to extract from ```json ... ``` fence first
    fence_pattern = r"```(?:json)?\s*(\{.*?\})\s*```"
    fence_match = re.search(fence_pattern, text, re.DOTALL)
    if fence_match:
        candidate = fence_match.group(1)
        try:
            result = json.loads(candidate)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass  # Fall through to raw scan

    # Try to find a raw JSON object by scanning for balanced braces
    brace_start = text.find("{")
    if brace_start == -1:
        return None

    depth = 0
    in_string = False
    escape_next = False
    for i, ch in enumerate(text[brace_start:], start=brace_start):
        if escape_next:
            escape_next = False
            continue
        if ch == "\\" and in_string:
            escape_next = True
            continue
        if ch == '"' and not escape_next:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = text[brace_start : i + 1]
                try:
                    result = json.loads(candidate)
                    if isinstance(result, dict):
                        return result
                except json.JSONDecodeError:
                    return None

    logger.debug("parse_json_block: no valid JSON object found")
    return None


def parse_file_list(text: str) -> list[str]:
    """Extract file paths from lines matching 'FILE: path | PURPOSE: ...' format.

    Returns list of path strings; ignores non-matching lines.
    """
    paths: list[str] = []
    # Match lines like: FILE: some/path/file.py | PURPOSE: anything
    pattern = re.compile(r"FILE:\s*([^\|]+?)(?:\s*\|.*)?$", re.IGNORECASE)
    for line in text.splitlines():
        m = pattern.search(line.strip())
        if m:
            path = m.group(1).strip()
            if path:
                paths.append(path)
    return paths


def parse_patch_bundle(text: str) -> dict | None:
    """Extract and strictly validate a patch bundle JSON from LLM text.

    Required shape:
        {"patches": [{"file": str, "action": str, "content": str}, ...]}

    Returns None if structure is missing or invalid — never returns partial bundles.
    """
    raw = parse_json_block(text)
    if raw is None:
        logger.warning("parse_patch_bundle: no JSON block found")
        return None

    # Validate top-level key
    if "patches" not in raw:
        logger.warning("parse_patch_bundle: missing 'patches' key")
        return None

    patches = raw["patches"]
    if not isinstance(patches, list):
        logger.warning("parse_patch_bundle: 'patches' is not a list")
        return None

    # Validate every patch entry
    required_keys = {"file", "action", "content"}
    for idx, patch in enumerate(patches):
        if not isinstance(patch, dict):
            logger.warning("parse_patch_bundle: patch[%d] is not a dict", idx)
            return None
        missing = required_keys - patch.keys()
        if missing:
            logger.warning("parse_patch_bundle: patch[%d] missing keys: %s", idx, missing)
            return None
        for key in required_keys:
            if not isinstance(patch[key], str):
                logger.warning(
                    "parse_patch_bundle: patch[%d].%s is not a string", idx, key
                )
                return None

    return raw


def parse_review_decision(text: str) -> str:
    """Find 'approved' or 'rejected' in LLM text (case-insensitive).

    Returns 'approved' or 'rejected'. Defaults to 'rejected' for safety
    if neither word is found or text is empty.
    """
    if not text:
        return "rejected"

    lower = text.lower()

    # Check both words; prefer whichever appears first
    approved_pos = lower.find("approved")
    rejected_pos = lower.find("rejected")

    if approved_pos == -1 and rejected_pos == -1:
        # Neither found — safe default
        return "rejected"

    if approved_pos == -1:
        return "rejected"

    if rejected_pos == -1:
        return "approved"

    # Both found — return whichever comes first in the text
    return "approved" if approved_pos < rejected_pos else "rejected"
>>>>>>> V4
