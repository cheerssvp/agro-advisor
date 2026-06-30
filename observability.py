"""Optional tracing: exports ADK's built-in OpenTelemetry spans to LangSmith.

Google ADK instruments every LLM call and tool call with OpenTelemetry spans
via `google.adk.telemetry.tracer`, but doesn't activate an exporter unless you
run through `adk web`/`adk api_server` -- our own `cli.py` (using
InMemoryRunner directly) doesn't get that for free. LangSmith accepts raw
OTLP traces, so no `langsmith` SDK or LangChain dependency is needed: this
just points the standard OTLP HTTP exporter at LangSmith's OTEL endpoint and
lets ADK's existing instrumentation flow through it.

No-op (and safe to always call) when LANGSMITH_API_KEY isn't set -- tracing
is purely additive, never required for the app to run.
"""

from __future__ import annotations

import os

LANGSMITH_OTEL_ENDPOINT = "https://api.smith.langchain.com/otel"


def setup_langsmith_tracing() -> bool:
    """Wires ADK's OpenTelemetry spans to LangSmith if LANGSMITH_API_KEY is set.

    Must be called before any agent/tool runs (e.g. once at CLI startup) so
    the global TracerProvider is in place before ADK creates its first span.
    Returns True if tracing was activated, False if skipped (no API key).
    """
    api_key = os.environ.get("LANGSMITH_API_KEY")
    if not api_key:
        return False

    headers = f"x-api-key={api_key}"
    project = os.environ.get("LANGSMITH_PROJECT")
    if project:
        headers += f",Langsmith-Project={project}"

    os.environ.setdefault("OTEL_EXPORTER_OTLP_ENDPOINT", LANGSMITH_OTEL_ENDPOINT)
    os.environ.setdefault("OTEL_EXPORTER_OTLP_HEADERS", headers)

    from google.adk.telemetry.setup import maybe_set_otel_providers

    maybe_set_otel_providers()
    return True


def flush_tracing() -> None:
    """Force-exports any buffered spans before the process exits.

    BatchSpanProcessor exports on a background timer (default every 5s) --
    a short-lived CLI run can exit before that fires, silently dropping the
    trace. Safe to call even when tracing was never activated.
    """
    from opentelemetry import trace

    provider = trace.get_tracer_provider()
    force_flush = getattr(provider, "force_flush", None)
    if force_flush:
        force_flush()
