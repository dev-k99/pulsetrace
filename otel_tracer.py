"""
otel_tracer.py — PulseTrace OTel Simulation Engine
────────────────────────────────────────────────────
Uses the real OpenTelemetry SDK to generate structurally valid trace/span IDs
and parent-child relationships. Realistic timing is injected post-hoc from
per-agent latency profiles because live OTel context manager durations are
effectively 0ms in a synchronous demo context.

All costs are in South African Rand (ZAR).
"""

from __future__ import annotations

import random
import uuid
from datetime import datetime, timedelta

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

# ─── Agent Registry ────────────────────────────────────────────────────────────

AGENTS: list[str] = ["GPT-4o", "Claude-3.5", "Gemini-1.5", "Llama-3", "Mistral-7B"]

# Cost per 1,000 tokens in ZAR (approx. 1 USD = 18.5 ZAR)
COST_PER_1K_TOKENS_ZAR: dict[str, dict[str, float]] = {
    "GPT-4o":     {"input": 0.09,   "output": 0.28},
    "Claude-3.5": {"input": 0.055,  "output": 0.28},
    "Gemini-1.5": {"input": 0.0065, "output": 0.019},
    "Llama-3":    {"input": 0.0037, "output": 0.0037},
    "Mistral-7B": {"input": 0.0019, "output": 0.0019},
}

# (mean_ms, std_ms) latency profile per agent per span type
LATENCY_PROFILES_MS: dict[str, tuple[float, float]] = {
    "GPT-4o":     (1800.0, 600.0),
    "Claude-3.5": (1400.0, 500.0),
    "Gemini-1.5": (900.0,  350.0),
    "Llama-3":    (500.0,  200.0),
    "Mistral-7B": (320.0,  130.0),
}

# Span latency multipliers relative to the agent base latency
SPAN_LATENCY_FACTOR: dict[str, float] = {
    "agent.plan":     0.15,
    "tool.call":      0.20,
    "tool.search":    0.18,
    "tool.retrieve":  0.14,
    "tool.write":     0.12,
    "llm.call":       1.00,   # primary latency driver
    "llm.reflect":    0.45,
    "agent.respond":  0.10,
}

# Tools that can appear in tool spans
TOOL_NAMES: list[str] = [
    "search_web",
    "read_file",
    "write_file",
    "query_db",
    "fetch_api",
    "retrieve_memory",
    "summarize_context",
]

# Mandatory span pipeline (root always first, respond always last)
PIPELINE_CORE: list[str] = ["agent.plan", "llm.call", "agent.respond"]
PIPELINE_OPTIONAL: list[str] = [
    "tool.call",
    "tool.search",
    "tool.retrieve",
    "llm.reflect",
    "tool.write",
]


# ─── Internal Helpers ──────────────────────────────────────────────────────────

def _sample_latency(agent: str, span_name: str) -> float:
    """Returns a realistic latency in milliseconds, clamped to a minimum of 50ms."""
    mean, std = LATENCY_PROFILES_MS.get(agent, (800.0, 300.0))
    factor = SPAN_LATENCY_FACTOR.get(span_name, 0.25)
    raw = random.gauss(mean * factor, std * factor * 0.3)
    return max(50.0, raw)


def _sample_tokens(span_name: str) -> tuple[int, int]:
    """Returns (input_tokens, output_tokens) for a given span type."""
    if span_name == "agent.plan":
        return random.randint(150, 600), 0
    if span_name == "llm.call":
        return random.randint(400, 2000), random.randint(80, 800)
    if span_name == "llm.reflect":
        return random.randint(200, 800), random.randint(50, 300)
    if span_name == "agent.respond":
        return 0, random.randint(40, 280)
    # tool spans — no tokens consumed directly
    return 0, 0


def _compute_cost(agent: str, tokens_in: int, tokens_out: int) -> float:
    """Returns cost in ZAR for the given token counts."""
    rates = COST_PER_1K_TOKENS_ZAR.get(agent, {"input": 0.01, "output": 0.02})
    return (tokens_in / 1000.0) * rates["input"] + (tokens_out / 1000.0) * rates["output"]


# ─── Core Functions ────────────────────────────────────────────────────────────

