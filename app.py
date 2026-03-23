"""
app.py — PulseTrace Main Application
──────────────────────────────────────
PulseTrace is a free, open-source AI AgentOps monitoring dashboard built with
Streamlit. It simulates OpenTelemetry traces, evaluation metrics, agent health,
and structured logs — all backed by a local SQLite database.

Run locally:
    streamlit run app.py

Dark theme with accent #00ff9d is configured in .streamlit/config.toml.
All costs are displayed in South African Rand (ZAR).
"""

from __future__ import annotations

import random
from datetime import date, datetime, timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

import evals_db
import otel_tracer

# ─── Constants ────────────────────────────────────────────────────────────────

DB_PATH   = "pulsetrace.db"
AGENTS    = ["All Agents", "GPT-4o", "Claude-3.5", "Gemini-1.5", "Llama-3", "Mistral-7B"]
PALETTE   = ["#00ff9d", "#00aaff", "#ff6644", "#aa44ff", "#ffaa00"]
CHART_H   = 300   # unified chart height across all tabs

# ─── Page Config ──────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="PulseTrace — AgentOps Monitor",
    page_icon="◉",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={"About": "PulseTrace v1.0 — Free AI AgentOps Monitoring Dashboard"},
)

# ─── CSS ──────────────────────────────────────────────────────────────────────

