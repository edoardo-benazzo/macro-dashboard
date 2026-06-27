"""
My Macro Views — personal journal & track record page.
Stores weekly macro calls in views_journal.json and scores them after 4 weeks.
"""

import datetime as dt
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Allow imports from parent directory
sys.path.insert(0, str(Path(__file__).parent.parent))
from journal import load_entries, save_entry, delete_entry
from data_fetchers import fetch_price_return_4w

st.set_page_config(page_title="My Macro Views", layout="wide",
                   initial_sidebar_state="collapsed")

st.markdown("""
<style>
html, body, [class*="css"] {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
}
#MainMenu, footer, header { visibility: hidden; }
[data-testid="metric-container"] {
  background: #0A1628; border: 1px solid #1A2540;
  border-radius: 8px; padding: 14px 18px 12px;
}
.sect-div { border:none; border-top:1px solid #1A2540; margin:20px 0; }
</style>
""", unsafe_allow_html=True)

st.markdown(
    '<h2 style="font-size:22px;font-weight:800;color:#FFFFFF;margin-bottom:4px">'
    'My Macro Views</h2>'
    '<p style="font-size:12px;color:#4A607A;margin-bottom:20px">'
    'Record your weekly macro thesis. Reviewed automatically after 4 weeks.</p>',
    unsafe_allow_html=True)

# ── Asset tickers for scoring ──────────────────────────────────────────────────
_ASSET_TICKERS = {
    "US Rates 2Y":  "SHY",        # SHY rises when 2Y rates fall → invert for rate direction
    "US Rates 10Y": "TLT",        # TLT rises when 10Y falls → invert for rate direction
    "USD/DXY":      "DX-Y.NYB",
    "S&P 500":      "^GSPC",
    "Gold":         "GC=F",
    "Crude Oil":    "CL=F",
}

# For rates: "Higher" means rates went UP → bond ETF went DOWN
_RATE_ASSETS = {"US Rates 2Y", "US Rates 10Y"}


# ── Form ───────────────────────────────────────────────────────────────────────
with st.expander("➕ Add New View", expanded=True):
    with st.form("new_view"):
        col1, col2 = st.columns(2)
        with col1:
            entry_date = st.date_input(
                "Date", value=dt.date.today(), key="jrn_date")
            regime = st.selectbox(
                "Macro Regime",
                ["Goldilocks", "Reflation", "Stagflation", "Deflation Risk", "Uncertain"],
                key="jrn_regime")
            conviction = st.slider("Overall Conviction (1-5)", 1, 5, 3, key="jrn_conv")
        with col2:
            thesis = st.text_area(
                "Key Thesis (max 280 chars)",
                max_chars=280, height=80, key="jrn_thesis",
                placeholder="What's driving markets? What's the core macro story?")
            kill_trade = st.text_area(
                "What kills my trade? (max 280 chars)",
                max_chars=280, height=80, key="jrn_kill",
                placeholder="What would prove me wrong? What's the biggest risk?")

        st.markdown("**Asset Calls**")
        RATE_OPTS  = ["Higher", "Lower", "Unchanged"]
        ASSET_OPTS = ["Bullish", "Bearish", "Neutral"]

        c1, c2, c3 = st.columns(3)
        with c1:
            us2y_dir  = st.selectbox("US Rates 2Y",  RATE_OPTS,  key="jrn_2y")
            us10y_dir = st.selectbox("US Rates 10Y", RATE_OPTS,  key="jrn_10y")
        with c2:
            usd_dir   = st.selectbox("USD/DXY",      ASSET_OPTS, key="jrn_usd")
            sp_dir    = st.selectbox("S&P 500",       ASSET_OPTS, key="jrn_sp")
        with c3:
            gold_dir  = st.selectbox("Gold",          ASSET_OPTS, key="jrn_gold")
            oil_dir   = st.selectbox("Crude Oil",     ASSET_OPTS, key="jrn_oil")

        submitted = st.form_submit_button("Save View ✓", use_container_width=True)

    if submitted:
        entry = {
            "date":       str(entry_date),
            "regime":     regime,
            "conviction": conviction,
            "thesis":     thesis.strip(),
            "kill_trade": kill_trade.strip(),
            "calls": {
                "US Rates 2Y":  us2y_dir,
                "US Rates 10Y": us10y_dir,
                "USD/DXY":      usd_dir,
                "S&P 500":      sp_dir,
                "Gold":         gold_dir,
                "Crude Oil":    oil_dir,
            },
        }
        save_entry(entry)
        st.success("View saved!")
        st.rerun()


# ── Track record ───────────────────────────────────────────────────────────────
entries = load_entries()
if not entries:
    st.caption("No views yet — add your first one above.")
    st.stop()

st.markdown('<hr class="sect-div">', unsafe_allow_html=True)
st.markdown(
    '<p style="font-size:14px;font-weight:700;color:#E2E8F0;margin-bottom:4px">'
    'Track Record</p>'
    '<p style="font-size:11px;color:#4A607A;margin-bottom:12px">'
    'Price returns fetched for entries ≥4 weeks old. Correct direction = ✅ Wrong = ❌ Flat/N/A = ➖</p>',
    unsafe_allow_html=True)

