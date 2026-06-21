"""
Macro Dashboard — Hedge Fund Edition
--------------------------------------
US & Europe macro · Economic calendar · Macro news · Bitcoin
Data: FRED · Yahoo Finance · CoinGecko · mempool.space · Alternative.me

Run locally:  streamlit run app.py
FRED key:     .streamlit/secrets.toml  →  FRED_API_KEY = "..."
Calendar +:   .streamlit/secrets.toml  →  FINNHUB_API_KEY = "..."  (free at finnhub.io)
"""

import datetime as dt
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from config import (
    FRED_SERIES, MARKET_TICKERS, DEFAULT_LOOKBACK_YEARS,
    CORRELATION_TICKERS, CORRELATION_WINDOW_DAYS, tradingview_url,
)
from data_fetchers import (
    load_all_fred, load_all_markets, latest_snapshot, compute_beta,
    compute_sahm_rule, cpi_vs_target, yield_curve_status,
    credit_spread_status, classify_macro_regime, classify_eu_macro_regime,
    compute_correlation_matrix, compute_zscore, zscore_label,
    compute_real_fed_funds, compute_btp_bund_spread, btp_bund_status,
    compute_recession_probability, series_trend,
)
from news_fetcher import fetch_all_macro_news, IMPACT_CATEGORIES
from crypto_fetchers import (
    fetch_btc_coingecko, fetch_crypto_global, fetch_fear_greed,
    fetch_btc_hashrate, fetch_btc_history,
    compute_btc_technicals, halving_cycle_info,
)
from calendar_fetcher import get_calendar, flag, importance_dot, beat_miss_label

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Macro Dashboard", layout="wide", page_icon="📊",
                   initial_sidebar_state="collapsed")

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
html, body, [class*="css"] {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
}
#MainMenu, footer, header { visibility: hidden; }

