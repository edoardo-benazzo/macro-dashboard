"""
Macro Dashboard — Institutional Edition
US & Europe macro · Economic calendar · Macro news · Bitcoin
Data: FRED · Yahoo Finance · CoinGecko · mempool.space · Alternative.me
"""

import datetime as dt
import hashlib
import math
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from streamlit_autorefresh import st_autorefresh

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
    compute_recession_probability, compute_positioning_implication,
    compute_policy_tracker, series_trend, get_earnings_calendar,
    # Modules 1-4
    compute_inflation_expectations, compute_forward_rate_curve,
    fetch_cot_data, compute_cot_signals,
    compute_divergence_scanner, compute_cb_tracker_extended,
)
from news_fetcher import fetch_all_news, article_id, SOURCE_TIER_COLOR, detect_todays_releases
from crypto_fetchers import (
    fetch_btc_bybit, fetch_btc_price, fetch_btc_coingecko, fetch_crypto_global,
    fetch_fear_greed, fetch_btc_hashrate, fetch_btc_history,
    fetch_btc_cg_history,
    compute_btc_technicals, halving_cycle_info, compute_s2f,
    _ATH, _JAN25_HIGH, _100K_LEVEL, _CYCLE4_ATH,
    _HALVING_PRICE, _CYCLE_LOW, _REALIZED_PRICE, _MVRV_REALIZED,
)
from calendar_fetcher import get_calendar, flag, importance_dot, beat_miss_label

# ── Global safe formatters ─────────────────────────────────────────────────────

def fmt(value, decimals: int = 2, suffix: str = "", prefix: str = "") -> str:
    """Safe number formatter — never returns nan/None/inf to the UI."""
    try:
        if value is None:
            return "—"
        f = float(value)
        if math.isnan(f) or math.isinf(f):
            return "—"
        return f"{prefix}{f:,.{decimals}f}{suffix}"
    except Exception:
        return "—"


def to_float(x):
    """Extract a plain Python float from any scalar, numpy type, pandas Series, or array."""
    try:
        if x is None:
            return None
        if hasattr(x, 'iloc'):
            x = x.dropna()
            if len(x) == 0:
                return None
            x = x.iloc[-1]
        if hasattr(x, 'ndim') and x.ndim > 0:
            x = x.flat[0]
        if hasattr(x, 'item'):
            x = x.item()
        v = float(x)
        return None if (math.isnan(v) or math.isinf(v)) else v
    except Exception:
        return None


def _safe_delta(value) -> str | None:
    """Return None instead of a NaN/None delta (for st.metric delta parameter)."""
    try:
        if value is None:
            return None
        f = float(value)
        if math.isnan(f) or math.isinf(f):
            return None
        return value  # return as-is (already formatted string or number)
    except Exception:
        return None


# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Macro Dashboard", layout="wide",
                   initial_sidebar_state="collapsed")

st.markdown("""
<style>
/* Kill the rerun overlay completely */
.stApp [data-testid="stAppViewContainer"] {
    opacity: 1 !important;
    transition: none !important;
}
iframe { opacity: 1 !important; }
.stSpinner { display: none !important; }
.stApp { opacity: 1 !important; }

/* Target the actual dimming element */
div[class*="withScreencast"] > div {
    opacity: 1 !important;
    transition: none !important;
}
* { transition: none !important; }
</style>
""", unsafe_allow_html=True)

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
html, body, [class*="css"] {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
}
#MainMenu, footer, header { visibility: hidden; }