def generate_trace(agent_name: str, base_time: datetime | None = None) -> list[dict]:
    """
    Generate a realistic multi-span OTel trace for a single agent run.

    Uses the OTel SDK for structurally valid trace/span IDs and parent-child
    linkage. Timestamps are overridden post-hoc with realistic values derived
    from agent latency profiles.

    Args:
        agent_name: Name of the agent (must be in AGENTS list).
        base_time:  Start time for the trace. Defaults to utcnow().

    Returns:
        List of span dicts, each ready for direct SQLite insertion.
    """
    if base_time is None:
        base_time = datetime.utcnow()

    # ── Build the OTel provider (per-call, not shared — thread safety) ─────────
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("pulsetrace")

    # ── Choose which optional spans to include ─────────────────────────────────
    n_optional = random.randint(1, min(5, len(PIPELINE_OPTIONAL)))
    optional_spans = random.sample(PIPELINE_OPTIONAL, n_optional)

    # Full pipeline: plan → [optionals] → llm.call → respond
    pipeline = ["agent.plan"] + optional_spans + ["llm.call", "agent.respond"]

    # ── Inject error on ~8% of runs (on the llm.call span) ────────────────────
    error_run = random.random() < 0.08

    # ── Create spans using OTel context managers (for valid IDs) ──────────────
    # We walk the pipeline. The root span wraps everything; child spans are
    # sequential siblings under the root (flat hierarchy for Gantt clarity).
    span_objects: list = []

    with tracer.start_as_current_span("agent.plan") as root_span:
        span_objects.append(("agent.plan", root_span, None))
        for span_name in pipeline[1:]:
            status = StatusCode.ERROR if (error_run and span_name == "llm.call") else StatusCode.OK
            with tracer.start_as_current_span(span_name) as child:
                child.set_status(status)
                span_objects.append((span_name, child, root_span))

        # Propagate error to root if any child errored
        if error_run:
            root_span.set_status(StatusCode.ERROR)

    # ── Read finished spans from exporter ─────────────────────────────────────
    finished = {
        format(s.context.span_id, "016x"): s
        for s in exporter.get_finished_spans()
    }

    # ── Build realistic timeline from latency profiles ─────────────────────────
    cursor = base_time  # wall-clock cursor advances as spans execute sequentially
    result: list[dict] = []

    # Map OTel span name → finished ReadableSpan (for ID extraction)
    # OTel names spans by the string passed to start_as_current_span
    name_to_span: dict[str, object] = {}
    for s in exporter.get_finished_spans():
        name_to_span[s.name] = s

    root_otel = name_to_span.get("agent.plan")
    trace_id_hex = format(root_otel.context.trace_id, "032x") if root_otel else uuid.uuid4().hex + uuid.uuid4().hex[:0]

    for span_name in pipeline:
        otel_span = name_to_span.get(span_name)
        span_id = format(otel_span.context.span_id, "016x") if otel_span else uuid.uuid4().hex[:16]
        parent_span_id = (
            format(otel_span.parent.span_id, "016x")
            if (otel_span and otel_span.parent)
            else None
        )

        latency_ms = _sample_latency(agent_name, span_name)
        start_dt = cursor
        end_dt = cursor + timedelta(milliseconds=latency_ms)
        cursor = end_dt  # next span starts where this one ends

        tokens_in, tokens_out = _sample_tokens(span_name)
        cost_zar = _compute_cost(agent_name, tokens_in, tokens_out)

        is_error = error_run and span_name == "llm.call"
        status = "ERROR" if is_error else "OK"

        # Root span encompasses the entire pipeline
        if span_name == "agent.plan":
            parent_span_id = None

        span_dict: dict = {
            "trace_id":      trace_id_hex,
            "span_id":       span_id,
            "parent_span_id": parent_span_id,
            "agent":         agent_name,
            "span_name":     span_name,
            "start_time":    start_dt.isoformat(),
            "end_time":      end_dt.isoformat(),
            "latency_ms":    round(latency_ms, 2),
            "status":        status,
            "tokens_input":  tokens_in,
            "tokens_output": tokens_out,
            "cost_zar":      round(cost_zar, 6),
            "model":         agent_name,
            "tool_name":     random.choice(TOOL_NAMES) if span_name.startswith("tool.") else None,
            "attributes":    _build_attributes(agent_name, span_name, tokens_in, tokens_out, latency_ms),
        }
        result.append(span_dict)

    # Fix root span end_time to cover the whole trace
    if result:
        result[0]["end_time"] = result[-1]["end_time"]
        total_ms = sum(s["latency_ms"] for s in result[1:]) + result[0]["latency_ms"]
        result[0]["latency_ms"] = round(total_ms, 2)

    return result


def _build_attributes(
    agent: str, span_name: str, tokens_in: int, tokens_out: int, latency_ms: float
) -> str:
    """Returns a JSON-serializable string of span attributes."""
    import json
    attrs: dict = {
        "agent.name": agent,
        "span.type": span_name.split(".")[0],
        "latency_ms": round(latency_ms, 2),
    }
    if tokens_in or tokens_out:
        attrs["llm.tokens.input"] = tokens_in
        attrs["llm.tokens.output"] = tokens_out
        attrs["llm.tokens.total"] = tokens_in + tokens_out
    if span_name.startswith("tool."):
        attrs["tool.name"] = random.choice(TOOL_NAMES)
    return json.dumps(attrs)


def simulate_agent_run(
    agent_name: str,
    run_time: datetime | None = None,
) -> dict:
    """
    Simulate a complete agent run and return a summary + all spans.

    Args:
        agent_name: One of the AGENTS names.
        run_time:   Timestamp for this run. Defaults to utcnow().

    Returns:
        Dict containing summary fields and a 'spans' key with the full span list.
        All spans are ready for insertion into the SQLite traces table.
    """
    if run_time is None:
        run_time = datetime.utcnow()

    spans = generate_trace(agent_name, base_time=run_time)

    total_tokens_in  = sum(s["tokens_input"]  for s in spans)
    total_tokens_out = sum(s["tokens_output"] for s in spans)
    total_cost_zar   = sum(s["cost_zar"]      for s in spans)
    total_latency_ms = spans[0]["latency_ms"] if spans else 0.0  # root span = total

    # Determine overall status: ERROR if any span errored
    run_status = "ERROR" if any(s["status"] == "ERROR" for s in spans) else "OK"

    return {
        "trace_id":          spans[0]["trace_id"] if spans else uuid.uuid4().hex,
        "agent":             agent_name,
        "total_latency_ms":  round(total_latency_ms, 2),
        "total_tokens_input":  total_tokens_in,
        "total_tokens_output": total_tokens_out,
        "total_cost_zar":    round(total_cost_zar, 6),
        "status":            run_status,
        "span_count":        len(spans),
        "run_time":          run_time.isoformat(),
        "spans":             spans,
    }
