"""
evals_db.py — PulseTrace Data Layer
─────────────────────────────────────
All SQLite schema definitions, seeding logic, query functions, and export
utilities live here. Zero Streamlit imports — pure Python + stdlib + Pandas.

Important: Each function opens its own sqlite3 connection. This is intentional —
Streamlit's threading model makes module-level connection singletons unsafe.

All costs are denominated in South African Rand (ZAR).
"""

from __future__ import annotations

import json
import random
import sqlite3
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
from faker import Faker

import otel_tracer

# ─── Configuration ─────────────────────────────────────────────────────────────

DB_PATH = "pulsetrace.db"

AGENTS: list[str] = ["GPT-4o", "Claude-3.5", "Gemini-1.5", "Llama-3", "Mistral-7B"]

_fake = Faker()

# Pre-seeded health profiles per agent (baseline — jitter applied at read time)
_AGENT_HEALTH_PRESETS: list[dict] = [
    {"name": "GPT-4o",     "status": "Healthy",  "uptime_pct": 99.8, "error_rate": 0.2,  "avg_latency": 1750.0, "total_runs": 0},
    {"name": "Claude-3.5", "status": "Healthy",  "uptime_pct": 99.5, "error_rate": 0.5,  "avg_latency": 1400.0, "total_runs": 0},
    {"name": "Gemini-1.5", "status": "Degraded", "uptime_pct": 94.2, "error_rate": 3.1,  "avg_latency": 2240.0, "total_runs": 0},
    {"name": "Llama-3",    "status": "Healthy",  "uptime_pct": 98.7, "error_rate": 1.3,  "avg_latency": 520.0,  "total_runs": 0},
    {"name": "Mistral-7B", "status": "Down",     "uptime_pct": 71.0, "error_rate": 12.4, "avg_latency": 340.0,  "total_runs": 0},
]

# Realistic log message templates — {placeholders} filled at generation time
_LOG_TEMPLATES: dict[str, list[str]] = {
    "INFO": [
        "Agent {agent} initialized with context window 128k tokens",
        "Trace {trace_id} completed successfully with {spans} spans",
        "Cache hit for embedding key hash:{key}",
        "Memory retrieval returned {k} results in {ms}ms",
        "Tool dispatch: {tool} called by {agent}",
        "Token budget: {used}/{total} ({pct}% utilised)",
        "Checkpoint saved — agent state persisted to memory store",
        "Model {agent} loaded, device: cuda:0, precision: bf16",
        "Eval run #{n} completed — pass_rate={pct}%",
    ],
    "WARN": [
        "Token limit approaching: {pct}% of context window used by {agent}",
        "High latency detected: {agent} took {ms}ms (threshold: 2000ms)",
        "Retry attempt {n}/3 for tool: {tool}",
        "Rate limit warning: {remaining} requests remaining this minute",
        "Embedding cache miss — falling back to live inference",
        "Response quality score below threshold: {score:.2f}",
        "Slow tool call: {tool} exceeded 800ms SLA",
    ],
    "ERROR": [
        "Rate limit exceeded for model {agent}: retry after {s}s",
        "Tool call failed: {tool} returned HTTP {code}",
        "Context overflow: input tokens {tokens} exceed max {max_tokens}",
        "Span {span_id} timeout after {ms}ms",
        "Database connection lost — using cached results",
        "LLM inference error: {agent} returned status ERROR",
        "Memory store write failed: disk quota exceeded",
    ],
}


# ─── Schema ────────────────────────────────────────────────────────────────────

_DDL = """
CREATE TABLE IF NOT EXISTS traces (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id        TEXT NOT NULL,
    span_id         TEXT NOT NULL,
    parent_span_id  TEXT,
    agent           TEXT NOT NULL,
    span_name       TEXT NOT NULL,
    start_time      TEXT NOT NULL,
    end_time        TEXT NOT NULL,
    latency_ms      REAL    DEFAULT 0.0,
    status          TEXT    DEFAULT 'OK',
    tokens_input    INTEGER DEFAULT 0,
    tokens_output   INTEGER DEFAULT 0,
    cost_zar        REAL    DEFAULT 0.0,
    model           TEXT,
    tool_name       TEXT,
    attributes      TEXT,
    created_at      TEXT    DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS evaluations (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    agent            TEXT NOT NULL,
    eval_date        TEXT NOT NULL,
    latency_ms       REAL,
    pass_rate        REAL,
    cost_zar         REAL,
    tokens_per_second REAL,
    total_runs       INTEGER DEFAULT 1,
    created_at       TEXT    DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS agents (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    status      TEXT    DEFAULT 'Healthy',
    uptime_pct  REAL    DEFAULT 100.0,
    error_rate  REAL    DEFAULT 0.0,
    last_ping   TEXT,
    avg_latency REAL    DEFAULT 0.0,
    total_runs  INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS logs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    agent      TEXT NOT NULL,
    level      TEXT NOT NULL,
    message    TEXT NOT NULL,
    timestamp  TEXT NOT NULL,
    trace_id   TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


# ─── Init ──────────────────────────────────────────────────────────────────────

def init_db(db_path: str = DB_PATH) -> None:
    """Create all tables if they don't already exist."""
    with sqlite3.connect(db_path) as conn:
        conn.executescript(_DDL)
        conn.commit()