def _score_call(call: str, ret: float | None, is_rate: bool) -> str:
    """Score a call given the 4-week return. For rate assets, invert the bond ETF return."""
    if ret is None:
        return "➖"
    eff = -ret if is_rate else ret  # "Higher rates" = bond ETF fell
    if call in ("Bullish", "Higher"):
        return "✅" if eff > 1.0 else "❌" if eff < -1.0 else "➖"
    if call in ("Bearish", "Lower"):
        return "✅" if eff < -1.0 else "❌" if eff > 1.0 else "➖"
    return "➖"  # Unchanged / Neutral


today = dt.date.today()
_ASSETS = list(_ASSET_TICKERS.keys())

# Summary stats accumulators
hit_counts = {a: {"correct": 0, "total": 0} for a in _ASSETS}
conv_acc   = []  # (conviction, hit_rate) per entry

rows_data = []
for entry in entries:
    entry_date = dt.date.fromisoformat(entry["date"])
    is_old = (today - entry_date).days >= 28
    calls  = entry.get("calls", {})

    scores = {}
    rets   = {}
    if is_old:
        for asset, ticker in _ASSET_TICKERS.items():
            ret = fetch_price_return_4w(ticker, entry["date"])
            rets[asset] = ret
            call = calls.get(asset)
            if call:
                sc = _score_call(call, ret, asset in _RATE_ASSETS)
                scores[asset] = sc
                if sc == "✅":
                    hit_counts[asset]["correct"] += 1
                    hit_counts[asset]["total"] += 1
                elif sc == "❌":
                    hit_counts[asset]["total"] += 1
    else:
        for asset in _ASSETS:
            scores[asset] = "⏳"
            rets[asset]   = None

    entry_hits = [v for v in scores.values() if v == "✅"]
    entry_total = [v for v in scores.values() if v in ("✅", "❌")]
    entry_hr = len(entry_hits) / len(entry_total) * 100 if entry_total else None
    if entry_hr is not None:
        conv_acc.append((entry.get("conviction", 3), entry_hr))

    rows_data.append({
        "entry": entry, "is_old": is_old,
        "scores": scores, "rets": rets,
        "hr": entry_hr,
    })

# ── Summary stats row ─────────────────────────────────────────────────────────
scored_entries = [r for r in rows_data if r["is_old"]]
if scored_entries:
    stat_cols = st.columns(len(_ASSETS) + 1)
    overall_hits = sum(
        1 for r in scored_entries for s in r["scores"].values() if s == "✅"
    )
    overall_total = sum(
        1 for r in scored_entries for s in r["scores"].values() if s in ("✅", "❌")
    )
    overall_hr = round(overall_hits / overall_total * 100) if overall_total else 0
    stat_cols[0].metric("Overall Hit Rate", f"{overall_hr}%",
                        f"{overall_hits}/{overall_total} calls")
    for i, asset in enumerate(_ASSETS):
        h = hit_counts[asset]
        hr = round(h["correct"] / h["total"] * 100) if h["total"] else None
        stat_cols[i + 1].metric(asset, f"{hr}%" if hr is not None else "—",
                                f"{h['correct']}/{h['total']}")

    # Conviction vs accuracy scatter
    if len(conv_acc) >= 3:
        st.markdown('<hr class="sect-div">', unsafe_allow_html=True)
        st.markdown(
            '<p style="font-size:12px;font-weight:700;color:#A0AEC0;margin-bottom:6px">'
            'CONVICTION vs ACCURACY</p>', unsafe_allow_html=True)
        fig_cv = go.Figure()
        convs  = [x[0] for x in conv_acc]
        hrs    = [x[1] for x in conv_acc]
        fig_cv.add_trace(go.Scatter(
            x=convs, y=hrs, mode="markers",
            marker=dict(size=12, color="#2979FF", opacity=0.8),
            hovertemplate="Conviction: %{x}<br>Hit Rate: %{y:.0f}%<extra></extra>",
        ))
        fig_cv.update_layout(
            template="plotly_dark",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(10,22,40,0.6)",
            xaxis=dict(title="Conviction Level (1-5)", gridcolor="#1A2540",
                       tickvals=[1, 2, 3, 4, 5]),
            yaxis=dict(title="Hit Rate (%)", range=[0, 105], gridcolor="#1A2540"),
            height=220, margin=dict(l=8, r=8, t=8, b=8),
        )
        fig_cv.add_hline(y=50, line_dash="dash", line_color="#2D3E56", line_width=1,
                         annotation_text="50% (coin flip)", annotation_font_color="#2D3E56")
        st.plotly_chart(fig_cv, use_container_width=True)
        st.caption("Are your highest-conviction calls more accurate? Ideally, this chart shows a positive slope.")

