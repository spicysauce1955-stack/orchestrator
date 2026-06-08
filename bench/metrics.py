"""Per-contestant metric extraction. Parsers are tolerant: agent CLIs evolve."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Metrics:
    cost_usd: float | None
    tokens: int | None
    turns: int | None


def _iter_json_lines(stream: str):
    for line in stream.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def parse_claude_stream(stream: str) -> Metrics:
    """claude -p --output-format stream-json: cost+turns from the final `result` event."""
    cost = tokens = turns = None
    for obj in _iter_json_lines(stream):
        if obj.get("type") == "result":
            if obj.get("total_cost_usd") is not None:
                cost = float(obj["total_cost_usd"])
            if obj.get("num_turns") is not None:
                turns = int(obj["num_turns"])
            usage = obj.get("usage") or {}
            it, ot = usage.get("input_tokens"), usage.get("output_tokens")
            if it is not None or ot is not None:
                tokens = int(it or 0) + int(ot or 0)
    return Metrics(cost_usd=cost, tokens=tokens, turns=turns)


def parse_codex_jsonl(stream: str) -> Metrics:
    """codex exec --json: tolerant scan. Turns = agent/command items; tokens summed
    from any `usage` objects. Cost left None (derive externally if needed)."""
    turns = 0
    tokens = 0
    saw_tokens = False
    for obj in _iter_json_lines(stream):
        t = obj.get("type", "")
        if t.startswith("item.completed") or t.startswith("turn.completed"):
            turns += 1 if "item" in obj else 0
        usage = obj.get("usage") or (obj.get("info") or {}).get("usage")
        if isinstance(usage, dict):
            it, ot = usage.get("input_tokens"), usage.get("output_tokens")
            if it is not None or ot is not None:
                tokens += int(it or 0) + int(ot or 0)
                saw_tokens = True
    return Metrics(cost_usd=None, tokens=tokens if saw_tokens else None,
                   turns=turns if turns else None)


def orchestrator_metrics(repo_root: Path, run_id: str, span_db: Path) -> Metrics:
    """Read contestant A's cost/tokens from the orchestrator span store via `orch metrics`."""
    proc = subprocess.run(
        [sys.executable, "-m", "orchestrator.cli", "metrics", run_id, "--repo", str(repo_root)],
        cwd=repo_root, capture_output=True, text=True,
        env={"ORCH_SPAN_DB": str(span_db)} | dict(os.environ),
    )
    cost = _grep_float(proc.stdout, r"total: \$([0-9.]+)")
    tokens = _grep_int(proc.stdout, r"\(([0-9]+) tokens")
    # turns filled by caller from span count
    return Metrics(cost_usd=cost, tokens=tokens, turns=None)


def _grep_float(text: str, pat: str) -> float | None:
    m = re.search(pat, text)
    return float(m.group(1)) if m else None


def _grep_int(text: str, pat: str) -> int | None:
    m = re.search(pat, text)
    return int(m.group(1)) if m else None
