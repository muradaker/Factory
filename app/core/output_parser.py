"""
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