# ─── Seeding ───────────────────────────────────────────────────────────────────

def seed_database(db_path: str = DB_PATH, force: bool = False) -> None:
    """
    Populate the database with realistic fake data.

    Args:
        db_path: Path to the SQLite file.
        force:   If True, wipe all existing data before re-seeding.
                 If False (default), skip seeding when data already exists.
    """
    with sqlite3.connect(db_path) as conn:
        if not force:
            count = conn.execute("SELECT COUNT(*) FROM traces").fetchone()[0]
            if count > 0:
                return  # Already seeded — idempotent guard

        if force:
            conn.executescript("""
                DELETE FROM traces;
                DELETE FROM evaluations;
                DELETE FROM agents;
                DELETE FROM logs;
            """)

        now = datetime.utcnow()

        # ── Insert agent health rows ───────────────────────────────────────────
        for preset in _AGENT_HEALTH_PRESETS:
            conn.execute(
                """
                INSERT OR REPLACE INTO agents
                    (name, status, uptime_pct, error_rate, last_ping, avg_latency, total_runs)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    preset["name"],
                    preset["status"],
                    preset["uptime_pct"],
                    preset["error_rate"],
                    now.isoformat(),
                    preset["avg_latency"],
                    preset["total_runs"],
                ),
            )

        # ── Generate 60 traces spread across the last 14 days ─────────────────
        # 12 traces per agent, distributed randomly across the window
        all_trace_runs: list[dict] = []
        for agent in AGENTS:
            for _ in range(12):
                hours_ago = random.uniform(0.5, 14 * 24)
                run_time = now - timedelta(hours=hours_ago)
                run = otel_tracer.simulate_agent_run(agent, run_time=run_time)
                all_trace_runs.append(run)

        # Insert all spans into the traces table
        for run in all_trace_runs:
            _insert_spans(conn, run["spans"])

        # Update agent run counts
        for agent in AGENTS:
            count = sum(1 for r in all_trace_runs if r["agent"] == agent)
            conn.execute(
                "UPDATE agents SET total_runs = ? WHERE name = ?", (count, agent)
            )

        # ── Build evaluation rows (one per agent per day in range) ─────────────
        _seed_evaluations(conn, all_trace_runs, now)

        # ── Generate 240 log entries (60% INFO, 25% WARN, 15% ERROR) ──────────
        _seed_logs(conn, all_trace_runs, now)

        conn.commit()


def _insert_spans(conn: sqlite3.Connection, spans: list[dict]) -> None:
    """Bulk-insert a list of span dicts into the traces table."""
    conn.executemany(
        """
        INSERT INTO traces
            (trace_id, span_id, parent_span_id, agent, span_name,
             start_time, end_time, latency_ms, status,
             tokens_input, tokens_output, cost_zar, model, tool_name, attributes)
        VALUES
            (:trace_id, :span_id, :parent_span_id, :agent, :span_name,
             :start_time, :end_time, :latency_ms, :status,
             :tokens_input, :tokens_output, :cost_zar, :model, :tool_name, :attributes)
        """,
        spans,
    )


def _seed_evaluations(
    conn: sqlite3.Connection,
    runs: list[dict],
    now: datetime,
) -> None:
    """Aggregate trace runs into daily evaluation summary rows."""
    # Group runs by (agent, date)
    buckets: dict[tuple[str, str], list[dict]] = {}
    for run in runs:
        run_date = datetime.fromisoformat(run["run_time"]).date().isoformat()
        key = (run["agent"], run_date)
        buckets.setdefault(key, []).append(run)

    for (agent, date_str), day_runs in buckets.items():
        avg_latency = sum(r["total_latency_ms"] for r in day_runs) / len(day_runs)
        total_cost  = sum(r["total_cost_zar"]   for r in day_runs)
        total_tokens_out = sum(r["total_tokens_output"] for r in day_runs)
        error_count = sum(1 for r in day_runs if r["status"] == "ERROR")
        pass_rate   = 1.0 - (error_count / len(day_runs))
        # tokens per second — use avg latency as denominator
        tps = (total_tokens_out / len(day_runs)) / (avg_latency / 1000.0) if avg_latency > 0 else 0

        conn.execute(
            """
            INSERT INTO evaluations
                (agent, eval_date, latency_ms, pass_rate, cost_zar, tokens_per_second, total_runs)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (agent, date_str, round(avg_latency, 2), round(pass_rate, 4),
             round(total_cost, 6), round(tps, 2), len(day_runs)),
        )


