"""Observability layer: OTel spans (spec §9)."""

from orchestrator.observability.spans import configure_tracing, get_tracer

__all__ = ["configure_tracing", "get_tracer"]