/* metric cards */
[data-testid="metric-container"] {
  background: #141928; border: 1px solid #1C2538;
  border-radius: 10px; padding: 14px 18px 12px;
  transition: border-color 0.2s;
}
[data-testid="metric-container"]:hover { border-color: #00C896; }
[data-testid="stMetricLabel"] p {
  font-size: 11px !important; font-weight: 700 !important;
  letter-spacing: 0.8px !important; text-transform: uppercase !important;
  color: #4A5568 !important;
}
[data-testid="stMetricValue"] {
  font-size: 22px !important; font-weight: 700 !important;
  letter-spacing: -0.5px !important; color: #E2E8F0 !important;
}

/* tabs */
[data-testid="stTabs"] [data-baseweb="tab-list"] {
  background: transparent; border-bottom: 1px solid #1C2538; gap: 0;
}
[data-testid="stTabs"] [data-baseweb="tab"] {
  font-size: 12px; font-weight: 700; letter-spacing: 0.4px;
  padding: 10px 18px; color: #4A5568;
  border-bottom: 2px solid transparent;
}
[data-testid="stTabs"] [aria-selected="true"] {
  color: #00C896 !important; border-bottom-color: #00C896 !important;
  background: transparent !important;
}

/* news & calendar cards */
.card {
  background: #141928; border: 1px solid #1C2538;
  border-left: 3px solid #1C2538; border-radius: 0 8px 8px 0;
  padding: 12px 16px 10px; margin: 6px 0; transition: border-left-color 0.2s;
}
.card:hover { border-left-color: #00C896; }
.card-meta  { font-size:10px; font-weight:700; letter-spacing:0.8px; color:#3D4A5C; text-transform:uppercase; }
.card-title { font-size:14px; font-weight:600; color:#E2E8F0; line-height:1.45; margin:5px 0 3px; }
.card-sub   { font-size:12px; color:#5A6E85; line-height:1.5; margin-top:4px; }

/* badges */
.badge { display:inline-block; padding:2px 7px; border-radius:4px;
         font-size:9px; font-weight:800; letter-spacing:0.7px;
         text-transform:uppercase; margin:0 3px 0 0; vertical-align:middle; }
.badge-hawkish  { background:rgba(255,71,87,.15);   color:#FF4757; border:1px solid rgba(255,71,87,.35); }
.badge-dovish   { background:rgba(0,200,150,.15);   color:#00C896; border:1px solid rgba(0,200,150,.35); }
.badge-risk_off { background:rgba(255,165,2,.15);   color:#FFA502; border:1px solid rgba(255,165,2,.35); }
.badge-risk_on  { background:rgba(0,200,100,.12);   color:#00C864; border:1px solid rgba(0,200,100,.35); }
.badge-inflation{ background:rgba(255,107,107,.15); color:#FF6B6B; border:1px solid rgba(255,107,107,.35); }
.badge-fed      { background:rgba(78,154,255,.15);  color:#4E9AFF; border:1px solid rgba(78,154,255,.35); }
.badge-ecb      { background:rgba(0,200,150,.12);   color:#00C896; border:1px solid rgba(0,200,150,.30); }
.badge-labor    { background:rgba(165,94,234,.15);  color:#A55EEA; border:1px solid rgba(165,94,234,.35); }
.badge-geo      { background:rgba(255,71,87,.12);   color:#FF7088; border:1px solid rgba(255,71,87,.30); }
.badge-btc      { background:rgba(247,147,26,.15);  color:#F7931A; border:1px solid rgba(247,147,26,.35); }

/* calendar row */
.cal-row {
  display:grid; grid-template-columns:90px 24px 16px 1fr 70px 90px 90px 120px;
  align-items:center; gap:8px; padding:9px 14px; border-radius:8px; margin:3px 0;
  background:#141928; border:1px solid #1C2538; font-size:12px;
}
.cal-row:hover { border-color:#2D3A52; }
.cal-date  { color:#5A6E85; font-weight:700; font-size:11px; }
.cal-name  { color:#E2E8F0; font-weight:600; }
.cal-val   { color:#9AA5B4; text-align:right; font-size:11px; font-variant-numeric:tabular-nums; }
.cal-est   { color:#7B8FA5; text-align:right; font-size:11px; }
.cal-act   { color:#E2E8F0; font-weight:700; text-align:right; font-size:11px; }
.beat  { color:#00C896; font-weight:800; font-size:10px; }
.miss  { color:#FF4757; font-weight:800; font-size:10px; }
.inline{ color:#9AA5B4; font-weight:700; font-size:10px; }
.upcoming-tag { color:#4A5568; font-style:italic; font-size:10px; }

/* section divider */
.sect-div { border:none; border-top:1px solid #1C2538; margin:20px 0; }

/* sidebar */
[data-testid="stSidebar"] { background:#0B0F19; border-right:1px solid #1C2538; }
</style>
""", unsafe_allow_html=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _market_status() -> dict:
    ET  = ZoneInfo("America/New_York")
    now = dt.datetime.now(ET)
    t   = now.hour * 60 + now.minute
    wd  = now.weekday()
    if wd >= 5: return {"label": "CLOSED",      "color": "#4A5568"}
    if 570 <= t < 960:  return {"label": "MARKET OPEN",  "color": "#00C896"}
    if 240 <= t < 570:  return {"label": "PRE-MARKET",   "color": "#FFA502"}
    if 960 <= t < 1200: return {"label": "AFTER-HOURS",  "color": "#4E9AFF"}
    return {"label": "CLOSED", "color": "#4A5568"}


def _page_header():
    ms = _market_status()
    ts = dt.datetime.now().strftime("%d %b %Y · %H:%M")
    st.markdown(f"""
    <div style="display:flex;align-items:center;justify-content:space-between;
                padding:10px 0 16px;border-bottom:1px solid #1C2538;margin-bottom:18px">
      <div>
        <span style="font-size:21px;font-weight:800;letter-spacing:-0.5px;color:#E2E8F0">
          MACRO DASHBOARD</span>
        <span style="font-size:10px;font-weight:700;letter-spacing:1.4px;
                     color:#3D4A5C;margin-left:14px;text-transform:uppercase">
          Hedge Fund Intelligence</span>
      </div>
      <div style="text-align:right;line-height:1.7">
        <span style="font-size:11px;font-weight:700;color:{ms['color']}">● {ms['label']}</span>
        <span style="font-size:11px;color:#3D4A5C;margin-left:10px">{ts}</span>
      </div>
    </div>""", unsafe_allow_html=True)


# ── Plotly dark theme ──────────────────────────────────────────────────────────

_PALETTE = ["#00C896","#4E9AFF","#FF6B6B","#FFA502","#A55EEA",
            "#F7931A","#45B7D1","#FF4E81","#76FF7A","#FFD166"]

_BASE = dict(
    template="plotly_dark",
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(20,25,40,0.4)",
    font=dict(family="Inter, -apple-system, sans-serif", size=11, color="#7B8FA5"),
    xaxis=dict(gridcolor="#1C2538", showgrid=True, zeroline=False,
               linecolor="#1C2538", tickfont=dict(size=10)),
    yaxis=dict(gridcolor="#1C2538", showgrid=True, zeroline=False,
               linecolor="#1C2538", tickfont=dict(size=10)),
    margin=dict(l=6, r=6, t=36, b=6),
    height=255,
    showlegend=False,
    legend=dict(bgcolor="rgba(0,0,0,0)", bordercolor="#1C2538",
                font=dict(size=10), orientation="h", y=1.08),
    title_font=dict(size=13, color="#E2E8F0"),
    hoverlabel=dict(bgcolor="#141928", bordercolor="#1C2538",
                    font=dict(size=12, color="#E2E8F0")),
)

_RANGE_BUTTONS = dict(
    buttons=[
        dict(count=1,  label="1M", step="month", stepmode="backward"),
        dict(count=3,  label="3M", step="month", stepmode="backward"),
        dict(count=6,  label="6M", step="month", stepmode="backward"),
        dict(count=1,  label="1Y", step="year",  stepmode="backward"),
        dict(count=3,  label="3Y", step="year",  stepmode="backward"),
        dict(step="all", label="ALL"),
    ],
    bgcolor="#141928", activecolor="#00C896",
    borderwidth=0, font=dict(color="#7B8FA5", size=9), x=0, y=1.02,
)


def _fig(**kw) -> go.Figure:
    layout = {**_BASE, **kw}
    return go.Figure(layout=go.Layout(**layout))


def line_chart(series: pd.Series, title: str, units: str,
               hlines: list | None = None, color: str = "#00C896",
               height: int = 255, range_selector: bool = True) -> go.Figure:
    fig = _fig(title=title, yaxis_title=units, height=height)
    fig.add_trace(go.Scatter(
        x=series.index, y=series.values, mode="lines",
        line=dict(color=color, width=1.8),
        fill="tozeroy", fillcolor=f"{color}14",
        hovertemplate="%{y:.3f}<extra></extra>",
    ))
    if hlines:
        for hl in hlines:
            fig.add_hline(y=hl["y"], line_dash=hl.get("dash","dash"),
                          line_color=hl.get("color","#4A5568"), line_width=1.1,
                          annotation_text=hl.get("label",""),
                          annotation_font_size=9, annotation_font_color="#5A6E85")
    if range_selector:
        fig.update_xaxes(rangeselector=_RANGE_BUTTONS, rangeslider=dict(visible=False))
    return fig


def multi_line_chart(series_dict: dict, title: str, units: str,
                     height: int = 275, range_selector: bool = True) -> go.Figure:
    fig = _fig(title=title, yaxis_title=units, height=height, showlegend=True)
    for i, (name, s) in enumerate(series_dict.items()):
        if s is not None and not s.dropna().empty:
            fig.add_trace(go.Scatter(
                x=s.dropna().index, y=s.dropna().values,
                mode="lines", name=name,
                line=dict(color=_PALETTE[i % len(_PALETTE)], width=1.8),
                hovertemplate=f"{name}: %{{y:.3f}}<extra></extra>",
            ))
    if range_selector:
        fig.update_xaxes(rangeselector=_RANGE_BUTTONS, rangeslider=dict(visible=False))
    return fig


def tv_link(symbol_key: str):
    url = tradingview_url(symbol_key)
    if url:
        st.markdown(
            f'<a href="{url}" target="_blank" style="font-size:11px;color:#3D4A5C;'
            f'text-decoration:none;font-weight:600">📊 TradingView ↗</a>',
            unsafe_allow_html=True)


def chart_col(col, series: pd.Series, title: str, units: str,
              tv_key: str = None, hlines: list = None, color: str = "#00C896"):
    with col:
        st.plotly_chart(line_chart(series, title, units, hlines, color),
                        use_container_width=True)
        if tv_key:
            tv_link(tv_key)


def sect(title: str, caption: str = ""):
    st.markdown(
        f'<hr class="sect-div">'
        f'<p style="font-size:15px;font-weight:700;color:#E2E8F0;'
        f'margin:0 0 {"4" if caption else "14"}px;letter-spacing:-0.2px">{title}</p>',
        unsafe_allow_html=True)
    if caption:
        st.caption(caption)


def zscore_pill(key: str):
    if not show_zscore:
        return
    s = _s(key)
    if s is None:
        return
    z = compute_zscore(s)
    if z["zscore"] is not None:
        st.caption(f"Z-score vs history: **{z['zscore']:+.1f}σ** — {zscore_label(z['zscore'])}")


# ── Data loading & sidebar ─────────────────────────────────────────────────────

st.sidebar.markdown(
    '<p style="font-size:17px;font-weight:800;color:#E2E8F0;margin-bottom:6px">'
    '⚙️ Settings</p>', unsafe_allow_html=True)

lookback_years = st.sidebar.slider("Lookback (years)", 1, 10, DEFAULT_LOOKBACK_YEARS)
yahoo_period   = f"{lookback_years}y"
fred_start     = (dt.date.today() - dt.timedelta(days=365 * lookback_years)).isoformat()

try:
    fred_api_key = st.secrets["FRED_API_KEY"]
except Exception:
    fred_api_key = None
if not fred_api_key:
    fred_api_key = st.sidebar.text_input("FRED API key", type="password",
                                          help="Free at fred.stlouisfed.org")

try:
    finnhub_key = st.secrets["FINNHUB_API_KEY"]
except Exception:
    finnhub_key = None
if not finnhub_key:
    finnhub_key = st.sidebar.text_input(
        "FinnHub API key (optional)", type="password",
        help="Free at finnhub.io — adds consensus forecasts to Economic Calendar")

show_zscore = st.sidebar.checkbox("Show Z-scores", value=True)

st.sidebar.markdown("---")
if st.sidebar.button("🔄 Force Refresh All Data", use_container_width=True):
    st.cache_data.clear()
    st.rerun()

last_refresh = dt.datetime.now().strftime("%H:%M:%S")
st.sidebar.caption(f"Data cached 15 min · Last load: {last_refresh}")
st.sidebar.caption("FRED · Yahoo Finance · CoinGecko\nmempool.space · Alternative.me")

# ── Load data ──────────────────────────────────────────────────────────────────

fred_data   = None
market_data = None

if fred_api_key:
    with st.spinner("Loading macro data from FRED…"):
        fred_data = load_all_fred(FRED_SERIES, fred_api_key, fred_start)

with st.spinner("Loading market data…"):
    market_data = load_all_markets(MARKET_TICKERS, period=yahoo_period)

# FRED quick accessors
def _s(key: str) -> pd.Series | None:
    if fred_data is None: return None
    entry = fred_data.get(key, {})
    s = entry.get("series")
    return None if (s is None or s.dropna().empty) else s

def _latest(key: str) -> float | None:
    s = _s(key)
    return s.dropna().iloc[-1] if s is not None else None


# ── Page header ────────────────────────────────────────────────────────────────
_page_header()

# ── Today's release banner (shown on any tab) ──────────────────────────────────
today_evts, upcoming_evts, recent_evts = get_calendar(fred_data, finnhub_key)
if today_evts:
    names = " · ".join(f"**{e['name']}**" for e in today_evts[:4])
    st.info(f"📅 **RELEASES TODAY:** {names}", icon="🔔")


# ── Tabs ───────────────────────────────────────────────────────────────────────
(tab_score, tab_cal, tab_news,
 tab_crypto, tab_macro, tab_markets, tab_cross) = st.tabs([
    "📋  Scorecard",
    "📅  Calendar",
    "📰  News",
    "₿  Bitcoin",
    "🏛️  Macro",
    "📈  Markets",
    "🔀  Cross-Asset",
])


# ══════════════════════════════════════════════════════════════════════════════
# SCORECARD
# ══════════════════════════════════════════════════════════════════════════════

with tab_score:
    if fred_data is None:
        st.warning("Enter your FRED API key in the sidebar to load macro data.")
    else:
        cpi_l=_latest("cpi_yoy"); core_pce_l=_latest("core_pce_yoy")
        pce_l=_latest("pce_yoy"); ffr_l=_latest("fed_funds")
        y10_l=_latest("10y_yield"); y2_l=_latest("2y_yield"); y3m_l=_latest("3m_yield")
        real_10y_l=_latest("real_10y"); unrate_l=_latest("unemployment")
        cfnai_l=_latest("cfnai"); hy_oas_l=_latest("hy_oas")
        claims_l=_latest("initial_claims"); sent_l=_latest("consumer_sentiment")
        eu_hicp_l=_latest("eu_hicp"); ecb_l=_latest("ecb_deposit_rate")
        eu_10y_l=_latest("eu_10y_yield"); eu_unemp_l=_latest("eu_unemployment")
        de_10y_l=_latest("de_10y_yield"); it_10y_l=_latest("it_10y_yield")

        sp2s10s=(y10_l-y2_l)  if (y10_l and y2_l)  else None
        sp3m10s=(y10_l-y3m_l) if (y10_l and y3m_l) else None
        sahm=compute_sahm_rule(_s("unemployment"))
        regime=classify_macro_regime(cfnai_l, cpi_l)
        credit=credit_spread_status(hy_oas_l)
        eu_reg=classify_eu_macro_regime(eu_hicp_l, eu_unemp_l)
        btp_bps=(it_10y_l-de_10y_l)*100 if (it_10y_l and de_10y_l) else None
        btp_st=btp_bund_status(btp_bps)
        rec=compute_recession_probability(sp2s10s, sp3m10s, sahm["value"], hy_oas_l, cfnai_l)

        # Regime banners
        col_us, col_eu = st.columns(2)
        with col_us:
            st.markdown("**🇺🇸 US Macro Regime**")
            if regime["label"]:
                st.markdown(f"<p style='font-size:26px;font-weight:800;margin:4px 0 2px'>"
                            f"{regime['label']}</p>", unsafe_allow_html=True)
                st.caption(regime["description"])
        with col_eu:
            st.markdown("**🇪🇺 EU Macro Regime**")
            if eu_reg["label"]:
                st.markdown(f"<p style='font-size:26px;font-weight:800;margin:4px 0 2px'>"
                            f"{eu_reg['label']}</p>", unsafe_allow_html=True)
                st.caption(eu_reg["description"])

        st.markdown('<hr class="sect-div">', unsafe_allow_html=True)

        # Recession probability
        if rec["probability"] is not None:
            rp = rec["probability"]
            color = "#FF4757" if rp>=70 else "#FFA502" if rp>=40 else "#00C896"
            st.markdown(f"**🇺🇸 US Recession Probability: "
                        f"<span style='color:{color}'>{rec['label']} — {rp}%</span>**",
                        unsafe_allow_html=True)
            c1,_ = st.columns([3,1])
            with c1: st.progress(rp/100)
            st.caption("Composite: 3m10y spread (30%) · Sahm Rule (25%) · 2s10s (20%) · HY OAS (15%) · CFNAI (10%)")

        st.markdown('<hr class="sect-div">', unsafe_allow_html=True)

        # Metrics grid
        st.markdown("**Key Signals**")
        c1,c2,c3,c4 = st.columns(4)

        with c1:
            st.markdown('<p style="font-size:10px;font-weight:700;letter-spacing:0.8px;color:#3D4A5C;text-transform:uppercase;margin-bottom:8px">Rates</p>', unsafe_allow_html=True)
            if ffr_l:    st.metric("Fed Funds",  f"{ffr_l:.2f}%")
            if ecb_l:    st.metric("ECB Rate",   f"{ecb_l:.2f}%")
            if y10_l:    st.metric("US 10Y",     f"{y10_l:.2f}%")
            if eu_10y_l: st.metric("EU 10Y",     f"{eu_10y_l:.2f}%")
            if real_10y_l: st.metric("Real 10Y", f"{real_10y_l:.2f}%")

        with c2:
            st.markdown('<p style="font-size:10px;font-weight:700;letter-spacing:0.8px;color:#3D4A5C;text-transform:uppercase;margin-bottom:8px">Inflation</p>', unsafe_allow_html=True)
            if cpi_l:
                g=cpi_vs_target(cpi_l)
                st.metric("US CPI",     f"{cpi_l:.2f}%",   f"{g['gap']:+.2f}pp vs 2%")
            if pce_l:    st.metric("US PCE",      f"{pce_l:.2f}%")
            if core_pce_l: st.metric("Core PCE", f"{core_pce_l:.2f}%")
            if eu_hicp_l:
                g2=cpi_vs_target(eu_hicp_l)
                st.metric("EU HICP", f"{eu_hicp_l:.2f}%", f"{g2['gap']:+.2f}pp vs 2%")

        with c3:
            st.markdown('<p style="font-size:10px;font-weight:700;letter-spacing:0.8px;color:#3D4A5C;text-transform:uppercase;margin-bottom:8px">Labor & Growth</p>', unsafe_allow_html=True)
            if unrate_l:   st.metric("US Unemp.",    f"{unrate_l:.2f}%")
            if eu_unemp_l: st.metric("EU Unemp.",    f"{eu_unemp_l:.2f}%")
            if claims_l:   st.metric("Init. Claims", f"{claims_l:,.0f}")
            if sahm["value"] is not None:
                st.metric("Sahm Rule", f"{sahm['value']:.2f}pp",
                          "🔴 Triggered" if sahm["triggered"] else "🟢 Clear")
            if cfnai_l:
                st.metric("CFNAI", f"{cfnai_l:.2f}",
                          "▲ Above trend" if cfnai_l>0 else "▼ Below trend")

        with c4:
            st.markdown('<p style="font-size:10px;font-weight:700;letter-spacing:0.8px;color:#3D4A5C;text-transform:uppercase;margin-bottom:8px">Risk Signals</p>', unsafe_allow_html=True)
            if sp2s10s is not None: st.metric("2s10s",    f"{sp2s10s:.2f}%", yield_curve_status(sp2s10s)["label"])
            if sp3m10s is not None: st.metric("3m10y",    f"{sp3m10s:.2f}%", yield_curve_status(sp3m10s)["label"])
            if hy_oas_l:            st.metric("HY OAS",   f"{hy_oas_l:.2f}%", credit["label"])
            if btp_bps is not None: st.metric("BTP-Bund", f"{btp_bps:.0f}bps", btp_st["label"])
            if sent_l:              st.metric("Sentiment", f"{sent_l:.1f}")

        st.markdown('<hr class="sect-div">', unsafe_allow_html=True)

        # Alerts
        st.markdown("**🚨 Active Alerts**")
        alerts = []
        if sp2s10s is not None and sp2s10s < 0:
            alerts.append(("error",   f"🔴 2s10s yield curve inverted ({sp2s10s:.2f}%)"))
        if sp3m10s is not None and sp3m10s < 0:
            alerts.append(("error",   f"🔴 3m10y inverted ({sp3m10s:.2f}%) — Fed's recession signal"))
        if sahm["triggered"]:
            alerts.append(("error",   "🔴 Sahm Rule triggered"))
        if rec["probability"] and rec["probability"] >= 40:
            alerts.append(("warning", f"🟠 Recession probability elevated: {rec['probability']}%"))
        if btp_bps and btp_bps > 250:
            alerts.append(("error",   f"🔴 BTP-Bund at fragmentation risk: {btp_bps:.0f}bps"))
        elif btp_bps and btp_bps > 150:
            alerts.append(("warning", f"🟠 BTP-Bund elevated: {btp_bps:.0f}bps"))
        if hy_oas_l and hy_oas_l > 5:
            alerts.append(("warning", f"🟠 US HY spreads elevated: {hy_oas_l:.2f}%"))
        if cpi_l and cpi_l > 3:
            alerts.append(("warning", f"🟡 US CPI above 3%: {cpi_l:.2f}%"))
        if eu_hicp_l and eu_hicp_l > 3:
            alerts.append(("warning", f"🟡 EU HICP above 3%: {eu_hicp_l:.2f}%"))

        if not alerts:
            st.success("No major macro alerts at this time.")
        else:
            for kind, msg in alerts:
                if kind == "error":    st.error(msg)
                elif kind == "warning": st.warning(msg)
                else:                   st.info(msg)

        # Next upcoming events mini-strip
        if upcoming_evts:
            st.markdown('<hr class="sect-div">', unsafe_allow_html=True)
            st.markdown("**📅 Next on the Calendar**")
            up_cols = st.columns(4)
            for i, evt in enumerate(upcoming_evts[:4]):
                with up_cols[i]:
                    dot = importance_dot(evt["importance"])
                    apx = "~" if evt.get("approximate") else ""
                    st.metric(f"{flag(evt['country'])} {evt['name'][:25]}",
                              f"{apx}{evt['date'].strftime('%b %d')}",
                              f"Prev: {evt.get('prev_fmt','—')}")


# ══════════════════════════════════════════════════════════════════════════════
# ECONOMIC CALENDAR
# ══════════════════════════════════════════════════════════════════════════════

with tab_cal:
    if not finnhub_key:
        st.info(
            "**💡 Add a free FinnHub API key** (sidebar) to unlock consensus forecasts, "
            "exact release times, and beat/miss classification on all events. "
            "Free account at **finnhub.io**. Without it, you still see the full schedule "
            "with previous values and actuals via FRED.", icon="ℹ️"
        )

    cal_hdr, cal_refresh = st.columns([5,1])
    with cal_hdr:
        src_label = "FinnHub + FOMC/ECB schedule" if finnhub_key else "FRED data + FOMC/ECB schedule (approx. dates)"
        st.caption(f"Source: {src_label} · Cache: 15 min")
    with cal_refresh:
        if st.button("↻ Refresh", key="cal_refresh", use_container_width=True):
            st.cache_data.clear(); st.rerun()

    # Column headers
    def _cal_header():
        st.markdown("""
        <div style="display:grid;grid-template-columns:90px 24px 16px 1fr 70px 90px 90px 120px;
                    gap:8px;padding:6px 14px;font-size:10px;font-weight:700;letter-spacing:0.8px;
                    text-transform:uppercase;color:#3D4A5C;border-bottom:1px solid #1C2538;
                    margin-bottom:4px">
          <span>Date</span><span></span><span></span><span>Event</span>
          <span style="text-align:right">Prev</span>
          <span style="text-align:right">Forecast</span>
          <span style="text-align:right">Actual</span>
          <span>Signal</span>
        </div>""", unsafe_allow_html=True)

    def _cal_row(evt: dict, is_today: bool = False):
        bg     = "background:#1A2035;" if is_today else ""
        border = "border-left-color:#F7931A;" if is_today else ""
        dot    = importance_dot(evt["importance"])
        fl     = flag(evt["country"])
        name   = evt["name"]
        apx    = "~" if evt.get("approximate") else ""
        date_s = evt["date"].strftime("%b %d")
        time_s = evt.get("time_et","") or ""

        prev_s  = evt.get("prev_fmt")  or evt.get("prev")  or "—"
        fcast_s = evt.get("forecast_fmt") or (evt.get("forecast") and f"{evt['forecast']:.2f}") or "—"
        act_s   = evt.get("actual_fmt") or (evt.get("actual") and f"{evt['actual']:.2f}") or "—"
        bm      = evt.get("beat_miss") or ""

        bm_class = ""
        if "BEAT" in bm or "COOLER" in bm: bm_class = "beat"
        elif "MISS" in bm or "HOTTER" in bm: bm_class = "miss"
        elif "IN-LINE" in bm: bm_class = "inline"

        act_color = "#00C896" if bm_class=="beat" else "#FF4757" if bm_class=="miss" else "#E2E8F0"
        upcom_cls = 'class="upcoming-tag"' if evt["status"]=="upcoming" else ""
        act_span  = f'<span style="color:{act_color};font-weight:700">{act_s}</span>' if act_s != "—" else '<span style="color:#3D4A5C">—</span>'

        st.markdown(f"""
        <div class="cal-row" style="{bg}{border}">
          <span class="cal-date">{apx}{date_s}{f"<br><span style='font-size:9px;color:#3D4A5C'>{time_s} ET</span>" if time_s else ""}</span>
          <span>{fl}</span>
          <span>{dot}</span>
          <span class="cal-name">{name}</span>
          <span class="cal-val">{prev_s}</span>
          <span class="cal-est">{fcast_s}</span>
          <span class="cal-act">{act_span}</span>
          <span class="{bm_class}">{bm}</span>
        </div>""", unsafe_allow_html=True)

    # ── Today ─────────────────────────────────────────────────────────────────
    if today_evts:
        st.markdown(f"### 📅 Today — {dt.date.today().strftime('%A, %B %d %Y')}")
        _cal_header()
        for e in today_evts:
            _cal_row(e, is_today=True)

    # ── Upcoming ──────────────────────────────────────────────────────────────
    st.markdown(f"### Upcoming Releases {'(next 45 days)' if finnhub_key else '(approximate dates, next 60 days)'}")
    st.caption("🔴 = High impact · 🟡 = Medium impact · ~ = Approximate date")
    _cal_header()

    imp_filter = st.multiselect("Filter by importance", ["high","medium","low"],
                                 default=["high","medium"], label_visibility="collapsed")
    filtered_up = [e for e in upcoming_evts if e["importance"] in imp_filter]
    if not filtered_up:
        st.info("No upcoming events matching filter.")
    else:
        last_month = None
        for e in filtered_up:
            month_lbl = e["date"].strftime("%B %Y")
            if month_lbl != last_month:
                st.markdown(f'<p style="font-size:11px;font-weight:700;color:#3D4A5C;'
                            f'letter-spacing:0.8px;text-transform:uppercase;'
                            f'margin:12px 0 4px">{month_lbl}</p>', unsafe_allow_html=True)
                last_month = month_lbl
            _cal_row(e)

    # ── Recent releases ────────────────────────────────────────────────────────
    if recent_evts:
        st.markdown("### Recent Releases (past 21 days)")
        _cal_header()
        for e in recent_evts:
            _cal_row(e)

    st.markdown('<hr class="sect-div">', unsafe_allow_html=True)
    st.caption(
        "**Beat/Miss logic:** For inflation (CPI, PCE, HICP) — actual > forecast = 🔴 HOTTER (hawkish); "
        "actual < forecast = 🟢 COOLER (dovish). For growth/jobs — actual > forecast = 🟢 BEAT; "
        "actual < forecast = 🔴 MISS. Consensus forecasts require FinnHub API key."
    )


# ══════════════════════════════════════════════════════════════════════════════
# MACRO NEWS
# ══════════════════════════════════════════════════════════════════════════════

with tab_news:
    hdr, btn = st.columns([5,1])
    with hdr:
        st.caption("Reuters · CNBC · MarketWatch · Investing.com — auto-classified by impact · 30-min cache")
    with btn:
        if st.button("↻ Refresh", key="news_refresh", use_container_width=True):
            fetch_all_macro_news.clear(); st.rerun()

    filter_tags = st.multiselect(
        "Filter by tag", list(IMPACT_CATEGORIES.keys()),
        format_func=lambda k: IMPACT_CATEGORIES[k]["label"],
        default=[], placeholder="Show all", label_visibility="collapsed",
    )

    with st.spinner("Fetching macro news…"):
        articles = fetch_all_macro_news()

    if not articles:
        st.warning("Could not fetch news — check network or try refreshing.")
    else:
        if filter_tags:
            articles = [a for a in articles if any(t in a["tags"] for t in filter_tags)]

        COLOR_MAP = {
            "hawkish":"#FF4757","dovish":"#00C896","risk_off":"#FFA502",
            "risk_on":"#00C864","inflation":"#FF6B6B","fed":"#4E9AFF",
            "ecb":"#00C896","labor":"#A55EEA","geopolitical":"#FF7088","crypto":"#F7931A",
        }

        for art in articles:
            badges_html = "".join(
                f'<span class="badge badge-{t}">{IMPACT_CATEGORIES[t]["label"]}</span>'
                for t in art["tags"] if t in IMPACT_CATEGORIES
            )
            border = COLOR_MAP.get(art["tags"][0], "#1C2538") if art["tags"] else "#1C2538"
            ttl = art["title"].replace("<","&lt;").replace(">","&gt;")
            dsc = art["desc"].replace("<","&lt;").replace(">","&gt;")[:200]
            link_open  = f'<a href="{art["link"]}" target="_blank" style="text-decoration:none">' if art["link"] else ""
            link_close = "</a>" if art["link"] else ""

            st.markdown(f"""
            <div class="card" style="border-left-color:{border}">
              <div class="card-meta">{art['source']} · {art['time_ago']} &nbsp; {badges_html}</div>
              {link_open}<div class="card-title">{ttl}</div>{link_close}
              <div class="card-sub">{dsc}{'…' if len(art['desc'])>200 else ''}</div>
            </div>""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# BITCOIN
# ══════════════════════════════════════════════════════════════════════════════

with tab_crypto:
    cg      = fetch_btc_coingecko()
    cg_glob = fetch_crypto_global()
    fg      = fetch_fear_greed()
    hr      = fetch_btc_hashrate()
    btc_df  = fetch_btc_history(period=yahoo_period)
    halving = halving_cycle_info()
    tech    = compute_btc_technicals(btc_df) if not btc_df.empty else {}

    btc_price = cg.get("price") or (btc_df["Close"].iloc[-1] if not btc_df.empty else None)

    # Top bar
    if btc_price:
        chg24 = cg.get("change_24h") or 0
        c_chg = "#00C896" if chg24 >= 0 else "#FF4757"
        sign  = "+" if chg24 >= 0 else ""
        mc    = cg.get("market_cap"); dom = cg_glob.get("btc_dominance")
        vol   = cg.get("volume_24h")
        mc_s  = f"${mc/1e9:.0f}B"  if mc  else "—"
        dom_s = f"{dom:.1f}%"      if dom else "—"
        vol_s = f"${vol/1e9:.1f}B" if vol else "—"
        st.markdown(f"""
        <div style="background:#141928;border:1px solid #1C2538;border-radius:10px;
                    padding:16px 24px;margin-bottom:16px;display:flex;
                    align-items:center;gap:36px;flex-wrap:wrap">
          <div>
            <div style="font-size:10px;font-weight:700;letter-spacing:1px;color:#3D4A5C;text-transform:uppercase">Bitcoin</div>
            <div style="font-size:34px;font-weight:800;color:#E2E8F0;letter-spacing:-1px">${btc_price:,.0f}</div>
            <div style="font-size:13px;font-weight:700;color:{c_chg}">{sign}{chg24:.2f}% (24h)</div>
          </div>
          <div style="display:flex;gap:28px;flex-wrap:wrap">
            {"".join(f'<div><div style="font-size:9px;font-weight:700;color:#3D4A5C;text-transform:uppercase;letter-spacing:0.8px">{lbl}</div><div style="font-size:17px;font-weight:700;color:#E2E8F0">{val}</div></div>' for lbl,val in [("Market Cap",mc_s),("Dominance",dom_s),("Volume 24h",vol_s),("Cycle",halving["cycle_label"])])}
          </div>
        </div>""", unsafe_allow_html=True)

    btc_t1, btc_t2 = st.tabs(["₿ Price & Technicals", "📊 On-Chain & Risk"])

    # ── Price & Technicals ────────────────────────────────────────────────────
    with btc_t1:
        c1,c2,c3,c4,c5 = st.columns(5)
        for col, val, lbl, fmt in [
            (c1, cg.get("change_24h"),     "24h Change",      "{:+.2f}%"),
            (c2, cg.get("change_7d"),      "7d Change",       "{:+.2f}%"),
            (c3, cg.get("change_30d"),     "30d Change",      "{:+.2f}%"),
            (c4, cg.get("ath_change"),     "From ATH",        "{:.1f}%"),
            (c5, tech.get("mayer_multiple"),"Mayer Multiple", "{:.3f}"),
        ]:
            if val is not None: col.metric(lbl, fmt.format(val))

        c1,c2,c3,_ = st.columns(4)
        if cg.get("ath"):       c1.metric("All-Time High", f"${cg['ath']:,.0f}")
        if cg.get("circulating"):c2.metric("Circulating",  f"{cg['circulating']/1e6:.3f}M BTC")
        if cg.get("circulating") and cg.get("max_supply"):
            pct = cg["circulating"]/cg["max_supply"]*100
            c3.metric("% of 21M Mined", f"{pct:.2f}%")

        # Price chart + MAs
        if not btc_df.empty:
            close = btc_df["Close"].dropna()
            fig_btc = _fig(title="Bitcoin Price (USD)", yaxis_title="USD",
                           height=320, showlegend=True)
            fig_btc.add_trace(go.Scatter(x=close.index, y=close.values, name="BTC",
                                          mode="lines", line=dict(color="#F7931A",width=2),
                                          fill="tozeroy", fillcolor="rgba(247,147,26,0.07)"))
            if tech.get("ma200_series") is not None:
                m200 = tech["ma200_series"].dropna()
                fig_btc.add_trace(go.Scatter(x=m200.index, y=m200.values, name="200D MA",
                                              mode="lines", line=dict(color="#4E9AFF",width=1.4,dash="dot")))
            if tech.get("ma50_series") is not None:
                m50 = tech["ma50_series"].dropna()
                fig_btc.add_trace(go.Scatter(x=m50.index, y=m50.values, name="50D MA",
                                              mode="lines", line=dict(color="#A55EEA",width=1.2,dash="dot")))
            fig_btc.update_xaxes(rangeselector=_RANGE_BUTTONS, rangeslider=dict(visible=False))
            st.plotly_chart(fig_btc, use_container_width=True)

        st.markdown('<hr class="sect-div">', unsafe_allow_html=True)

        # Mayer Multiple
        if tech.get("mayer_series") is not None:
            mm = tech["mayer_series"].dropna()
            fig_mm = line_chart(mm, "Mayer Multiple (Price / 200D MA)", "ratio",
                                hlines=[
                                    {"y":2.4,"color":"#FF4757","label":"2.4 — euphoric"},
                                    {"y":1.0,"color":"#4A5568","label":"1.0 — at 200D MA"},
                                    {"y":0.6,"color":"#00C896","label":"0.6 — oversold"},
                                ], color="#F7931A", height=220)
            st.plotly_chart(fig_mm, use_container_width=True)
            st.caption("Mayer Multiple > 2.4 → historically near cycle tops. < 0.6 → historically deep value.")

        st.markdown('<hr class="sect-div">', unsafe_allow_html=True)

        # Halving cycle
        st.markdown("**Halving Cycle Tracker**")
        c1,c2,c3,c4 = st.columns(4)
        c1.metric("Last Halving",  halving["last_halving"])
        c2.metric("Next Halving",  halving["next_halving"])
        c3.metric("Days Since",    f"{halving['days_since']:,}")
        c4.metric("Days to Next",  f"{halving['days_to_next']:,}")
        st.progress(halving["pct_through"]/100)
        st.caption(f"{halving['pct_through']:.1f}% through current 4-year cycle — **{halving['cycle_label']}**")

    # ── On-Chain & Risk ───────────────────────────────────────────────────────
    with btc_t2:
        col_gauge, col_mining = st.columns([1, 2])

        with col_gauge:
            if fg.get("value") is not None:
                val   = fg["value"]; lbl = fg.get("label","")
                gc    = ("#FF4757" if val<25 else "#FF7043" if val<45 else
                         "#FFA502" if val<55 else "#00C896" if val<75 else "#00E676")
                fig_fg = go.Figure(go.Indicator(
                    mode="gauge+number",
                    value=val,
                    title={"text": f"<b>Fear & Greed</b><br><span style='font-size:12px;color:#9AA5B4'>{lbl}</span>",
                           "font": {"size":14,"color":"#E2E8F0"}},
                    number={"font":{"size":42,"color":gc}},
                    gauge={
                        "axis":{"range":[0,100],"tickwidth":1,"tickcolor":"#3D4A5C",
                                "tickfont":{"color":"#3D4A5C","size":8}},
                        "bar":{"color":gc,"thickness":0.22},
                        "bgcolor":"#141928","borderwidth":0,
                        "steps":[
                            {"range":[0, 25],"color":"rgba(255,71,87,0.16)"},
                            {"range":[25,45],"color":"rgba(255,112,67,0.13)"},
                            {"range":[45,55],"color":"rgba(255,165,2,0.13)"},
                            {"range":[55,75],"color":"rgba(0,200,150,0.10)"},
                            {"range":[75,100],"color":"rgba(0,230,118,0.15)"},
                        ],
                        "threshold":{"line":{"color":gc,"width":3},"thickness":0.8,"value":val},
                    }
                ))
                fig_fg.update_layout(paper_bgcolor="rgba(0,0,0,0)",
                                      font=dict(family="Inter, sans-serif"),
                                      height=220, margin=dict(l=16,r=16,t=50,b=10))
                st.plotly_chart(fig_fg, use_container_width=True)
                st.caption("0 = Extreme Fear → historically good entries\n"
                           "100 = Extreme Greed → historically caution territory")

        with col_mining:
            st.markdown("**Mining & Network Security**")
            if hr:
                c1,c2 = st.columns(2)
                if hr.get("hashrate_ehs"):  c1.metric("Hash Rate",     f"{hr['hashrate_ehs']:.1f} EH/s")
                if hr.get("difficulty"):     c2.metric("Difficulty",    f"{hr['difficulty']/1e12:.2f}T")
                c1,c2 = st.columns(2)
                if hr.get("difficulty_change_pct") is not None:
                    c1.metric("Next Adjustment", f"{hr['difficulty_change_pct']:+.2f}%")
                if hr.get("remaining_blocks"):
                    c2.metric("Blocks to Retarget", f"{hr['remaining_blocks']:,}")

            # Fear & Greed 30-day history
            if fg.get("history"):
                hist_df = pd.DataFrame(fg["history"])
                hist_df["date"] = pd.to_datetime(hist_df["date"], unit="s")
                hist_df = hist_df.sort_values("date")
                fig_fgh = _fig(title="Fear & Greed — 30D History", height=175, range_selector=False)
                fig_fgh.add_trace(go.Bar(
                    x=hist_df["date"], y=hist_df["value"],
                    marker_color=[
                        "#FF4757" if v<25 else "#FF7043" if v<45 else
                        "#FFA502" if v<55 else "#00C896" if v<75 else "#00E676"
                        for v in hist_df["value"]
                    ],
                    hovertemplate="%{y}<extra></extra>",
                ))
                fig_fgh.add_hline(y=50, line_dash="dot", line_color="#3D4A5C", line_width=1)
                st.plotly_chart(fig_fgh, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# MACRO TAB
# ══════════════════════════════════════════════════════════════════════════════

with tab_macro:
    if fred_data is None:
        st.warning("Enter your FRED API key in the sidebar to load macro data.")
    else:
        r_us, r_eu, r_uk = st.tabs(["🇺🇸 United States", "🇪🇺 Euro Area", "🇬🇧 United Kingdom"])

        # ═══ US ═══════════════════════════════════════════════════════════════
        with r_us:
            sect("Monetary Policy")
            ffr=_s("fed_funds"); core_pce=_s("core_pce_yoy")
            ffr_l=_latest("fed_funds"); core_pce_l=_latest("core_pce_yoy")
            real_ffr=compute_real_fed_funds(ffr, core_pce)
            c1,c2,c3=st.columns(3)
            if ffr_l:       c1.metric("Fed Funds Rate",      f"{ffr_l:.2f}%")
            if not real_ffr.empty:
                c2.metric("Real Fed Funds Rate",  f"{real_ffr.dropna().iloc[-1]:.2f}%",
                          help="FFR minus Core PCE — true tightness gauge")
            if core_pce_l: c3.metric("Core PCE (Fed target)", f"{core_pce_l:.2f}%")
            col_a,col_b=st.columns(2)
            if ffr:       chart_col(col_a,ffr.dropna(),"Fed Funds Rate","%")
            if not real_ffr.empty:
                chart_col(col_b,real_ffr.dropna(),"Real Fed Funds Rate","%",
                          hlines=[{"y":0,"color":"#4A5568","label":"Neutral"}])

            sect("Yield Curve & Treasury Yields")
            y3m=_s("3m_yield"); y2=_s("2y_yield"); y10=_s("10y_yield"); y30=_s("30y_yield")
            y3m_l=_latest("3m_yield"); y2_l=_latest("2y_yield")
            y10_l=_latest("10y_yield"); y30_l=_latest("30y_yield")
            sp2=(y10_l-y2_l) if (y10_l and y2_l) else None
            sp3=(y10_l-y3m_l) if (y10_l and y3m_l) else None
            c1,c2,c3,c4=st.columns(4)
            for col,val,lbl in [(c1,y3m_l,"3M"),(c2,y2_l,"2Y"),(c3,y10_l,"10Y"),(c4,y30_l,"30Y")]:
                if val: col.metric(f"{lbl} Yield",f"{val:.2f}%")
            c1,c2=st.columns(2)
            if sp2 is not None: c1.metric("2s10s Spread",f"{sp2:.2f}%",yield_curve_status(sp2)["label"])
            if sp3 is not None: c2.metric("3m10y Spread",f"{sp3:.2f}%",yield_curve_status(sp3)["label"],
                                           help="Fed's preferred recession indicator")
            col_a,col_b=st.columns(2)
            if y2 and y10:
                chart_col(col_a,(y10-y2).dropna(),"2s10s Spread","%",
                          hlines=[{"y":0,"color":"#FF4757","label":"Inversion"}])
            if y3m and y10:
                chart_col(col_b,(y10-y3m).dropna(),"3m10y Spread","%",
                          hlines=[{"y":0,"color":"#FF4757","label":"Inversion"}])
            if any(s is not None for s in [y3m,y2,y10,y30]):
                fig_yc=multi_line_chart({"3M":y3m,"2Y":y2,"10Y":y10,"30Y":y30},
                                         "US Treasury Yield Curve — All Tenors","%")
                st.plotly_chart(fig_yc,use_container_width=True)
            col_a,col_b=st.columns(2)
            if y2:  chart_col(col_a,y2.dropna(), "2Y Treasury","%","2y_yield")
            if y10: chart_col(col_b,y10.dropna(),"10Y Treasury","%","10y_yield")

            sect("Real Yields & Inflation Expectations",
                 "Real yields (TIPS) strip out inflation and drive risk-asset valuations. "
                 "Positive real yields create genuine competition for equities.")
            r10=_s("real_10y"); be=_s("breakeven_10y")
            c1,c2=st.columns(2)
            if _latest("real_10y"): c1.metric("10Y Real (TIPS)",f"{_latest('real_10y'):.2f}%")
            if _latest("breakeven_10y"): c2.metric("10Y Breakeven",f"{_latest('breakeven_10y'):.2f}%")
            col_a,col_b=st.columns(2)
            if r10: chart_col(col_a,r10.dropna(),"10Y TIPS Real Yield","%",
                              hlines=[{"y":0,"color":"#4A5568","label":"Zero"}])
            if be:  chart_col(col_b,be.dropna(),"10Y Breakeven Inflation","%",
                              hlines=[{"y":2.0,"color":"#FFA502","dash":"dot","label":"2%"}])

            sect("Inflation — CPI, PCE & PPI")
            cpi=_s("cpi_yoy"); cc=_s("core_cpi_yoy")
            pce=_s("pce_yoy"); cpce=_s("core_pce_yoy"); ppi=_s("ppi_yoy")
            c1,c2,c3,c4,c5=st.columns(5)
            for col,key,lbl in [(c1,"cpi_yoy","CPI"),(c2,"core_cpi_yoy","Core CPI"),
                                (c3,"pce_yoy","PCE"),(c4,"core_pce_yoy","Core PCE"),(c5,"ppi_yoy","PPI")]:
                v=_latest(key)
                if v is not None:
                    g=cpi_vs_target(v)
                    col.metric(lbl,f"{v:.2f}%",f"{g['gap']:+.2f}pp vs 2%")
            fig_inf=multi_line_chart({"CPI":cpi,"Core CPI":cc,"PCE":pce,"Core PCE":cpce},
                                      "US Inflation (YoY %)","%")
            fig_inf.add_hline(y=2.0,line_dash="dash",line_color="#FFA502",line_width=1,
                              annotation_text="2%",annotation_font_size=9,annotation_font_color="#8896A8")
            st.plotly_chart(fig_inf,use_container_width=True)
            col_a,col_b=st.columns(2)
            if pce:  chart_col(col_a,pce.dropna(),"PCE Inflation YoY","%",
                               hlines=[{"y":2.0,"color":"#FFA502","label":"2%"}])
            if ppi:  chart_col(col_b,ppi.dropna(),"PPI YoY %","%")
            st.caption("Core PCE is the Fed's primary target. PPI typically leads CPI by 3-6 months.")
            zscore_pill("core_pce_yoy")

            sect("Labor Market")
            unemp=_s("unemployment"); nfp=_s("nfp"); claims=_s("initial_claims")
            sahm=compute_sahm_rule(unemp)
            c1,c2,c3,c4=st.columns(4)
            if _latest("unemployment"):
                tr=series_trend(unemp,3)
                c1.metric("Unemployment",f"{_latest('unemployment'):.2f}%",f"{tr:+.2f}pp vs 3m" if tr else None)
            if nfp is not None and not nfp.dropna().empty:
                mom=nfp.dropna().diff().iloc[-1]
                c2.metric("NFP (k)",f"{nfp.dropna().iloc[-1]:,.0f}",f"{mom:+,.0f} MoM")
            if _latest("initial_claims"):
                tr2=series_trend(claims,4)
                c3.metric("Init. Claims",f"{_latest('initial_claims'):,.0f}",f"{tr2:+,.0f} vs 4wk" if tr2 else None)
            if sahm["value"] is not None:
                c4.metric("Sahm Rule",f"{sahm['value']:.2f}pp","🔴 Triggered" if sahm["triggered"] else "🟢 Clear")
            if sahm["triggered"]:
                st.error("🔴 **Sahm Rule triggered** — early recession signal.",icon="🚨")
            col_a,col_b=st.columns(2)
            if unemp: chart_col(col_a,unemp.dropna(),"Unemployment Rate","%")
            if claims: chart_col(col_b,claims.dropna(),"Initial Claims","persons",
                                 hlines=[{"y":300000,"color":"#FFA502","label":"~300k elevated"}])
            if sahm["series"] is not None:
                fig_sahm=line_chart(sahm["series"].dropna(),"Sahm Rule Indicator","pp",
                                    hlines=[{"y":0.50,"color":"#FF4757","label":"Trigger (0.50)"}])
                st.plotly_chart(fig_sahm,use_container_width=True)

            sect("Leading Indicators")
            c1,c2,c3,c4=st.columns(4)
            for col,key,lbl,fmt in [
                (c1,"retail_sales_yoy","Retail Sales YoY","{:.2f}%"),
                (c2,"housing_starts","Housing Starts (k)","{:,.0f}"),
                (c3,"consumer_sentiment","UMich Sentiment","{:.1f}"),
                (c4,"m2_yoy","M2 YoY %","{:.2f}%"),
            ]:
                v=_latest(key)
                if v is not None:
                    tr=series_trend(_s(key),3)
                    col.metric(lbl,fmt.format(v),f"{tr:+.2f} vs 3m" if tr else None)
            col_a,col_b=st.columns(2)
            rs=_s("retail_sales_yoy"); hs=_s("housing_starts")
            if rs: chart_col(col_a,rs.dropna(),"Retail Sales YoY","%",hlines=[{"y":0,"color":"#4A5568","label":"Zero"}])
            if hs: chart_col(col_b,hs.dropna(),"Housing Starts","k")
            col_a,col_b=st.columns(2)
            se=_s("consumer_sentiment"); m2=_s("m2_yoy")
            if se: chart_col(col_a,se.dropna(),"UMich Consumer Sentiment","index")
            if m2: chart_col(col_b,m2.dropna(),"M2 Money Supply YoY","%",
                             hlines=[{"y":0,"color":"#FF4757","label":"Contraction"}])

            sect("Growth (CFNAI) & Credit Spreads")
            cfnai=_s("cfnai"); hy=_s("hy_oas"); ig=_s("ig_oas")
            cfnai_l=_latest("cfnai"); hy_l=_latest("hy_oas"); ig_l=_latest("ig_oas")
            cst=credit_spread_status(hy_l)
            c1,c2,c3=st.columns(3)
            if cfnai_l: c1.metric("CFNAI",f"{cfnai_l:.2f}","▲ Above trend" if cfnai_l>0 else "▼ Below trend")
            if hy_l:    c2.metric("HY OAS",f"{hy_l:.2f}%",cst["label"])
            if ig_l:    c3.metric("IG OAS",f"{ig_l:.2f}%")
            if cst["status"] in ("elevated","crisis"):
                st.warning(f"{cst['label']}",icon="📉")
            col_a,col_b=st.columns(2)
            if cfnai: chart_col(col_a,cfnai.dropna(),"CFNAI","index",
                                hlines=[{"y":0,"color":"#4A5568","label":"Trend"},
                                        {"y":-0.7,"color":"#FF4757","dash":"dot","label":"Recession risk"}])
            if hy:    chart_col(col_b,hy.dropna(),"HY Credit Spread (OAS)","%",
                                hlines=[{"y":5,"color":"#FFA502","label":"Elevated"},
                                        {"y":8,"color":"#FF4757","label":"Crisis"}])

        # ═══ EU ═══════════════════════════════════════════════════════════════
        with r_eu:
            sect("ECB Monetary Policy")
            ecb_rate=_s("ecb_deposit_rate"); eu_10y=_s("eu_10y_yield")
            ecb_l=_latest("ecb_deposit_rate"); eu_10y_l=_latest("eu_10y_yield")
            c1,c2=st.columns(2)
            if ecb_l:    c1.metric("ECB Deposit Rate",f"{ecb_l:.2f}%")
            if eu_10y_l: c2.metric("Euro Area 10Y",   f"{eu_10y_l:.2f}%")
            col_a,col_b=st.columns(2)
            if ecb_rate: chart_col(col_a,ecb_rate.dropna(),"ECB Deposit Rate","%")
            if eu_10y:   chart_col(col_b,eu_10y.dropna(),"Euro Area 10Y Yield","%","eu_10y_yield")

            sect("Sovereign Yields & BTP-Bund Spread",
                 "BTP-Bund = Italy 10Y minus Germany 10Y in bps. The primary EU fragmentation risk gauge.")
            de=_s("de_10y_yield"); it=_s("it_10y_yield")
            fr=_s("fr_10y_yield"); es=_s("es_10y_yield")
            de_l=_latest("de_10y_yield"); it_l=_latest("it_10y_yield")
            fr_l=_latest("fr_10y_yield"); es_l=_latest("es_10y_yield")
            c1,c2,c3,c4=st.columns(4)
            for col,val,lbl in [(c1,de_l,"Germany (Bund)"),(c2,it_l,"Italy (BTP)"),
                                (c3,fr_l,"France (OAT)"),(c4,es_l,"Spain (Bonos)")]:
                if val: col.metric(f"{lbl} 10Y",f"{val:.2f}%")
            btp=compute_btp_bund_spread(it,de)
            if not btp.empty:
                btp_l=btp.dropna().iloc[-1]; btp_st=btp_bund_status(btp_l)
                tr_b=series_trend(btp,3)
                c1,c2=st.columns(2)
                c1.metric("BTP-Bund Spread",f"{btp_l:.0f} bps",btp_st["label"])
                if tr_b: c2.metric("vs 3m ago",f"{tr_b:+.0f}bps")
                if btp_st["status"] in ("elevated","stress"):
                    st.warning(f"{btp_st['label']} — {btp_l:.0f}bps. ECB steps in above ~200-250bps.",icon="⚠️")
                col_a,col_b=st.columns(2)
                chart_col(col_a,btp.dropna(),"BTP-Bund Spread","bps",
                          hlines=[{"y":150,"color":"#FFA502","label":"Elevated (150bps)"},
                                  {"y":250,"color":"#FF4757","label":"Crisis (250bps)"}])
                with col_b:
                    fig_cy=multi_line_chart({"Germany":de,"Italy":it,"France":fr,"Spain":es},
                                             "Euro Area 10Y Sovereign Yields","%")
                    st.plotly_chart(fig_cy,use_container_width=True)

            sect("HICP Inflation & Labor")
            eu_hicp=_s("eu_hicp"); eu_hicp_l=_latest("eu_hicp")
            eu_u=_s("eu_unemployment"); eu_u_l=_latest("eu_unemployment"); eur=_s("eur_usd")
            c1,c2,c3=st.columns(3)
            if eu_hicp_l:
                g=cpi_vs_target(eu_hicp_l)
                c1.metric("EU HICP YoY",f"{eu_hicp_l:.2f}%",f"{g['gap']:+.2f}pp vs 2%")
                zscore_pill("eu_hicp")
            if eu_u_l:
                tr=series_trend(eu_u,3)
                c2.metric("EU Unemployment",f"{eu_u_l:.2f}%",f"{tr:+.2f}pp vs 3m" if tr else None)
            if _latest("eur_usd"): c3.metric("EUR/USD",f"{_latest('eur_usd'):.4f}")
            col_a,col_b=st.columns(2)
            if eu_hicp:
                fig_hicp=line_chart(eu_hicp.dropna(),"EU HICP YoY %","%",
                                    hlines=[{"y":2.0,"color":"#FFA502","label":"2% ECB target"}])
                with col_a: st.plotly_chart(fig_hicp,use_container_width=True)
            if eur: chart_col(col_b,eur.dropna(),"EUR/USD","USD per EUR","eur_usd")
            eu_reg2=classify_eu_macro_regime(eu_hicp_l,eu_u_l)
            if eu_reg2["regime"]:
                st.markdown(f"**EU Regime: {eu_reg2['label']}** — {eu_reg2['description']}")

        # ═══ UK ═══════════════════════════════════════════════════════════════
        with r_uk:
            sect("Bank of England & UK Rates")
            boe=_s("boe_rate"); uk10=_s("uk_10y_yield")
            c1,c2=st.columns(2)
            if _latest("boe_rate"):    c1.metric("BoE Base Rate",f"{_latest('boe_rate'):.2f}%")
            if _latest("uk_10y_yield"):c2.metric("UK 10Y Gilt",  f"{_latest('uk_10y_yield'):.2f}%")
            col_a,col_b=st.columns(2)
            if boe:  chart_col(col_a,boe.dropna(), "BoE Base Rate","%")
            if uk10: chart_col(col_b,uk10.dropna(),"UK 10Y Gilt Yield","%","uk_10y_yield")

            sect("UK Inflation & Labor")
            uk_cpi=_s("uk_cpi_yoy"); uk_u=_s("uk_unemployment")
            c1,c2=st.columns(2)
            if _latest("uk_cpi_yoy"):
                g=cpi_vs_target(_latest("uk_cpi_yoy"))
                c1.metric("UK CPI YoY",f"{_latest('uk_cpi_yoy'):.2f}%",f"{g['gap']:+.2f}pp vs 2%")
            if _latest("uk_unemployment"):
                tr=series_trend(uk_u,3)
                c2.metric("UK Unemployment",f"{_latest('uk_unemployment'):.2f}%",f"{tr:+.2f}pp vs 3m" if tr else None)
            col_a,col_b=st.columns(2)
            if uk_cpi: chart_col(col_a,uk_cpi.dropna(),"UK CPI YoY %","%",
                                 hlines=[{"y":2.0,"color":"#FFA502","label":"2%"}])
            if uk_u:   chart_col(col_b,uk_u.dropna(),"UK Unemployment","%")

            sect("3-Way Yield Comparison — US / Germany / UK")
            fig_3w=multi_line_chart({"US 10Y":_s("10y_yield"),
                                      "Germany Bund":_s("de_10y_yield"),
                                      "UK Gilt":uk10},
                                     "10Y Yields — US vs DE vs UK","%",height=300)
            st.plotly_chart(fig_3w,use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# MARKETS TAB
# ══════════════════════════════════════════════════════════════════════════════

with tab_markets:
    bench_df  = market_data.get("^GSPC",{}).get("df")
    bench_ret = bench_df["Close"].pct_change() if bench_df is not None else None
    eu_bench_df  = market_data.get("^STOXX50E",{}).get("df")
    eu_bench_ret = eu_bench_df["Close"].pct_change() if eu_bench_df is not None else None

    def snap_grid(tickers, ncols=3):
        cols=st.columns(ncols)
        for i,t in enumerate(tickers):
            meta=market_data.get(t)
            if not meta: continue
            snap=latest_snapshot(meta["df"])
            if snap:
                last,_,pct,_=snap
                cols[i%ncols].metric(meta["label"],f"{last:,.2f}",f"{pct:+.2f}%",help=t)
            else:
                cols[i%ncols].metric(meta["label"],"N/A")

    def chart_grid(tickers, ncols=2, color="#00C896"):
        cols=st.columns(ncols); i=0
        for t in tickers:
            meta=market_data.get(t)
            if not meta or meta["df"] is None or meta["df"].empty: continue
            chart_col(cols[i%ncols],meta["df"]["Close"],f"{meta['label']} ({t})","",t,color=color)
            i+=1

    def beta_grid(tickers, br, ncols=3):
        if br is None: st.warning("Benchmark unavailable."); return
        cols=st.columns(ncols); i=0
        for t in tickers:
            meta=market_data.get(t)
            if not meta or meta["df"] is None or meta["df"].empty: continue
            beta=compute_beta(meta["df"]["Close"].pct_change(),br)
            cols[i%ncols].metric(meta["label"],f"{beta:.2f}" if pd.notna(beta) else "N/A")
            i+=1

    mkt_us, mkt_fi, mkt_comm, mkt_eu, mkt_sect = st.tabs(
        ["🇺🇸 US Equity","💵 Fixed Income","🪙 Commodities & FX","🇪🇺 EU Markets","📊 Sectors"]
    )

    with mkt_us:
        snap_grid(["^GSPC","^IXIC","^DJI","IWM","^VIX"])
        sect("Historical Charts")
        chart_grid(["^GSPC","^IXIC","^DJI","IWM"])
        sect("Beta vs S&P 500")
        beta_grid(["^IXIC","^DJI","IWM","^VIX"],bench_ret)

    with mkt_fi:
        snap_grid(["TLT","SHY","TIP","HYG","LQD"])
        sect("Historical Charts")
        chart_grid(["TLT","SHY","TIP","HYG","LQD"])
        # HYG/LQD stress
        sect("HYG/LQD Credit Stress Proxy",
             "Falling = HY underperforming IG = credit risk widening in real time.")
        hyg_df=market_data.get("HYG",{}).get("df"); lqd_df=market_data.get("LQD",{}).get("df")
        if hyg_df is not None and lqd_df is not None and not hyg_df.empty and not lqd_df.empty:
            ratio=(hyg_df["Close"]/hyg_df["Close"].iloc[0]*100)/(lqd_df["Close"]/lqd_df["Close"].iloc[0]*100)
            st.plotly_chart(line_chart(ratio,"HYG/LQD Relative Performance (rebased=100)","ratio",
                                        color="#FFA502",height=220),use_container_width=True)
        sect("Beta vs S&P 500")
        beta_grid(["TLT","SHY","TIP","HYG","LQD"],bench_ret)

    with mkt_comm:
        st.caption("**Copper (HG=F)** is a leading global growth indicator — real-time economic demand gauge.")
        snap_grid(["GC=F","SI=F","CL=F","NG=F","HG=F"])
        chart_grid(["GC=F","SI=F","CL=F","NG=F","HG=F"])
        sect("USD & FX")
        snap_grid(["DX-Y.NYB","EURUSD=X","GBPUSD=X","JPY=X","CHF=X"])
        chart_grid(["DX-Y.NYB","EURUSD=X","GBPUSD=X","JPY=X","CHF=X"],color="#4E9AFF")

    with mkt_eu:
        snap_grid(["^STOXX50E","^GDAXI","^FTSE","^FCHI","FTSEMIB.MI","^IBEX"])
        sect("Historical Charts")
        chart_grid(["^STOXX50E","^GDAXI","^FTSE","^FCHI","FTSEMIB.MI","^IBEX"])
        sect("Beta vs Euro Stoxx 50")
        beta_grid(["^GDAXI","^FTSE","^FCHI","FTSEMIB.MI","^IBEX"],eu_bench_ret)

    with mkt_sect:
        sects=["XLF","XLE","XLK","XLV","XLU","XLI"]
        st.caption("Sector rotation tells you where in the cycle: Fin/Ind = early · Tech = mid · Energy/Util/HC = late.")
        snap_grid(sects)
        rebase={}
        for t in sects:
            df2=market_data.get(t,{}).get("df"); lbl=market_data.get(t,{}).get("label",t)
            if df2 is not None and not df2.empty:
                rebase[lbl]=df2["Close"]/df2["Close"].iloc[0]*100
        if rebase:
            st.plotly_chart(multi_line_chart(rebase,"Sector ETF Relative Performance (rebased=100)","index",height=300),
                             use_container_width=True)
        sect("Beta vs S&P 500")
        beta_grid(sects,bench_ret)


# ══════════════════════════════════════════════════════════════════════════════
# CROSS-ASSET TAB
# ══════════════════════════════════════════════════════════════════════════════

with tab_cross:
    sect("Cross-Asset Correlation Matrix",
         f"Rolling {CORRELATION_WINDOW_DAYS}-day return correlation — current-regime read, not long-run average.")
    corr=compute_correlation_matrix(market_data,CORRELATION_TICKERS,CORRELATION_WINDOW_DAYS)
    if not corr.empty:
        labels=[MARKET_TICKERS.get(t,t) for t in corr.columns]
        hm=go.Figure(data=go.Heatmap(
            z=corr.values,x=labels,y=labels,
            colorscale="RdBu",zmid=0,zmin=-1,zmax=1,
            text=corr.round(2).values,texttemplate="%{text}",textfont={"size":10},
            colorbar=dict(title="Corr.",thickness=12,len=0.9),
        ))
        hm.update_layout(**{k:v for k,v in _BASE.items() if k not in ("height","showlegend","margin")},
                          height=520,margin=dict(l=8,r=8,t=30,b=8),
                          title=f"{CORRELATION_WINDOW_DAYS}-Day Rolling Correlation")
        st.plotly_chart(hm,use_container_width=True)
        st.markdown("""
**Reading:** +1 (red) = moving together — weak diversification · −1 (blue) = opposite — true hedge · ~0 (white) = uncorrelated

**Key tells:** S&P 500 vs TLT flipping negative→positive = bonds stop hedging (inflation regime) ·
Copper decoupling from equities = growth crack forming
        """)
    else:
        st.warning("Not enough data for the correlation matrix.")

    sect("US Recession Probability Scorecard")
    if fred_data is not None:
        y10_l=_latest("10y_yield"); y2_l=_latest("2y_yield"); y3m_l=_latest("3m_yield")
        sp2=(y10_l-y2_l)  if (y10_l and y2_l)  else None
        sp3=(y10_l-y3m_l) if (y10_l and y3m_l) else None
        sahm=compute_sahm_rule(_s("unemployment"))
        hy_l=_latest("hy_oas"); cfnai_l=_latest("cfnai")
        rec=compute_recession_probability(sp2,sp3,sahm["value"],hy_l,cfnai_l)
        if rec["probability"] is not None:
            rp=rec["probability"]
            color="#FF4757" if rp>=70 else "#FFA502" if rp>=40 else "#00C896"
            c1,c2=st.columns([1,3])
            c1.metric("Composite",f"{rp}%",rec["label"])
            with c2: st.progress(rp/100)
            c1,c2,c3=st.columns(3)
            for i,(lbl,val,dlt) in enumerate([
                ("3m10y",f"{sp3:.2f}%" if sp3 else "N/A",yield_curve_status(sp3)["label"] if sp3 else None),
                ("2s10s",f"{sp2:.2f}%" if sp2 else "N/A",yield_curve_status(sp2)["label"] if sp2 else None),
                ("Sahm", f"{sahm['value']:.2f}pp" if sahm["value"] else "N/A","🔴 Triggered" if sahm["triggered"] else "🟢 Clear"),
                ("HY OAS",f"{hy_l:.2f}%" if hy_l else "N/A",credit_spread_status(hy_l)["label"] if hy_l else None),
                ("CFNAI",f"{cfnai_l:.2f}" if cfnai_l else "N/A","Below trend" if (cfnai_l or 0)<0 else "Above trend"),
            ]):
                [c1,c2,c3][i%3].metric(lbl,val,dlt)

    sect("Global Yield & Inflation")
    if fred_data is not None:
        col_a,col_b=st.columns(2)
        with col_a:
            st.plotly_chart(multi_line_chart({"US 10Y":_s("10y_yield"),"Germany":_s("de_10y_yield"),
                                               "Italy BTP":_s("it_10y_yield"),"UK Gilt":_s("uk_10y_yield")},
                                              "10Y Sovereign Yields — Global","%"),use_container_width=True)
        with col_b:
            fig_gi=multi_line_chart({"US CPI":_s("cpi_yoy"),"Core PCE":_s("core_pce_yoy"),
                                      "EU HICP":_s("eu_hicp"),"UK CPI":_s("uk_cpi_yoy")},
                                     "Inflation — US / EU / UK (YoY %)","%")
            fig_gi.add_hline(y=2.0,line_dash="dash",line_color="#4A5568",line_width=1)
            st.plotly_chart(fig_gi,use_container_width=True)

st.markdown(
    '<p style="font-size:10px;color:#1C2538;text-align:center;margin-top:28px">'
    'FRED · Yahoo Finance · CoinGecko · mempool.space · Alternative.me · FinnHub (optional) · '
    'For informational purposes only — not investment advice.</p>',
    unsafe_allow_html=True)