def _seed_logs(
    conn: sqlite3.Connection,
    runs: list[dict],
    now: datetime,
) -> None:
    """Generate 240 realistic log entries referencing real trace IDs."""
    level_weights = [("INFO", 0.60), ("WARN", 0.25), ("ERROR", 0.15)]
    levels  = [lw[0] for lw in level_weights]
    weights = [lw[1] for lw in level_weights]

    trace_ids = [r["trace_id"] for r in runs]

    for _ in range(240):
        level = random.choices(levels, weights=weights, k=1)[0]
        agent = random.choice(AGENTS)
        template = random.choice(_LOG_TEMPLATES[level])
        trace_id = random.choice(trace_ids)
        hours_ago = random.uniform(0, 14 * 24)
        timestamp = (now - timedelta(hours=hours_ago)).isoformat()

        message = template.format(
            agent=agent,
            trace_id=trace_id[:12] + "...",
            spans=random.randint(4, 8),
            key=_fake.md5()[:8],
            k=random.randint(3, 20),
            ms=random.randint(50, 3000),
            tool=random.choice(otel_tracer.TOOL_NAMES),
            used=random.randint(10000, 100000),
            total=128000,
            pct=random.randint(10, 95),
            n=random.randint(1, 3),
            remaining=random.randint(0, 60),
            score=random.uniform(0.2, 0.85),
            s=random.randint(30, 120),
            code=random.choice([400, 401, 429, 500, 503]),
            tokens=random.randint(128001, 200000),
            max_tokens=128000,
            span_id=_fake.md5()[:16],
        )

        conn.execute(
            "INSERT INTO logs (agent, level, message, timestamp, trace_id) VALUES (?, ?, ?, ?, ?)",
            (agent, level, message, timestamp, trace_id),
        )


# ─── Query Functions ───────────────────────────────────────────────────────────

def get_traces(
    agent: str = "All Agents",
    start_date=None,
    end_date=None,
    db_path: str = DB_PATH,
) -> pd.DataFrame:
    """
    Return root-level spans (one row per agent run) filtered by agent and date.

    Each row represents a complete agent run — the root span that encompasses
    all child spans for that trace_id.
    """
    params: list = []
    clauses: list[str] = ["parent_span_id IS NULL"]

    if agent and agent != "All Agents":
        clauses.append("agent = ?")
        params.append(agent)

    if start_date:
        clauses.append("start_time >= ?")
        params.append(str(start_date))

    if end_date:
        clauses.append("start_time <= ?")
        params.append(str(end_date) + "T23:59:59")

    where = " AND ".join(clauses)

    sql = f"""
        SELECT
            trace_id,
            agent,
            span_name,
            start_time,
            end_time,
            latency_ms,
            tokens_input,
            tokens_output,
            cost_zar,
            status
        FROM traces
        WHERE {where}
        ORDER BY start_time DESC
        LIMIT 200
    """

    with sqlite3.connect(db_path) as conn:
        df = pd.read_sql_query(sql, conn, params=params)

    if not df.empty:
        df["start_time"] = pd.to_datetime(df["start_time"])

    return df


def get_spans_for_trace(trace_id: str, db_path: str = DB_PATH) -> pd.DataFrame:
    """Return all spans for a given trace_id, ordered by start_time."""
    sql = """
        SELECT
            span_name, span_id, parent_span_id,
            start_time, end_time, latency_ms,
            status, tokens_input, tokens_output, cost_zar,
            tool_name, attributes
        FROM traces
        WHERE trace_id = ?
        ORDER BY start_time ASC
    """
    with sqlite3.connect(db_path) as conn:
        df = pd.read_sql_query(sql, conn, params=[trace_id])

    if not df.empty:
        df["start_time"] = pd.to_datetime(df["start_time"])
        df["end_time"]   = pd.to_datetime(df["end_time"])

    return df


def get_evaluations(
    agent: str = "All Agents",
    start_date=None,
    end_date=None,
    db_path: str = DB_PATH,
) -> pd.DataFrame:
    """Return evaluation summary rows filtered by agent and date range."""
    params: list = []
    clauses: list[str] = []

    if agent and agent != "All Agents":
        clauses.append("agent = ?")
        params.append(agent)

    if start_date:
        clauses.append("eval_date >= ?")
        params.append(str(start_date))

    if end_date:
        clauses.append("eval_date <= ?")
        params.append(str(end_date))

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    sql = f"""
        SELECT agent, eval_date, latency_ms, pass_rate, cost_zar, tokens_per_second, total_runs
        FROM evaluations
        {where}
        ORDER BY eval_date ASC
    """

    with sqlite3.connect(db_path) as conn:
        df = pd.read_sql_query(sql, conn, params=params)

    if not df.empty:
        df["eval_date"] = pd.to_datetime(df["eval_date"])

    return df


