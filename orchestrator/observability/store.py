"""Durable, queryable SQLite span store (spec §9, M6d).

The OTel sink for runtime runs: a custom SpanExporter writes every span as one
row — the single record of truth. `orch status|metrics|memory` query this store
(see query.py). Spans of one run share a trace_id; the run_id lives on the root
`run` span's `run.id` attribute.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Sequence
from pathlib import Path

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

_SCHEMA = """
CREATE TABLE IF NOT EXISTS spans (
    trace_id  TEXT NOT NULL,
    span_id   TEXT NOT NULL PRIMARY KEY,
    parent_id TEXT,
    name      TEXT NOT NULL,
    start_ns  INTEGER NOT NULL,
    end_ns    INTEGER NOT NULL,
    attrs     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_spans_trace ON spans(trace_id);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    """Open (creating parent dir + schema) a connection to the span store."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.executescript(_SCHEMA)
    return conn


class SqliteSpanExporter(SpanExporter):
    """Writes finished spans into the SQLite span store (one row per span)."""

    def __init__(self, db_path: Path) -> None:
        self._conn = connect(db_path)
        self._lock = threading.Lock()

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        rows = []
        for span in spans:
            ctx = span.get_span_context()
            parent = span.parent.span_id if span.parent else None
            rows.append(
                (
                    format(ctx.trace_id, "032x"),
                    format(ctx.span_id, "016x"),
                    format(parent, "016x") if parent is not None else None,
                    span.name,
                    int(span.start_time or 0),
                    int(span.end_time or 0),
                    json.dumps(dict(span.attributes or {})),
                )
            )
        with self._lock:
            self._conn.executemany(
                "INSERT OR REPLACE INTO spans "
                "(trace_id, span_id, parent_id, name, start_ns, end_ns, attrs) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            self._conn.commit()
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        with self._lock:
            self._conn.close()