/* metric cards */
[data-testid="metric-container"] {
  background: #0A1628; border: 1px solid #1A2540;
  border-radius: 8px; padding: 14px 18px 12px;
  transition: border-color 0.2s;
}
[data-testid="metric-container"]:hover { border-color: #1A6EFF; }
[data-testid="stMetricLabel"] p {
  font-size: 10px !important; font-weight: 700 !important;
  letter-spacing: 0.9px !important; text-transform: uppercase !important;
  color: #4A607A !important;
}
[data-testid="stMetricValue"] {
  font-size: 22px !important; font-weight: 700 !important;
  letter-spacing: -0.5px !important; color: #FFFFFF !important;
}
[data-testid="stMetricDelta"] {
  font-size: 11px !important; color: #A0AEC0 !important;
}

/* tabs */
[data-testid="stTabs"] [data-baseweb="tab-list"] {
  background: transparent; border-bottom: 1px solid #1A2540; gap: 0;
}
[data-testid="stTabs"] [data-baseweb="tab"] {
  font-size: 11px; font-weight: 700; letter-spacing: 0.6px;
  padding: 10px 20px; color: #4A607A; text-transform: uppercase;
  border-bottom: 2px solid transparent;
}
[data-testid="stTabs"] [aria-selected="true"] {
  color: #1A6EFF !important; border-bottom-color: #1A6EFF !important;
  background: transparent !important;
}

/* news & calendar cards */
.card {
  background: #0A1628; border: 1px solid #1A2540;
  border-left: 3px solid #1A2540; border-radius: 0 6px 6px 0;
  padding: 12px 16px 10px; margin: 5px 0; transition: border-left-color 0.2s;
}
.card:hover { border-left-color: #1A6EFF; }
.card-meta  { font-size:10px; font-weight:700; letter-spacing:0.8px; color:#2D3E56; text-transform:uppercase; }
.card-title { font-size:14px; font-weight:600; color:#E2E8F0; line-height:1.45; margin:5px 0 3px; }
.card-sub   { font-size:12px; color:#4A607A; line-height:1.5; margin-top:4px; }

/* badges */
.badge { display:inline-block; padding:2px 7px; border-radius:3px;
         font-size:9px; font-weight:800; letter-spacing:0.7px;
         text-transform:uppercase; margin:0 3px 0 0; vertical-align:middle; }
.badge-hawkish   { background:rgba(255,71,87,.15);   color:#FF4757; border:1px solid rgba(255,71,87,.35); }
.badge-dovish    { background:rgba(0,200,150,.15);   color:#00C896; border:1px solid rgba(0,200,150,.35); }
.badge-risk_off  { background:rgba(255,165,2,.15);   color:#FFA502; border:1px solid rgba(255,165,2,.35); }
.badge-risk_on   { background:rgba(0,200,100,.12);   color:#00C864; border:1px solid rgba(0,200,100,.35); }
.badge-inflation { background:rgba(255,107,107,.15); color:#FF6B6B; border:1px solid rgba(255,107,107,.35); }
.badge-fed       { background:rgba(41,121,255,.15);  color:#2979FF; border:1px solid rgba(41,121,255,.35); }
.badge-ecb       { background:rgba(0,200,150,.12);   color:#00C896; border:1px solid rgba(0,200,150,.30); }
.badge-labor     { background:rgba(165,94,234,.15);  color:#A55EEA; border:1px solid rgba(165,94,234,.35); }
.badge-geo       { background:rgba(255,71,87,.12);   color:#FF7088; border:1px solid rgba(255,71,87,.30); }
.badge-btc       { background:rgba(247,147,26,.15);  color:#F7931A; border:1px solid rgba(247,147,26,.35); }
.badge-macro     { background:rgba(41,121,255,.15);  color:#2979FF; border:1px solid rgba(41,121,255,.35); }
.badge-geopolitical { background:rgba(255,71,87,.12); color:#FF7088; border:1px solid rgba(255,71,87,.30); }

/* alert boxes */
.alert { border-radius:6px; padding:10px 14px; margin:5px 0;
         font-size:13px; font-weight:500; line-height:1.5; }
.alert-error   { background:rgba(255,71,87,.08);   border:1px solid rgba(255,71,87,.35);
                 border-left:3px solid #FF4757;     color:#FF8A94; }
.alert-warning { background:rgba(255,165,2,.08);   border:1px solid rgba(255,165,2,.35);
                 border-left:3px solid #FFA502;     color:#FFBD57; }
.alert-info    { background:rgba(41,121,255,.08);  border:1px solid rgba(41,121,255,.35);
                 border-left:3px solid #1A6EFF;     color:#7AADFF; }
.alert-success { background:rgba(0,200,150,.08);   border:1px solid rgba(0,200,150,.35);
                 border-left:3px solid #00C896;     color:#4DDBB5; }

/* calendar row */
.cal-row {
  display:grid; grid-template-columns:90px 36px 36px 1fr 70px 90px 90px 100px;
  align-items:center; gap:8px; padding:9px 14px; border-radius:6px; margin:3px 0;
  background:#0A1628; border:1px solid #1A2540; font-size:12px;
}
.cal-row:hover { border-color:#2D3E56; }
.cal-date  { color:#4A607A; font-weight:700; font-size:11px; }
.cal-name  { color:#E2E8F0; font-weight:600; }
.cal-val   { color:#7B8FA5; text-align:right; font-size:11px; font-variant-numeric:tabular-nums; }
.cal-est   { color:#5A6E85; text-align:right; font-size:11px; }
.cal-act   { color:#E2E8F0; font-weight:700; text-align:right; font-size:11px; }
.beat   { color:#00C896; font-weight:800; font-size:10px; letter-spacing:0.4px; }
.miss   { color:#FF4757; font-weight:800; font-size:10px; letter-spacing:0.4px; }
.inline { color:#7B8FA5; font-weight:700; font-size:10px; }
.upcoming-tag { color:#2D3E56; font-style:italic; font-size:10px; }
.ctag { display:inline-block; font-size:9px; font-weight:700; padding:1px 5px;
        border-radius:3px; background:#0F1E36; color:#4A607A; letter-spacing:0.4px; }
.imp-high { color:#FF4757; font-size:9px; font-weight:800; }
.imp-med  { color:#FFA502; font-size:9px; font-weight:800; }
.imp-low  { color:#2D3E56; font-size:9px; font-weight:700; }

/* section divider */
.sect-div { border:none; border-top:1px solid #1A2540; margin:20px 0; }

/* sidebar */
[data-testid="stSidebar"] { background:#050D1F; border-right:1px solid #1A2540; }

/* progress bar */
[data-testid="stProgressBar"] > div > div { background-color: #1A6EFF; }
</style>
""", unsafe_allow_html=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _alert(text: str, level: str = "info"):
    st.markdown(f'<div class="alert alert-{level}">{text}</div>',
                unsafe_allow_html=True)


def _market_status() -> dict:
    ET  = ZoneInfo("America/New_York")
    now = dt.datetime.now(ET)
    t   = now.hour * 60 + now.minute
    wd  = now.weekday()
    if wd >= 5:          return {"label": "MARKET CLOSED", "color": "#2D3E56"}
    if 570 <= t < 960:   return {"label": "MARKET OPEN",   "color": "#00C896"}
    if 240 <= t < 570:   return {"label": "PRE-MARKET",    "color": "#FFA502"}
    if 960 <= t < 1200:  return {"label": "AFTER-HOURS",   "color": "#FFA502"}
    return {"label": "MARKET CLOSED", "color": "#2D3E56"}


def is_market_hours() -> bool:
    """True during regular US equity hours: Mon-Fri 9:30am-4:00pm ET."""
    ET  = ZoneInfo("America/New_York")
    now = dt.datetime.now(ET)
    if now.weekday() >= 5:
        return False
    t = now.hour * 60 + now.minute
    return 570 <= t < 960   # 9:30=570, 16:00=960


def is_extended_hours() -> bool:
    """True during pre-market (4am-9:30am) or after-hours (4pm-8pm) ET."""
    ET  = ZoneInfo("America/New_York")
    now = dt.datetime.now(ET)
    if now.weekday() >= 5:
        return False
    t = now.hour * 60 + now.minute
    return (240 <= t < 570) or (960 <= t < 1200)  # 4am-9:30am or 4pm-8pm


def _page_header():
    ms = _market_status()
    ts = dt.datetime.now().strftime("%d %b %Y  %H:%M")
    st.markdown(f"""
    <div style="display:flex;align-items:center;justify-content:space-between;
                padding:10px 0 16px;border-bottom:1px solid #1A2540;margin-bottom:18px">
      <div>
        <span style="font-size:20px;font-weight:800;letter-spacing:0.5px;color:#FFFFFF">
          MACRO DASHBOARD</span>
        <span style="font-size:10px;font-weight:700;letter-spacing:1.6px;
                     color:#2D3E56;margin-left:16px;text-transform:uppercase">
          Institutional Intelligence</span>
      </div>
      <div style="text-align:right;line-height:1.8">
        <span style="font-size:11px;font-weight:700;color:{ms['color']};
                     letter-spacing:0.6px">&#9679; {ms['label']}</span>
        <span style="font-size:11px;color:#2D3E56;margin-left:12px">{ts}</span>
      </div>
    </div>""", unsafe_allow_html=True)


# ── Plotly theme ───────────────────────────────────────────────────────────────

_PALETTE = ["#2979FF", "#4FC3F7", "#A78BFA", "#F7931A", "#FF6584",
            "#26C6DA", "#66BB6A", "#FFA726", "#EC407A", "#00C896"]

_BASE = dict(
    template="plotly_dark",
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(10,22,40,0.6)",
    font=dict(family="Inter, -apple-system, sans-serif", size=11, color="#7B8FA5"),
    xaxis=dict(gridcolor="#1A2540", showgrid=True, zeroline=False,
               linecolor="#1A2540", tickfont=dict(size=10)),
    yaxis=dict(gridcolor="#1A2540", showgrid=True, zeroline=False,
               linecolor="#1A2540", tickfont=dict(size=10)),
    margin=dict(l=6, r=6, t=36, b=6),
    height=255,
    showlegend=False,
    legend=dict(bgcolor="rgba(0,0,0,0)", bordercolor="#1A2540",
                font=dict(size=10), orientation="h", y=1.08),
    title_font=dict(size=13, color="#E2E8F0"),
    hoverlabel=dict(bgcolor="#0A1628", bordercolor="#1A2540",
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
    bgcolor="#0A1628", activecolor="#1A6EFF",
    borderwidth=0, font=dict(color="#7B8FA5", size=9), x=0, y=1.02,
)


def _hex_rgba(hex_color: str, alpha: float = 0.08) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def _fig(**kw) -> go.Figure:
    layout = {**_BASE, **kw}
    return go.Figure(layout=go.Layout(**layout))


def line_chart(series: pd.Series, title: str, units: str,
               hlines: list | None = None, color: str = "#2979FF",
               height: int = 255, range_selector: bool = True) -> go.Figure:
    fig = _fig(title=title, yaxis_title=units, height=height)
    fig.add_trace(go.Scatter(
        x=series.index, y=series.values, mode="lines",
        line=dict(color=color, width=1.8),
        fill="tozeroy", fillcolor=_hex_rgba(color, 0.08),
        hovertemplate="%{y:.3f}<extra></extra>",
    ))
    if hlines:
        for hl in hlines:
            fig.add_hline(y=hl["y"], line_dash=hl.get("dash", "dash"),
                          line_color=hl.get("color", "#2D3E56"), line_width=1.1,
                          annotation_text=hl.get("label", ""),
                          annotation_font_size=9, annotation_font_color="#4A607A")
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
            f'<a href="{url}" target="_blank" style="font-size:10px;color:#2D3E56;'
            f'text-decoration:none;font-weight:700;letter-spacing:0.6px">'
            f'TRADINGVIEW &#8599;</a>',
            unsafe_allow_html=True)


def chart_col(col, series: pd.Series, title: str, units: str,
              tv_key: str = None, hlines: list = None, color: str = "#2979FF"):
    with col:
        if series is not None and not series.dropna().empty and len(series.dropna()) > 1:
            st.plotly_chart(line_chart(series, title, units, hlines, color),
                            use_container_width=True)
            if tv_key:
                tv_link(tv_key)
        else:
            st.caption(f"{title}: chart data unavailable.")


def sect(title: str, caption: str = ""):
    st.markdown(
        f'<hr class="sect-div">'
        f'<p style="font-size:14px;font-weight:700;color:#E2E8F0;'
        f'margin:0 0 {"4" if caption else "14"}px;letter-spacing:0.2px">'
        f'{title}</p>',
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
        st.caption(f"Z-score vs history: **{z['zscore']:+.1f}sigma** — {zscore_label(z['zscore'])}")


# ── News rendering helpers ─────────────────────────────────────────────────────

# (border, badge-bg, badge-text, badge-border) per category
_NEWS_STYLE: dict[str, tuple[str, str, str, str]] = {
    "CENTRAL BANKS": ("#2979FF", "rgba(41,121,255,.18)",  "#6FA8FF", "rgba(41,121,255,.4)"),
    "MACRO":         ("#00C896", "rgba(0,200,150,.15)",   "#00C896", "rgba(0,200,150,.4)"),
    "GEOPOLITICAL":  ("#FF4757", "rgba(255,71,87,.15)",   "#FF7088", "rgba(255,71,87,.4)"),
    "MARKETS":       ("#FFA502", "rgba(255,165,2,.15)",   "#FFA502", "rgba(255,165,2,.4)"),
    "TECH & AI":     ("#A78BFA", "rgba(167,139,250,.15)", "#A78BFA", "rgba(167,139,250,.4)"),
}
_NEWS_FALLBACK = ("#1A6EFF", "rgba(26,110,255,.15)", "#6FA8FF", "rgba(26,110,255,.4)")

# TradingView link patterns (most specific first to win overlap tiebreaks)
import re as _re
_TV_LINK_STYLE = (
    "color:#5A9FFF;text-decoration:underline;text-underline-offset:2px;"
    "text-decoration-thickness:1px"
)
_TV_PATTERNS = [
    (_re.compile(r"\bS&P\s*500\b|\bS&P500\b", _re.I), "https://www.tradingview.com/chart/?symbol=SP:SPX"),
    (_re.compile(r"\bEuro\s+Stoxx\b", _re.I),          "https://www.tradingview.com/chart/?symbol=INDEX:STOXX50E"),
    (_re.compile(r"\bDow\s+Jones\b", _re.I),           "https://www.tradingview.com/chart/?symbol=DJ:DJI"),
    (_re.compile(r"\bDollar\s+[Ii]ndex\b|\bDXY\b|\bDollar\b", _re.I), "https://www.tradingview.com/chart/?symbol=TVC:DXY"),
    (_re.compile(r"\bEUR/USD\b|\beuro\b", _re.I),      "https://www.tradingview.com/chart/?symbol=FX:EURUSD"),
    (_re.compile(r"\b(?:10[- ]year|US\s*10Y)\s+yields?\b|\btreasury\s+yields?\b", _re.I),
                                                        "https://www.tradingview.com/chart/?symbol=TVC:US10Y"),
    (_re.compile(r"\b(?:2[- ]year|US\s*2Y)\s+yield\b", _re.I), "https://www.tradingview.com/chart/?symbol=TVC:US02Y"),
    (_re.compile(r"\bcrude\s+oil\b", _re.I),           "https://www.tradingview.com/chart/?symbol=NYMEX:CL1!"),
    (_re.compile(r"\bNasdaq\b", _re.I),                "https://www.tradingview.com/chart/?symbol=NASDAQ:IXIC"),
    (_re.compile(r"\bGold\b", _re.I),                  "https://www.tradingview.com/chart/?symbol=COMEX:GC1!"),
    (_re.compile(r"\bOil\b", _re.I),                   "https://www.tradingview.com/chart/?symbol=NYMEX:CL1!"),
    (_re.compile(r"\bVIX\b"),                          "https://www.tradingview.com/chart/?symbol=CBOE:VIX"),
    (_re.compile(r"\bBitcoin\b|\bBTC\b"),              "https://www.tradingview.com/chart/?symbol=BITSTAMP:BTCUSD"),
    (_re.compile(r"\bDAX\b"),                          "https://www.tradingview.com/chart/?symbol=XETR:DAX"),
    (_re.compile(r"\bFTSE\b", _re.I),                 "https://www.tradingview.com/chart/?symbol=FOREXCOM:UK100"),
]


def _add_tv_links(text: str) -> str:
    """Replace known financial terms in plain text with TradingView links."""
    # Collect all non-overlapping matches across all patterns
    matches: list[tuple[int, int, str, str]] = []
    for pattern, url in _TV_PATTERNS:
        for m in pattern.finditer(text):
            matches.append((m.start(), m.end(), m.group(0), url))

    matches.sort(key=lambda x: x[0])

    # Remove overlaps (keep first match at each position)
    filtered: list[tuple[int, int, str, str]] = []
    last_end = 0
    for start, end, matched, url in matches:
        if start >= last_end:
            filtered.append((start, end, matched, url))
            last_end = end

    parts: list[str] = []
    pos = 0
    for start, end, matched, url in filtered:
        parts.append(text[pos:start])
        parts.append(
            f'<a href="{url}" target="_blank" style="{_TV_LINK_STYLE}">{matched}</a>'
        )
        pos = end
    parts.append(text[pos:])
    return "".join(parts)


# NOTE: all interactive widget keys must be globally unique.
# Use url_hash + tab_key + loop_idx pattern for any widget
# inside article render loops. Never use article title or
# index alone as a key.
def _render_articles(articles: list, tab_key: str = "all"):
    if not articles:
        st.caption("No articles in this category yet.")
        return

    read_set: set = st.session_state.get("news_read", set())

    for idx, art in enumerate(articles):
        cat   = art.get("category", "MACRO")
        src   = art.get("source", "")
        ta    = art.get("time_ago", "")
        link  = art.get("link", "")
        imp   = art.get("importance", 1)
        mi    = art.get("market_impact")
        tier  = art.get("source_tier", 3)
        sc    = art.get("source_count", 1)
        aid   = article_id(art)
        is_rd = aid in read_set

        url = art.get("url", link)
        _hash = hashlib.md5(f"{url}{tab_key}{idx}".encode()).hexdigest()[:12]
        button_key = f"btn_{_hash}"

        title = _re.sub(r"<[^>]+>", " ", art.get("title", ""))
        title = _re.sub(r"\s+", " ", title).strip()

        bdr, bg_c, txt_c, ring_c = _NEWS_STYLE.get(cat, _NEWS_FALLBACK)
        src_color = SOURCE_TIER_COLOR.get(tier, "#4A607A")
        dim = "opacity:0.45;" if is_rd else ""

        if imp == 3:
            imp_h = ('<span style="background:rgba(41,121,255,.2);color:#6FA8FF;'
                     'border:1px solid rgba(41,121,255,.4);padding:1px 5px;'
                     'border-radius:2px;font-size:9px;font-weight:700;'
                     'white-space:nowrap">HIGH</span> ')
        elif imp == 2:
            imp_h = ('<span style="background:rgba(100,116,139,.12);color:#8BA0B8;'
                     'border:1px solid rgba(100,116,139,.25);padding:1px 5px;'
                     'border-radius:2px;font-size:9px;font-weight:700;'
                     'white-space:nowrap">MED</span> ')
        else:
            imp_h = ""

        sc_h = (
            f'<span style="font-size:8px;color:#374A5E;background:#0D1521;'
            f'padding:1px 4px;border-radius:2px;border:1px solid #1A2540;'
            f'margin-left:4px">{sc}&nbsp;src</span>'
            if sc >= 2 else ""
        )

        cat_d  = cat.replace("&", "&amp;")
        safe_t = (title.replace("&", "&amp;").replace("<", "&lt;")
                       .replace(">", "&gt;").replace('"', "&quot;"))
        safe_l = link.replace('"', "%22") if link else ""
        hl_c   = "#E2E8F0" if imp == 3 else "#C5D0DC" if imp == 2 else "#7A8FA8"
        hl_w   = "700" if imp == 3 else "600" if imp == 2 else "500"

        if safe_l:
            hl_h = (f'<a href="{safe_l}" target="_blank" style="color:{hl_c};'
                    f'text-decoration:none;font-weight:{hl_w};font-size:13px">'
                    f'{safe_t}</a>')
        else:
            hl_h = f'<span style="color:{hl_c};font-weight:{hl_w};font-size:13px">{safe_t}</span>'

        card = (
            f'<div style="{dim}border-left:3px solid {bdr};padding:4px 4px 4px 8px;margin:1px 0">'
            f'<div style="display:flex;align-items:center;gap:4px;flex-wrap:nowrap;'
            f'overflow:hidden;line-height:1.1">'
            f'<span style="background:{bg_c};color:{txt_c};border:1px solid {ring_c};'
            f'padding:1px 5px;border-radius:2px;font-size:9px;font-weight:800;'
            f'white-space:nowrap">{cat_d}</span>'
            f'{imp_h}'
            f'<span style="color:{src_color};font-size:10px;font-weight:700;'
            f'white-space:nowrap">{src}</span>'
            f'<span style="color:#374A5E;font-size:10px;margin-left:auto;'
            f'white-space:nowrap">{ta}{sc_h}</span>'
            f'</div>'
            f'<div style="margin:3px 0 0">{hl_h}</div>'
            f'</div>'
        )

        c_main, c_btn = st.columns([20, 1])
        with c_main:
            st.markdown(card, unsafe_allow_html=True)
            if mi and imp >= 2:
                st.markdown(
                    f'<div style="padding-left:11px;font-size:10.5px;color:#4A7A9B;'
                    f'margin:-2px 0 3px">{_add_tv_links(mi)}</div>',
                    unsafe_allow_html=True,
                )
        with c_btn:
            if st.button(
                "↩" if is_rd else "✓",
                key=button_key,
                help="Mark unread" if is_rd else "Mark read",
            ):
                if is_rd:
                    st.session_state.news_read.discard(aid)
                else:
                    st.session_state.news_read.add(aid)
                st.rerun()

        st.markdown(
            '<hr style="border:none;border-top:1px solid #0E1C30;margin:3px 0">',
            unsafe_allow_html=True,
        )


# ── Data loading & sidebar ─────────────────────────────────────────────────────

st.sidebar.markdown(
    '<p style="font-size:13px;font-weight:800;color:#A0AEC0;margin-bottom:8px;'
    'letter-spacing:1.2px;text-transform:uppercase">Settings</p>',
    unsafe_allow_html=True)

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
    te_api_key = st.secrets["TE_API_KEY"]
except Exception:
    te_api_key = None
if not te_api_key:
    te_api_key = st.sidebar.text_input(
        "Trading Economics API key (optional)", type="password",
        help="Free at tradingeconomics.com/api — powers the 30-day forward calendar with consensus forecasts")

show_zscore = st.sidebar.checkbox("Show Z-scores", value=True)

st.sidebar.markdown("---")
if st.sidebar.button("Force Refresh All Data", use_container_width=True):
    st.cache_data.clear()
    st.rerun()

last_refresh = dt.datetime.now().strftime("%H:%M:%S")
st.sidebar.caption(f"Markets 2 min · Macro 6h · Last load: {last_refresh}")
st.sidebar.caption("FRED · Yahoo Finance · CoinGecko\nmempool.space · Trading Economics")

# ── Load data ──────────────────────────────────────────────────────────────────

fred_data   = None
market_data = None

if fred_api_key:
    with st.spinner("Loading macro data from FRED..."):
        fred_data = load_all_fred(FRED_SERIES, fred_api_key, fred_start)

with st.spinner("Loading market data..."):
    market_data = load_all_markets(MARKET_TICKERS, period=yahoo_period)


def _s(key: str) -> pd.Series | None:
    if fred_data is None: return None
    entry = fred_data.get(key, {})
    s = entry.get("series")
    return None if (s is None or s.dropna().empty) else s


def _latest(key: str) -> float | None:
    s = _s(key)
    if s is None: return None
    try:
        return float(s.dropna().values[-1])
    except Exception:
        return None


# ── Page header & today's event banner ────────────────────────────────────────
_page_header()

today_evts, upcoming_evts, recent_evts = get_calendar(fred_data, te_api_key)
if today_evts:
    names = " · ".join(f"<strong>{e['name']}</strong>" for e in today_evts[:4])
    _alert(f"RELEASES TODAY: {names}", "info")

# ── Tabs ───────────────────────────────────────────────────────────────────────
(tab_score, tab_cal, tab_news,
 tab_crypto, tab_macro, tab_markets, tab_cross, tab_signals) = st.tabs([
    "Scorecard", "Calendar", "News",
    "Bitcoin", "Macro", "Markets", "Cross-Asset", "Signals",
])


# ══════════════════════════════════════════════════════════════════════════════
# SCORECARD
# ══════════════════════════════════════════════════════════════════════════════

with tab_score:
    if fred_data is None:
        _alert("Enter your FRED API key in the sidebar to load macro data.", "info")
    else:
        # ── data ──────────────────────────────────────────────────────────────
        cpi_l        = _latest("cpi_yoy");       core_pce_l  = _latest("core_pce_yoy")
        pce_l        = _latest("pce_yoy");        ffr_l       = _latest("fed_funds")
        y10_l        = _latest("10y_yield");      y2_l        = _latest("2y_yield")
        y3m_l        = _latest("3m_yield");       real_10y_l  = _latest("real_10y")
        bkeven_l     = _latest("breakeven_10y");  unrate_l    = _latest("unemployment")
        cfnai_l      = _latest("cfnai");          hy_oas_l    = _latest("hy_oas")
        ig_oas_l     = _latest("ig_oas");         claims_l    = _latest("initial_claims")
        sent_l       = _latest("consumer_sentiment")
        eu_hicp_l    = _latest("eu_hicp");        ecb_l       = _latest("ecb_deposit_rate")
        eu_10y_l     = _latest("eu_10y_yield");   eu_2y_l     = _latest("eu_2y_yield")
        eu_unemp_l   = _latest("eu_unemployment")
        de_10y_l     = _latest("de_10y_yield");   it_10y_l    = _latest("it_10y_yield")

        def _safe_sub(a, b):
            if a is None or b is None: return None
            try:
                v = float(a) - float(b)
                return None if (math.isnan(v) or math.isinf(v)) else v
            except Exception: return None

        sp2s10s    = _safe_sub(y10_l, y2_l)
        sp3m10s    = _safe_sub(y10_l, y3m_l)
        real_ffr_l = round(_safe_sub(ffr_l, cpi_l), 2) if _safe_sub(ffr_l, cpi_l) is not None else None
        hy_ig_ratio = round(hy_oas_l / ig_oas_l, 2) if (hy_oas_l and ig_oas_l and ig_oas_l > 0) else None

        _vix_df  = (market_data.get("^VIX") or {}).get("df")
        _vix_snp = latest_snapshot(_vix_df)
        vix_l    = float(_vix_snp[0]) if _vix_snp else None

        sahm    = compute_sahm_rule(_s("unemployment"))
        regime  = classify_macro_regime(cfnai_l, cpi_l)
        credit  = credit_spread_status(hy_oas_l)
        eu_reg  = classify_eu_macro_regime(eu_hicp_l, eu_unemp_l)
        btp_bps = (it_10y_l - de_10y_l) * 100 if (it_10y_l and de_10y_l) else None
        btp_st  = btp_bund_status(btp_bps)
        rec     = compute_recession_probability(sp2s10s, sp3m10s, sahm["value"], hy_oas_l, cfnai_l, ffr_l)
        positioning = compute_positioning_implication(
            regime, rec["probability"], sp2s10s, sp3m10s, hy_oas_l, real_10y_l, vix_l, ffr_l)
        policy = compute_policy_tracker(ffr_l, y2_l, ecb_l, eu_2y_l)

        _ts = dt.datetime.now().strftime("%H:%M:%S")
        st.caption(f"Last updated: {_ts} · Signals from FRED + Yahoo Finance · Recession model: 6-factor composite")

        # ── regime cards ──────────────────────────────────────────────────────
        _REGIME_META = {
            "goldilocks":     {"color": "#00C896", "bg": "rgba(0,200,150,0.08)"},
            "reflation":      {"color": "#FFA502", "bg": "rgba(255,165,2,0.08)"},
            "stagflation":    {"color": "#FF4757", "bg": "rgba(255,71,87,0.08)"},
            "deflation_risk": {"color": "#5580FF", "bg": "rgba(85,128,255,0.08)"},
            "partial":        {"color": "#A0AEC0", "bg": "rgba(160,174,192,0.05)"},
        }

        def _regime_card(title: str, reg: dict) -> str:
            rkey  = reg.get("regime") or "partial"
            meta  = _REGIME_META.get(rkey, _REGIME_META["partial"])
            label = reg.get("label") or "—"
            desc  = reg.get("description") or ""
            return (
                f'<div style="border-left:4px solid {meta["color"]};'
                f'background:{meta["bg"]};border-radius:6px;padding:14px 16px;'
                f'margin-bottom:4px">'
                f'<div style="font-size:9px;font-weight:700;letter-spacing:0.9px;'
                f'color:#4A607A;text-transform:uppercase;margin-bottom:6px">{title}</div>'
                f'<div style="font-size:26px;font-weight:800;color:{meta["color"]};'
                f'line-height:1.1;margin-bottom:4px">{label}</div>'
                f'<div style="font-size:11px;color:#A0AEC0">{desc}</div>'
                f'</div>'
            )

        col_us, col_eu = st.columns(2)
        with col_us:
            st.markdown(_regime_card("US Macro Regime", regime), unsafe_allow_html=True)
        with col_eu:
            st.markdown(_regime_card("EU Macro Regime", eu_reg), unsafe_allow_html=True)

        st.markdown('<hr class="sect-div">', unsafe_allow_html=True)

        # ── recession probability gauge ───────────────────────────────────────
        st.markdown(
            '<p style="font-size:12px;font-weight:700;color:#A0AEC0;'
            'letter-spacing:0.6px;margin-bottom:8px">US RECESSION PROBABILITY</p>',
            unsafe_allow_html=True)
        if rec["probability"] is not None:
            rp     = rec["probability"]
            rcolor = ("#FF4757" if rp >= 80 else "#FF6B35" if rp >= 60
                      else "#FFA502" if rp >= 40 else "#FFD700" if rp >= 20 else "#00C896")
            st.markdown(
                f'<div style="display:flex;align-items:center;gap:14px;margin-bottom:6px">'
                f'<div style="font-size:36px;font-weight:900;color:{rcolor}">{rp}%</div>'
                f'<div>'
                f'<div style="font-size:16px;font-weight:700;color:{rcolor}">{rec["label"]}</div>'
                f'<div style="font-size:11px;color:#4A607A">Based on 6 signals · Updated daily</div>'
                f'</div></div>'
                f'<div style="background:#1A2540;border-radius:4px;height:10px;width:100%;margin-bottom:4px">'
                f'<div style="background:{rcolor};height:10px;border-radius:4px;width:{rp}%"></div>'
                f'</div>'
                f'<div style="display:flex;justify-content:space-between;font-size:9px;color:#2D3E56">'
                f'<span>0% LOW</span><span>20% ELEVATED</span><span>40% MODERATE</span>'
                f'<span>60% HIGH</span><span>80% VERY HIGH</span><span>100%</span>'
                f'</div>',
                unsafe_allow_html=True)
            st.caption(
                "3M10Y spread (25%) · Sahm Rule (25%) · 2s10s (20%) · "
                "HY OAS (15%) · CFNAI (10%) · FFR vs Neutral (5%)")

        st.markdown('<hr class="sect-div">', unsafe_allow_html=True)

        # ── key signals grid ──────────────────────────────────────────────────
        st.markdown(
            '<p style="font-size:12px;font-weight:700;color:#A0AEC0;'
            'letter-spacing:0.6px;margin-bottom:8px">KEY SIGNALS</p>',
            unsafe_allow_html=True)
        c1, c2, c3, c4 = st.columns(4)

        def _col_hdr(txt):
            st.markdown(
                f'<p style="font-size:9px;font-weight:700;letter-spacing:0.9px;'
                f'color:#2D3E56;text-transform:uppercase;margin-bottom:6px">{txt}</p>',
                unsafe_allow_html=True)

        def _num(val, fmt, red_if_above=None, green_if_below=None):
            if val is None:
                return "—"
            color = "#FFFFFF"
            if red_if_above is not None and val > red_if_above:
                color = "#FF4757"
            elif green_if_below is not None and val < green_if_below:
                color = "#00C896"
            return f'<span style="color:{color}">{fmt.format(val)}</span>'

        with c1:
            _col_hdr("Rates")
            if ffr_l is not None:
                st.metric("Fed Funds", f"{ffr_l:.2f}%")
            if ecb_l is not None:
                st.metric("ECB Rate",  f"{ecb_l:.2f}%")
            if y10_l is not None:
                st.metric("US 10Y",    f"{y10_l:.2f}%")
            if sp3m10s is not None:
                st.metric("3M10Y Spread", f"{sp3m10s:.2f}%",
                          "⚠ Inverted" if sp3m10s < 0 else yield_curve_status(sp3m10s)["label"])
            if real_ffr_l is not None:
                st.metric("Real FFR", f"{real_ffr_l:.2f}%",
                          "Restrictive" if real_ffr_l > 1.0 else "Accommodative" if real_ffr_l < 0 else "Neutral")
            if real_10y_l is not None:
                st.metric("Real 10Y TIPS", f"{real_10y_l:.2f}%")

        with c2:
            _col_hdr("Inflation")
            if cpi_l is not None:
                g = cpi_vs_target(cpi_l)
                st.metric("US CPI",    f"{cpi_l:.2f}%",    f"{g['gap']:+.2f}pp vs 2%")
            if core_pce_l is not None:
                st.metric("Core PCE",  f"{core_pce_l:.2f}%")
            if pce_l is not None:
                st.metric("US PCE",    f"{pce_l:.2f}%")
            if bkeven_l is not None:
                st.metric("Breakeven 10Y", f"{bkeven_l:.2f}%",
                          "Above target" if bkeven_l > 2.5 else "Anchored" if bkeven_l <= 2.5 else None)
            if eu_hicp_l is not None:
                g2 = cpi_vs_target(eu_hicp_l)
                st.metric("EU HICP",   f"{eu_hicp_l:.2f}%", f"{g2['gap']:+.2f}pp vs 2%")

        with c3:
            _col_hdr("Labor & Growth")
            if unrate_l is not None:
                st.metric("US Unemp.",    f"{unrate_l:.2f}%")
            if eu_unemp_l is not None:
                st.metric("EU Unemp.",    f"{eu_unemp_l:.2f}%")
            if claims_l is not None:
                st.metric("Init. Claims", f"{claims_l:,.0f}")
            if sahm["value"] is not None:
                st.metric("Sahm Rule", f"{sahm['value']:.2f}pp",
                          "⚠ Triggered" if sahm["triggered"] else "Clear")
            if cfnai_l is not None:
                st.metric("CFNAI", f"{cfnai_l:.2f}",
                          "Above trend" if cfnai_l > 0 else "Below trend")

        with c4:
            _col_hdr("Risk")
            if sp2s10s is not None:
                st.metric("2s10s Spread", f"{sp2s10s:.2f}%",
                          "⚠ Inverted" if sp2s10s < 0 else yield_curve_status(sp2s10s)["label"])
            if vix_l is not None:
                vix_label = ("Crisis" if vix_l >= 40 else "Fear" if vix_l >= 30
                             else "Elevated" if vix_l >= 20 else "Normal" if vix_l >= 15 else "Complacent")
                st.metric("VIX", f"{vix_l:.1f}", vix_label)
            if hy_oas_l is not None:
                st.metric("HY OAS", f"{hy_oas_l:.2f}%", credit["label"])
            if hy_ig_ratio is not None:
                st.metric("HY/IG Ratio", f"{hy_ig_ratio:.2f}x",
                          "Stressed" if hy_ig_ratio > 4.0 else "Elevated" if hy_ig_ratio > 3.0 else "Normal")
            if btp_bps is not None:
                st.metric("BTP-Bund", f"{btp_bps:.0f}bps", btp_st["label"])

        st.markdown('<hr class="sect-div">', unsafe_allow_html=True)

        # ── Fed & ECB policy tracker ──────────────────────────────────────────
        st.markdown(
            '<p style="font-size:12px;font-weight:700;color:#A0AEC0;'
            'letter-spacing:0.6px;margin-bottom:8px">FED & ECB POLICY TRACKER</p>',
            unsafe_allow_html=True)
        _dir_color = {"CUTS": "#00C896", "HIKES": "#FF4757", "HOLD": "#FFA502"}

        def _policy_card(bank: str, rate: float | None, spread: float | None, direction: str | None) -> str:
            rate_str  = f"{rate:.2f}%" if rate is not None else "—"
            spr_str   = (f"{spread:+.2f}%" if spread is not None else "—")
            dir_str   = direction or "—"
            dcolor    = _dir_color.get(dir_str, "#A0AEC0")
            spr_label = "2Y yield vs policy rate"
            return (
                f'<div style="border:1px solid #1A2540;border-radius:6px;padding:14px 16px">'
                f'<div style="font-size:9px;font-weight:700;letter-spacing:0.9px;'
                f'color:#4A607A;text-transform:uppercase;margin-bottom:8px">{bank}</div>'
                f'<div style="display:flex;justify-content:space-between;align-items:flex-end">'
                f'<div>'
                f'<div style="font-size:11px;color:#4A607A">Policy Rate</div>'
                f'<div style="font-size:24px;font-weight:800;color:#FFFFFF">{rate_str}</div>'
                f'</div>'
                f'<div style="text-align:right">'
                f'<div style="font-size:11px;color:#4A607A">{spr_label}</div>'
                f'<div style="font-size:16px;font-weight:700;color:#A0AEC0">{spr_str}</div>'
                f'</div>'
                f'</div>'
                f'<div style="margin-top:10px;padding-top:8px;border-top:1px solid #1A2540">'
                f'<span style="font-size:9px;color:#4A607A;text-transform:uppercase;'
                f'letter-spacing:0.7px">Market implied next move: </span>'
                f'<span style="font-size:13px;font-weight:800;color:{dcolor}">{dir_str}</span>'
                f'</div>'
                f'</div>'
            )

        pc1, pc2 = st.columns(2)
        with pc1:
            st.markdown(
                _policy_card("Federal Reserve", policy["fed_funds"],
                             policy["fed_spread"], policy["fed_direction"]),
                unsafe_allow_html=True)
        with pc2:
            st.markdown(
                _policy_card("European Central Bank", policy["ecb_rate"],
                             policy["ecb_spread"], policy["ecb_direction"]),
                unsafe_allow_html=True)
        st.caption("Direction inferred from 2Y sovereign yield vs policy rate. "
                   "Spread < -0.25% → market pricing cuts; > +0.25% → hikes.")

        st.markdown('<hr class="sect-div">', unsafe_allow_html=True)

        # ── market positioning table ──────────────────────────────────────────
        st.markdown(
            '<p style="font-size:12px;font-weight:700;color:#A0AEC0;'
            'letter-spacing:0.6px;margin-bottom:8px">MARKET POSITIONING</p>',
            unsafe_allow_html=True)
        _sig_color = {
            "Bullish": "#00C896", "Cautious": "#FFA502",
            "Neutral": "#A0AEC0", "Bearish": "#FF4757",
        }
        if positioning:
            rows_html = "".join(
                f'<tr style="border-bottom:1px solid #1A2540">'
                f'<td style="padding:8px 12px;font-size:12px;font-weight:600;color:#FFFFFF">{r["asset"]}</td>'
                f'<td style="padding:8px 12px">'
                f'<span style="font-size:12px;font-weight:700;color:{_sig_color.get(r["signal"], "#A0AEC0")}">'
                f'{r["signal"]}</span></td>'
                f'<td style="padding:8px 12px;font-size:11px;color:#A0AEC0">{r["rationale"]}</td>'
                f'</tr>'
                for r in positioning
            )
            st.markdown(
                f'<table style="width:100%;border-collapse:collapse;border:1px solid #1A2540;border-radius:6px">'
                f'<thead><tr style="border-bottom:2px solid #1A2540">'
                f'<th style="padding:8px 12px;text-align:left;font-size:9px;font-weight:700;'
                f'letter-spacing:0.9px;color:#4A607A;text-transform:uppercase">Asset</th>'
                f'<th style="padding:8px 12px;text-align:left;font-size:9px;font-weight:700;'
                f'letter-spacing:0.9px;color:#4A607A;text-transform:uppercase">Signal</th>'
                f'<th style="padding:8px 12px;text-align:left;font-size:9px;font-weight:700;'
                f'letter-spacing:0.9px;color:#4A607A;text-transform:uppercase">Rationale</th>'
                f'</tr></thead>'
                f'<tbody>{rows_html}</tbody>'
                f'</table>',
                unsafe_allow_html=True)
            st.caption("Rule-based signals derived from macro regime, recession probability, and real-time market data.")

        st.markdown('<hr class="sect-div">', unsafe_allow_html=True)

        # ── active alerts ─────────────────────────────────────────────────────
        st.markdown(
            '<p style="font-size:12px;font-weight:700;color:#A0AEC0;'
            'letter-spacing:0.6px;margin-bottom:6px">ACTIVE ALERTS</p>',
            unsafe_allow_html=True)

        alerts = []
        if sp3m10s is not None and sp3m10s < 0:
            alerts.append(("error",   f"3M10Y inverted ({sp3m10s:.2f}%) — Fed's preferred recession signal"))
        if sp2s10s is not None and sp2s10s < 0:
            alerts.append(("error",   f"2s10s yield curve inverted ({sp2s10s:.2f}%)"))
        if sahm["triggered"]:
            alerts.append(("error",   "Sahm Rule triggered — early recession signal"))
        if rec["probability"] is not None and rec["probability"] >= 60:
            alerts.append(("error",   f"Recession probability HIGH: {rec['probability']}%"))
        elif rec["probability"] is not None and rec["probability"] >= 40:
            alerts.append(("warning", f"Recession probability elevated: {rec['probability']}%"))
        if vix_l is not None and vix_l >= 30:
            alerts.append(("error",   f"VIX in Fear/Crisis zone: {vix_l:.1f}"))
        elif vix_l is not None and vix_l >= 20:
            alerts.append(("warning", f"VIX elevated: {vix_l:.1f}"))
        if real_ffr_l is not None and real_ffr_l > 2.0:
            alerts.append(("warning", f"Real Fed Funds highly restrictive: {real_ffr_l:.2f}%"))
        if btp_bps is not None and btp_bps > 250:
            alerts.append(("error",   f"BTP-Bund at fragmentation risk: {btp_bps:.0f}bps"))
        elif btp_bps is not None and btp_bps > 150:
            alerts.append(("warning", f"BTP-Bund elevated: {btp_bps:.0f}bps"))
        if hy_oas_l is not None and hy_oas_l > 5:
            alerts.append(("warning", f"US HY spreads elevated: {hy_oas_l:.2f}%"))
        if cpi_l is not None and cpi_l > 3:
            alerts.append(("warning", f"US CPI above 3%: {cpi_l:.2f}%"))
        if eu_hicp_l is not None and eu_hicp_l > 3:
            alerts.append(("warning", f"EU HICP above 3%: {eu_hicp_l:.2f}%"))

        if not alerts:
            _alert("No major macro alerts at this time.", "success")
        else:
            for kind, msg in alerts:
                _alert(msg, kind)

        # ── next on calendar ──────────────────────────────────────────────────
        if upcoming_evts:
            st.markdown('<hr class="sect-div">', unsafe_allow_html=True)
            st.markdown(
                '<p style="font-size:12px;font-weight:700;color:#A0AEC0;'
                'letter-spacing:0.6px;margin-bottom:8px">NEXT ON THE CALENDAR</p>',
                unsafe_allow_html=True)
            up_cols = st.columns(4)
            for i, evt in enumerate(upcoming_evts[:4]):
                apx = "~" if evt.get("approximate") else ""
                with up_cols[i]:
                    st.metric(
                        f"[{flag(evt['country'])}] {evt['name'][:22]}",
                        f"{apx}{evt['date'].strftime('%b %d')}",
                        f"Prev: {evt.get('prev_fmt','—')}")


# ══════════════════════════════════════════════════════════════════════════════
# ECONOMIC CALENDAR
# ══════════════════════════════════════════════════════════════════════════════

with tab_cal:
    if not te_api_key:
        _alert(
            "Add a free Trading Economics API key (sidebar) to unlock consensus forecasts "
            "and exact release times for the full 30-day forward calendar. "
            "Free account at tradingeconomics.com/api. "
            "Without it, you see the built-in 2025-2026 static schedule enriched with FRED actuals.",
            "info")

    cal_hdr, cal_refresh = st.columns([5, 1])
    with cal_hdr:
        src_label = "Trading Economics + CB schedule" if te_api_key else "Static 2025-2026 schedule + FRED actuals"
        st.caption(f"Source: {src_label}")
    with cal_refresh:
        if st.button("Refresh", key="cal_refresh", use_container_width=True):
            st.cache_data.clear(); st.rerun()

    def _cal_header():
        st.markdown("""
        <div style="display:grid;grid-template-columns:90px 36px 36px 1fr 70px 90px 90px 100px;
                    gap:8px;padding:6px 14px;font-size:9px;font-weight:700;letter-spacing:0.9px;
                    text-transform:uppercase;color:#2D3E56;border-bottom:1px solid #1A2540;
                    margin-bottom:4px">
          <span>Date</span><span>Country</span><span>Imp.</span><span>Event</span>
          <span style="text-align:right">Prev</span>
          <span style="text-align:right">Forecast</span>
          <span style="text-align:right">Actual</span>
          <span>Signal</span>
        </div>""", unsafe_allow_html=True)

    def _cal_row(evt: dict, is_today: bool = False):
        bg     = "background:#0F1E36;" if is_today else ""
        border = "border-left-color:#1A6EFF;" if is_today else ""
        fl     = flag(evt["country"])
        imp    = importance_dot(evt["importance"])
        imp_cls = {"HIGH": "imp-high", "MED": "imp-med"}.get(imp, "imp-low")
        name    = evt["name"]
        apx     = "~" if evt.get("approximate") else ""
        date_s  = evt["date"].strftime("%b %d")
        time_s  = evt.get("time_et", "") or ""

        prev_s  = evt.get("prev_fmt")   or (evt.get("prev")     and f"{evt['prev']:.2f}")     or "—"
        fcast_s = evt.get("forecast_fmt") or (evt.get("forecast") and f"{evt['forecast']:.2f}") or "—"
        act_s   = evt.get("actual_fmt") or (evt.get("actual")   and f"{evt['actual']:.2f}")   or "—"
        bm      = evt.get("beat_miss")  or ""

        bm_class = ""
        if "BEAT" in bm or "COOLER" in bm:  bm_class = "beat"
        elif "MISS" in bm or "HOTTER" in bm: bm_class = "miss"
        elif "IN-LINE" in bm:                bm_class = "inline"

        act_color = "#00C896" if bm_class == "beat" else "#FF4757" if bm_class == "miss" else "#E2E8F0"
        act_span  = (f'<span style="color:{act_color};font-weight:700">{act_s}</span>'
                     if act_s != "—" else '<span style="color:#2D3E56">—</span>')

        st.markdown(f"""
        <div class="cal-row" style="{bg}{border}">
          <span class="cal-date">{apx}{date_s}{f"<br><span style='font-size:9px;color:#2D3E56'>{time_s} ET</span>" if time_s else ""}</span>
          <span class="ctag">{fl}</span>
          <span class="{imp_cls}">{imp}</span>
          <span class="cal-name">{name}</span>
          <span class="cal-val">{prev_s}</span>
          <span class="cal-est">{fcast_s}</span>
          <span class="cal-act">{act_span}</span>
          <span class="{bm_class}">{bm}</span>
        </div>""", unsafe_allow_html=True)

    if today_evts:
        st.markdown(f"### Today — {dt.date.today().strftime('%A, %B %d %Y')}")
        _cal_header()
        for e in today_evts:
            _cal_row(e, is_today=True)

    st.markdown(f"### Upcoming {'(next 45 days, Trading Economics)' if te_api_key else '(next 60 days, static schedule)'}")
    st.caption("HIGH = high impact · MED = medium impact · ~ = approximate release date")
    _cal_header()

    imp_filter = st.multiselect("Filter by importance", ["high", "medium", "low"],
                                 default=["high", "medium"], label_visibility="collapsed",
                                 key="cal_imp_filter")
    filtered_up = [e for e in upcoming_evts if e["importance"] in imp_filter]
    if not filtered_up:
        _alert("No upcoming events matching the current filter.", "info")
    else:
        last_month = None
        for e in filtered_up:
            month_lbl = e["date"].strftime("%B %Y")
            if month_lbl != last_month:
                st.markdown(
                    f'<p style="font-size:10px;font-weight:700;color:#2D3E56;'
                    f'letter-spacing:0.9px;text-transform:uppercase;margin:12px 0 4px">'
                    f'{month_lbl}</p>', unsafe_allow_html=True)
                last_month = month_lbl
            _cal_row(e)

    if recent_evts:
        st.markdown("### Recent Releases (past 30 days)")
        _cal_header()
        for e in recent_evts:
            _cal_row(e)

    st.markdown('<hr class="sect-div">', unsafe_allow_html=True)
    st.caption(
        "Beat/Miss logic: Inflation (CPI, PCE, HICP) — actual > forecast = HOTTER (hawkish); "
        "actual < forecast = COOLER (dovish). Growth/jobs — actual > forecast = BEAT; "
        "actual < forecast = MISS. Consensus forecasts available with Trading Economics API key."
    )


# ══════════════════════════════════════════════════════════════════════════════
# MACRO NEWS
# ══════════════════════════════════════════════════════════════════════════════

# ── Session state for read tracking ──────────────────────────────────────────
if "news_read" not in st.session_state:
    st.session_state.news_read = set()

with tab_news:
    st_autorefresh(interval=300000 if is_market_hours() else 600000, key="news_refresh")
    with st.spinner("Fetching news from 52 feeds..."):
        _news = fetch_all_news()
    all_articles = _news["articles"]
    _fetched_at  = dt.datetime.fromisoformat(_news["fetched_at"])

    if not all_articles:
        _alert("Could not fetch news — check network or try refreshing.", "warning")
    else:
        # ── Debug / status line ───────────────────────────────────────────
        _now_utc    = dt.datetime.now(dt.timezone.utc)
        _oldest     = min(a["pub"] for a in all_articles)
        _oldest_hr  = int((_now_utc - _oldest).total_seconds() / 3600)
        _refresh_m  = max(0, int((_now_utc - _fetched_at).total_seconds() / 60))
        st.caption(
            f"{len(all_articles)} articles · last 48h · "
            f"oldest: {_oldest_hr} hr ago · updated {_refresh_m} min ago"
        )

        # ── Today's key releases banner ───────────────────────────────────
        _releases = detect_todays_releases(all_articles)
        if _releases:
            st.markdown(
                f'<div style="border-left:3px solid #FFA502;background:rgba(255,165,2,0.07);'
                f'border-radius:4px;padding:6px 12px;margin-bottom:6px;'
                f'font-size:11px;font-weight:600;color:#FFA502">'
                f'TODAY: {" · ".join(_releases)}'
                f'</div>',
                unsafe_allow_html=True,
            )

        # ── Control bar (one line) ────────────────────────────────────────
        f1, f2, f3, f4, f5 = st.columns([3.5, 4.5, 1.2, 0.8, 0.8])
        with f1:
            imp_filter = st.radio(
                "Tier",
                ["Tier 1+2", "Tier 1 Only", "All Stories"],
                horizontal=True, index=0,
                label_visibility="collapsed",
                key="news_imp_filter",
            )
        with f2:
            search_q = st.text_input(
                "Search", placeholder="Search headlines...",
                label_visibility="collapsed", key="news_search",
            )
        with f3:
            show_unread = st.toggle("New Only", key="news_unread_toggle")
        with f4:
            if st.button("Clear", key="news_mark_all", use_container_width=True):
                for a in all_articles:
                    st.session_state.news_read.add(article_id(a))
                st.rerun()
        with f5:
            if st.button("⟳", key="news_refresh_btn", use_container_width=True,
                         help="Refresh news"):
                fetch_all_news.clear(); st.rerun()

        # ── Apply filters ─────────────────────────────────────────────────
        # Re-sort explicitly: importance DESC → newest first within tier
        pool = sorted(
            all_articles,
            key=lambda a: (-a.get("importance", 1), -a["pub"].timestamp()),
        )

        if search_q:
            sq = search_q.strip().lower()
            pool = [a for a in pool if sq in a["title"].lower()]
            n = len(pool)
            st.caption(f"{n} result{'s' if n != 1 else ''} for \"{search_q}\"")

        if imp_filter == "Tier 1 Only":
            pool = [a for a in pool if a.get("importance", 1) == 3]
        elif imp_filter == "Tier 1+2":
            pool = [a for a in pool if a.get("importance", 1) >= 2]

        if show_unread:
            _rs = st.session_state.news_read
            pool = [a for a in pool if article_id(a) not in _rs]

        # ── Category tabs ─────────────────────────────────────────────────
        (n_all, n_cb, n_macro, n_geo,
         n_mkt, n_tech, n_earn) = st.tabs([
            "All", "Central Banks", "Macro",
            "Geopolitical", "Markets", "Tech & AI", "Earnings",
        ])

        with n_all:
            _render_articles(pool, "all")

        with n_cb:
            _render_articles([a for a in pool
                              if a.get("category") == "CENTRAL BANKS"], "cb")

        with n_macro:
            _render_articles([a for a in pool
                              if a.get("category") == "MACRO"], "mac")

        with n_geo:
            _render_articles([a for a in pool
                              if a.get("category") == "GEOPOLITICAL"], "geo")

        with n_mkt:
            _render_articles([a for a in pool
                              if a.get("category") == "MARKETS"], "mkt")

        with n_tech:
            _render_articles([a for a in pool
                              if a.get("category") == "TECH & AI"], "tech")

        with n_earn:
            with st.spinner("Loading earnings calendar..."):
                earnings = get_earnings_calendar()

            if not earnings:
                st.caption(
                    "Earnings dates temporarily unavailable — yfinance data may be delayed. "
                    "Check earnings.com or finance.yahoo.com for current schedules."
                )
            else:
                _upcoming = [e for e in earnings if e["days"] >= 0]
                if not _upcoming:
                    st.caption(
                        "Earnings dates temporarily unavailable — yfinance data may be delayed. "
                        "Check earnings.com or finance.yahoo.com for current schedules."
                    )
                else:
                    _groups = [
                        ("THIS WEEK",  [e for e in _upcoming if e["days"] <= 7],        "#1A6EFF"),
                        ("THIS MONTH", [e for e in _upcoming if 8 <= e["days"] <= 30],  "#8BA0B8"),
                        ("LATER",      [e for e in _upcoming if e["days"] > 30],        "#374A5E"),
                    ]
                    for _label, _items, _color in _groups:
                        if not _items:
                            continue
                        st.markdown(
                            f'<span style="color:{_color};font-size:10px;'
                            f'font-weight:800;letter-spacing:1px">{_label}</span>',
                            unsafe_allow_html=True,
                        )
                        _rows = [
                            {
                                "Ticker":      e["ticker"],
                                "Company":     (e["name"] or e["ticker"])[:28],
                                "Next Earnings": e["date"].strftime("%b %d, %Y"),
                                "Days Until":  e["days"],
                                "EPS Est.":    f"${e['eps_est']:.2f}" if e.get("eps_est") is not None else "—",
                                "Last EPS":    f"${e['eps_last']:.2f}" if e.get("eps_last") is not None else "—",
                            }
                            for e in _items
                        ]
                        st.dataframe(
                            pd.DataFrame(_rows),
                            hide_index=True,
                            use_container_width=True,
                        )


# ══════════════════════════════════════════════════════════════════════════════
# BITCOIN
# ══════════════════════════════════════════════════════════════════════════════

with tab_crypto:
    # Crypto never closes — always refresh every 10s
    st_autorefresh(interval=10000, key="btc_refresh")
    # ── Data fetch ────────────────────────────────────────────────────────────
    btc_px  = fetch_btc_bybit()
    cg      = fetch_btc_coingecko()
    cg_glob = fetch_crypto_global()
    fg      = fetch_fear_greed()
    hr      = fetch_btc_hashrate()
    btc_df  = fetch_btc_history(period=yahoo_period)
    cg_hist = fetch_btc_cg_history(days=365)
    halving = halving_cycle_info()
    tech    = compute_btc_technicals(btc_df) if not btc_df.empty else {}

    try:
        _btc_fallback = float(btc_df["Close"].dropna().values[-1]) if not btc_df.empty else None
    except Exception:
        _btc_fallback = None
    btc_price = btc_px.get("price") or cg.get("price") or _btc_fallback

    # ── helper: % from current price ─────────────────────────────────────────
    def _pct_from(level: float | None) -> str:
        if level is None or not btc_price:
            return "—"
        try:
            p = (btc_price - level) / level * 100
            if math.isnan(p) or math.isinf(p):
                return "—"
            color = "#00C896" if p >= 0 else "#FF4757"
            return f'<span style="color:{color}">{p:+.1f}%</span>'
        except Exception:
            return "—"

    # ── compute performance changes from CG history ───────────────────────────
    chg_90d = chg_1y = None
    if not cg_hist.empty and btc_price:
        try:
            if len(cg_hist) > 90:
                base90 = float(cg_hist.iloc[-91])
                if base90 and not math.isnan(base90):
                    v = (btc_price / base90 - 1) * 100
                    chg_90d = v if not math.isnan(v) else None
        except Exception:
            chg_90d = None
        try:
            if len(cg_hist) > 365:
                base1y = float(cg_hist.iloc[-366])
                if base1y and not math.isnan(base1y):
                    v = (btc_price / base1y - 1) * 100
                    chg_1y = v if not math.isnan(v) else None
        except Exception:
            chg_1y = None

    def _safe_chg(v):
        if v is None: return None
        try:
            f = float(v)
            return None if (math.isnan(f) or math.isinf(f)) else f
        except Exception:
            return None

    chg_24h = _safe_chg(btc_px.get("change_24h") or cg.get("change_24h"))
    chg_7d  = _safe_chg(cg.get("change_7d"))
    chg_30d = _safe_chg(cg.get("change_30d"))
    ath_chg = _safe_chg((btc_price / _ATH - 1) * 100)      if btc_price else None
    low_chg = _safe_chg((btc_price / _CYCLE_LOW - 1) * 100) if btc_price else None

    # ── 1. Price header ───────────────────────────────────────────────────────
    if btc_price:
        _chg24_safe = chg_24h if (chg_24h is not None and not (isinstance(chg_24h, float) and (math.isnan(chg_24h) or math.isinf(chg_24h)))) else None
        c_chg = "#00C896" if (_chg24_safe or 0) >= 0 else "#FF4757"
        sign  = "+" if (_chg24_safe or 0) >= 0 else ""
        mc    = cg.get("market_cap")
        dom   = cg_glob.get("btc_dominance")
        vol   = btc_px.get("volume_24h") or cg.get("volume_24h")
        hi24  = btc_px.get("high_24h")
        lo24  = btc_px.get("low_24h")
        src   = btc_px.get("source", "Bybit")
        ts_s  = ""
        if btc_px.get("fetched_at"):
            ts_s = dt.datetime.fromisoformat(btc_px["fetched_at"]).strftime("%H:%M:%S UTC")

        extras = []
        if mc and not (isinstance(mc, float) and math.isnan(mc)):
            extras.append(("Market Cap", f"${mc/1e9:.0f}B"))
        if dom and not (isinstance(dom, float) and math.isnan(dom)):
            extras.append(("BTC Dom.", f"{dom:.1f}%"))
        if vol and not (isinstance(vol, float) and math.isnan(vol)):
            extras.append(("24h Vol", f"${vol/1e9:.1f}B"))
        if hi24 and not (isinstance(hi24, float) and math.isnan(hi24)):
            extras.append(("24h High", f"${hi24:,.0f}"))
        if lo24 and not (isinstance(lo24, float) and math.isnan(lo24)):
            extras.append(("24h Low", f"${lo24:,.0f}"))
        extras.append(("Cycle Phase", halving["cycle_label"]))

        chg24_display = f"{sign}{_chg24_safe:.2f}% (24h)" if _chg24_safe is not None else "— (24h)"

        st.markdown(
            f'<div style="background:#0A1628;border:1px solid #1A2540;border-radius:8px;'
            f'padding:16px 24px;margin-bottom:10px;display:flex;'
            f'align-items:center;gap:36px;flex-wrap:wrap">'
            f'<div>'
            f'<div style="font-size:9px;font-weight:700;letter-spacing:1.2px;'
            f'color:#2D3E56;text-transform:uppercase">Bitcoin · {src}'
            f'{f" · {ts_s}" if ts_s else ""}</div>'
            f'<div style="font-size:38px;font-weight:800;color:#FFFFFF;'
            f'letter-spacing:-1px">${btc_price:,.0f}</div>'
            f'<div style="font-size:14px;font-weight:700;color:{c_chg}">'
            f'{chg24_display}</div>'
            f'</div>'
            f'<div style="display:flex;gap:24px;flex-wrap:wrap">'
            + "".join(
                f'<div><div style="font-size:9px;font-weight:700;color:#2D3E56;'
                f'text-transform:uppercase;letter-spacing:0.8px">{lbl}</div>'
                f'<div style="font-size:15px;font-weight:700;color:#E2E8F0">{val}</div></div>'
                for lbl, val in extras
            )
            + f'</div></div>',
            unsafe_allow_html=True,
        )

    # Quick links
    st.markdown(
        '<div style="display:flex;gap:10px;margin-bottom:14px">'
        '<a href="https://charts.bitbo.io/index/" target="_blank" '
        'style="display:inline-block;padding:7px 16px;'
        'background:rgba(247,147,26,0.12);color:#F7931A;'
        'border:1px solid rgba(247,147,26,0.35);border-radius:5px;font-size:12px;'
        'font-weight:700;text-decoration:none">Bitbo Charts →</a>'
        '<a href="https://www.tradingview.com/chart/?symbol=BITSTAMP:BTCUSD" '
        'target="_blank" style="display:inline-block;padding:7px 16px;'
        'background:rgba(41,121,255,0.10);color:#5B9BFF;'
        'border:1px solid rgba(41,121,255,0.30);border-radius:5px;font-size:12px;'
        'font-weight:700;text-decoration:none">TradingView →</a>'
        '</div>',
        unsafe_allow_html=True,
    )

    # ── 2. Performance table ──────────────────────────────────────────────────
    st.markdown(
        '<p style="font-size:12px;font-weight:700;color:#A0AEC0;'
        'letter-spacing:0.6px;margin-bottom:8px">PERFORMANCE</p>',
        unsafe_allow_html=True)
    _perf_rows = [
        ("24h",           chg_24h),
        ("7 Days",        chg_7d),
        ("30 Days",       chg_30d),
        ("90 Days",       chg_90d),
        ("1 Year",        chg_1y),
        ("From ATH",      ath_chg),
        ("From 2022 Low", low_chg),
    ]
    perf_cols = st.columns(len(_perf_rows))
    for col, (lbl, val) in zip(perf_cols, _perf_rows):
        if val is not None and not (isinstance(val, float) and (math.isnan(val) or math.isinf(val))):
            c = "#00C896" if val >= 0 else "#FF4757"
            col.markdown(
                f'<div style="text-align:center">'
                f'<div style="font-size:10px;color:#4A607A;margin-bottom:3px">{lbl}</div>'
                f'<div style="font-size:15px;font-weight:700;color:{c}">{val:+.1f}%</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

    st.markdown('<hr class="sect-div">', unsafe_allow_html=True)

    # ── 3. 4-Year Cycle section ───────────────────────────────────────────────
    _PHASE_COLOR = {
        "Early Bull":               "#00C896",
        "Bull Market Peak Zone":    "#FFA502",
        "Post-Peak / Early Bear":   "#FF6B35",
        "Bear Market":              "#FF4757",
        "Pre-Halving Accumulation": "#5B9BFF",
    }
    phase_color = _PHASE_COLOR.get(halving["cycle_label"], "#A0AEC0")
    pct = halving["pct_through"]

    st.markdown(
        '<p style="font-size:12px;font-weight:700;color:#A0AEC0;'
        'letter-spacing:0.6px;margin-bottom:10px">4-YEAR HALVING CYCLE</p>',
        unsafe_allow_html=True)

    st.markdown(
        f'<div style="border:1px solid #1A2540;border-left:4px solid {phase_color};'
        f'border-radius:6px;padding:14px 18px;margin-bottom:12px">'
        f'<div style="display:flex;justify-content:space-between;align-items:flex-start;'
        f'flex-wrap:wrap;gap:12px;margin-bottom:12px">'
        f'<div>'
        f'<div style="font-size:9px;color:#4A607A;text-transform:uppercase;'
        f'letter-spacing:0.9px;margin-bottom:4px">Current Phase</div>'
        f'<div style="font-size:22px;font-weight:800;color:{phase_color}">'
        f'{halving["cycle_label"]}</div>'
        f'<div style="font-size:11px;color:#A0AEC0;margin-top:2px">'
        f'{pct:.1f}% through cycle · {halving["days_since"]:,} days since halving</div>'
        f'</div>'
        f'<div style="display:flex;gap:24px;flex-wrap:wrap">'
        f'<div><div style="font-size:9px;color:#4A607A;text-transform:uppercase;'
        f'letter-spacing:0.9px">Last Halving</div>'
        f'<div style="font-size:14px;font-weight:700;color:#E2E8F0">'
        f'{halving["last_halving"]}</div>'
        f'<div style="font-size:10px;color:#4A607A">Block {halving["last_halving_block"]:,}'
        f' · BTC {_HALVING_PRICE:,}</div>'
        f'</div>'
        f'<div><div style="font-size:9px;color:#4A607A;text-transform:uppercase;'
        f'letter-spacing:0.9px">Next Halving (est.)</div>'
        f'<div style="font-size:14px;font-weight:700;color:#E2E8F0">'
        f'{halving["next_halving"]}</div>'
        f'<div style="font-size:10px;color:#4A607A">'
        f'{halving["days_to_next"]:,} days remaining</div>'
        f'</div>'
        f'</div>'
        f'</div>'
        f'<div style="background:#1A2540;border-radius:4px;height:8px;width:100%;'
        f'margin-bottom:5px">'
        f'<div style="background:{phase_color};height:8px;border-radius:4px;'
        f'width:{pct}%"></div>'
        f'</div>'
        f'<div style="display:flex;justify-content:space-between;font-size:9px;color:#2D3E56">'
        f'<span>Apr 2024</span>'
        f'<span>12mo — Early Bull</span>'
        f'<span>18mo — Peak Zone</span>'
        f'<span>24mo — Post-Peak</span>'
        f'<span>36mo — Bear</span>'
        f'<span>Apr 2028</span>'
        f'</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # Historical halving dates
    _halvings = [
        ("Halving 1", "Nov 28 2012", "Block 210,000"),
        ("Halving 2", "Jul 9 2016",  "Block 420,000"),
        ("Halving 3", "May 11 2020", "Block 630,000"),
        ("Halving 4", "Apr 20 2024", "Block 840,000  ·  BTC $63,210"),
        ("Halving 5", "~Apr 2028",   "estimated"),
    ]
    _peaks = [
        ("Cycle 1", "Jun 2011",  "$31",      ""),
        ("Cycle 2", "Nov 2013",  "$1,242",   ""),
        ("Cycle 3", "Dec 2017",  "$19,891",  ""),
        ("Cycle 4", "Nov 2021",  "$69,044",  ""),
        ("Cycle 5", "Oct 2025",  "$126,198", "← most recent ATH"),
    ]

    hv_col, pk_col = st.columns(2)
    with hv_col:
        st.markdown(
            '<p style="font-size:11px;font-weight:700;color:#4A607A;'
            'letter-spacing:0.6px;margin:4px 0 6px">HALVING DATES</p>',
            unsafe_allow_html=True)
        hv_rows = "".join(
            f'<div style="display:flex;gap:12px;padding:5px 0;border-bottom:1px solid #0E1C30">'
            f'<span style="font-size:10px;color:#4A607A;width:64px">{h}</span>'
            f'<span style="font-size:11px;font-weight:600;color:#E2E8F0;width:80px">{d}</span>'
            f'<span style="font-size:10px;color:#2D3E56">{blk}</span>'
            f'</div>'
            for h, d, blk in _halvings
        )
        st.markdown(
            f'<div style="background:#060E1A;border:1px solid #1A2540;'
            f'border-radius:6px;padding:8px 12px">{hv_rows}</div>',
            unsafe_allow_html=True)
    with pk_col:
        st.markdown(
            '<p style="font-size:11px;font-weight:700;color:#4A607A;'
            'letter-spacing:0.6px;margin:4px 0 6px">CYCLE PEAKS</p>',
            unsafe_allow_html=True)
        pk_rows = "".join(
            f'<div style="display:flex;gap:12px;padding:5px 0;border-bottom:1px solid #0E1C30">'
            f'<span style="font-size:10px;color:#4A607A;width:52px">{cy}</span>'
            f'<span style="font-size:10px;color:#2D3E56;width:68px">{date}</span>'
            f'<span style="font-size:13px;font-weight:700;color:#F7931A;width:76px">{price}</span>'
            f'<span style="font-size:10px;color:#4A607A">{note}</span>'
            f'</div>'
            for cy, date, price, note in _peaks
        )
        st.markdown(
            f'<div style="background:#060E1A;border:1px solid #1A2540;'
            f'border-radius:6px;padding:8px 12px">{pk_rows}</div>',
            unsafe_allow_html=True)

    st.markdown('<hr class="sect-div">', unsafe_allow_html=True)

    # ── 4. Key Price Levels ───────────────────────────────────────────────────
    st.markdown(
        '<p style="font-size:12px;font-weight:700;color:#A0AEC0;'
        'letter-spacing:0.6px;margin-bottom:8px">KEY PRICE LEVELS</p>',
        unsafe_allow_html=True)
    ma200_v = tech.get("ma200")
    ma50_v  = tech.get("ma50")
    _levels = [
        ("Cycle 5 ATH",      _ATH,            "Oct 6 2025"),
        ("Jan 2025 High",    _JAN25_HIGH,      ""),
        ("$100K Level",      _100K_LEVEL,      "psychological"),
        ("200-Day MA",       ma200_v,          "calculated"),
        ("50-Day MA",        ma50_v,           "calculated"),
        ("Realized Price",   _REALIZED_PRICE,  "approx — see charts.bitbo.io/index/"),
        ("Halving Price",    _HALVING_PRICE,   "Apr 20 2024"),
        ("Cycle 4 ATH",      _CYCLE4_ATH,      "Nov 2021"),
        ("Cycle Low",        _CYCLE_LOW,       "Nov 21 2022"),
    ]
    lv_rows = "".join(
        f'<tr style="border-bottom:1px solid #0E1C30">'
        f'<td style="padding:6px 12px;font-size:12px;color:#A0AEC0">{name}</td>'
        f'<td style="padding:6px 12px;font-size:13px;font-weight:700;color:#E2E8F0">'
        f'{"$" + f"{lvl:,.0f}" if lvl else "—"}</td>'
        f'<td style="padding:6px 12px;font-size:12px">{_pct_from(lvl)}</td>'
        f'<td style="padding:6px 12px;font-size:10px;color:#2D3E56">{note}</td>'
        f'</tr>'
        for name, lvl, note in _levels
    )
    st.markdown(
        f'<table style="width:100%;border-collapse:collapse;border:1px solid #1A2540;'
        f'border-radius:6px">'
        f'<thead><tr style="border-bottom:2px solid #1A2540">'
        f'<th style="padding:6px 12px;text-align:left;font-size:9px;font-weight:700;'
        f'letter-spacing:0.9px;color:#4A607A;text-transform:uppercase">Level</th>'
        f'<th style="padding:6px 12px;text-align:left;font-size:9px;font-weight:700;'
        f'letter-spacing:0.9px;color:#4A607A;text-transform:uppercase">Price</th>'
        f'<th style="padding:6px 12px;text-align:left;font-size:9px;font-weight:700;'
        f'letter-spacing:0.9px;color:#4A607A;text-transform:uppercase">% from Current</th>'
        f'<th style="padding:6px 12px;text-align:left;font-size:9px;font-weight:700;'
        f'letter-spacing:0.9px;color:#4A607A;text-transform:uppercase">Note</th>'
        f'</tr></thead><tbody>{lv_rows}</tbody></table>',
        unsafe_allow_html=True)

    st.markdown('<hr class="sect-div">', unsafe_allow_html=True)

    # ── 5. On-Chain Valuation ─────────────────────────────────────────────────
    st.markdown(
        '<p style="font-size:12px;font-weight:700;color:#A0AEC0;'
        'letter-spacing:0.6px;margin-bottom:10px">ON-CHAIN VALUATION</p>',
        unsafe_allow_html=True)

    oc_col1, oc_col2 = st.columns(2)

    with oc_col1:
        # MVRV (live calc)
        st.markdown(
            '<p style="font-size:11px;font-weight:700;color:#4A607A;'
            'letter-spacing:0.6px;margin-bottom:6px">MVRV RATIO</p>',
            unsafe_allow_html=True)
        if btc_price and _MVRV_REALIZED:
            try:
                mvrv = btc_price / _MVRV_REALIZED
                if math.isnan(mvrv) or math.isinf(mvrv):
                    st.caption("MVRV data unavailable.")
                else:
                    if mvrv < 1.0:   mv_lbl, mv_c = "Below cost basis — historically strong buy", "#00C896"
                    elif mvrv < 2.0: mv_lbl, mv_c = "Fair value / accumulation", "#A0AEC0"
                    elif mvrv < 3.5: mv_lbl, mv_c = "Overvalued — distribution zone", "#FFA502"
                    else:             mv_lbl, mv_c = "Extreme — historical cycle top territory", "#FF4757"
                    st.markdown(
                        f'<div style="display:flex;align-items:center;gap:14px;margin-bottom:4px">'
                        f'<div style="font-size:30px;font-weight:900;color:{mv_c}">{mvrv:.2f}</div>'
                        f'<div style="font-size:12px;color:{mv_c}">{mv_lbl}</div>'
                        f'</div>'
                        f'<div style="font-size:10px;color:#4A607A">'
                        f'Price / Realized Price · realized ≈ ${_MVRV_REALIZED:,}</div>',
                        unsafe_allow_html=True)
            except Exception:
                st.caption("MVRV data unavailable.")

        st.markdown('<div style="margin-top:14px"></div>', unsafe_allow_html=True)

        # Mayer Multiple (live calc)
        st.markdown(
            '<p style="font-size:11px;font-weight:700;color:#4A607A;'
            'letter-spacing:0.6px;margin-bottom:6px">MAYER MULTIPLE</p>',
            unsafe_allow_html=True)
        mm_val = tech.get("mayer_multiple")
        if mm_val and btc_price:
            try:
                mm_f = float(mm_val)
                if math.isnan(mm_f) or math.isinf(mm_f):
                    st.caption("Mayer Multiple data unavailable.")
                else:
                    ma200_val = tech.get("ma200")
                    if mm_f < 0.8:   mm_lbl, mm_c = "Extreme Undervalue — strong buy zone", "#00C896"
                    elif mm_f < 1.0: mm_lbl, mm_c = "Undervalue",                           "#00C896"
                    elif mm_f < 1.5: mm_lbl, mm_c = "Fair Value",                           "#A0AEC0"
                    elif mm_f < 2.4: mm_lbl, mm_c = "Overvalue — sell zone begins",         "#FFA502"
                    else:            mm_lbl, mm_c = "Extreme Overvalue — near cycle top",   "#FF4757"
                    ma_note = f" · 200DMA = ${ma200_val:,.0f}" if (ma200_val and not (isinstance(ma200_val, float) and math.isnan(ma200_val))) else ""
                    st.markdown(
                        f'<div style="display:flex;align-items:center;gap:14px;margin-bottom:4px">'
                        f'<div style="font-size:30px;font-weight:900;color:{mm_c}">{mm_f:.3f}</div>'
                        f'<div style="font-size:12px;color:{mm_c}">{mm_lbl}</div>'
                        f'</div>'
                        f'<div style="font-size:10px;color:#4A607A">Price / 200D MA'
                        f'{ma_note}</div>',
                        unsafe_allow_html=True)
            except Exception:
                st.caption("Mayer Multiple data unavailable.")

    with oc_col2:
        # MVRV Z-Score (hardcoded with date)
        st.markdown(
            '<p style="font-size:11px;font-weight:700;color:#4A607A;'
            'letter-spacing:0.6px;margin-bottom:6px">MVRV Z-SCORE</p>',
            unsafe_allow_html=True)
        _zscore_val   = 0.41
        _zscore_date  = "Jun 19 2026"
        _zscore_lbl   = "Near fair value — mild accumulation zone"
        _zscore_color = "#A0AEC0"
        st.markdown(
            f'<div style="display:flex;align-items:center;gap:14px;margin-bottom:4px">'
            f'<div style="font-size:30px;font-weight:900;color:{_zscore_color}">'
            f'{_zscore_val}</div>'
            f'<div>'
            f'<div style="font-size:12px;color:{_zscore_color}">{_zscore_lbl}</div>'
            f'<div style="font-size:10px;color:#2D3E56">As of {_zscore_date} · '
            f'updated weekly</div>'
            f'</div></div>'
            f'<div style="font-size:10px;color:#2D3E56;margin-top:2px">'
            f'Zones: &lt;0 undervalued · 0-2 fair · 2-6 overvalued · &gt;6 extreme</div>',
            unsafe_allow_html=True)
        st.caption("Live data: [charts.bitbo.io/index/](https://charts.bitbo.io/index/)")

        st.markdown('<div style="margin-top:14px"></div>', unsafe_allow_html=True)

        # NUPL (hardcoded with date)
        st.markdown(
            '<p style="font-size:11px;font-weight:700;color:#4A607A;'
            'letter-spacing:0.6px;margin-bottom:6px">NUPL (NET UNREALIZED P/L)</p>',
            unsafe_allow_html=True)
        _nupl_val  = 0.28
        _nupl_date = "Jun 2026"
        _nupl_lbl  = "Hope / Fear — mid-cycle"
        _nupl_c    = "#A0AEC0"
        st.markdown(
            f'<div style="display:flex;align-items:center;gap:14px;margin-bottom:4px">'
            f'<div style="font-size:30px;font-weight:900;color:{_nupl_c}">{_nupl_val}</div>'
            f'<div>'
            f'<div style="font-size:12px;color:{_nupl_c}">{_nupl_lbl}</div>'
            f'<div style="font-size:10px;color:#2D3E56">As of {_nupl_date} · '
            f'updated weekly</div>'
            f'</div></div>',
            unsafe_allow_html=True)
        st.caption("Live data: [charts.bitbo.io/index/](https://charts.bitbo.io/index/)")

    st.markdown('<hr class="sect-div">', unsafe_allow_html=True)

    # ── 6. Mining & Network Security ─────────────────────────────────────────
    st.markdown(
        '<p style="font-size:12px;font-weight:700;color:#A0AEC0;'
        'letter-spacing:0.6px;margin-bottom:8px">MINING & NETWORK SECURITY</p>',
        unsafe_allow_html=True)
    if hr:
        m1, m2, m3, m4 = st.columns(4)
        _hr_ehs = hr.get("hashrate_ehs")
        if _hr_ehs is not None and not (isinstance(_hr_ehs, float) and (math.isnan(_hr_ehs) or math.isinf(_hr_ehs))):
            m1.metric("Hash Rate", f"{_hr_ehs:.1f} EH/s")
        _diff = hr.get("difficulty")
        if _diff is not None:
            try:
                _diff_t = float(_diff) / 1e12
                if not math.isnan(_diff_t):
                    m2.metric("Difficulty", f"{_diff_t:.2f}T")
            except Exception:
                pass
        _dc = hr.get("difficulty_change_pct")
        if _dc is not None and not (isinstance(_dc, float) and (math.isnan(_dc) or math.isinf(_dc))):
            m3.metric("Next Adjustment", f"{float(_dc):+.2f}%")
        _rb = hr.get("remaining_blocks")
        if _rb is not None:
            m4.metric("Blocks to Retarget", f"{int(_rb):,}")
    else:
        st.caption("Mining data temporarily unavailable (mempool.space).")

    _circ = cg.get("circulating")
    _max  = cg.get("max_supply")
    if _circ and _max:
        try:
            pct_mined = float(_circ) / float(_max) * 100
            if not math.isnan(pct_mined):
                s1, s2, s3 = st.columns(3)
                s1.metric("Circulating Supply", f"{float(_circ)/1e6:.3f}M BTC")
                s2.metric("Max Supply",         "21.000M BTC")
                s3.metric("% of 21M Mined",     f"{pct_mined:.2f}%")
        except Exception:
            pass

    st.markdown('<hr class="sect-div">', unsafe_allow_html=True)

    # ── 7. Fear & Greed ──────────────────────────────────────────────────────
    fg_col, fgh_col = st.columns([1, 2])
    with fg_col:
        if fg.get("value") is not None:
            fgv = fg["value"]; fgl = fg.get("label", "")
            fgc = ("#FF4757" if fgv < 25 else "#FF7043" if fgv < 45 else
                   "#FFA502" if fgv < 55 else "#00C896" if fgv < 75 else "#00E676")
            fig_fg = go.Figure(go.Indicator(
                mode="gauge+number",
                value=fgv,
                title={"text": f"<b>Fear & Greed</b><br>"
                               f"<span style='font-size:12px;color:#9AA5B4'>{fgl}</span>",
                       "font": {"size": 14, "color": "#E2E8F0"}},
                number={"font": {"size": 42, "color": fgc}},
                gauge={
                    "axis": {"range": [0, 100], "tickwidth": 1, "tickcolor": "#2D3E56",
                             "tickfont": {"color": "#2D3E56", "size": 8}},
                    "bar": {"color": fgc, "thickness": 0.22},
                    "bgcolor": "#0A1628", "borderwidth": 0,
                    "steps": [
                        {"range": [0,  25], "color": "rgba(255,71,87,0.12)"},
                        {"range": [25, 45], "color": "rgba(255,112,67,0.10)"},
                        {"range": [45, 55], "color": "rgba(255,165,2,0.10)"},
                        {"range": [55, 75], "color": "rgba(0,200,150,0.08)"},
                        {"range": [75,100], "color": "rgba(0,230,118,0.12)"},
                    ],
                    "threshold": {"line": {"color": fgc, "width": 3},
                                  "thickness": 0.8, "value": fgv},
                }
            ))
            fig_fg.update_layout(paper_bgcolor="rgba(0,0,0,0)",
                                 font=dict(family="Inter, sans-serif"),
                                 height=220, margin=dict(l=16, r=16, t=50, b=10))
            st.plotly_chart(fig_fg, use_container_width=True)
            st.caption("0 = Extreme Fear · 100 = Extreme Greed")

    with fgh_col:
        if fg.get("history"):
            hist_df = pd.DataFrame(fg["history"])
            hist_df["date"] = pd.to_datetime(hist_df["date"], unit="s")
            hist_df = hist_df.sort_values("date")
            fig_fgh = _fig(title="Fear & Greed — 30D History", height=220)
            fig_fgh.add_trace(go.Bar(
                x=hist_df["date"], y=hist_df["value"],
                marker_color=[
                    "#FF4757" if v < 25 else "#FF7043" if v < 45 else
                    "#FFA502" if v < 55 else "#00C896" if v < 75 else "#00E676"
                    for v in hist_df["value"]
                ],
                hovertemplate="%{y}<extra></extra>",
            ))
            fig_fgh.add_hline(y=50, line_dash="dot", line_color="#2D3E56", line_width=1)
            st.plotly_chart(fig_fgh, use_container_width=True)

    if tech.get("mayer_series") is not None:
        mm_ser = tech["mayer_series"].dropna()
        if len(mm_ser) > 1:
            fig_mm = line_chart(mm_ser, "Mayer Multiple (Price / 200D MA)", "ratio",
                                hlines=[
                                    {"y": 2.4, "color": "#FF4757", "label": "2.4 — euphoric"},
                                    {"y": 1.0, "color": "#2D3E56", "label": "1.0 — fair"},
                                    {"y": 0.8, "color": "#00C896", "label": "0.8 — undervalue"},
                                ], color="#F7931A", height=220)
            st.plotly_chart(fig_mm, use_container_width=True)
            st.caption("Mayer Multiple > 2.4 — historically near cycle tops. "
                       "< 0.8 — historically strong accumulation zone.")
        else:
            st.caption("Mayer Multiple chart data unavailable.")


# ══════════════════════════════════════════════════════════════════════════════
# MACRO TAB
# ══════════════════════════════════════════════════════════════════════════════

with tab_macro:
    if fred_data is None:
        _alert("Enter your FRED API key in the sidebar to load macro data.", "info")
    else:
        r_us, r_eu, r_uk = st.tabs(["United States", "Euro Area", "United Kingdom"])

        # ═══ US ═══════════════════════════════════════════════════════════════
        with r_us:
            sect("Monetary Policy")
            ffr = _s("fed_funds"); core_pce = _s("core_pce_yoy")
            ffr_l2 = _latest("fed_funds"); core_pce_l2 = _latest("core_pce_yoy")
            real_ffr = compute_real_fed_funds(ffr, core_pce)
            c1, c2, c3 = st.columns(3)
            if ffr_l2:        c1.metric("Fed Funds Rate",      f"{ffr_l2:.2f}%")
            if not real_ffr.empty:
                try:
                    _rffr = float(real_ffr.dropna().values[-1])
                    c2.metric("Real Fed Funds Rate", f"{_rffr:.2f}%",
                              help="FFR minus Core PCE — true tightness gauge")
                except Exception:
                    pass
            if core_pce_l2:  c3.metric("Core PCE (Fed target)", f"{core_pce_l2:.2f}%")
            col_a, col_b = st.columns(2)
            if ffr is not None:      chart_col(col_a, ffr.dropna(), "Fed Funds Rate", "%")
            if not real_ffr.empty:
                chart_col(col_b, real_ffr.dropna(), "Real Fed Funds Rate", "%",
                          hlines=[{"y": 0, "color": "#2D3E56", "label": "Neutral"}])

            sect("Yield Curve & Treasury Yields")
            y3m = _s("3m_yield"); y2 = _s("2y_yield")
            y10 = _s("10y_yield"); y30 = _s("30y_yield")
            y3m_l2 = _latest("3m_yield"); y2_l2  = _latest("2y_yield")
            y10_l2 = _latest("10y_yield"); y30_l2 = _latest("30y_yield")
            sp2 = (y10_l2 - y2_l2)  if (y10_l2 and y2_l2)  else None
            sp3 = (y10_l2 - y3m_l2) if (y10_l2 and y3m_l2) else None
            c1, c2, c3, c4 = st.columns(4)
            for col, val, lbl in [(c1,y3m_l2,"3M"),(c2,y2_l2,"2Y"),(c3,y10_l2,"10Y"),(c4,y30_l2,"30Y")]:
                if val: col.metric(f"{lbl} Yield", f"{val:.2f}%")
            c1, c2 = st.columns(2)
            if sp2 is not None: c1.metric("2s10s Spread", f"{sp2:.2f}%", yield_curve_status(sp2)["label"])
            if sp3 is not None: c2.metric("3m10y Spread", f"{sp3:.2f}%", yield_curve_status(sp3)["label"],
                                           help="Fed's preferred recession indicator")
            col_a, col_b = st.columns(2)
            if y2 is not None and y10 is not None:
                chart_col(col_a, (y10 - y2).dropna(), "2s10s Spread", "%",
                          hlines=[{"y": 0, "color": "#FF4757", "label": "Inversion"}])
            if y3m is not None and y10 is not None:
                chart_col(col_b, (y10 - y3m).dropna(), "3m10y Spread", "%",
                          hlines=[{"y": 0, "color": "#FF4757", "label": "Inversion"}])
            if any(s is not None for s in [y3m, y2, y10, y30]):
                fig_yc = multi_line_chart({"3M": y3m, "2Y": y2, "10Y": y10, "30Y": y30},
                                           "US Treasury Yield Curve — All Tenors", "%")
                st.plotly_chart(fig_yc, use_container_width=True)
            col_a, col_b = st.columns(2)
            if y2 is not None:  chart_col(col_a, y2.dropna(),  "2Y Treasury",  "%", "2y_yield")
            if y10 is not None: chart_col(col_b, y10.dropna(), "10Y Treasury", "%", "10y_yield")

            sect("Real Yields & Inflation Expectations",
                 "Real yields (TIPS) strip out inflation and drive risk-asset valuations. "
                 "Positive real yields create genuine competition for equities.")
            r10 = _s("real_10y"); be = _s("breakeven_10y")
            c1, c2 = st.columns(2)
            if _latest("real_10y"):      c1.metric("10Y Real (TIPS)",  f"{_latest('real_10y'):.2f}%")
            if _latest("breakeven_10y"): c2.metric("10Y Breakeven",    f"{_latest('breakeven_10y'):.2f}%")
            col_a, col_b = st.columns(2)
            if r10 is not None: chart_col(col_a, r10.dropna(), "10Y TIPS Real Yield", "%",
                                hlines=[{"y": 0, "color": "#2D3E56", "label": "Zero"}])
            if be is not None:  chart_col(col_b, be.dropna(),  "10Y Breakeven Inflation", "%",
                                hlines=[{"y": 2.0, "color": "#FFA502", "dash": "dot", "label": "2%"}])

            sect("Inflation — CPI, PCE & PPI")
            cpi = _s("cpi_yoy"); cc = _s("core_cpi_yoy")
            pce = _s("pce_yoy"); cpce = _s("core_pce_yoy"); ppi = _s("ppi_yoy")
            c1, c2, c3, c4, c5 = st.columns(5)
            for col, key, lbl in [(c1,"cpi_yoy","CPI"),(c2,"core_cpi_yoy","Core CPI"),
                                  (c3,"pce_yoy","PCE"),(c4,"core_pce_yoy","Core PCE"),(c5,"ppi_yoy","PPI")]:
                v = _latest(key)
                if v is not None:
                    g = cpi_vs_target(v)
                    col.metric(lbl, f"{v:.2f}%", f"{g['gap']:+.2f}pp vs 2%")
            fig_inf = multi_line_chart({"CPI": cpi, "Core CPI": cc, "PCE": pce, "Core PCE": cpce},
                                        "US Inflation (YoY %)", "%")
            fig_inf.add_hline(y=2.0, line_dash="dash", line_color="#FFA502", line_width=1,
                              annotation_text="2%", annotation_font_size=9, annotation_font_color="#7B8FA5")
            st.plotly_chart(fig_inf, use_container_width=True)
            col_a, col_b = st.columns(2)
            if pce is not None: chart_col(col_a, pce.dropna(), "PCE Inflation YoY", "%",
                               hlines=[{"y": 2.0, "color": "#FFA502", "label": "2%"}])
            if ppi is not None: chart_col(col_b, ppi.dropna(), "PPI YoY %", "%")
            st.caption("Core PCE is the Fed's primary target. PPI typically leads CPI by 3-6 months.")
            zscore_pill("core_pce_yoy")

            sect("Labor Market")
            unemp = _s("unemployment"); nfp = _s("nfp"); claims = _s("initial_claims")
            sahm2 = compute_sahm_rule(unemp)
            c1, c2, c3, c4 = st.columns(4)
            if _latest("unemployment"):
                tr = series_trend(unemp, 3)
                c1.metric("Unemployment", f"{_latest('unemployment'):.2f}%",
                          f"{tr:+.2f}pp vs 3m" if tr else None)
            if nfp is not None and not nfp.dropna().empty:
                try:
                    _nfp_s = nfp.dropna()
                    _nfp_last = float(_nfp_s.values[-1])
                    _nfp_mom = float(_nfp_s.diff().values[-1])
                    c2.metric("NFP (k)", f"{_nfp_last:,.0f}",
                              f"{_nfp_mom:+,.0f} MoM" if math.isfinite(_nfp_mom) else None)
                except Exception:
                    pass
            if _latest("initial_claims"):
                tr2 = series_trend(claims, 4)
                c3.metric("Init. Claims", f"{_latest('initial_claims'):,.0f}",
                          f"{tr2:+,.0f} vs 4wk" if tr2 else None)
            if sahm2["value"] is not None:
                c4.metric("Sahm Rule", f"{sahm2['value']:.2f}pp",
                          "Triggered" if sahm2["triggered"] else "Clear")
            if sahm2["triggered"]:
                _alert("Sahm Rule triggered — early recession signal.", "error")
            col_a, col_b = st.columns(2)
            if unemp is not None:  chart_col(col_a, unemp.dropna(), "Unemployment Rate", "%")
            if claims is not None: chart_col(col_b, claims.dropna(), "Initial Claims", "persons",
                                   hlines=[{"y": 300000, "color": "#FFA502", "label": "~300k elevated"}])
            if sahm2["series"] is not None:
                fig_sahm = line_chart(sahm2["series"].dropna(), "Sahm Rule Indicator", "pp",
                                      hlines=[{"y": 0.50, "color": "#FF4757", "label": "Trigger (0.50)"}])
                st.plotly_chart(fig_sahm, use_container_width=True)

            sect("Leading Indicators")
            c1, c2, c3, c4 = st.columns(4)
            for col, key, lbl, _fstr in [
                (c1, "retail_sales_yoy",   "Retail Sales YoY",  "{:.2f}%"),
                (c2, "housing_starts",     "Housing Starts (k)", "{:,.0f}"),
                (c3, "consumer_sentiment", "UMich Sentiment",   "{:.1f}"),
                (c4, "m2_yoy",             "M2 YoY %",          "{:.2f}%"),
            ]:
                v = _latest(key)
                if v is not None:
                    tr = series_trend(_s(key), 3)
                    col.metric(lbl, _fstr.format(v), f"{tr:+.2f} vs 3m" if tr else None)
            col_a, col_b = st.columns(2)
            rs = _s("retail_sales_yoy"); hs = _s("housing_starts")
            if rs is not None: chart_col(col_a, rs.dropna(), "Retail Sales YoY", "%",
                               hlines=[{"y": 0, "color": "#2D3E56", "label": "Zero"}])
            if hs is not None: chart_col(col_b, hs.dropna(), "Housing Starts", "k")
            col_a, col_b = st.columns(2)
            se = _s("consumer_sentiment"); m2 = _s("m2_yoy")
            if se is not None: chart_col(col_a, se.dropna(), "UMich Consumer Sentiment", "index")
            if m2 is not None: chart_col(col_b, m2.dropna(), "M2 Money Supply YoY", "%",
                               hlines=[{"y": 0, "color": "#FF4757", "label": "Contraction"}])

            sect("Growth (CFNAI) & Credit Spreads")
            cfnai = _s("cfnai"); hy = _s("hy_oas"); ig = _s("ig_oas")
            cfnai_l2 = _latest("cfnai"); hy_l2 = _latest("hy_oas"); ig_l2 = _latest("ig_oas")
            cst = credit_spread_status(hy_l2)
            c1, c2, c3 = st.columns(3)
            if cfnai_l2 is not None:
                c1.metric("CFNAI", f"{cfnai_l2:.2f}",
                          "Above trend" if cfnai_l2 > 0 else "Below trend")
            if hy_l2 is not None: c2.metric("HY OAS", f"{hy_l2:.2f}%", cst["label"])
            if ig_l2 is not None: c3.metric("IG OAS", f"{ig_l2:.2f}%")
            if cst["status"] in ("elevated", "crisis"):
                _alert(f"HY credit spreads {cst['label'].lower()} — {hy_l2:.2f}%", "warning")
            col_a, col_b = st.columns(2)
            if cfnai is not None: chart_col(col_a, cfnai.dropna(), "CFNAI", "index",
                                  hlines=[{"y": 0,    "color": "#2D3E56", "label": "Trend"},
                                          {"y": -0.7, "color": "#FF4757", "dash": "dot", "label": "Recession risk"}])
            if hy is not None:    chart_col(col_b, hy.dropna(), "HY Credit Spread (OAS)", "%",
                                  hlines=[{"y": 5, "color": "#FFA502", "label": "Elevated"},
                                          {"y": 8, "color": "#FF4757", "label": "Crisis"}])

        # ═══ EU ═══════════════════════════════════════════════════════════════
        with r_eu:
            sect("ECB Monetary Policy")
            ecb_rate = _s("ecb_deposit_rate"); eu_10y_s = _s("eu_10y_yield")
            ecb_l2 = _latest("ecb_deposit_rate"); eu_10y_l2 = _latest("eu_10y_yield")
            c1, c2 = st.columns(2)
            if ecb_l2:    c1.metric("ECB Deposit Rate", f"{ecb_l2:.2f}%")
            if eu_10y_l2: c2.metric("Euro Area 10Y",    f"{eu_10y_l2:.2f}%")
            col_a, col_b = st.columns(2)
            if ecb_rate is not None: chart_col(col_a, ecb_rate.dropna(), "ECB Deposit Rate", "%")
            if eu_10y_s is not None: chart_col(col_b, eu_10y_s.dropna(), "Euro Area 10Y Yield", "%", "eu_10y_yield")

            sect("Sovereign Yields & BTP-Bund Spread",
                 "BTP-Bund = Italy 10Y minus Germany 10Y in bps. The primary EU fragmentation risk gauge.")
            de = _s("de_10y_yield"); it = _s("it_10y_yield")
            fr = _s("fr_10y_yield"); es = _s("es_10y_yield")
            de_l2 = _latest("de_10y_yield"); it_l2 = _latest("it_10y_yield")
            fr_l2 = _latest("fr_10y_yield"); es_l2 = _latest("es_10y_yield")
            c1, c2, c3, c4 = st.columns(4)
            for col, val, lbl in [(c1,de_l2,"Germany (Bund)"),(c2,it_l2,"Italy (BTP)"),
                                  (c3,fr_l2,"France (OAT)"),(c4,es_l2,"Spain (Bonos)")]:
                if val: col.metric(f"{lbl} 10Y", f"{val:.2f}%")
            btp = compute_btp_bund_spread(it, de)
            if not btp.empty:
                try:
                    btp_l2 = float(btp.dropna().values[-1])
                except Exception:
                    btp_l2 = None
                if btp_l2 is not None:
                    btp_st2 = btp_bund_status(btp_l2)
                    tr_b = series_trend(btp, 3)
                    c1, c2 = st.columns(2)
                    c1.metric("BTP-Bund Spread", f"{btp_l2:.0f} bps", btp_st2["label"])
                    if tr_b: c2.metric("vs 3m ago", f"{tr_b:+.0f}bps")
                    if btp_st2["status"] in ("elevated", "stress"):
                        _alert(f"BTP-Bund {btp_st2['label']} — {btp_l2:.0f}bps. ECB steps in above ~200-250bps.", "warning")
                col_a, col_b = st.columns(2)
                chart_col(col_a, btp.dropna(), "BTP-Bund Spread", "bps",
                          hlines=[{"y": 150, "color": "#FFA502", "label": "Elevated (150bps)"},
                                  {"y": 250, "color": "#FF4757", "label": "Crisis (250bps)"}])
                with col_b:
                    fig_cy = multi_line_chart({"Germany": de, "Italy": it, "France": fr, "Spain": es},
                                               "Euro Area 10Y Sovereign Yields", "%")
                    st.plotly_chart(fig_cy, use_container_width=True)

            sect("HICP Inflation & Labor")
            eu_hicp_s = _s("eu_hicp"); eu_hicp_l2 = _latest("eu_hicp")
            eu_u = _s("eu_unemployment"); eu_u_l2 = _latest("eu_unemployment")
            eur = _s("eur_usd")
            c1, c2, c3 = st.columns(3)
            if eu_hicp_l2 is not None:
                g = cpi_vs_target(eu_hicp_l2)
                c1.metric("EU HICP YoY", f"{eu_hicp_l2:.2f}%", f"{g['gap']:+.2f}pp vs 2%")
                zscore_pill("eu_hicp")
            if eu_u_l2 is not None:
                tr = series_trend(eu_u, 3)
                c2.metric("EU Unemployment", f"{eu_u_l2:.2f}%", f"{tr:+.2f}pp vs 3m" if tr else None)
            if _latest("eur_usd"): c3.metric("EUR/USD", f"{_latest('eur_usd'):.4f}")
            col_a, col_b = st.columns(2)
            if eu_hicp_s is not None:
                fig_hicp = line_chart(eu_hicp_s.dropna(), "EU HICP YoY %", "%",
                                      hlines=[{"y": 2.0, "color": "#FFA502", "label": "2% ECB target"}])
                with col_a: st.plotly_chart(fig_hicp, use_container_width=True)
            if eur is not None: chart_col(col_b, eur.dropna(), "EUR/USD", "USD per EUR", "eur_usd")
            eu_reg2 = classify_eu_macro_regime(eu_hicp_l2, eu_u_l2)
            if eu_reg2["regime"]:
                st.caption(f"EU Regime: {eu_reg2['label']} — {eu_reg2['description']}")

        # ═══ UK ═══════════════════════════════════════════════════════════════
        with r_uk:
            sect("Bank of England & UK Rates")
            boe = _s("boe_rate"); uk10 = _s("uk_10y_yield")
            c1, c2 = st.columns(2)
            if _latest("boe_rate"):     c1.metric("BoE Base Rate", f"{_latest('boe_rate'):.2f}%")
            if _latest("uk_10y_yield"): c2.metric("UK 10Y Gilt",   f"{_latest('uk_10y_yield'):.2f}%")
            col_a, col_b = st.columns(2)
            if boe is not None:  chart_col(col_a, boe.dropna(),  "BoE Base Rate",      "%")
            if uk10 is not None: chart_col(col_b, uk10.dropna(), "UK 10Y Gilt Yield",  "%", "uk_10y_yield")

            sect("UK Inflation & Labor")
            uk_cpi = _s("uk_cpi_yoy"); uk_u = _s("uk_unemployment")
            c1, c2 = st.columns(2)
            if _latest("uk_cpi_yoy"):
                g = cpi_vs_target(_latest("uk_cpi_yoy"))
                c1.metric("UK CPI YoY", f"{_latest('uk_cpi_yoy'):.2f}%", f"{g['gap']:+.2f}pp vs 2%")
            if _latest("uk_unemployment"):
                tr = series_trend(uk_u, 3)
                c2.metric("UK Unemployment", f"{_latest('uk_unemployment'):.2f}%",
                          f"{tr:+.2f}pp vs 3m" if tr else None)
            col_a, col_b = st.columns(2)
            if uk_cpi is not None: chart_col(col_a, uk_cpi.dropna(), "UK CPI YoY %", "%",
                                   hlines=[{"y": 2.0, "color": "#FFA502", "label": "2%"}])
            if uk_u is not None:   chart_col(col_b, uk_u.dropna(),   "UK Unemployment", "%")

            sect("3-Way Yield Comparison — US / Germany / UK")
            fig_3w = multi_line_chart(
                {"US 10Y": _s("10y_yield"), "Germany Bund": _s("de_10y_yield"), "UK Gilt": uk10},
                "10Y Yields — US vs DE vs UK", "%", height=300)
            st.plotly_chart(fig_3w, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# MARKETS TAB
# ══════════════════════════════════════════════════════════════════════════════

with tab_markets:
    if is_market_hours():
        st_autorefresh(interval=120000, key="markets_refresh")
    bench_df     = market_data.get("^GSPC", {}).get("df")
    try:
        bench_ret = bench_df["Close"].squeeze().dropna().pct_change().dropna() if bench_df is not None else None
    except Exception:
        bench_ret = None
    eu_bench_df  = market_data.get("^STOXX50E", {}).get("df")
    try:
        eu_bench_ret = eu_bench_df["Close"].squeeze().dropna().pct_change().dropna() if eu_bench_df is not None else None
    except Exception:
        eu_bench_ret = None

    def snap_grid(tickers):
        cols = st.columns(len(tickers))
        for i, ticker in enumerate(tickers):
            meta  = market_data.get(ticker) or {}
            label = meta.get("label", ticker)
            with cols[i]:
                try:
                    df = meta.get("df")
                    if df is None or df.empty:
                        st.metric(label, "—")
                        continue
                    if isinstance(df.columns, pd.MultiIndex):
                        df = df.copy()
                        df.columns = df.columns.get_level_values(0)
                    closes = df["Close"].dropna()
                    if len(closes) < 2:
                        st.metric(label, "—")
                        continue
                    last = float(closes.values[-1])
                    prev = float(closes.values[-2])
                    chg  = ((last - prev) / prev) * 100
                    chg_s = f"{chg:+.2f}%" if math.isfinite(chg) else None
                    st.metric(label, fmt(last, 2), chg_s)
                except Exception:
                    st.metric(label, "—")

    def chart_grid(tickers, ncols=2, color="#2979FF"):
        cols = st.columns(ncols); i = 0
        for t in tickers:
            meta = market_data.get(t)
            if not meta or meta["df"] is None or meta["df"].empty: continue
            close = meta["df"]["Close"].squeeze().dropna()
            if close.empty or len(close) < 2: continue
            chart_col(cols[i % ncols], close,
                      f"{meta['label']} ({t})", "", t, color=color)
            i += 1

    def beta_grid(tickers, bench_ret):
        cols = st.columns(len(tickers))
        for i, ticker in enumerate(tickers):
            with cols[i]:
                try:
                    df = yf.Ticker(ticker).history(period='1y')
                    if df is None or df.empty:
                        st.metric(ticker, "—")
                        continue
                    close = df['Close'].squeeze().dropna()
                    if len(close) < 20:
                        st.metric(ticker, "—")
                        continue
                    ret = close.pct_change().dropna()
                    if bench_ret is None or not hasattr(bench_ret, '__len__') or len(bench_ret) < 20:
                        st.metric(ticker, "—")
                        continue
                    combined = pd.DataFrame({
                        'stock': ret,
                        'bench': bench_ret
                    }).dropna()
                    if len(combined) < 20:
                        st.metric(ticker, "—")
                        continue
                    cov = float(combined['stock'].cov(combined['bench']))
                    var = float(combined['bench'].var())
                    if var == 0:
                        st.metric(ticker, "—")
                        continue
                    beta = cov / var
                    if math.isnan(beta) or math.isinf(beta):
                        st.metric(ticker, "—")
                        continue
                    st.metric(ticker, f"{beta:.2f}")
                except Exception:
                    st.metric(ticker, "—")

    mkt_us, mkt_fi, mkt_comm, mkt_eu, mkt_sect = st.tabs(
        ["US Equity", "Fixed Income", "Commodities & FX", "EU Markets", "Sectors"])

    with mkt_us:
        snap_grid(["^GSPC", "^IXIC", "^DJI", "IWM", "^VIX"])
        sect("Historical Charts")
        chart_grid(["^GSPC", "^IXIC", "^DJI", "IWM"])
        sect("Beta vs S&P 500")
        beta_grid(["^IXIC", "^DJI", "IWM", "^VIX"], bench_ret)

    with mkt_fi:
        snap_grid(["TLT", "SHY", "TIP", "HYG", "LQD"])
        sect("Historical Charts")
        chart_grid(["TLT", "SHY", "TIP", "HYG", "LQD"])
        sect("HYG/LQD Credit Stress Proxy",
             "Falling = HY underperforming IG = credit risk widening in real time.")
        hyg_df = market_data.get("HYG", {}).get("df")
        lqd_df = market_data.get("LQD", {}).get("df")
        if hyg_df is not None and lqd_df is not None and not hyg_df.empty and not lqd_df.empty:
            try:
                hyg_close = hyg_df["Close"].dropna()
                lqd_close = lqd_df["Close"].dropna()
                if not hyg_close.empty and not lqd_close.empty and hyg_close.iloc[0] and lqd_close.iloc[0]:
                    ratio = (hyg_close / hyg_close.iloc[0] * 100) / (lqd_close / lqd_close.iloc[0] * 100)
                    ratio = ratio.dropna()
                    if len(ratio) > 1:
                        st.plotly_chart(
                            line_chart(ratio, "HYG/LQD Relative Performance (rebased=100)", "ratio",
                                       color="#FFA502", height=220),
                            use_container_width=True)
                    else:
                        st.caption("HYG/LQD chart data unavailable.")
            except Exception:
                st.caption("HYG/LQD chart data unavailable.")
        sect("Beta vs S&P 500")
        beta_grid(["TLT", "SHY", "TIP", "HYG", "LQD"], bench_ret)

    with mkt_comm:
        st.caption("Copper (HG=F) is a leading global growth indicator — real-time economic demand gauge.")
        snap_grid(["GC=F", "SI=F", "CL=F", "NG=F", "HG=F"])
        chart_grid(["GC=F", "SI=F", "CL=F", "NG=F", "HG=F"])
        sect("USD & FX")
        snap_grid(["DX-Y.NYB", "EURUSD=X", "GBPUSD=X", "JPY=X", "CHF=X"])
        chart_grid(["DX-Y.NYB", "EURUSD=X", "GBPUSD=X", "JPY=X", "CHF=X"], color="#4FC3F7")

    with mkt_eu:
        snap_grid(["^STOXX50E", "^GDAXI", "^FTSE", "^FCHI", "FTSEMIB.MI", "^IBEX"])
        sect("Historical Charts")
        chart_grid(["^STOXX50E", "^GDAXI", "^FTSE", "^FCHI", "FTSEMIB.MI", "^IBEX"])
        sect("Beta vs Euro Stoxx 50")
        beta_grid(["^GDAXI", "^FTSE", "^FCHI", "FTSEMIB.MI", "^IBEX"], eu_bench_ret)

    with mkt_sect:
        sects = ["XLF", "XLE", "XLK", "XLV", "XLU", "XLI"]
        st.caption("Sector rotation tells you where in the cycle: Fin/Ind = early · Tech = mid · Energy/Util/HC = late.")
        st.caption("Prices update during market hours (Mon–Fri 9:30am–4pm ET). Charts use historical close prices.")
        snap_grid(sects)
        rebase = {}
        for t in sects:
            df2 = market_data.get(t, {}).get("df"); lbl = market_data.get(t, {}).get("label", t)
            if df2 is not None and not df2.empty:
                try:
                    base = df2["Close"].iloc[0]
                    if base and not (isinstance(base, float) and math.isnan(base)):
                        rebase[lbl] = df2["Close"] / base * 100
                except Exception:
                    pass
        if rebase:
            st.plotly_chart(
                multi_line_chart(rebase, "Sector ETF Relative Performance (rebased=100)", "index", height=300),
                use_container_width=True)
        else:
            st.caption("Chart data unavailable.")
        sect("Beta vs S&P 500")
        beta_grid(sects, bench_ret)


# ══════════════════════════════════════════════════════════════════════════════
# CROSS-ASSET TAB
# ══════════════════════════════════════════════════════════════════════════════

with tab_cross:
    sect("Cross-Asset Correlation Matrix",
         f"Rolling {CORRELATION_WINDOW_DAYS}-day return correlation — current-regime read, not long-run average.")
    corr = compute_correlation_matrix(market_data, CORRELATION_TICKERS, CORRELATION_WINDOW_DAYS)
    if not corr.empty:
        labels = [MARKET_TICKERS.get(t, t) for t in corr.columns]
        hm = go.Figure(data=go.Heatmap(
            z=corr.values, x=labels, y=labels,
            colorscale="RdBu", zmid=0, zmin=-1, zmax=1,
            text=corr.round(2).values, texttemplate="%{text}",
            textfont={"size": 10},
            colorbar=dict(title="Corr.", thickness=12, len=0.9),
        ))
        hm.update_layout(**{k: v for k, v in _BASE.items()
                            if k not in ("height", "showlegend", "margin")},
                          height=520, margin=dict(l=8, r=8, t=30, b=8),
                          title=f"{CORRELATION_WINDOW_DAYS}-Day Rolling Correlation")
        st.plotly_chart(hm, use_container_width=True)
        st.markdown("""
**Reading:** +1 (red) = moving together — weak diversification · -1 (blue) = opposite — true hedge · ~0 (white) = uncorrelated

**Key tells:** S&P 500 vs TLT flipping negative to positive = bonds stop hedging (inflation regime) ·
Copper decoupling from equities = growth crack forming
        """)
    else:
        _alert("Not enough data for the correlation matrix.", "warning")

    sect("US Recession Probability Scorecard")
    if fred_data is not None:
        y10_lx = _latest("10y_yield"); y2_lx = _latest("2y_yield"); y3m_lx = _latest("3m_yield")
        sp2x = (y10_lx - y2_lx)  if (y10_lx and y2_lx)  else None
        sp3x = (y10_lx - y3m_lx) if (y10_lx and y3m_lx) else None
        sahmx = compute_sahm_rule(_s("unemployment"))
        hy_lx = _latest("hy_oas"); cfnai_lx = _latest("cfnai")
        recx  = compute_recession_probability(sp2x, sp3x, sahmx["value"], hy_lx, cfnai_lx)
        if recx["probability"] is not None:
            rpx = recx["probability"]
            c1, c2 = st.columns([1, 3])
            c1.metric("Composite", f"{rpx}%", recx["label"])
            with c2: st.progress(rpx / 100)
            c1, c2, c3 = st.columns(3)
            for i, (lbl, val, dlt) in enumerate([
                ("3m10y", fmt(to_float(sp3x), 2, "%"),
                          yield_curve_status(sp3x)["label"] if sp3x is not None else None),
                ("2s10s", fmt(to_float(sp2x), 2, "%"),
                          yield_curve_status(sp2x)["label"] if sp2x is not None else None),
                ("Sahm",  fmt(to_float(sahmx["value"]), 2, "pp"),
                          "Triggered" if sahmx["triggered"] else "Clear"),
                ("HY OAS", fmt(to_float(hy_lx), 2, "%"),
                           credit_spread_status(hy_lx)["label"] if hy_lx is not None else None),
                ("CFNAI", fmt(to_float(cfnai_lx), 2),
                          "Below trend" if (cfnai_lx or 0) < 0 else "Above trend"),
            ]):
                [c1, c2, c3][i % 3].metric(lbl, val, dlt)

    sect("Global Yield & Inflation")
    if fred_data is not None:
        col_a, col_b = st.columns(2)
        with col_a:
            st.plotly_chart(
                multi_line_chart({"US 10Y": _s("10y_yield"), "Germany": _s("de_10y_yield"),
                                   "Italy BTP": _s("it_10y_yield"), "UK Gilt": _s("uk_10y_yield")},
                                  "10Y Sovereign Yields — Global", "%"),
                use_container_width=True)
        with col_b:
            fig_gi = multi_line_chart({"US CPI": _s("cpi_yoy"), "Core PCE": _s("core_pce_yoy"),
                                        "EU HICP": _s("eu_hicp"), "UK CPI": _s("uk_cpi_yoy")},
                                       "Inflation — US / EU / UK (YoY %)", "%")
            fig_gi.add_hline(y=2.0, line_dash="dash", line_color="#2D3E56", line_width=1)
            st.plotly_chart(fig_gi, use_container_width=True)

# ══════════════════════════════════════════════════════════════════════════════
# SIGNALS TAB (Modules 1-4)
# ══════════════════════════════════════════════════════════════════════════════

with tab_signals:
    if fred_data is None:
        _alert("Enter your FRED API key in the sidebar to load signal data.", "info")
    else:
        sig_m1, sig_m2, sig_m3, sig_m4 = st.tabs([
            "Market Expectations", "CFTC Positioning",
            "Divergence Scanner", "Central Banks",
        ])

        # ══ MODULE 1 — Market-Implied Forward Signals ══════════════════════════
        with sig_m1:
            ie  = compute_inflation_expectations(fred_data)
            frc = compute_forward_rate_curve(fred_data)

            st.markdown(
                '<p style="font-size:12px;font-weight:700;color:#A0AEC0;'
                'letter-spacing:0.6px;margin-bottom:8px">INFLATION EXPECTATIONS</p>',
                unsafe_allow_html=True)

            # Gap analysis row
            gap10 = ie.get("gap10")
            be10  = ie.get("be10")
            gap_color = "#FF4757" if (gap10 or 0) > 0.5 else "#FFA502" if (gap10 or 0) > 0 else "#00C896"
            if gap10 is not None:
                st.markdown(
                    f'<div style="border:1px solid #1A2540;border-left:4px solid {gap_color};'
                    f'border-radius:6px;padding:12px 16px;margin-bottom:12px;'
                    f'display:flex;align-items:center;gap:20px">'
                    f'<div>'
                    f'<div style="font-size:9px;color:#4A607A;text-transform:uppercase;'
                    f'letter-spacing:0.9px">10Y Breakeven vs Fed 2% Target</div>'
                    f'<div style="font-size:28px;font-weight:900;color:{gap_color}">'
                    f'{gap10:+.2f}pp</div>'
                    f'</div>'
                    f'<div style="font-size:12px;color:{gap_color}">'
                    f'{"Above target — inflation compensation exceeds Fed goal" if gap10 > 0 else "Below target — market confident of disinflation"}'
                    f'</div></div>',
                    unsafe_allow_html=True)

            # Metrics grid
            m1c1, m1c2, m1c3 = st.columns(3)
            _series_info = [
                (m1c1, "breakeven_10y", "10Y Breakeven", ie.get("be10"),
                 ie.get("be10_trend"), ie.get("be10_wchg"), ie.get("be10_mchg")),
                (m1c2, "breakeven_5y",  "5Y Breakeven", ie.get("be5"),
                 ie.get("be5_trend"), ie.get("be5_wchg"), ie.get("be5_mchg")),
                (m1c3, "breakeven_5y5y","5Y5Y Forward", ie.get("be55"),
                 ie.get("be55_trend"), ie.get("be55_wchg"), ie.get("be55_mchg")),
            ]
            for col, key, lbl, val, trend, wchg, mchg in _series_info:
                with col:
                    if val is not None and not (isinstance(val, float) and (math.isnan(val) or math.isinf(val))):
                        col.metric(lbl, f"{val:.2f}%", trend)
                        _wchg_ok = wchg is not None and not (isinstance(wchg, float) and (math.isnan(wchg) or math.isinf(wchg)))
                        _mchg_ok = mchg is not None and not (isinstance(mchg, float) and (math.isnan(mchg) or math.isinf(mchg)))
                        if _wchg_ok and _mchg_ok:
                            col.caption(f"1W: {wchg:+.2f}pp  |  1M: {mchg:+.2f}pp")
                    else:
                        col.metric(lbl, "—")

            # Breakevens chart
            if any(ie.get(k) is not None for k in ["be10_s", "be5_s", "be55_s"]):
                fig_be = multi_line_chart(
                    {
                        "10Y Breakeven": ie.get("be10_s"),
                        "5Y Breakeven":  ie.get("be5_s"),
                        "5Y5Y Forward":  ie.get("be55_s"),
                    },
                    "Inflation Breakevens — 3Y History", "%", height=280)
                fig_be.add_hline(y=2.0, line_dash="dash", line_color="#FFA502",
                                 line_width=1, annotation_text="2% Fed Target",
                                 annotation_font_color="#FFA502")
                st.plotly_chart(fig_be, use_container_width=True)

            if ie.get("interpretation"):
                st.info(ie["interpretation"])

            with st.expander("📚 Why breakevens matter for rate traders"):
                st.markdown("""
**Breakeven inflation** is derived from TIPS (Treasury Inflation-Protected Securities) vs nominal Treasuries.
It represents the market's *implied* average annual inflation over the specified period.

- **10Y Breakeven (T10YIE):** What market expects CPI to average over 10 years.
  If it exceeds 2.5% persistently, bond vigilantes typically sell Treasuries → yields rise.
- **5Y5Y Forward (T5YIFR):** Strips out near-term distortions. This is what the Fed
  watches most closely — a sustained rise above 2.5% signals loss of long-run credibility.
- **Trading implication:** Rising breakevens = long TIPS/gold/commodities,
  short duration. Falling = opposite. The *direction* matters more than the *level*.
""")

            st.markdown('<hr class="sect-div">', unsafe_allow_html=True)
            st.markdown(
                '<p style="font-size:12px;font-weight:700;color:#A0AEC0;'
                'letter-spacing:0.6px;margin-bottom:8px">RATE PATH EXPECTATIONS</p>',
                unsafe_allow_html=True)

            # Forward rate metrics
            rp1, rp2, rp3, rp4 = st.columns(4)
            for col, lbl, val in [
                (rp1, "Current 2Y Yield", frc.get("y2")),
                (rp2, "Current 10Y Yield", frc.get("y10")),
                (rp3, "2Y Rate, 2Y Fwd",  frc.get("fwd_2y2")),
                (rp4, "2Y Rate, 3Y Fwd",  frc.get("fwd_3y2")),
            ]:
                col.metric(lbl, f"{val:.2f}%" if val is not None else "—")

            # Forward curve bar chart
            fwd_vals = {
                "Now": frc.get("y2"),
                "2Y Fwd": frc.get("fwd_2y2"),
                "3Y Fwd": frc.get("fwd_3y2"),
                "10Y Now": frc.get("y10"),
            }
            if any(v is not None for v in fwd_vals.values()):
                labels = [k for k, v in fwd_vals.items() if v is not None]
                values = [v for v in fwd_vals.values() if v is not None]
                fig_fwd = go.Figure(go.Bar(
                    x=labels, y=values,
                    marker_color=["#2979FF", "#4FC3F7", "#A78BFA", "#FFA726"],
                    text=[f"{v:.2f}%" for v in values],
                    textposition="outside",
                ))
                fig_fwd.update_layout(
                    title="Rate Path — Current vs Forward Curve",
                    template="plotly_dark",
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(10,22,40,0.6)",
                    yaxis=dict(gridcolor="#1A2540", title="%"),
                    height=260, margin=dict(l=6, r=6, t=36, b=6),
                    font=dict(family="Inter, sans-serif", size=11, color="#7B8FA5"),
                )
                st.plotly_chart(fig_fwd, use_container_width=True)

            if frc.get("interpretation"):
                st.info(frc["interpretation"])

        # ══ MODULE 2 — CFTC Positioning ═══════════════════════════════════════
        with sig_m2:
            with st.spinner("Loading CFTC COT data..."):
                cot_raw = fetch_cot_data()
            cot = compute_cot_signals(cot_raw)

            st.markdown(
                '<p style="font-size:12px;font-weight:700;color:#A0AEC0;'
                'letter-spacing:0.6px;margin-bottom:4px">SPECULATIVE POSITIONING (CFTC COT)</p>',
                unsafe_allow_html=True)
            st.caption("Non-commercial (speculative) net long contracts — updated weekly (Tuesday release).")

            # Summary horizontal bar chart
            bar_labels = [r["label"] for r in cot if "net" in r]
            bar_vals   = [r["net"] for r in cot if "net" in r]
            bar_colors = ["#00C896" if v >= 0 else "#FF4757" for v in bar_vals]

            if bar_vals:
                fig_cot = go.Figure(go.Bar(
                    x=bar_vals, y=bar_labels,
                    orientation="h",
                    marker_color=bar_colors,
                    text=[f"{v:+,}" for v in bar_vals],
                    textposition="auto",
                    hovertemplate="%{y}: %{x:,.0f}<extra></extra>",
                ))
                fig_cot.update_layout(
                    title="Net Speculative Positions (contracts)",
                    template="plotly_dark",
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(10,22,40,0.6)",
                    xaxis=dict(gridcolor="#1A2540", title="Net Contracts"),
                    height=280, margin=dict(l=8, r=8, t=36, b=8),
                    font=dict(family="Inter, sans-serif", size=11, color="#7B8FA5"),
                )
                fig_cot.add_vline(x=0, line_color="#2D3E56", line_width=1)
                st.plotly_chart(fig_cot, use_container_width=True)
            else:
                _alert("CFTC data unavailable — the public API may be temporarily down.", "warning")

            # Signal cards
            st.markdown('<hr class="sect-div">', unsafe_allow_html=True)
            valid_cot = [r for r in cot if "net" in r]
            if valid_cot:
                cot_cols = st.columns(len(valid_cot))
                for i, row in enumerate(valid_cot):
                    with cot_cols[i]:
                        p = row["pct_rank"]
                        sc = row["sig_color"]
                        st.markdown(
                            f'<div style="border:1px solid #1A2540;border-radius:6px;'
                            f'padding:12px;text-align:center">'
                            f'<div style="font-size:11px;font-weight:700;color:#E2E8F0;'
                            f'margin-bottom:6px">{row["label"]}</div>'
                            f'<div style="font-size:22px;font-weight:900;color:#FFFFFF">'
                            f'{row["net"]:+,.0f}</div>'
                            f'<div style="font-size:10px;color:#4A607A">net contracts</div>'
                            f'<div style="font-size:14px;font-weight:700;color:{sc};'
                            f'margin:8px 0 4px">{row["signal"]}</div>'
                            f'<div style="font-size:10px;color:#4A607A">'
                            f'52W Pct: {p}th</div>'
                            f'<div style="font-size:10px;color:#2D3E56">'
                            f'as of {row.get("date","")}</div>'
                            f'</div>',
                            unsafe_allow_html=True)

            # Historical positioning charts
            st.markdown('<hr class="sect-div">', unsafe_allow_html=True)
            for row in valid_cot:
                s = row.get("net_series")
                if s is None or s.empty:
                    continue
                fig_h = _fig(title=f"{row['label']} — Net Speculative Positioning", height=200)
                fig_h.add_trace(go.Bar(
                    x=s.index, y=s.values,
                    marker_color=["#00C896" if v >= 0 else "#FF4757" for v in s.values],
                    hovertemplate="%{x|%Y-%m-%d}: %{y:,.0f}<extra></extra>",
                ))
                fig_h.add_hline(y=0, line_color="#2D3E56", line_width=1)
                st.plotly_chart(fig_h, use_container_width=True)

            for row in cot:
                if "error" in row:
                    st.caption(f"{row['label']}: data unavailable ({row['error'][:80]})")

            with st.expander("📚 What is CFTC positioning and why does it matter?"):
                st.markdown("""
**The CFTC (Commodity Futures Trading Commission)** publishes the Commitments of Traders
(COT) report every Friday, covering positions as of the previous Tuesday.

**Non-commercial (speculative) positions** are held by hedge funds, CTA trend-followers,
and discretionary macro funds — the most sentiment-driven part of the market.

**Net Long = Longs − Shorts.** A large net long means speculators are collectively betting
on price appreciation.

**Why crowded positioning creates reversal risk:**
When 80%+ of speculators are long (percentile rank >80%), they have already bought.
There are fewer incremental buyers left — but many potential sellers. A small price
reversal forces stop-losses, creating a cascade. Historically, crowded extremes
*precede* sharp reversals within 4-8 weeks.

**Trading implication:** Don't short just because positioning is crowded — you need
a catalyst. But it tells you the *risk/reward* is asymmetric. Crowded longs = downside
risk disproportionate. Crowded shorts = upside squeeze risk.
""")

        # ══ MODULE 3 — Divergence Scanner ══════════════════════════════════════
        with sig_m3:
            with st.spinner("Scanning for divergences..."):
                divergences = compute_divergence_scanner(market_data, fred_data)

            st.markdown(
                '<p style="font-size:12px;font-weight:700;color:#A0AEC0;'
                'letter-spacing:0.6px;margin-bottom:8px">CROSS-ASSET DIVERGENCE SCANNER</p>',
                unsafe_allow_html=True)
            st.caption("Flags when asset prices are moving against what macro fundamentals imply.")

            _STATUS_META = {
                "Red":   ("#FF4757", "rgba(255,71,87,0.08)",  "🔴 DIVERGENCE"),
                "Amber": ("#FFA502", "rgba(255,165,2,0.08)",  "🟡 MILD"),
                "Green": ("#00C896", "rgba(0,200,150,0.06)",  "🟢 ALIGNED"),
                "Grey":  ("#4A607A", "rgba(74,96,122,0.06)",  "⬜ N/A"),
            }

            red_count   = sum(1 for d in divergences if d["status"] == "Red")
            amber_count = sum(1 for d in divergences if d["status"] == "Amber")
            green_count = sum(1 for d in divergences if d["status"] == "Green")

            scan_col1, scan_col2, scan_col3 = st.columns(3)
            scan_col1.metric("🔴 Divergences", red_count)
            scan_col2.metric("🟡 Mild",        amber_count)
            scan_col3.metric("🟢 Aligned",     green_count)

            st.markdown('<hr class="sect-div">', unsafe_allow_html=True)

            for div in divergences:
                status = div["status"]
                meta   = _STATUS_META.get(status, _STATUS_META["Grey"])
                color, bg, label = meta
                first  = div.get("first_seen")
                st.markdown(
                    f'<div style="border:1px solid #1A2540;border-left:4px solid {color};'
                    f'background:{bg};border-radius:6px;padding:12px 16px;margin-bottom:8px">'
                    f'<div style="display:flex;justify-content:space-between;'
                    f'align-items:center;margin-bottom:6px">'
                    f'<div style="font-size:14px;font-weight:700;color:#E2E8F0">'
                    f'{div["name"]}</div>'
                    f'<div style="font-size:11px;font-weight:700;color:{color}">{label}</div>'
                    f'</div>'
                    f'<div style="font-size:12px;color:#A0AEC0;line-height:1.5">'
                    f'{div["description"]}</div>'
                    + (f'<div style="font-size:10px;color:#2D3E56;margin-top:6px">'
                       f'Signal noted: {first}</div>' if first else "")
                    + '</div>',
                    unsafe_allow_html=True)

            with st.expander("📚 Why divergences signal opportunity"):
                st.markdown("""
**Cross-asset divergences** occur when two markets that historically move together
(or inversely) temporarily de-couple. They matter because:

1. **They reveal mispricing.** One market is "wrong" — it must eventually converge.
2. **They signal regime shifts.** When traditional relationships break, a new macro
   theme is emerging (e.g., stagflation breaking the equity-bond correlation).
3. **They create asymmetric trades.** You know which direction the correction should go.

**Rules of thumb:**
- A divergence lasting <2 weeks is noise. >4 weeks is a signal worth trading.
- Divergences in *multiple* asset pairs simultaneously are far more significant.
- Always check positioning (Module 2) — crowded positioning often explains the divergence.

**Classic historical example:**
Late 2021 — Gold fell while real yields fell (Module 3 flag). This resolved via
gold recovering ~15% in early 2022 as the real rate narrative changed.
""")

        # ══ MODULE 4 — Central Bank Monitor ════════════════════════════════════
        with sig_m4:
            cb = compute_cb_tracker_extended(fred_data)

            st.markdown(
                '<p style="font-size:12px;font-weight:700;color:#A0AEC0;'
                'letter-spacing:0.6px;margin-bottom:8px">CENTRAL BANK MONITOR</p>',
                unsafe_allow_html=True)

            _DIR_COLOR = {"CUTS": "#00C896", "HIKES": "#FF4757", "HOLD": "#FFA502"}
            _STANCE_COLOR = {
                "Restrictive": "#FF4757", "Accommodative": "#00C896", "Neutral": "#FFA502",
            }

            # 4-column summary cards
            banks = [
                ("Federal Reserve", "fed",  "🇺🇸"),
                ("ECB",             "ecb",  "🇪🇺"),
                ("Bank of England", "boe",  "🇬🇧"),
                ("Bank of Japan",   "boj",  "🇯🇵"),
            ]
            cb_cols = st.columns(4)
            for i, (name, key, flag_emoji) in enumerate(banks):
                b = cb.get(key, {})
                rate      = b.get("rate")
                real      = b.get("real_rate")
                move      = b.get("implied_move") or "—"
                stance    = b.get("stance") or "—"
                mv_c      = _DIR_COLOR.get(move, "#A0AEC0")
                st_c      = _STANCE_COLOR.get(stance, "#A0AEC0")
                neutral_r = b.get("neutral")

                extra = ""
                if key == "fed" and b.get("next_meeting"):
                    extra = (f'<div style="font-size:10px;color:#4A607A;margin-top:4px">'
                             f'Next FOMC: {b["next_meeting"].strftime("%b %d, %Y")}</div>')
                if key == "boj" and b.get("ycc_note"):
                    extra = (f'<div style="font-size:10px;color:#4A607A;margin-top:4px">'
                             f'{b["ycc_note"]}</div>')

                with cb_cols[i]:
                    st.markdown(
                        f'<div style="border:1px solid #1A2540;border-radius:6px;padding:14px 12px">'
                        f'<div style="font-size:9px;font-weight:700;color:#4A607A;'
                        f'text-transform:uppercase;letter-spacing:0.9px;margin-bottom:6px">'
                        f'{flag_emoji} {name}</div>'
                        f'<div style="font-size:26px;font-weight:900;color:#FFFFFF">'
                        f'{"—" if rate is None else f"{rate:.2f}%"}</div>'
                        f'<div style="font-size:10px;color:#4A607A">Policy Rate</div>'
                        f'<div style="margin:8px 0 4px;padding-top:6px;border-top:1px solid #1A2540">'
                        f'<span style="font-size:9px;color:#4A607A">Next move: </span>'
                        f'<span style="font-size:13px;font-weight:700;color:{mv_c}">{move}</span>'
                        f'</div>'
                        f'<div style="font-size:10px;color:{st_c}">{stance}</div>'
                        + (f'<div style="font-size:10px;color:#4A607A">Real rate: '
                           f'{real:+.2f}%</div>' if real is not None else "")
                        + (f'<div style="font-size:10px;color:#2D3E56">Neutral: '
                           f'~{neutral_r:.1f}%</div>' if neutral_r is not None else "")
                        + extra
                        + '</div>',
                        unsafe_allow_html=True)

            st.caption(
                "Implied next move: 2Y yield vs policy rate spread."
                " Spread < -0.25% → CUTS; > +0.25% → HIKES; else HOLD.")

            st.markdown('<hr class="sect-div">', unsafe_allow_html=True)

            # Timeline chart — all 4 policy rates
            rate_series = {}
            for _, key, _ in banks:
                b = cb.get(key, {})
                s = b.get("series")
                label_map = {"fed": "Fed", "ecb": "ECB", "boe": "BOE", "boj": "BOJ"}
                if s is not None and not s.empty:
                    # Last 5 years
                    cutoff = pd.Timestamp.now() - pd.DateOffset(years=5)
                    s_filt = s[s.index >= cutoff]
                    if not s_filt.empty:
                        rate_series[label_map[key]] = s_filt
            if rate_series:
                fig_cb = multi_line_chart(rate_series, "Central Bank Policy Rates — 5Y", "%", height=300)
                st.plotly_chart(fig_cb, use_container_width=True)

            # Divergence note
            fed_b = cb.get("fed", {})
            ecb_b = cb.get("ecb", {})
            boe_b = cb.get("boe", {})
            boj_b = cb.get("boj", {})

            cutting = [b for b in ["Fed", "ECB", "BOE"] if cb.get(b.lower().replace(" ",""), {}).get("implied_move") == "CUTS"]
            hiking  = [b for b in ["Fed", "ECB", "BOE"] if cb.get(b.lower().replace(" ",""), {}).get("implied_move") == "HIKES"]

            divergence_text = []
            fed_move = fed_b.get("implied_move")
            ecb_move = ecb_b.get("implied_move")
            boe_move = boe_b.get("implied_move")
            boj_move = boj_b.get("implied_move")

            if fed_move and ecb_move and fed_move != ecb_move:
                divergence_text.append(
                    f"Fed ({fed_move}) and ECB ({ecb_move}) are out of sync — "
                    f"this divergence typically creates EUR/USD trending conditions. "
                    f"Cutting central bank's currency tends to weaken relative to the other."
                )
            if boj_move == "HIKES" and fed_move == "CUTS":
                divergence_text.append(
                    "BOJ hiking while Fed cuts — classic JPY tailwind. Yen carry trades "
                    "unwind when the rate differential narrows. Watch USD/JPY for sharp moves."
                )
            if not divergence_text:
                divergence_text.append("No major policy divergence flagged at this time.")

            st.markdown(
                '<p style="font-size:12px;font-weight:700;color:#A0AEC0;'
                'letter-spacing:0.6px;margin-bottom:6px">POLICY DIVERGENCE & FX IMPLICATIONS</p>',
                unsafe_allow_html=True)
            for txt in divergence_text:
                st.info(txt)

            with st.expander("📚 How central bank divergence drives FX"):
                st.markdown("""
**Interest rate differentials are the single most powerful driver of exchange rates**
over medium-term (3-24 month) horizons.

**The mechanism:**
1. Fed hikes while ECB holds → US rates > EU rates
2. Capital flows from EUR-denominated assets into USD assets chasing yield
3. Demand for USD rises → EUR/USD falls

**The textbook view vs reality:**
- Textbook: Higher rates = stronger currency (always)
- Reality: The *change in expectation* matters more than the level.
  A Fed that's hiking but "almost done" is less bullish for USD than one just starting.

**The yen carry trade:**
BOJ's ultra-low rates let investors borrow cheap JPY, invest in higher-yielding assets.
When BOJ raises rates, this unwind happens violently — JPY spikes, risky assets sell off.
Watch USD/JPY as the global risk sentiment barometer when BOJ is active.

**Key rule:** When two major central banks diverge on policy direction,
that currency pair enters a trending (not ranging) environment — your alpha.
""")


st.markdown(
    '<p style="font-size:10px;color:#1A2540;text-align:center;margin-top:28px">'
    'FRED · Yahoo Finance · CoinGecko · mempool.space · Alternative.me · Trading Economics (optional) · '
    'CFTC (COT data) · For informational purposes only. Not investment advice.</p>',
    unsafe_allow_html=True)
