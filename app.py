"""Streamlit UI for the Cloud Architecture Designer."""
from __future__ import annotations

import json
from pathlib import Path

import plotly.express as px
import streamlit as st

from pipeline import diagram, explainer, export, extractor, orchestrator, validator, vision_extractor
from rag import retriever

st.set_page_config(
    page_title="Cloud Architecture Designer",
    page_icon="☁️",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Google Font + Design System CSS — AI-Native + Glassmorphism
# ---------------------------------------------------------------------------
st.markdown(
    """
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">

    <style>
      /* ── Design tokens ─────────────────────────────────────────── */
      :root {
        --bg:        #0f172a;
        --surface:   rgba(255,255,255,0.06);
        --surface-hover: rgba(255,255,255,0.10);
        --border:    rgba(255,255,255,0.12);
        --primary:   #7C3AED;
        --primary-light: #a78bfa;
        --accent:    #0891B2;
        --text:      #e2e8f0;
        --muted:     #94a3b8;
        --success:   #10b981;
        --danger:    #f43f5e;
        --warn:      #f59e0b;
        --radius:    14px;
        --transition: 200ms ease;
      }

      /* ── Base ──────────────────────────────────────────────────── */
      html, body, .stApp {
        font-family: 'Inter', sans-serif !important;
        background: var(--bg) !important;
        color: var(--text) !important;
      }

      /* ── Scrollbar ─────────────────────────────────────────────── */
      ::-webkit-scrollbar { width: 6px; height: 6px; }
      ::-webkit-scrollbar-track { background: transparent; }
      ::-webkit-scrollbar-thumb { background: rgba(124,58,237,0.4); border-radius: 99px; }

      /* ── Glass card ────────────────────────────────────────────── */
      .glass-card {
        background: var(--surface);
        backdrop-filter: blur(12px);
        -webkit-backdrop-filter: blur(12px);
        border: 1px solid var(--border);
        border-radius: var(--radius);
        padding: 18px 20px;
        transition: background var(--transition), box-shadow var(--transition), transform var(--transition);
      }
      .glass-card:hover {
        background: var(--surface-hover);
        box-shadow: 0 0 0 1px rgba(124,58,237,0.3), 0 8px 32px rgba(124,58,237,0.15);
        transform: translateY(-2px);
      }

      /* ── Hero banner ───────────────────────────────────────────── */
      .hero {
        background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 45%, #0c4a6e 100%);
        border: 1px solid var(--border);
        border-radius: 16px;
        padding: 32px 36px 28px;
        margin-bottom: 20px;
        position: relative;
        overflow: hidden;
      }
      .hero::before {
        content: '';
        position: absolute;
        inset: 0;
        background-image:
          linear-gradient(rgba(255,255,255,0.03) 1px, transparent 1px),
          linear-gradient(90deg, rgba(255,255,255,0.03) 1px, transparent 1px);
        background-size: 40px 40px;
        pointer-events: none;
      }
      .hero-title {
        font-size: 2.1rem;
        font-weight: 700;
        margin: 0 0 8px 0;
        background: linear-gradient(90deg, #a78bfa, #38bdf8);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
      }
      .hero-sub {
        color: #93c5fd;
        margin: 0 0 16px 0;
        font-size: 0.97rem;
        line-height: 1.6;
      }
      .hero-pills {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin-top: 4px;
      }
      .hero-pill {
        background: rgba(124,58,237,0.18);
        border: 1px solid rgba(124,58,237,0.35);
        color: #c4b5fd;
        padding: 3px 11px;
        border-radius: 999px;
        font-size: 0.75rem;
        font-weight: 500;
        letter-spacing: 0.01em;
      }

      /* ── Badges ────────────────────────────────────────────────── */
      .badge {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 999px;
        font-size: 0.76rem;
        font-weight: 600;
        margin: 2px 4px 2px 0;
        letter-spacing: 0.03em;
      }
      .badge-hipaa  { background: rgba(239,68,68,0.15);  color: #fca5a5; border: 1px solid rgba(239,68,68,0.35); }
      .badge-pci    { background: rgba(245,158,11,0.15); color: #fcd34d; border: 1px solid rgba(245,158,11,0.35); }
      .badge-soc2   { background: rgba(14,165,233,0.15); color: #7dd3fc; border: 1px solid rgba(14,165,233,0.35); }
      .badge-ha     { background: rgba(124,58,237,0.15); color: #c4b5fd; border: 1px solid rgba(124,58,237,0.35); }
      .badge-region { background: rgba(8,145,178,0.15);  color: #67e8f9; border: 1px solid rgba(8,145,178,0.35); }
      .badge-valid  { background: rgba(16,185,129,0.15); color: #6ee7b7; border: 1px solid rgba(16,185,129,0.35); }
      .badge-fail   { background: rgba(244,63,94,0.15);  color: #fda4af; border: 1px solid rgba(244,63,94,0.35); }
      .badge-warn   { background: rgba(245,158,11,0.15); color: #fcd34d; border: 1px solid rgba(245,158,11,0.35); }
      .badge-muted  { background: rgba(148,163,184,0.12); color: #94a3b8; border: 1px solid rgba(148,163,184,0.2); }

      /* ── Preset cards ──────────────────────────────────────────── */
      .preset-card {
        background: var(--surface);
        backdrop-filter: blur(10px);
        -webkit-backdrop-filter: blur(10px);
        border: 1px solid var(--border);
        border-radius: var(--radius);
        padding: 16px 18px;
        height: 100%;
        transition: background var(--transition), box-shadow var(--transition), transform var(--transition);
        cursor: default;
      }
      .preset-card:hover {
        background: var(--surface-hover);
        box-shadow: 0 0 0 1px rgba(124,58,237,0.4), 0 8px 24px rgba(124,58,237,0.18);
        transform: translateY(-2px);
      }
      .preset-card-icon { font-size: 1.6rem; margin-bottom: 8px; display: block; }
      .preset-card h4   { margin: 0 0 5px 0; font-size: 0.95rem; color: #f1f5f9; font-weight: 600; }
      .preset-card p    { margin: 0; font-size: 0.82rem; color: var(--muted); line-height: 1.5; }

      /* ── Sidebar ───────────────────────────────────────────────── */
      [data-testid="stSidebar"] {
        background: #111827 !important;
        border-right: 1px solid var(--border) !important;
      }
      [data-testid="stSidebar"]::before {
        content: '';
        display: block;
        height: 3px;
        background: linear-gradient(90deg, var(--primary), var(--accent));
        margin-bottom: 4px;
      }
      .sidebar-section-label {
        text-transform: uppercase;
        letter-spacing: 0.08em;
        font-size: 0.68rem;
        font-weight: 600;
        color: var(--muted);
        margin: 16px 0 6px 0;
      }
      .sidebar-divider {
        border: none;
        border-top: 1px solid var(--border);
        margin: 12px 0;
      }

      /* ── Primary button — purple → cyan gradient ────────────────── */
      .stButton > button[kind="primary"],
      .stButton > button[data-testid="baseButton-primary"] {
        background: linear-gradient(90deg, var(--primary) 0%, var(--accent) 100%) !important;
        color: #fff !important;
        border: none !important;
        font-weight: 600 !important;
        letter-spacing: 0.02em !important;
        border-radius: 10px !important;
        transition: box-shadow var(--transition), transform var(--transition) !important;
      }
      .stButton > button[kind="primary"]:hover,
      .stButton > button[data-testid="baseButton-primary"]:hover {
        box-shadow: 0 0 20px rgba(124,58,237,0.55) !important;
        transform: translateY(-1px) !important;
      }

      /* ── Secondary buttons ─────────────────────────────────────── */
      .stButton > button:not([kind="primary"]) {
        background: var(--surface) !important;
        color: var(--primary-light) !important;
        border: 1px solid rgba(124,58,237,0.35) !important;
        border-radius: 10px !important;
        font-weight: 500 !important;
        transition: background var(--transition), box-shadow var(--transition) !important;
      }
      .stButton > button:not([kind="primary"]):hover {
        background: rgba(124,58,237,0.12) !important;
        box-shadow: 0 0 10px rgba(124,58,237,0.2) !important;
      }

      /* ── Tabs ──────────────────────────────────────────────────── */
      [data-testid="stTabs"] [data-baseweb="tab-list"] {
        background: transparent !important;
        border-bottom: 1px solid var(--border) !important;
        gap: 4px;
      }
      [data-testid="stTabs"] [data-baseweb="tab"] {
        background: transparent !important;
        color: var(--muted) !important;
        border: none !important;
        border-bottom: 2px solid transparent !important;
        border-radius: 0 !important;
        padding: 8px 14px !important;
        font-size: 0.87rem !important;
        font-weight: 500 !important;
        transition: color var(--transition), border-color var(--transition) !important;
      }
      [data-testid="stTabs"] [data-baseweb="tab"]:hover {
        color: var(--text) !important;
      }
      [data-testid="stTabs"] [aria-selected="true"][data-baseweb="tab"] {
        color: var(--primary-light) !important;
        border-bottom-color: var(--primary) !important;
        background: transparent !important;
      }

      /* ── Metrics ───────────────────────────────────────────────── */
      [data-testid="metric-container"] {
        background: var(--surface) !important;
        border: 1px solid var(--border) !important;
        border-radius: 12px !important;
        padding: 14px 18px !important;
      }
      [data-testid="stMetricValue"] { color: #f1f5f9 !important; font-weight: 700 !important; }
      [data-testid="stMetricLabel"] { color: var(--muted) !important; font-size: 0.78rem !important; text-transform: uppercase; letter-spacing: 0.05em; }
      [data-testid="stMetricDelta"]  { font-size: 0.82rem !important; }

      /* ── Code blocks ───────────────────────────────────────────── */
      .stCodeBlock pre, pre {
        background: #0d1117 !important;
        border: 1px solid var(--border) !important;
        border-left: 3px solid var(--primary) !important;
        border-radius: 10px !important;
        font-size: 0.83rem !important;
      }

      /* ── Inputs ────────────────────────────────────────────────── */
      textarea, input[type="text"], .stTextArea textarea {
        background: #1e293b !important;
        color: var(--text) !important;
        border: 1px solid var(--border) !important;
        border-radius: 10px !important;
        font-family: 'Inter', sans-serif !important;
        transition: border-color var(--transition), box-shadow var(--transition) !important;
      }
      textarea:focus, input[type="text"]:focus, .stTextArea textarea:focus {
        border-color: rgba(124,58,237,0.6) !important;
        box-shadow: 0 0 0 3px rgba(124,58,237,0.15) !important;
        outline: none !important;
      }

      /* ── Select box ────────────────────────────────────────────── */
      [data-baseweb="select"] > div {
        background: #1e293b !important;
        border-color: var(--border) !important;
        border-radius: 10px !important;
        color: var(--text) !important;
      }

      /* ── Alerts ────────────────────────────────────────────────── */
      [data-testid="stAlert"] {
        border-radius: 10px !important;
      }
      [data-testid="stAlert"][kind="success"] {
        background: rgba(16,185,129,0.1) !important;
        border-color: rgba(16,185,129,0.3) !important;
      }
      [data-testid="stAlert"][kind="error"] {
        background: rgba(244,63,94,0.1) !important;
        border-color: rgba(244,63,94,0.3) !important;
      }
      [data-testid="stAlert"][kind="warning"] {
        background: rgba(245,158,11,0.1) !important;
        border-color: rgba(245,158,11,0.3) !important;
      }

      /* ── Expanders ─────────────────────────────────────────────── */
      [data-testid="stExpander"] {
        background: var(--surface) !important;
        border: 1px solid var(--border) !important;
        border-radius: 12px !important;
      }
      [data-testid="stExpander"] summary {
        color: var(--text) !important;
        font-weight: 500 !important;
      }

      /* ── Dataframes ────────────────────────────────────────────── */
      [data-testid="stDataFrame"] {
        border: 1px solid var(--border) !important;
        border-radius: 10px !important;
        overflow: hidden;
      }

      /* ── Diff colours (same class names, dark-adapted) ─────────── */
      .diff-added    { background: rgba(16,185,129,0.15); padding: 2px 6px; border-radius: 4px; color: #6ee7b7; }
      .diff-modified { background: rgba(245,158,11,0.15); padding: 2px 6px; border-radius: 4px; color: #fcd34d; }
      .diff-same     { color: #475569; }

      /* ── Reduced motion ────────────────────────────────────────── */
      @media (prefers-reduced-motion: reduce) {
        *, *::before, *::after {
          animation-duration: 0.01ms !important;
          transition-duration: 0.01ms !important;
        }
      }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Hero banner
# ---------------------------------------------------------------------------
st.markdown(
    """
    <div class="hero">
      <div class="hero-title">☁ Cloud Architecture Designer</div>
      <p class="hero-sub">
        Natural language → AWS diagram + Terraform + cost estimate + rationale.<br>
        Template-driven, deterministic HCL — LLM only for extraction, repair &amp; explanation.
      </p>
      <div class="hero-pills">
        <span class="hero-pill">4 workload templates</span>
        <span class="hero-pill">3 compliance patches</span>
        <span class="hero-pill">deterministic HCL</span>
        <span class="hero-pill">LLM-repair only on failure</span>
        <span class="hero-pill">RAG-cited rationale</span>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Example prompt gallery — click a card to load it
# ---------------------------------------------------------------------------
_DEFAULT_FLAGS = {"hipaa": False, "pci": False, "soc2": False, "ha": False, "multi_region": False}


def _flags(**overrides) -> dict:
    out = dict(_DEFAULT_FLAGS)
    out.update(overrides)
    return out


PRESETS = [
    {
        "icon": "🏥",
        "title": "HIPAA telemedicine API",
        "blurb": "Regulated healthcare workload, multi-AZ, encryption at rest.",
        "prompt": "HIPAA telemedicine API serving ~10k patients/day, multi-AZ high availability, encrypted PHI storage",
        "template": "web_api",
        "flags": _flags(hipaa=True, ha=True),
    },
    {
        "icon": "💳",
        "title": "PCI payments API",
        "blurb": "Card data, WAF-ready, threat detection, encrypted RDS.",
        "prompt": "PCI-DSS payment processing API with tokenization, threat detection, and encrypted card-data storage",
        "template": "web_api",
        "flags": _flags(pci=True, ha=True),
    },
    {
        "icon": "🔒",
        "title": "SOC2 B2B SaaS",
        "blurb": "Audit logging, strict password policy, multi-region.",
        "prompt": "SOC2-ready B2B SaaS API with audit logging, strict password policies, and multi-region failover",
        "template": "web_api",
        "flags": _flags(soc2=True, ha=True, multi_region=True),
    },
    {
        "icon": "🔄",
        "title": "Nightly ETL pipeline",
        "blurb": "Batch data ingest into an S3 data lake.",
        "prompt": "Nightly ETL pipeline pulling from Postgres into an S3 data lake, ~50GB/day, schema inference with Glue",
        "template": "data_pipeline",
        "flags": _flags(),
    },
    {
        "icon": "🤖",
        "title": "ML training workload",
        "blurb": "GPU training + model artifact storage.",
        "prompt": "ML training pipeline for a computer vision model, weekly retrain on ~2TB images, needs GPU instances and model registry",
        "template": "ml_training",
        "flags": _flags(),
    },
    {
        "icon": "🌐",
        "title": "Marketing static site",
        "blurb": "Low-cost CDN-fronted landing page.",
        "prompt": "Marketing static site, global CDN, low traffic (~1M monthly views), custom domain with HTTPS",
        "template": "static_site",
        "flags": _flags(),
    },
]

# session state defaults
if "prompt_text" not in st.session_state:
    st.session_state.prompt_text = PRESETS[0]["prompt"]
    st.session_state.template_choice = PRESETS[0]["template"]
    for k, v in PRESETS[0]["flags"].items():
        st.session_state[k] = v
    st.session_state.compare_mode = False


def _apply_preset(idx: int) -> None:
    p = PRESETS[idx]
    st.session_state.prompt_text = p["prompt"]
    st.session_state.template_choice = p["template"]
    for k, v in p["flags"].items():
        st.session_state[k] = v


# ---------------------------------------------------------------------------
# Eval scoreboard — loads eval/results/ if present
# ---------------------------------------------------------------------------
_EVAL_DIR = Path("eval/results")


def _render_eval_scoreboard() -> None:
    summary_path = _EVAL_DIR / "summary.json"
    per_case_path = _EVAL_DIR / "per_case.json"
    if not summary_path.exists() or not per_case_path.exists():
        st.caption(
            "No eval results yet. Run `python -m eval.run_eval` to populate "
            "this scoreboard (15 reference prompts)."
        )
        return
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    cases = json.loads(per_case_path.read_text(encoding="utf-8"))

    pass_n = summary.get("pass_count", 0)
    fail_n = summary.get("fail_count", 0)
    total = summary.get("cases", pass_n + fail_n)
    rate = summary.get("pass_rate", 0.0)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Cases", total)
    c2.metric("Pass", pass_n)
    c3.metric("Fail", fail_n)
    c4.metric("Pass rate", f"{rate*100:.0f}%")
    c5.metric("tfsec HIGH (sum)", summary.get("total_tfsec_high", 0))

    table_rows = []
    for r in cases:
        icon = "✅" if r.get("pass") else "❌"
        table_rows.append(
            {
                "": icon,
                "id": r["id"],
                "workload": "✓" if r["workload_match"] else "✗",
                "recall": r["component_recall"],
                "tf_valid": "✓" if r["tf_valid"] else "✗",
                "tfsec_high": r.get("tfsec_high", 0),
                "cost_ok": "✓" if r["cost_within_range"] else "✗",
                "compliance": "✓" if r.get("compliance_match", True) else "✗",
                "monthly_$": f"${r['monthly_cost']:.0f}",
            }
        )
    st.dataframe(table_rows, use_container_width=True, hide_index=True)


with st.expander("📊  Eval scoreboard (15 reference prompts)", expanded=False):
    _render_eval_scoreboard()

with st.expander("📋  Try a preset prompt", expanded=True):
    rows = [PRESETS[:3], PRESETS[3:]]
    for row in rows:
        cols = st.columns(3)
        for col, preset in zip(cols, row):
            with col:
                st.markdown(
                    f"""<div class="preset-card">
                          <span class="preset-card-icon">{preset['icon']}</span>
                          <h4>{preset['title']}</h4>
                          <p>{preset['blurb']}</p>
                        </div>""",
                    unsafe_allow_html=True,
                )
                st.button(
                    "Use this prompt",
                    key=f"preset_{preset['title']}",
                    on_click=_apply_preset,
                    args=(PRESETS.index(preset),),
                    use_container_width=True,
                )

# ---------------------------------------------------------------------------
# Sidebar — input form
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown('<div class="sidebar-section-label">Workload</div>', unsafe_allow_html=True)
    prompt = st.text_area("Describe your workload", key="prompt_text", height=140, label_visibility="collapsed",
                          placeholder="e.g. HIPAA telemedicine API, 10k patients/day, multi-AZ…")

    st.markdown('<hr class="sidebar-divider">', unsafe_allow_html=True)
    st.markdown('<div class="sidebar-section-label">Template</div>', unsafe_allow_html=True)
    st.selectbox(
        "Template",
        ["auto", "web_api", "data_pipeline", "ml_training", "static_site"],
        key="template_choice",
        label_visibility="collapsed",
    )

    st.markdown('<hr class="sidebar-divider">', unsafe_allow_html=True)
    st.markdown('<div class="sidebar-section-label">Compliance</div>', unsafe_allow_html=True)
    st.checkbox("HIPAA", key="hipaa")
    st.checkbox("PCI-DSS", key="pci")
    st.checkbox("SOC2", key="soc2")

    st.markdown('<hr class="sidebar-divider">', unsafe_allow_html=True)
    st.markdown('<div class="sidebar-section-label">Availability</div>', unsafe_allow_html=True)
    st.checkbox("High availability", key="ha")
    st.checkbox("Multi-region", key="multi_region")

    st.markdown('<hr class="sidebar-divider">', unsafe_allow_html=True)
    st.markdown('<div class="sidebar-section-label">Compare Mode</div>', unsafe_allow_html=True)
    st.checkbox(
        "Run with ↔ without HIPAA",
        key="compare_mode",
        help="Runs the pipeline twice and shows both diagrams, cost delta, and resource delta side-by-side.",
    )

    st.markdown('<hr class="sidebar-divider">', unsafe_allow_html=True)
    st.markdown('<div class="sidebar-section-label">Or upload a sketch</div>', unsafe_allow_html=True)
    st.caption(
        "Upload a hand-drawn architecture, AWS console screenshot, or slide "
        "diagram. Gemini Vision will extract the spec."
    )
    uploaded_image = st.file_uploader(
        "Architecture image",
        type=["png", "jpg", "jpeg", "webp", "gif"],
        key="arch_image",
        label_visibility="collapsed",
    )

    st.markdown('<hr class="sidebar-divider">', unsafe_allow_html=True)
    run_btn = st.button("⚡ Generate", type="primary", use_container_width=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _render_badges(result) -> None:
    badges: list[str] = []
    if result.tf_valid:
        badges.append('<span class="badge badge-valid">✓ TF valid</span>')
    else:
        badges.append('<span class="badge badge-fail">✗ TF invalid</span>')
    badges.append(
        f'<span class="badge badge-muted">{result.tf_attempts} repair attempt'
        f'{"s" if result.tf_attempts != 1 else ""}</span>'
    )
    if result.tfsec_high:
        badges.append(f'<span class="badge badge-warn">tfsec HIGH: {result.tfsec_high}</span>')
    if result.validate_skipped:
        badges.append('<span class="badge badge-muted">validate skipped</span>')
    _badge_cls = {"HIPAA": "badge-hipaa", "PCI": "badge-pci", "SOC2": "badge-soc2"}
    for c in result.spec.compliance:
        cls = _badge_cls.get(c, "badge-muted")
        badges.append(f'<span class="badge {cls}">{c}</span>')
    if result.spec.ha_required:
        badges.append('<span class="badge badge-ha">HA</span>')
    if result.spec.multi_region:
        badges.append('<span class="badge badge-region">Multi-region</span>')
    badges.append(f'<span class="badge badge-muted">{result.spec.region}</span>')
    badges.append(f'<span class="badge badge-muted">{result.spec.scale}</span>')
    st.markdown(" ".join(badges), unsafe_allow_html=True)


def _diff_resources(base: list[dict], final: list[dict]) -> tuple[list[dict], list[dict]]:
    base_by_name = {r["name"]: r for r in base}
    final_by_name = {r["name"]: r for r in final}

    left_rows = []
    for r in base:
        left_rows.append({"name": r["name"], "type": r["type"], "status": "same"})

    right_rows = []
    for r in final:
        if r["name"] not in base_by_name:
            status = "added"
        elif base_by_name[r["name"]].get("args") != r.get("args"):
            status = "modified"
        else:
            status = "same"
        right_rows.append({"name": r["name"], "type": r["type"], "status": status})

    for row in left_rows:
        f = final_by_name.get(row["name"])
        if f is not None and f.get("args") != base_by_name[row["name"]].get("args"):
            row["status"] = "modified"
    return left_rows, right_rows


def _render_diff_column(rows: list[dict]) -> str:
    lines = []
    for r in rows:
        cls = {
            "added": "diff-added",
            "modified": "diff-modified",
            "same": "diff-same",
        }[r["status"]]
        mark = {"added": "+ ", "modified": "~ ", "same": "  "}[r["status"]]
        lines.append(
            f'<div class="{cls}"><code>{mark}{r["type"]}.{r["name"]}</code></div>'
        )
    return "\n".join(lines) or '<em class="diff-same">(no resources)</em>'


# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------
def _maybe_vision_spec(text_prompt: str):
    """If the user uploaded an image, run Gemini Vision -> ArchSpec."""
    img = st.session_state.get("arch_image")
    if img is None:
        return None, text_prompt
    image_bytes = img.getvalue()
    mime = vision_extractor.detect_mime(img.name)
    with st.spinner("Reading architecture image with Gemini Vision…"):
        v_spec = vision_extractor.extract_from_image(
            image_bytes, mime_type=mime, caption=text_prompt or ""
        )
    with st.expander("👁  Vision extraction result", expanded=True):
        st.image(image_bytes, caption="Uploaded sketch", use_container_width=True)
        st.caption(f"Inferred summary: _{v_spec.raw_prompt}_")
    return v_spec, (v_spec.raw_prompt or text_prompt or "")


def _build_overrides(include_hipaa: bool | None = None) -> dict:
    overrides: dict = {}
    if st.session_state.template_choice != "auto":
        overrides["workload_type"] = st.session_state.template_choice
    compliance = []
    hipaa_on = st.session_state.hipaa if include_hipaa is None else include_hipaa
    if hipaa_on:
        compliance.append("HIPAA")
    if st.session_state.pci:
        compliance.append("PCI")
    if st.session_state.soc2:
        compliance.append("SOC2")
    if compliance:
        overrides["compliance"] = compliance
    if st.session_state.ha:
        overrides["ha_required"] = True
    if st.session_state.multi_region:
        overrides["multi_region"] = True
    return overrides


if run_btn and st.session_state.compare_mode:
    # --- Compare mode: run pipeline twice, HIPAA on vs off ---
    vision_spec, retrieval_query = _maybe_vision_spec(prompt)
    with st.spinner("Retrieving knowledge…"):
        retrieved = retriever.retrieve(retrieval_query, k=5)
    spec_off = vision_spec.model_copy(deep=True) if vision_spec else None
    spec_on = vision_spec.model_copy(deep=True) if vision_spec else None
    with st.spinner("Running pipeline (HIPAA off)…"):
        result_off = orchestrator.run(prompt, overrides=_build_overrides(include_hipaa=False), retrieved=retrieved, spec=spec_off)
    with st.spinner("Running pipeline (HIPAA on)…"):
        result_on = orchestrator.run(prompt, overrides=_build_overrides(include_hipaa=True), retrieved=retrieved, spec=spec_on)

    st.subheader("🔁 Compare: without HIPAA ↔ with HIPAA")
    delta = result_on.monthly_cost - result_off.monthly_cost
    pct = (delta / result_off.monthly_cost * 100) if result_off.monthly_cost else 0.0
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Cost — no HIPAA", f"${result_off.monthly_cost:,.0f}")
    m2.metric("Cost — with HIPAA", f"${result_on.monthly_cost:,.0f}", f"{delta:+,.0f} USD")
    m3.metric("Resources", f"{len(result_off.template.get('resources', []))} → {len(result_on.template.get('resources', []))}")
    m4.metric("HIPAA overhead", f"{pct:+.0f}%")

    col_off, col_on = st.columns(2)
    for side, title, r in ((col_off, "Without HIPAA", result_off), (col_on, "With HIPAA", result_on)):
        with side:
            st.markdown(f"#### {title}")
            if r.diagram_path and Path(r.diagram_path).exists():
                st.image(r.diagram_path)
            else:
                st.code(r.diagram_mermaid, language="text")
            st.caption(
                f"{len(r.template.get('resources', []))} resources · "
                f"${r.monthly_cost:,.2f}/mo · "
                f"tfsec HIGH: {r.tfsec_high}"
            )

    base_names = {(x["type"], x["name"]) for x in result_off.template.get("resources", [])}
    on_names = {(x["type"], x["name"]) for x in result_on.template.get("resources", [])}
    added = sorted(on_names - base_names)
    removed = sorted(base_names - on_names)
    st.markdown("##### Resources added by HIPAA")
    if added:
        st.markdown(
            "\n".join(
                f'<div class="diff-added"><code>+ {t}.{n}</code></div>' for t, n in added
            ),
            unsafe_allow_html=True,
        )
    else:
        st.caption("No new resources.")
    if removed:
        st.markdown("##### Removed when HIPAA is on")
        st.markdown(
            "\n".join(f"<code>- {t}.{n}</code>" for t, n in removed),
            unsafe_allow_html=True,
        )
    st.stop()


if run_btn:
    overrides = _build_overrides()

    vision_spec, retrieval_query = _maybe_vision_spec(prompt)
    with st.spinner("Retrieving knowledge…"):
        retrieved = retriever.retrieve(retrieval_query, k=5)

    result = None
    with st.status("Running pipeline…", expanded=True) as status:
        for evt in orchestrator.run_streaming(
            prompt, overrides=overrides, retrieved=retrieved, spec=vision_spec
        ):
            if evt[0] == "stage_started":
                status.update(label=f"Stage: {evt[1]}…", state="running")
            elif evt[0] == "stage_done":
                st.write(f"✓ `{evt[1]}` ({evt[2]:.2f}s)")
            elif evt[0] == "result":
                result = evt[1]
                status.update(label="Pipeline complete", state="complete")

    # Top-line metrics
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Monthly cost", f"${result.monthly_cost:,.0f}")
    m2.metric("Resources", len(result.template.get("resources", [])))
    m3.metric("Patches applied", len(result.template.get("applied_patches", [])))
    m4.metric("TF repair attempts", result.tf_attempts)

    st.write("")
    _render_badges(result)
    st.write("")

    # Assumptions panel
    with st.expander("Assumptions", expanded=False):
        if result.spec.assumptions:
            for a in result.spec.assumptions:
                st.markdown(f"- {a}")
        else:
            st.caption("No assumptions recorded.")

    tabs = st.tabs(
        [
            "🗺 Diagram",
            "📜 Terraform",
            "🔐 Security",
            "💰 Cost",
            "🔁 Compare",
            "📖 Explanation",
            "🧠 Prompts",
            "🧾 Spec JSON",
        ]
    )

    # --- Diagram ---
    with tabs[0]:
        if result.diagram_path and Path(result.diagram_path).exists():
            st.image(result.diagram_path)
        else:
            err = diagram.last_error()
            st.warning(
                "PNG renderer unavailable — showing Mermaid fallback."
                + (f"  \n**Reason:** `{err}`" if err else "")
            )
            st.caption(
                "Fix: `pip install diagrams` and install Graphviz "
                "(`winget install Graphviz.Graphviz`), then restart Streamlit."
            )
            st.code(result.diagram_mermaid, language="text")

    # --- Terraform ---
    with tabs[1]:
        if result.tfsec_high:
            st.error(
                f"🚨  **tfsec found {result.tfsec_high} HIGH / CRITICAL finding"
                f"{'s' if result.tfsec_high != 1 else ''}.** "
                "Review before deploying."
            )
        elif result.validate_skipped and "tfsec" in (result.validate_skipped or "").lower():
            st.info("tfsec not installed — static security scan skipped.")
        else:
            st.success("✓ tfsec: no HIGH/CRITICAL findings")

        st.code(result.tf_code, language="hcl")
        dl_col1, dl_col2 = st.columns(2)
        with dl_col1:
            st.download_button("Download main.tf", result.tf_code, file_name="main.tf")
        with dl_col2:
            try:
                zip_bytes = export.build_zip(result)
                st.download_button(
                    "📦 Download bundle (.zip)",
                    zip_bytes,
                    file_name=f"{result.spec.project_name or 'cloudarch'}_bundle.zip",
                    mime="application/zip",
                )
            except Exception as e:
                st.caption(f"Bundle export unavailable: {e}")
        if result.tf_errors:
            with st.expander("Validator output"):
                for e in result.tf_errors:
                    st.code(e)

    # --- Security ---
    with tabs[2]:
        if result.validate_skipped:
            st.info(f"Validation skipped: {result.validate_skipped}")
        elif not result.tfsec_findings:
            st.success("✅ tfsec: no findings. Clean security scan.")
        else:
            by_sev: dict[str, list[dict]] = {}
            for f in result.tfsec_findings:
                by_sev.setdefault(f.get("severity", "UNKNOWN"), []).append(f)
            order = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
            seen = [s for s in order if s in by_sev] + [s for s in by_sev if s not in order]
            st.caption(
                f"{len(result.tfsec_findings)} finding(s) from tfsec. "
                "Sorted by severity."
            )
            for sev in seen:
                rows = by_sev[sev]
                header = f"**{sev}** — {len(rows)} finding(s)"
                if sev in ("HIGH", "CRITICAL"):
                    st.error(header)
                elif sev == "MEDIUM":
                    st.warning(header)
                else:
                    st.info(header)
                st.dataframe(
                    [
                        {
                            "rule": r.get("rule_id", ""),
                            "resource": r.get("resource", ""),
                            "description": r.get("description", ""),
                            "resolution": r.get("resolution", ""),
                            "location": r.get("location", ""),
                        }
                        for r in rows
                    ],
                    use_container_width=True,
                    hide_index=True,
                )

    # --- Cost ---
    with tabs[3]:
        c1, c2 = st.columns([1, 3])
        with c1:
            st.metric("Total monthly (USD)", f"${result.monthly_cost:,.2f}")
            meta = result.cost_meta or {}
            st.caption(
                f"Pricing data: {meta.get('source','static table')} — "
                f"updated {meta.get('updated','n/a')}.  \n"
                "Production usage will differ."
            )
        with c2:
            if result.cost_breakdown:
                rows = sorted(
                    result.cost_breakdown,
                    key=lambda r: r.get("monthly_usd", 0),
                    reverse=True,
                )
                labels = [f"{r.get('type','?')}.{r.get('name','?')}" for r in rows]
                values = [r.get("monthly_usd", 0) for r in rows]
                fig = px.bar(
                    x=values,
                    y=labels,
                    orientation="h",
                    labels={"x": "Monthly USD", "y": "Resource"},
                    text=[f"${v:,.0f}" for v in values],
                    color=values,
                    color_continuous_scale=[[0, "#0891B2"], [1, "#7C3AED"]],
                )
                fig.update_traces(textposition="outside")
                fig.update_layout(
                    height=max(280, 34 * len(rows)),
                    margin=dict(l=0, r=60, t=10, b=10),
                    yaxis=dict(autorange="reversed"),
                    plot_bgcolor="rgba(0,0,0,0)",
                    paper_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="#e2e8f0"),
                    coloraxis_showscale=False,
                    xaxis=dict(gridcolor="rgba(255,255,255,0.07)", color="#94a3b8"),
                    yaxis2=dict(color="#94a3b8"),
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No cost breakdown available.")
        with st.expander("Raw breakdown table"):
            st.dataframe(result.cost_breakdown, use_container_width=True)

    # --- Compare Base vs With Patches ---
    with tabs[4]:
        applied = result.template.get("applied_patches", [])
        if not applied:
            st.info(
                "No patches applied — base template matches the final architecture. "
                "Toggle HIPAA / HA / multi-region to see patches in action."
            )
        else:
            st.caption(
                f"Patches applied (in order): "
                + " → ".join(f"`{p}`" for p in applied)
            )
        left, right = _diff_resources(
            result.base_template.get("resources", []),
            result.template.get("resources", []),
        )
        col_l, col_r = st.columns(2)
        with col_l:
            st.markdown("**Base template** (no patches)")
            st.markdown(_render_diff_column(left), unsafe_allow_html=True)
        with col_r:
            st.markdown("**With patches**")
            st.markdown(_render_diff_column(right), unsafe_allow_html=True)
        st.caption(
            "Legend: "
            '<span class="diff-added">+ added</span> &nbsp; '
            '<span class="diff-modified">~ modified</span> &nbsp; '
            '<span class="diff-same">unchanged</span>',
            unsafe_allow_html=True,
        )

    # --- Explanation ---
    with tabs[5]:
        st.markdown(result.explanation)
        if retrieved:
            with st.expander("Retrieved sources"):
                for r in retrieved:
                    st.markdown(f"**{r['source']}** (score={r['score']:.2f})")
                    st.caption(r["snippet"])

    # --- Prompts ---
    with tabs[6]:
        st.caption(
            "These are the exact prompts shipped to Gemini at each LLM-touching stage. "
            "The HCL emitter and cost stages are deterministic and use no prompts."
        )
        from pipeline.prompts import load as _load_prompt
        from pipeline.prompts.allowlist import format_allowlist as _fmt_allowlist

        st.markdown("#### 🔹 Stage 1 — Extractor system prompt")
        st.caption(
            f"Turns the natural-language workload description into a JSON `ArchSpec`. "
            f"(version `{extractor.EXTRACTOR_PROMPT_VERSION}`, "
            f"voting samples={extractor.VOTING_SAMPLES})"
        )
        try:
            _ext_sys = _load_prompt(
                f"extractor.system.{extractor.EXTRACTOR_PROMPT_VERSION}"
            ).format(allowlist=_fmt_allowlist())
            _ext_user = _load_prompt(f"extractor.user.{extractor.EXTRACTOR_PROMPT_VERSION}")
        except Exception as e:
            _ext_sys = f"<could not load extractor prompt: {e}>"
            _ext_user = ""
        st.caption("**System instruction** — passed via `system_instruction` config field:")
        st.code(_ext_sys, language="text")
        if _ext_user:
            st.caption("**User turn template** — wraps the user prompt with RAG context and few-shot examples:")
            st.code(_ext_user, language="text")

        st.markdown("#### 🔹 Stage 6 — Validator repair prompt")
        st.caption(
            "Only invoked when `terraform validate` fails. The LLM sees the current HCL "
            "plus validator errors and returns a corrected version."
        )
        st.code(validator.REPAIR_PROMPT_TEMPLATE, language="text")

        st.markdown("#### 🔹 Stage 9 — Explainer prompt")
        st.caption(
            f"Generates the markdown design rationale with RAG citations. "
            f"(version `{explainer.EXPLAINER_PROMPT_VERSION}`)"
        )
        try:
            _exp_tpl = _load_prompt(f"explainer.{explainer.EXPLAINER_PROMPT_VERSION}")
        except Exception as e:
            _exp_tpl = f"<could not load explainer prompt: {e}>"
        st.code(_exp_tpl, language="text")

    # --- Spec JSON ---
    with tabs[7]:
        st.code(json.dumps(result.spec.to_dict(), indent=2), language="json")

else:
    st.info(
        "Pick a preset above or describe your workload in the sidebar, "
        "then click **⚡ Generate**."
    )
