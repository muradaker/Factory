"""
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