_CSS = """
<style>

/* ── Reset & base ─────────────────────────────────────────────────────────── */
[data-testid="stAppViewContainer"],
[data-testid="stMain"] {
    background-color: #0b0f1a;
}

/* ── Custom scrollbar ─────────────────────────────────────────────────────── */
::-webkit-scrollbar              { width: 5px; height: 5px; }
::-webkit-scrollbar-track        { background: #0b0f1a; }
::-webkit-scrollbar-thumb        { background: rgba(0,255,157,0.18); border-radius: 4px; }
::-webkit-scrollbar-thumb:hover  { background: rgba(0,255,157,0.35); }

/* ── Sidebar ─────────────────────────────────────────────────────────────── */
[data-testid="stSidebar"] {
    background-color: #0d1117 !important;
    border-right: 1px solid rgba(0,255,157,0.1);
}
[data-testid="stSidebar"] * { font-family: monospace !important; }
[data-testid="stSidebar"] .stSelectbox label,
[data-testid="stSidebar"] .stDateInput  label { display: none; }

/* ── Sidebar brand ───────────────────────────────────────────────────────── */
.sb-brand {
    font-size: 1.25rem;
    font-weight: 800;
    color: #00ff9d;
    letter-spacing: 0.04em;
    line-height: 1.2;
}
.sb-tagline {
    font-size: 0.68rem;
    color: #444;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    margin-top: 2px;
}

/* ── Sidebar section heading ─────────────────────────────────────────────── */
.sb-label {
    font-size: 0.65rem;
    color: #555;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    margin-bottom: 4px;
    margin-top: 14px;
}

/* ── Sidebar status dots ─────────────────────────────────────────────────── */
.sb-status-row {
    display: flex;
    gap: 6px;
    align-items: center;
    margin-top: 10px;
    flex-wrap: wrap;
}
.sb-dot {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font-size: 0.68rem;
    font-family: monospace;
    color: #666;
}
.dot-ok   { width:7px;height:7px;border-radius:50%;background:#00ff9d;display:inline-block;box-shadow:0 0 4px #00ff9d66; }
.dot-warn { width:7px;height:7px;border-radius:50%;background:#ffaa00;display:inline-block;box-shadow:0 0 4px #ffaa0066; }
.dot-err  { width:7px;height:7px;border-radius:50%;background:#ff4444;display:inline-block;box-shadow:0 0 4px #ff444466; }

/* ── Buttons ─────────────────────────────────────────────────────────────── */
.stButton > button {
    border: 1px solid rgba(0,255,157,0.5) !important;
    color: #00ff9d !important;
    background: transparent !important;
    font-family: monospace !important;
    font-size: 0.82rem !important;
    letter-spacing: 0.06em;
    border-radius: 6px;
    transition: all 0.15s ease;
}
.stButton > button:hover {
    background: rgba(0,255,157,0.08) !important;
    border-color: #00ff9d !important;
    box-shadow: 0 0 12px rgba(0,255,157,0.15) !important;
}
.stButton > button[kind="primary"] {
    background: rgba(0,255,157,0.06) !important;
    border-color: #00ff9d !important;
}
.stButton > button[kind="primary"]:hover {
    background: rgba(0,255,157,0.15) !important;
    box-shadow: 0 0 16px rgba(0,255,157,0.2) !important;
}

/* ── Download buttons ────────────────────────────────────────────────────── */
[data-testid="stDownloadButton"] > button {
    border: 1px solid rgba(0,170,255,0.45) !important;
    color: #00aaff !important;
    background: transparent !important;
    font-family: monospace !important;
    font-size: 0.82rem !important;
    border-radius: 6px;
    transition: all 0.15s ease;
}
[data-testid="stDownloadButton"] > button:hover {
    background: rgba(0,170,255,0.08) !important;
    box-shadow: 0 0 12px rgba(0,170,255,0.15) !important;
}

/* ── Tabs ────────────────────────────────────────────────────────────────── */
[data-testid="stTabs"] {
    border-bottom: 1px solid rgba(255,255,255,0.06);
    margin-bottom: 4px;
}
[data-testid="stTabs"] [role="tab"] {
    font-family: monospace !important;
    font-size: 0.82rem;
    letter-spacing: 0.05em;
    color: #4a5568 !important;
    padding: 10px 18px;
    border-radius: 0;
    transition: color 0.15s;
}
[data-testid="stTabs"] [role="tab"]:hover { color: #888 !important; }
[data-testid="stTabs"] [role="tab"][aria-selected="true"] {
    color: #00ff9d !important;
    border-bottom: 2px solid #00ff9d !important;
    font-weight: 600;
}

/* ── Native st.metric override ───────────────────────────────────────────── */
[data-testid="metric-container"] {
    background: #111827;
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 10px;
    padding: 18px 20px;
}
[data-testid="metric-container"] [data-testid="stMetricValue"] {
    font-family: monospace !important;
    color: #e2e8f0 !important;
    font-size: 1.6rem !important;
    font-weight: 700 !important;
}
[data-testid="metric-container"] [data-testid="stMetricLabel"] {
    font-family: monospace !important;
    color: #4a5568 !important;
    font-size: 0.7rem !important;
    text-transform: uppercase;
    letter-spacing: 0.1em;
}

/* ── KPI cards (custom HTML, used in Evaluations tab) ────────────────────── */
.kpi-grid { display: grid; grid-template-columns: repeat(4,1fr); gap: 14px; margin-bottom: 24px; }
.kpi-card {
    background: linear-gradient(160deg, #131c2e 0%, #0f1623 100%);
    border: 1px solid rgba(0,255,157,0.12);
    border-radius: 12px;
    padding: 20px 22px 16px;
    position: relative;
    overflow: hidden;
    transition: border-color 0.2s, box-shadow 0.2s;
}
.kpi-card:hover {
    border-color: rgba(0,255,157,0.28);
    box-shadow: 0 4px 24px rgba(0,255,157,0.06);
}
.kpi-card::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 2px;
    background: linear-gradient(90deg, #00ff9d 0%, transparent 100%);
    opacity: 0.6;
}
.kpi-value {
    font-size: 2rem;
    font-weight: 700;
    color: #00ff9d;
    font-family: monospace;
    line-height: 1;
    margin-bottom: 8px;
    letter-spacing: -0.02em;
}
.kpi-label {
    font-size: 0.68rem;
    color: #4a5568;
    font-family: monospace;
    text-transform: uppercase;
    letter-spacing: 0.12em;
}
.kpi-delta {
    font-size: 0.72rem;
    font-family: monospace;
    margin-top: 10px;
    opacity: 0.8;
}
.kpi-delta-pos { color: #00ff9d; }
.kpi-delta-neg { color: #ff4444; }

/* ── Page header ─────────────────────────────────────────────────────────── */
.page-title {
    font-size: 1.75rem;
    font-weight: 800;
    color: #00ff9d;
    font-family: monospace;
    letter-spacing: 0.02em;
    line-height: 1;
}
.page-sub {
    font-size: 0.7rem;
    color: #3a4252;
    font-family: monospace;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    margin-top: 4px;
}

/* ── Header stats strip ──────────────────────────────────────────────────── */
.stats-strip {
    display: flex;
    gap: 0;
    margin: 18px 0 20px;
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 10px;
    overflow: hidden;
    background: #0d1117;
}
.stat-item {
    flex: 1;
    padding: 14px 20px;
    border-right: 1px solid rgba(255,255,255,0.05);
    position: relative;
}
.stat-item:last-child { border-right: none; }
.stat-value {
    font-size: 1.35rem;
    font-weight: 700;
    color: #e2e8f0;
    font-family: monospace;
    line-height: 1;
}
.stat-label {
    font-size: 0.62rem;
    color: #3a4252;
    font-family: monospace;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    margin-top: 5px;
}
.stat-accent { color: #00ff9d !important; }
.stat-warn   { color: #ffaa00 !important; }
.stat-err    { color: #ff4444 !important; }

/* ── Section label ───────────────────────────────────────────────────────── */
.sec-label {
    font-family: monospace;
    font-size: 0.65rem;
    color: #00ff9d;
    text-transform: uppercase;
    letter-spacing: 0.14em;
    border-left: 2px solid #00ff9d;
    padding-left: 8px;
    margin: 22px 0 12px;
    opacity: 0.7;
    display: block;
}

/* ── Status pills ────────────────────────────────────────────────────────── */
.pill {
    display: inline-block;
    padding: 2px 9px;
    border-radius: 20px;
    font-size: 0.68rem;
    font-family: monospace;
    font-weight: 600;
    letter-spacing: 0.06em;
}
.pill-ok   { background:rgba(0,255,157,0.1);  color:#00ff9d; border:1px solid rgba(0,255,157,0.3); }
.pill-err  { background:rgba(255,68,68,0.1);  color:#ff4444; border:1px solid rgba(255,68,68,0.3); }
.pill-warn { background:rgba(255,170,0,0.1);  color:#ffaa00; border:1px solid rgba(255,170,0,0.3); }
.pill-down { background:rgba(255,68,68,0.1);  color:#ff4444; border:1px solid rgba(255,68,68,0.3); }

/* ── Health cards ────────────────────────────────────────────────────────── */
.hcard {
    background: #0f1623;
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 12px;
    padding: 18px 20px 14px;
    margin-bottom: 14px;
    transition: border-color 0.2s;
}
.hcard:hover { border-color: rgba(255,255,255,0.12); }
.hcard-healthy  { border-left: 3px solid #00ff9d !important; }
.hcard-degraded { border-left: 3px solid #ffaa00 !important; }
.hcard-down     { border-left: 3px solid #ff4444 !important; }
.hcard-name {
    font-family: monospace;
    font-size: 0.95rem;
    font-weight: 700;
    color: #e2e8f0;
    margin-bottom: 10px;
}

/* ── Dataframe ───────────────────────────────────────────────────────────── */
[data-testid="stDataFrame"] {
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 8px;
    overflow: hidden;
}

/* ── Expanders ───────────────────────────────────────────────────────────── */
[data-testid="stExpander"] {
    border: 1px solid rgba(255,255,255,0.06) !important;
    border-radius: 8px !important;
    background: #0f1623 !important;
    margin-bottom: 6px;
}
[data-testid="stExpander"] summary {
    font-family: monospace !important;
    font-size: 0.8rem !important;
    color: #666 !important;
}
[data-testid="stExpander"] summary:hover { color: #aaa !important; }

/* ── Info / alert boxes ──────────────────────────────────────────────────── */
[data-testid="stInfo"]    { background: #0f1623 !important; border-radius: 8px !important; font-family: monospace !important; }
[data-testid="stSuccess"] { background: rgba(0,255,157,0.06) !important; border-radius: 8px !important; }

/* ── Input fields ────────────────────────────────────────────────────────── */
[data-testid="stTextInput"] input {
    font-family: monospace !important;
    font-size: 0.82rem !important;
    background: #0f1623 !important;
    border-color: rgba(255,255,255,0.1) !important;
    border-radius: 6px !important;
}
[data-testid="stTextInput"] input:focus {
    border-color: rgba(0,255,157,0.4) !important;
    box-shadow: 0 0 0 1px rgba(0,255,157,0.2) !important;
}
[data-testid="stSelectbox"] div[data-baseweb] { font-family: monospace !important; }

/* ── Divider ─────────────────────────────────────────────────────────────── */
hr { border-color: rgba(255,255,255,0.05) !important; margin: 20px 0 !important; }

/* ── Toast ───────────────────────────────────────────────────────────────── */
[data-testid="stToast"] {
    background: #131c2e !important;
    border: 1px solid rgba(0,255,157,0.2) !important;
    font-family: monospace !important;
    font-size: 0.8rem !important;
    border-radius: 8px !important;
}

</style>
"""


