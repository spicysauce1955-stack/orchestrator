"""Structured output parsing for task/review steps (spec §6)."""

from __future__ import annotations

import json
import re

_ENUM_RE = re.compile(r"enum\[([^\]]*)\]")
_JSON_OBJ_RE = re.compile(r"\{[^{}]*\}")


def _extract_json_object(text: str) -> dict | None:
    """Best-effort: pull the last flat JSON object out of prose/markdown.

    Real harnesses wrap structured output in explanatory text or ```json fences,
    so a whole-string json.loads fails. Scan for `{...}` candidates and return the
    last one that parses to a dict (models tend to conclude with their answer).
    """
    for candidate in reversed(_JSON_OBJ_RE.findall(text)):
        try:
            loaded = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(loaded, dict):
            return loaded
    return None


class Verdict:
    """Agent-as-judge verdict values (spec §6 review loop)."""

    APPROVE = "approve"
    REJECT = "reject"


def parse_output(output: str, output_schema: dict | None) -> tuple[dict | None, bool]:
    """Parse a step's textual output into structured output_data.

    If output_schema declares enum field(s), accept either a JSON object
    {field: value} or a bare value (single-field schema), and validate enum
    membership. Returns (output_data, is_error). No schema -> (None, False).
    """
    if not output_schema:
        return None, False

    data: dict | None = None
    try:
        loaded = json.loads(output)
        if isinstance(loaded, dict):
            data = loaded
    except (json.JSONDecodeError, TypeError):
        data = None
    if data is None:
        data = _extract_json_object(output)

    for field_name, spec in output_schema.items():
        allowed = None
        if isinstance(spec, str):
            m = _ENUM_RE.fullmatch(spec.strip())
            if m:
                allowed = [v.strip() for v in m.group(1).split(",") if v.strip()]
        if allowed is None:
            continue
        value = None
        if data is not None and field_name in data:
            value = str(data[field_name]).strip()
        elif len(output_schema) == 1:
            value = output.strip()
        if value not in allowed:
            return None, True
        data = {**(data or {}), field_name: value}

    return data, False