# ── Entry cards ───────────────────────────────────────────────────────────────
st.markdown('<hr class="sect-div">', unsafe_allow_html=True)
for row in rows_data:
    entry  = row["entry"]
    scores = row["scores"]
    rets   = row["rets"]
    is_old = row["is_old"]
    hr     = row["hr"]

    # Find best/worst calls for highlighting
    all_scored = {a: s for a, s in scores.items() if s in ("✅", "❌")}
    best_call  = next((a for a, s in all_scored.items() if s == "✅"), None)
    worst_call = next((a for a, s in all_scored.items() if s == "❌"), None)

    _regime_color = {
        "Goldilocks": "#00C896", "Reflation": "#FFA502",
        "Stagflation": "#FF4757", "Deflation Risk": "#5580FF", "Uncertain": "#A0AEC0",
    }
    rc = _regime_color.get(entry.get("regime", ""), "#A0AEC0")
    hr_str = f"{hr:.0f}%" if hr is not None else ("Pending ⏳" if not is_old else "—")

    st.markdown(
        f'<div style="border:1px solid #1A2540;border-left:4px solid {rc};'
        f'border-radius:6px;padding:14px 16px;margin-bottom:10px">'
        f'<div style="display:flex;justify-content:space-between;align-items:flex-start;'
        f'flex-wrap:wrap;gap:8px;margin-bottom:10px">'
        f'<div>'
        f'<div style="font-size:9px;color:#4A607A;text-transform:uppercase;letter-spacing:0.9px">'
        f'{entry["date"]}</div>'
        f'<div style="font-size:16px;font-weight:700;color:{rc}">'
        f'{entry.get("regime", "—")}</div>'
        f'<div style="font-size:10px;color:#4A607A">Conviction: '
        f'{"⭐" * entry.get("conviction", 3)}</div>'
        f'</div>'
        f'<div style="text-align:right">'
        f'<div style="font-size:9px;color:#4A607A;text-transform:uppercase">4W Hit Rate</div>'
        f'<div style="font-size:22px;font-weight:800;color:#FFFFFF">{hr_str}</div>'
        f'</div>'
        f'</div>'
        + (f'<div style="font-size:12px;color:#E2E8F0;margin-bottom:6px">'
           f'<strong>Thesis:</strong> {entry.get("thesis", "")}</div>'
           if entry.get("thesis") else "")
        + (f'<div style="font-size:11px;color:#4A607A;margin-bottom:10px">'
           f'<strong>Kill switch:</strong> {entry.get("kill_trade", "")}</div>'
           if entry.get("kill_trade") else "")
        + '</div>',
        unsafe_allow_html=True)

    # Asset call table
    call_cols = st.columns(len(_ASSETS))
    for i, asset in enumerate(_ASSETS):
        call  = entry.get("calls", {}).get(asset, "—")
        score = scores.get(asset, "—")
        ret   = rets.get(asset)
        ret_s = f"{ret:+.1f}%" if ret is not None else ""
        c_clr = "#E2E8F0"
        if score == "✅": c_clr = "#00C896"
        elif score == "❌": c_clr = "#FF4757"
        call_cols[i].markdown(
            f'<div style="text-align:center;border:1px solid #1A2540;border-radius:4px;padding:6px 4px">'
            f'<div style="font-size:9px;color:#4A607A">{asset}</div>'
            f'<div style="font-size:12px;font-weight:700;color:{c_clr}">{call}</div>'
            f'<div style="font-size:14px">{score}</div>'
            f'<div style="font-size:10px;color:#4A607A">{ret_s}</div>'
            f'</div>',
            unsafe_allow_html=True)

    if best_call or worst_call:
        hls = []
        if best_call:
            hls.append(f'Best call: <span style="color:#00C896">{best_call}</span>')
        if worst_call:
            hls.append(f'Worst call: <span style="color:#FF4757">{worst_call}</span>')
        st.markdown(
            f'<div style="font-size:10px;color:#4A607A;margin-top:6px">'
            f'{" · ".join(hls)}</div>',
            unsafe_allow_html=True)

    # Delete button
    del_key = f"del_{entry.get('id', entry['date'])}"
    if st.button("Delete", key=del_key, help="Remove this entry"):
        delete_entry(entry.get("id", ""))
        st.rerun()

    st.markdown('<hr style="border:none;border-top:1px solid #0E1C30;margin:6px 0">',
                unsafe_allow_html=True)

# ── Learn More ────────────────────────────────────────────────────────────────
with st.expander("📚 Why track your macro views?"):
    st.markdown("""
**The core problem with macro analysis:** It feels rigorous, but without a track record
you have no feedback loop. Confident calls with no accountability become just storytelling.

**What this journal builds:**
- **Hit rate by asset** — reveals where your edge actually is (and isn't)
- **Conviction vs accuracy** — if your 5/5 calls don't beat coin flips, lower your conviction
- **Kill switch discipline** — writing "what kills my trade" forces pre-mortems before the loss

**The 4-week window:** Short enough to capture a reaction, long enough to discount noise.
Not meant to capture entire macro cycles — this is about trade-level thesis precision.

**Historical base rates for macro forecasters:**
Most professional economists have sub-55% directional accuracy on rates.
Even 60%+ hit rate on 6 simultaneous calls would put you in elite company.
""")