def get_agent_health(db_path: str = DB_PATH) -> pd.DataFrame:
    """
    Return agent health rows, refreshing last_ping and injecting minor random
    jitter into live metrics so the health tab feels dynamic.
    """
    now_str = datetime.utcnow().isoformat()

    with sqlite3.connect(db_path) as conn:
        # Refresh last_ping for non-Down agents
        conn.execute(
            "UPDATE agents SET last_ping = ? WHERE status != 'Down'", (now_str,)
        )
        # Inject minor uptime jitter for Healthy/Degraded agents (±0.05%)
        conn.execute("""
            UPDATE agents
            SET uptime_pct = MIN(100.0, MAX(0.0, uptime_pct + (RANDOM() % 10) * 0.01))
            WHERE status != 'Down'
        """)
        conn.commit()

        df = pd.read_sql_query(
            "SELECT name, status, uptime_pct, error_rate, last_ping, avg_latency, total_runs "
            "FROM agents ORDER BY name",
            conn,
        )

    return df


def get_logs(
    level: Optional[list[str]] = None,
    search: Optional[str] = None,
    agent: str = "All Agents",
    db_path: str = DB_PATH,
) -> pd.DataFrame:
    """
    Return log entries filtered by level list, keyword search, and agent.

    Args:
        level:  List of levels to include e.g. ['ERROR', 'WARN']. None = all.
        search: Substring match against the message column.
        agent:  Agent name filter. 'All Agents' returns all.
    """
    params: list = []
    clauses: list[str] = []

    if level:
        placeholders = ", ".join("?" for _ in level)
        clauses.append(f"level IN ({placeholders})")
        params.extend(level)

    if search:
        clauses.append("message LIKE ?")
        params.append(f"%{search}%")

    if agent and agent != "All Agents":
        clauses.append("agent = ?")
        params.append(agent)

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    sql = f"""
        SELECT agent, level, message, timestamp, trace_id
        FROM logs
        {where}
        ORDER BY timestamp DESC
        LIMIT 500
    """

    with sqlite3.connect(db_path) as conn:
        df = pd.read_sql_query(sql, conn, params=params)

    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"])

    return df


# ─── Write Functions ───────────────────────────────────────────────────────────

def add_trace(trace_data: dict, db_path: str = DB_PATH) -> str:
    """
    Persist a simulated agent run to the database.

    Inserts all spans, adds a INFO log entry, and updates the agent's
    total_runs and avg_latency in the agents table.

    Returns the trace_id string.
    """
    spans    = trace_data["spans"]
    agent    = trace_data["agent"]
    trace_id = trace_data["trace_id"]

    with sqlite3.connect(db_path) as conn:
        # Insert spans
        _insert_spans(conn, spans)

        # Append a log entry for this run
        log_level = "ERROR" if trace_data["status"] == "ERROR" else "INFO"
        log_msg = (
            f"Agent {agent} run {trace_id[:12]}... completed "
            f"[{trace_data['status']}] "
            f"latency={trace_data['total_latency_ms']:.0f}ms "
            f"tokens={trace_data['total_tokens_input'] + trace_data['total_tokens_output']} "
            f"cost=R{trace_data['total_cost_zar']:.4f}"
        )
        conn.execute(
            "INSERT INTO logs (agent, level, message, timestamp, trace_id) VALUES (?, ?, ?, ?, ?)",
            (agent, log_level, log_msg, datetime.utcnow().isoformat(), trace_id),
        )

        # Update agent stats
        conn.execute(
            """
            UPDATE agents
            SET total_runs  = total_runs + 1,
                avg_latency = (avg_latency * total_runs + ?) / (total_runs + 1)
            WHERE name = ?
            """,
            (trace_data["total_latency_ms"], agent),
        )

        conn.commit()

    return trace_id


# ─── Export Functions ──────────────────────────────────────────────────────────

def export_csv(
    agent: str = "All Agents",
    start_date=None,
    end_date=None,
    db_path: str = DB_PATH,
) -> str:
    """Return a CSV string of all root-level traces matching the filters."""
    df = get_traces(agent, start_date, end_date, db_path)
    return df.to_csv(index=False)


def export_json(
    agent: str = "All Agents",
    start_date=None,
    end_date=None,
    db_path: str = DB_PATH,
) -> str:
    """Return a JSON string (records orientation) of all traces matching the filters."""
    df = get_traces(agent, start_date, end_date, db_path)
    return df.to_json(orient="records", indent=2, date_format="iso")