def inject_css() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _sec(text: str) -> None:
    """Render a section label with left accent bar."""
    st.markdown(f"<span class='sec-label'>{text}</span>", unsafe_allow_html=True)


def _kpi(label: str, value: str, delta: str | None = None, positive: bool = True) -> str:
    """Return an HTML KPI card string."""
    delta_class = "kpi-delta-pos" if positive else "kpi-delta-neg"
    delta_sign  = "+" if (positive and delta and not delta.startswith("-")) else ""
    delta_html  = f"<div class='kpi-delta {delta_class}'>{delta_sign}{delta}</div>" if delta else ""
    return f"""
    <div class='kpi-card'>
        <div class='kpi-value'>{value}</div>
        <div class='kpi-label'>{label}</div>
        {delta_html}
    </div>"""


def _empty(message: str) -> None:
    """Styled empty state."""
    st.markdown(
        f"<div style='padding:32px 0;text-align:center;color:#2d3748;"
        f"font-family:monospace;font-size:0.82rem;letter-spacing:0.06em;'>"
        f"{message}</div>",
        unsafe_allow_html=True,
    )


def _apply_dark_layout(fig: go.Figure, height: int = CHART_H) -> go.Figure:
    """Apply the PulseTrace dark theme to any Plotly figure."""
    fig.update_layout(
        paper_bgcolor="#0b0f1a",
        plot_bgcolor="#0f1623",
        font={"color": "#e2e8f0", "family": "monospace", "size": 11},
        height=height,
        margin={"l": 16, "r": 10, "t": 40, "b": 16},
        xaxis={
            "gridcolor": "rgba(255,255,255,0.04)",
            "linecolor": "rgba(255,255,255,0.06)",
            "tickfont": {"color": "#4a5568", "size": 10},
        },
        yaxis={
            "gridcolor": "rgba(255,255,255,0.04)",
            "linecolor": "rgba(255,255,255,0.06)",
            "tickfont": {"color": "#6b7280", "size": 10},
        },
        legend={
            "bgcolor": "rgba(0,0,0,0)",
            "bordercolor": "rgba(255,255,255,0.06)",
            "font": {"color": "#9ca3af", "size": 10},
        },
        title_font={"color": "#9ca3af", "size": 12, "family": "monospace"},
        title_x=0,
    )
    return fig


# ─── Session State ────────────────────────────────────────────────────────────

def init_session_state() -> None:
    today = date.today()
    defaults: dict = {
        "selected_agent": "All Agents",
        "date_start":     today - timedelta(days=7),
        "date_end":       today,
        "last_refresh":   datetime.now(),
        "refresh_count":  0,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


# ─── Sidebar ──────────────────────────────────────────────────────────────────

def render_sidebar() -> tuple[str, date, date]:
    with st.sidebar:
        # Brand
        st.markdown(
            "<div class='sb-brand'>◉ PulseTrace</div>"
            "<div class='sb-tagline'>AgentOps Monitor</div>",
            unsafe_allow_html=True,
        )
        st.divider()

        # Agent status dots (quick at-a-glance)
        health_df = evals_db.get_agent_health(DB_PATH)
        if not health_df.empty:
            dots_html = "<div class='sb-status-row'>"
            for _, r in health_df.iterrows():
                dot_cls = {"Healthy": "dot-ok", "Degraded": "dot-warn", "Down": "dot-err"}.get(r["status"], "dot-warn")
                dots_html += f"<span class='sb-dot'><span class='{dot_cls}'></span>{r['name'].split('-')[0]}</span>"
            dots_html += "</div>"
            st.markdown(dots_html, unsafe_allow_html=True)

        st.divider()

        # Agent filter
        st.markdown("<div class='sb-label'>Agent</div>", unsafe_allow_html=True)
        selected_agent = st.selectbox(
            "agent_select",
            options=AGENTS,
            index=AGENTS.index(st.session_state.selected_agent),
            label_visibility="collapsed",
        )
        st.session_state.selected_agent = selected_agent

        # Date range
        st.markdown("<div class='sb-label'>Date Range</div>", unsafe_allow_html=True)
        date_range = st.date_input(
            "date_range_input",
            value=(st.session_state.date_start, st.session_state.date_end),
            max_value=date.today(),
            label_visibility="collapsed",
        )

        if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
            start_date, end_date = date_range
        else:
            start_date = date_range[0] if date_range else st.session_state.date_start
            end_date   = start_date

        st.session_state.date_start = start_date
        st.session_state.date_end   = end_date

        st.divider()

        c1, c2 = st.columns(2)
        with c1:
            if st.button("Refresh", use_container_width=True):
                st.session_state.last_refresh = datetime.now()
                st.session_state.refresh_count += 1
                st.rerun()
        with c2:
            if st.button("Re-seed", use_container_width=True):
                evals_db.seed_database(DB_PATH, force=True)
                st.session_state.last_refresh = datetime.now()
                st.rerun()

        # Footer meta
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown(
            f"<div style='font-family:monospace;font-size:0.62rem;color:#2d3748;line-height:1.8;'>"
            f"Updated {st.session_state.last_refresh.strftime('%H:%M:%S')}<br>"
            f"Refreshes: {st.session_state.refresh_count}<br>"
            f"v1.0 · MIT · Free</div>",
            unsafe_allow_html=True,
        )

    return selected_agent, start_date, end_date


# ─── Header ───────────────────────────────────────────────────────────────────

def render_header(agent: str, start_date: date, end_date: date) -> None:
    """Page title + stats strip showing key numbers at a glance."""
    st.markdown(
        "<div class='page-title'>◉ PulseTrace</div>"
        "<div class='page-sub'>AI AgentOps Monitoring & Evaluation Dashboard</div>",
        unsafe_allow_html=True,
    )

    # Pull quick stats for the strip
    traces_df   = evals_db.get_traces(agent, start_date, end_date, DB_PATH)
    health_df   = evals_db.get_agent_health(DB_PATH)
    evals_df    = evals_db.get_evaluations(agent, start_date, end_date, DB_PATH)

    total_runs   = len(traces_df)
    error_count  = (traces_df["status"] == "ERROR").sum() if not traces_df.empty else 0
    error_rate   = (error_count / total_runs * 100) if total_runs else 0
    avg_latency  = traces_df["latency_ms"].mean() if not traces_df.empty else 0
    total_cost   = traces_df["cost_zar"].sum() if not traces_df.empty else 0
    healthy_cnt  = (health_df["status"] == "Healthy").sum() if not health_df.empty else 0
    total_agents = len(health_df)

    err_cls  = "stat-err"  if error_rate > 5  else ("stat-warn" if error_rate > 0 else "stat-accent")
    hlth_cls = "stat-accent" if healthy_cnt == total_agents else ("stat-warn" if healthy_cnt > 0 else "stat-err")

    st.markdown(
        f"""
        <div class='stats-strip'>
          <div class='stat-item'>
            <div class='stat-value stat-accent'>{total_runs:,}</div>
            <div class='stat-label'>Total Traces</div>
          </div>
          <div class='stat-item'>
            <div class='stat-value {hlth_cls}'>{healthy_cnt}/{total_agents}</div>
            <div class='stat-label'>Agents Healthy</div>
          </div>
          <div class='stat-item'>
            <div class='stat-value {err_cls}'>{error_rate:.1f}%</div>
            <div class='stat-label'>Error Rate</div>
          </div>
          <div class='stat-item'>
            <div class='stat-value'>{avg_latency:.0f} ms</div>
            <div class='stat-label'>Avg Latency</div>
          </div>
          <div class='stat-item'>
            <div class='stat-value'>R{total_cost:.3f}</div>
            <div class='stat-label'>Total Cost</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ─── Tab 1: Live Traces ───────────────────────────────────────────────────────

def render_traces_tab(agent: str, start_date: date, end_date: date) -> None:
    btn_col, _ = st.columns([1, 3])
    with btn_col:
        if st.button("Simulate Agent Run", type="primary", use_container_width=True):
            sim_agent = agent if agent != "All Agents" else random.choice(otel_tracer.AGENTS)
            run = otel_tracer.simulate_agent_run(sim_agent)
            evals_db.add_trace(run, DB_PATH)
            st.toast(
                f"Trace {run['trace_id'][:12]}... — {run['span_count']} spans · R{run['total_cost_zar']:.4f}"
            )
            st.rerun()

    traces_df = evals_db.get_traces(agent, start_date, end_date, DB_PATH)

    if traces_df.empty:
        _empty("No traces found for the selected filters. Click Simulate Agent Run to generate data.")
        return

    # ── Waterfall chart ───────────────────────────────────────────────────────
    _sec("Trace Waterfall — Most Recent Run")
    latest_id = traces_df.iloc[0]["trace_id"]
    spans_df  = evals_db.get_spans_for_trace(latest_id, DB_PATH)

    if not spans_df.empty:
        fig = px.timeline(
            spans_df,
            x_start="start_time",
            x_end="end_time",
            y="span_name",
            color="status",
            color_discrete_map={"OK": "#00ff9d", "ERROR": "#ff4444", "UNSET": "#4a5568"},
            hover_data={"span_id": True, "latency_ms": ":.1f",
                        "tokens_input": True, "tokens_output": True, "cost_zar": ":.6f"},
            title=f"trace_id: {latest_id[:24]}...  ·  {len(spans_df)} spans",
        )
        _apply_dark_layout(fig, height=240)
        fig.update_yaxes(autorange="reversed")
        st.plotly_chart(fig, use_container_width=True, theme=None)

    # ── Trace table ───────────────────────────────────────────────────────────
    _sec("All Traces")
    st.dataframe(
        traces_df[["trace_id", "agent", "start_time", "latency_ms",
                   "tokens_input", "tokens_output", "cost_zar", "status"]],
        column_config={
            "trace_id":      st.column_config.TextColumn("Trace ID", width="medium"),
            "agent":         st.column_config.TextColumn("Agent", width="small"),
            "start_time":    st.column_config.DatetimeColumn("Time", format="MMM D, HH:mm:ss", width="medium"),
            "latency_ms":    st.column_config.NumberColumn("Latency", format="%.0f ms", width="small"),
            "tokens_input":  st.column_config.NumberColumn("In Tokens", format="%d", width="small"),
            "tokens_output": st.column_config.NumberColumn("Out Tokens", format="%d", width="small"),
            "cost_zar":      st.column_config.NumberColumn("Cost (R)", format="R%.4f", width="small"),
            "status":        st.column_config.TextColumn("Status", width="small"),
        },
        hide_index=True,
        use_container_width=True,
        height=340,
    )

    # ── Span details ──────────────────────────────────────────────────────────
    _sec("Span Details")
    for _, row in traces_df.head(6).iterrows():
        pill_cls  = "pill-ok" if row["status"] == "OK" else "pill-err"
        label_html = (
            f"<span class='pill {pill_cls}'>{row['status']}</span>"
            f"&nbsp;&nbsp;<code style='color:#6b7280;font-size:0.78rem;'>{row['trace_id'][:20]}...</code>"
            f"&nbsp;·&nbsp;<span style='color:#9ca3af'>{row['agent']}</span>"
            f"&nbsp;·&nbsp;<span style='color:#6b7280'>{row['latency_ms']:.0f} ms</span>"
            f"&nbsp;·&nbsp;<span style='color:#4a5568'>R{row['cost_zar']:.4f}</span>"
        )
        with st.expander(label_html):
            detail = evals_db.get_spans_for_trace(row["trace_id"], DB_PATH)
            if not detail.empty:
                st.dataframe(
                    detail[["span_name", "latency_ms", "status", "tokens_input", "tokens_output", "cost_zar", "tool_name"]],
                    column_config={
                        "span_name":     st.column_config.TextColumn("Span"),
                        "latency_ms":    st.column_config.NumberColumn("Latency", format="%.0f ms"),
                        "status":        st.column_config.TextColumn("Status", width="small"),
                        "tokens_input":  st.column_config.NumberColumn("In", format="%d", width="small"),
                        "tokens_output": st.column_config.NumberColumn("Out", format="%d", width="small"),
                        "cost_zar":      st.column_config.NumberColumn("Cost (R)", format="R%.5f"),
                        "tool_name":     st.column_config.TextColumn("Tool"),
                    },
                    hide_index=True,
                    use_container_width=True,
                )


# ─── Tab 2: Evaluations ───────────────────────────────────────────────────────

def render_evals_tab(agent: str, start_date: date, end_date: date) -> None:
    btn_col, _ = st.columns([1, 3])
    with btn_col:
        if st.button("Run Fresh Eval", type="primary", use_container_width=True):
            evals_db.seed_database(DB_PATH, force=True)
            st.session_state.last_refresh = datetime.now()
            st.rerun()

    evals_df = evals_db.get_evaluations(agent, start_date, end_date, DB_PATH)

    if evals_df.empty:
        _empty("No evaluation data found for the selected filters.")
        return

    # ── Custom KPI cards ──────────────────────────────────────────────────────
    _sec("Key Metrics")

    avg_latency    = evals_df["latency_ms"].mean()
    pass_rate_pct  = evals_df["pass_rate"].mean() * 100
    total_cost_zar = evals_df["cost_zar"].sum()
    avg_tps        = evals_df["tokens_per_second"].mean()

    d_lat  = random.uniform(-80, 80)
    d_pass = random.uniform(-2.5, 2.5)
    d_cost = random.uniform(-0.05, 0.05)
    d_tps  = random.randint(-25, 25)

    cards_html = (
        "<div class='kpi-grid'>"
        + _kpi("Avg Latency",  f"{avg_latency:.0f} ms", f"{d_lat:.0f} ms",   d_lat  >= 0)
        + _kpi("Pass Rate",    f"{pass_rate_pct:.1f}%", f"{d_pass:.1f}%",    d_pass >= 0)
        + _kpi("Total Cost",   f"R{total_cost_zar:.3f}", f"R{d_cost:.3f}",   d_cost <= 0)
        + _kpi("Token/s",      f"{avg_tps:.0f}",         f"{d_tps}",         d_tps  >= 0)
        + "</div>"
    )
    st.markdown(cards_html, unsafe_allow_html=True)

    # ── 2×2 chart grid ────────────────────────────────────────────────────────
    _sec("Trends")
    col_left, col_right = st.columns(2)
    color_arg = "agent" if agent == "All Agents" else None

    with col_left:
        fig1 = px.line(
            evals_df.sort_values("eval_date"),
            x="eval_date", y="latency_ms", color=color_arg,
            markers=True, title="Latency (ms)",
            color_discrete_sequence=PALETTE,
        )
        _apply_dark_layout(fig1)
        st.plotly_chart(fig1, use_container_width=True, theme=None)

        fig3 = px.area(
            evals_df.sort_values("eval_date"),
            x="eval_date", y="cost_zar", color=color_arg,
            title="Daily Cost (R)", color_discrete_sequence=PALETTE,
        )
        _apply_dark_layout(fig3)
        st.plotly_chart(fig3, use_container_width=True, theme=None)

    with col_right:
        avg_pass = evals_df["pass_rate"].mean()
        fig2 = go.Figure(data=[go.Pie(
            labels=["Pass", "Fail"],
            values=[avg_pass, max(0.0, 1.0 - avg_pass)],
            hole=0.65,
            marker_colors=["#00ff9d", "#ff4444"],
            textfont={"color": "#e2e8f0", "family": "monospace"},
            hovertemplate="%{label}: %{percent}<extra></extra>",
        )])
        fig2.update_layout(
            title="Pass / Fail",
            paper_bgcolor="#0b0f1a", plot_bgcolor="#0f1623",
            font={"color": "#e2e8f0", "family": "monospace", "size": 11},
            height=CHART_H,
            margin={"l": 16, "r": 16, "t": 40, "b": 16},
            legend={"bgcolor": "rgba(0,0,0,0)", "font": {"color": "#9ca3af"}},
            title_font={"color": "#9ca3af", "size": 12},
            annotations=[{
                "text": f"{avg_pass * 100:.1f}%",
                "x": 0.5, "y": 0.5,
                "font_size": 24, "font_color": "#00ff9d",
                "font_family": "monospace", "showarrow": False,
            }],
        )
        st.plotly_chart(fig2, use_container_width=True, theme=None)

        token_df = (
            evals_df.groupby("agent")["tokens_per_second"]
            .mean().reset_index()
            .sort_values("tokens_per_second", ascending=False)
        )
        fig4 = px.bar(
            token_df, x="agent", y="tokens_per_second",
            title="Token Throughput (tok/s)", color="agent",
            color_discrete_sequence=PALETTE,
        )
        _apply_dark_layout(fig4)
        fig4.update_layout(showlegend=False)
        st.plotly_chart(fig4, use_container_width=True, theme=None)


# ─── Tab 3: Agent Health ──────────────────────────────────────────────────────

def render_health_tab(agent: str, start_date: date, end_date: date) -> None:
    # Auto-refresh countdown (cosmetic)
    components.html(
        """
        <div style="font-family:monospace;font-size:0.65rem;color:#2d3748;
                    letter-spacing:0.1em;padding:2px 0;">
            NEXT REFRESH IN <span id="t" style="color:#00ff9d;font-weight:700;">30</span>s
        </div>
        <script>
            var s=30;
            setInterval(function(){s--;if(s<=0)s=30;
            var e=document.getElementById('t');if(e)e.textContent=s;},1000);
        </script>
        """,
        height=24,
    )

    health_df = evals_db.get_agent_health(DB_PATH)
    if health_df.empty:
        _empty("No agent health data available.")
        return

    if agent != "All Agents":
        health_df = health_df[health_df["name"] == agent]

    _sec("Agent Status")
    cols = st.columns(3)

    for idx, (_, row) in enumerate(health_df.iterrows()):
        status    = row["status"]
        css_class = status.lower()
        badge_color = {"Healthy": "green", "Degraded": "orange", "Down": "red"}.get(status, "gray")

        with cols[idx % 3]:
            st.markdown(
                f"<div class='hcard hcard-{css_class}'>"
                f"<div class='hcard-name'>{row['name']}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )
            st.badge(status, color=badge_color)

            if row["error_rate"] > 5.0:
                st.badge(f"High Errors: {row['error_rate']:.1f}%", color="red")
            if row["avg_latency"] > 2000:
                st.badge(f"High Latency: {row['avg_latency']:.0f} ms", color="orange")
            if status == "Down":
                st.badge("OFFLINE", color="red")

            m1, m2 = st.columns(2)
            with m1:
                st.metric("Uptime",     f"{row['uptime_pct']:.1f}%")
                st.metric("Error Rate", f"{row['error_rate']:.1f}%")
            with m2:
                st.metric("Avg Latency", f"{row['avg_latency']:.0f} ms")
                st.metric("Total Runs",  f"{row['total_runs']:,}")

            last_ping = row["last_ping"] or "—"
            if last_ping and last_ping != "—":
                try:
                    last_ping = datetime.fromisoformat(last_ping).strftime("%H:%M:%S UTC")
                except ValueError:
                    pass
            st.caption(f"Last ping: {last_ping}")
            st.markdown("<br>", unsafe_allow_html=True)

    # ── Uptime overview chart ─────────────────────────────────────────────────
    _sec("Uptime Overview")
    if len(health_df) > 1 or agent == "All Agents":
        fig = px.bar(
            health_df.sort_values("uptime_pct", ascending=True),
            x="uptime_pct", y="name", orientation="h",
            color="status",
            color_discrete_map={"Healthy": "#00ff9d", "Degraded": "#ffaa00", "Down": "#ff4444"},
            title="Uptime %", range_x=[0, 100], text="uptime_pct",
        )
        fig.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
        _apply_dark_layout(fig, height=220)
        fig.update_layout(showlegend=True, yaxis_title="")
        st.plotly_chart(fig, use_container_width=True, theme=None)


# ─── Tab 4: Logs & Export ─────────────────────────────────────────────────────

def render_logs_tab(agent: str, start_date: date, end_date: date) -> None:
    # ── Filters ───────────────────────────────────────────────────────────────
    fc1, fc2, fc3 = st.columns([2, 3, 1])
    with fc1:
        selected_levels = st.multiselect(
            "Log Level",
            options=["INFO", "WARN", "ERROR"],
            default=["INFO", "WARN", "ERROR"],
            key="log_level_filter",
        )
    with fc2:
        search_term = st.text_input(
            "Search",
            placeholder="filter by keyword...",
            key="log_search",
        )
    with fc3:
        st.markdown("<br>", unsafe_allow_html=True)
        st.button("Apply", key="log_apply", use_container_width=True)

    logs_df = evals_db.get_logs(
        level=selected_levels or None,
        search=search_term or None,
        agent=agent,
        db_path=DB_PATH,
    )

    # ── Count metrics ─────────────────────────────────────────────────────────
    if not logs_df.empty:
        n_total = len(logs_df)
        n_info  = (logs_df["level"] == "INFO").sum()
        n_warn  = (logs_df["level"] == "WARN").sum()
        n_err   = (logs_df["level"] == "ERROR").sum()

        lc1, lc2, lc3, lc4 = st.columns(4)
        with lc1: st.metric("Total",  f"{n_total:,}")
        with lc2: st.metric("INFO",   f"{n_info:,}")
        with lc3: st.metric("WARN",   f"{n_warn:,}")
        with lc4: st.metric("ERROR",  f"{n_err:,}")

        st.markdown("")

        def _style_level(val: str) -> str:
            return {
                "ERROR": "color:#ff4444;font-weight:600;",
                "WARN":  "color:#ffaa00;font-weight:600;",
                "INFO":  "color:#00ff9d;",
            }.get(val, "")

        styled = logs_df.style.map(_style_level, subset=["level"])
        st.dataframe(
            styled,
            column_config={
                "agent":     st.column_config.TextColumn("Agent", width="small"),
                "level":     st.column_config.TextColumn("Level", width="small"),
                "message":   st.column_config.TextColumn("Message", width="large"),
                "timestamp": st.column_config.DatetimeColumn("Time", format="MMM D HH:mm:ss", width="medium"),
                "trace_id":  st.column_config.TextColumn("Trace ID", width="medium"),
            },
            hide_index=True,
            use_container_width=True,
            height=400,
        )
    else:
        _empty("No logs match the current filters.")

    # ── Export ────────────────────────────────────────────────────────────────
    st.divider()
    _sec("Export Data")

    exp1, exp2, _ = st.columns([1, 1, 3])
    with exp1:
        st.download_button(
            "Export CSV",
            data=evals_db.export_csv(agent, start_date, end_date, DB_PATH),
            file_name=f"pulsetrace_{agent.replace(' ', '_')}_{date.today()}.csv",
            mime="text/csv",
            use_container_width=True,
            help="Download all traces in the current filter as CSV",
        )
    with exp2:
        st.download_button(
            "Export JSON",
            data=evals_db.export_json(agent, start_date, end_date, DB_PATH),
            file_name=f"pulsetrace_{agent.replace(' ', '_')}_{date.today()}.json",
            mime="application/json",
            use_container_width=True,
            help="Download all traces in the current filter as JSON",
        )


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    inject_css()
    init_session_state()

    evals_db.init_db(DB_PATH)
    evals_db.seed_database(DB_PATH, force=False)

    agent, start_date, end_date = render_sidebar()

    render_header(agent, start_date, end_date)

    tab1, tab2, tab3, tab4 = st.tabs([
        "Live Traces",
        "Evaluations",
        "Agent Health",
        "Logs & Export",
    ])

    with tab1: render_traces_tab(agent, start_date, end_date)
    with tab2: render_evals_tab(agent, start_date, end_date)
    with tab3: render_health_tab(agent, start_date, end_date)
    with tab4: render_logs_tab(agent, start_date, end_date)


if __name__ == "__main__":
    main()
