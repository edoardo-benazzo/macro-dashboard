"""
Macro Dashboard
---------------
Free, self-hosted macro + markets dashboard covering the US and Europe.
Data sources: FRED (macro series) + Yahoo Finance (market prices).

Run locally with:
    streamlit run app.py

Requires a free FRED API key, supplied either via:
  - .streamlit/secrets.toml  →  FRED_API_KEY = "your_key_here"
  - or the sidebar text input below (not saved anywhere)
"""

import datetime as dt

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

st.set_page_config(page_title="Macro Dashboard", layout="wide", page_icon="📊")

# ── Sidebar ──────────────────────────────────────────────────────────────────

st.sidebar.title("⚙️ Settings")

lookback_years = st.sidebar.slider(
    "Historical lookback (years)", min_value=1, max_value=10, value=DEFAULT_LOOKBACK_YEARS
)
yahoo_period = f"{lookback_years}y"
fred_start   = (dt.date.today() - dt.timedelta(days=365 * lookback_years)).isoformat()

try:
    fred_api_key = st.secrets["FRED_API_KEY"]
except Exception:
    fred_api_key = None
if not fred_api_key:
    fred_api_key = st.sidebar.text_input(
        "FRED API key", type="password",
        help="Get a free key at https://fred.stlouisfed.org/docs/api/api_key.html"
    )

show_zscore = st.sidebar.checkbox("Show Z-scores (historical context)", value=True)

st.sidebar.markdown("---")
st.sidebar.caption(
    "Data: FRED (macro) + Yahoo Finance (markets). "
    "Cached 6h (macro) / 15min (markets)."
)

# ── Page header ───────────────────────────────────────────────────────────────

st.title("📊 Macro Dashboard")
st.caption(f"Last loaded: {dt.datetime.now().strftime('%Y-%m-%d %H:%M')}")

# ── Load data upfront (cached; tabs just read from these dicts) ───────────────

fred_data   = None
market_data = None

if fred_api_key:
    with st.spinner("Loading macro data from FRED…"):
        fred_data = load_all_fred(FRED_SERIES, fred_api_key, fred_start)

with st.spinner("Loading market data from Yahoo Finance…"):
    market_data = load_all_markets(MARKET_TICKERS, period=yahoo_period)


# ── Shared helpers ────────────────────────────────────────────────────────────

def _s(key: str) -> pd.Series | None:
    """Quick accessor for a FRED series (returns None on miss/error)."""
    if fred_data is None:
        return None
    entry = fred_data.get(key, {})
    s = entry.get("series")
    return None if s is None or s.dropna().empty else s


def _latest(key: str) -> float | None:
    s = _s(key)
    return s.dropna().iloc[-1] if s is not None else None


def line_chart(series: pd.Series, label: str, units: str,
               hlines: list | None = None) -> go.Figure:
    """Standard line chart with optional horizontal reference lines."""
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=series.index, y=series.values,
                             mode="lines", name=label))
    if hlines:
        for hline in hlines:
            fig.add_hline(
                y=hline["y"],
                line_dash=hline.get("dash", "dash"),
                line_color=hline.get("color", "gray"),
                annotation_text=hline.get("label", ""),
            )
    fig.update_layout(
        height=280,
        margin=dict(l=10, r=10, t=30, b=10),
        title=label,
        yaxis_title=units,
        showlegend=False,
    )
    return fig


def multi_line_chart(series_dict: dict, title: str, units: str) -> go.Figure:
    """Multiple series on one chart — series_dict = {name: pd.Series}."""
    fig = go.Figure()
    for name, s in series_dict.items():
        if s is not None and not s.dropna().empty:
            fig.add_trace(go.Scatter(x=s.dropna().index, y=s.dropna().values,
                                     mode="lines", name=name))
    fig.update_layout(
        height=300, margin=dict(l=10, r=10, t=30, b=10),
        title=title, yaxis_title=units,
    )
    return fig


def tv_link(symbol_key: str, label: str = "📊 Open in TradingView"):
    url = tradingview_url(symbol_key)
    if url:
        st.markdown(f"[{label}]({url})")


def chart_col(col, series: pd.Series, title: str, units: str,
              tv_key: str = None, hlines: list = None):
    with col:
        st.plotly_chart(line_chart(series, title, units, hlines),
                        use_container_width=True)
        if tv_key:
            tv_link(tv_key)


def zscore_badge(key: str):
    """Inline z-score context pill for a FRED series."""
    if not show_zscore:
        return
    s = _s(key)
    if s is None:
        return
    z = compute_zscore(s)
    if z["zscore"] is not None:
        st.caption(f"Z-score vs history: **{z['zscore']:+.1f}σ** — {zscore_label(z['zscore'])}")


def metric_with_trend(col, label: str, value: str, delta_val: float | None = None,
                       delta_label: str | None = None, help: str = None):
    """st.metric wrapper that adds a formatted trend delta."""
    delta_str = None
    if delta_val is not None:
        sign = "+" if delta_val > 0 else ""
        delta_str = f"{sign}{delta_val:.2f} vs 3m ago" if delta_label is None else delta_label
    col.metric(label, value, delta=delta_str, help=help)


# ── Tabs ──────────────────────────────────────────────────────────────────────

tab_scorecard, tab_macro, tab_markets, tab_crossasset = st.tabs(
    ["📋 Scorecard", "🏛️ Macro", "📈 Markets", "🔀 Cross-Asset"]
)

# ═══════════════════════════════════════════════════════════════════════════════
# SCORECARD TAB — morning-brief view
# ═══════════════════════════════════════════════════════════════════════════════

with tab_scorecard:
    if fred_data is None:
        st.warning("Enter your FRED API key in the sidebar to load the scorecard.")
    else:
        # Gather all the signals we need
        cpi_l       = _latest("cpi_yoy")
        core_pce_l  = _latest("core_pce_yoy")
        pce_l       = _latest("pce_yoy")
        ffr_l       = _latest("fed_funds")
        y10_l       = _latest("10y_yield")
        y2_l        = _latest("2y_yield")
        y3m_l       = _latest("3m_yield")
        real_10y_l  = _latest("real_10y")
        unrate_l    = _latest("unemployment")
        cfnai_l     = _latest("cfnai")
        hy_oas_l    = _latest("hy_oas")
        claims_l    = _latest("initial_claims")
        sent_l      = _latest("consumer_sentiment")

        spread_2s10s = (y10_l - y2_l)   if y10_l and y2_l   else None
        spread_3m10s = (y10_l - y3m_l)  if y10_l and y3m_l  else None
        sahm         = compute_sahm_rule(_s("unemployment"))
        regime       = classify_macro_regime(cfnai_l, cpi_l)
        credit_st    = credit_spread_status(hy_oas_l)
        curve_2s10s  = yield_curve_status(spread_2s10s)
        curve_3m10s  = yield_curve_status(spread_3m10s)
        rec_prob     = compute_recession_probability(
            spread_2s10s, spread_3m10s, sahm["value"], hy_oas_l, cfnai_l
        )

        # EU signals
        eu_hicp_l     = _latest("eu_hicp")
        ecb_l         = _latest("ecb_deposit_rate")
        eu_10y_l      = _latest("eu_10y_yield")
        eu_unemp_l    = _latest("eu_unemployment")
        de_10y_l      = _latest("de_10y_yield")
        it_10y_l      = _latest("it_10y_yield")
        eu_regime     = classify_eu_macro_regime(eu_hicp_l, eu_unemp_l)

        btp_bund_bps  = (it_10y_l - de_10y_l) * 100 if it_10y_l and de_10y_l else None
        btp_st        = btp_bund_status(btp_bund_bps)

        # ── Regime banner row ──
        col_us, col_eu = st.columns(2)
        with col_us:
            st.markdown("### 🇺🇸 US Macro Regime")
            if regime["regime"]:
                st.markdown(f"## {regime['label']}")
                st.caption(regime["description"])
        with col_eu:
            st.markdown("### 🇪🇺 EU Macro Regime")
            if eu_regime["regime"]:
                st.markdown(f"## {eu_regime['label']}")
                st.caption(eu_regime["description"])

        st.markdown("---")

        # ── Recession probability ──
        if rec_prob["probability"] is not None:
            rp = rec_prob["probability"]
            st.markdown(f"### 🇺🇸 US Recession Probability Score: {rec_prob['label']} ({rp}%)")
            prog_col, _ = st.columns([2, 1])
            with prog_col:
                st.progress(rp / 100)
            st.caption(
                "Composite of: 3m10y yield spread (30%), Sahm Rule (25%), "
                "2s10s spread (20%), HY credit spreads (15%), CFNAI (10%). "
                "A rules-based signal, not a formal probability model."
            )

        st.markdown("---")

        # ── Key metrics grid ──
        st.markdown("### Key Signals at a Glance")

        col1, col2, col3, col4 = st.columns(4)

        # Column 1: Rates & yields
        with col1:
            st.markdown("**Rates & Yields**")
            if ffr_l is not None:
                st.metric("Fed Funds Rate", f"{ffr_l:.2f}%")
            if ecb_l is not None:
                st.metric("ECB Deposit Rate", f"{ecb_l:.2f}%")
            if y10_l is not None:
                st.metric("US 10Y Yield", f"{y10_l:.2f}%")
            if eu_10y_l is not None:
                st.metric("EU 10Y Yield", f"{eu_10y_l:.2f}%")
            if real_10y_l is not None:
                st.metric("US Real 10Y (TIPS)", f"{real_10y_l:.2f}%")

        # Column 2: Inflation
        with col2:
            st.markdown("**Inflation**")
            if cpi_l is not None:
                info = cpi_vs_target(cpi_l)
                st.metric("US CPI (YoY)", f"{cpi_l:.2f}%",
                          delta=f"{info['gap']:+.2f}pp vs 2%")
            if pce_l is not None:
                st.metric("US PCE (YoY)", f"{pce_l:.2f}%")
            if core_pce_l is not None:
                st.metric("US Core PCE (YoY)", f"{core_pce_l:.2f}%")
            if eu_hicp_l is not None:
                eu_info = cpi_vs_target(eu_hicp_l)
                st.metric("EU HICP (YoY)", f"{eu_hicp_l:.2f}%",
                          delta=f"{eu_info['gap']:+.2f}pp vs 2%")

        # Column 3: Labor & growth
        with col3:
            st.markdown("**Labor & Growth**")
            if unrate_l is not None:
                st.metric("US Unemployment", f"{unrate_l:.2f}%")
            if eu_unemp_l is not None:
                st.metric("EU Unemployment", f"{eu_unemp_l:.2f}%")
            if claims_l is not None:
                st.metric("Initial Claims", f"{claims_l:,.0f}")
            if sahm["value"] is not None:
                triggered = "🔴 Triggered" if sahm["triggered"] else "🟢 Not triggered"
                st.metric("Sahm Rule", f"{sahm['value']:.2f}pp", delta=triggered)
            if cfnai_l is not None:
                st.metric("CFNAI", f"{cfnai_l:.2f}",
                          delta="Above trend" if cfnai_l > 0 else "Below trend")

        # Column 4: Risk signals
        with col4:
            st.markdown("**Risk Signals**")
            if spread_2s10s is not None:
                st.metric("2s10s Spread", f"{spread_2s10s:.2f}%",
                          delta=curve_2s10s["label"])
            if spread_3m10s is not None:
                st.metric("3m10s Spread", f"{spread_3m10s:.2f}%",
                          delta=curve_3m10s["label"])
            if hy_oas_l is not None:
                st.metric("US HY OAS", f"{hy_oas_l:.2f}%",
                          delta=credit_st["label"])
            if btp_bund_bps is not None:
                st.metric("BTP-Bund Spread", f"{btp_bund_bps:.0f} bps",
                          delta=btp_st["label"])
            if sent_l is not None:
                st.metric("UMich Sentiment", f"{sent_l:.1f}")

        st.markdown("---")

        # ── Active alerts ──
        st.markdown("### 🚨 Active Alerts")
        alerts = []
        if spread_2s10s is not None and spread_2s10s < 0:
            alerts.append(("error",   f"🔴 US yield curve inverted (2s10s: {spread_2s10s:.2f}%)"))
        if spread_3m10s is not None and spread_3m10s < 0:
            alerts.append(("error",   f"🔴 US 3m10y spread inverted ({spread_3m10s:.2f}%) — Fed's preferred recession signal"))
        if sahm["triggered"]:
            alerts.append(("error",   "🔴 Sahm Rule has triggered — historical recession signal"))
        if rec_prob["probability"] and rec_prob["probability"] >= 40:
            alerts.append(("warning", f"🟠 Recession probability elevated: {rec_prob['probability']}%"))
        if btp_bund_bps and btp_bund_bps > 250:
            alerts.append(("error",   f"🔴 BTP-Bund spread at fragmentation risk level: {btp_bund_bps:.0f}bps"))
        elif btp_bund_bps and btp_bund_bps > 150:
            alerts.append(("warning", f"🟠 BTP-Bund spread elevated: {btp_bund_bps:.0f}bps"))
        if hy_oas_l and hy_oas_l > 5:
            alerts.append(("warning", f"🟠 US HY credit spreads elevated: {hy_oas_l:.2f}%"))
        if cpi_l and cpi_l > 3:
            alerts.append(("warning", f"🟡 US CPI well above Fed target: {cpi_l:.2f}%"))
        if eu_hicp_l and eu_hicp_l > 3:
            alerts.append(("warning", f"🟡 EU HICP well above ECB target: {eu_hicp_l:.2f}%"))

        if not alerts:
            st.success("No major macro alerts at this time.")
        else:
            for kind, msg in alerts:
                if kind == "error":
                    st.error(msg)
                elif kind == "warning":
                    st.warning(msg)
                else:
                    st.info(msg)


# ═══════════════════════════════════════════════════════════════════════════════
# MACRO TAB
# ═══════════════════════════════════════════════════════════════════════════════

with tab_macro:
    if fred_data is None:
        st.warning("Enter your free FRED API key in the sidebar to load macro data.")
    else:
        region_us, region_eu, region_uk = st.tabs(
            ["🇺🇸 United States", "🇪🇺 Euro Area", "🇬🇧 United Kingdom"]
        )

        # ====================================================================
        # UNITED STATES
        # ====================================================================
        with region_us:

            # ── Monetary Policy ──────────────────────────────────────────────
            st.subheader("Monetary Policy")
            ffr  = _s("fed_funds")
            ffr_l = _latest("fed_funds")
            core_pce = _s("core_pce_yoy")

            c1, c2, c3 = st.columns(3)
            if ffr_l is not None:
                c1.metric("Fed Funds Rate", f"{ffr_l:.2f}%")
            real_ffr_series = compute_real_fed_funds(ffr, core_pce)
            if not real_ffr_series.empty:
                real_ffr_now = real_ffr_series.dropna().iloc[-1]
                c2.metric("Real Fed Funds Rate", f"{real_ffr_now:.2f}%",
                          help="FFR minus Core PCE YoY — the true monetary tightness signal")
                zscore_val = compute_zscore(real_ffr_series)
                c3.metric("Real FFR Z-score", f"{zscore_val['zscore']:+.1f}σ" if zscore_val["zscore"] else "N/A",
                          delta=zscore_label(zscore_val["zscore"]),
                          help="How tight is real policy vs its own history?")

            col_a, col_b = st.columns(2)
            if ffr is not None:
                chart_col(col_a, ffr.dropna(), "Effective Fed Funds Rate", "%")
            if not real_ffr_series.empty:
                chart_col(col_b, real_ffr_series.dropna(), "Real Fed Funds Rate (FFR - Core PCE)", "%",
                          hlines=[{"y": 0, "dash": "dash", "color": "gray", "label": "Neutral"}])
            st.caption("Real FFR below zero = the Fed is effectively still accommodating. "
                       "The higher above zero, the more restrictive the stance.")

            st.markdown("---")

            # ── Yield Curve ──────────────────────────────────────────────────
            st.subheader("Yield Curve & Treasury Yields")

            y10 = _s("10y_yield"); y2  = _s("2y_yield")
            y3m = _s("3m_yield");  y30 = _s("30y_yield")
            y10_l = _latest("10y_yield"); y2_l  = _latest("2y_yield")
            y3m_l = _latest("3m_yield");  y30_l = _latest("30y_yield")

            spread_2s10s = (y10_l - y2_l)  if y10_l and y2_l  else None
            spread_3m10s = (y10_l - y3m_l) if y10_l and y3m_l else None

            c1, c2, c3, c4 = st.columns(4)
            if y3m_l:  c1.metric("3-Month", f"{y3m_l:.2f}%")
            if y2_l:   c2.metric("2-Year",  f"{y2_l:.2f}%")
            if y10_l:  c3.metric("10-Year", f"{y10_l:.2f}%")
            if y30_l:  c4.metric("30-Year", f"{y30_l:.2f}%")

            c1, c2 = st.columns(2)
            if spread_2s10s is not None:
                curve_2 = yield_curve_status(spread_2s10s)
                c1.metric("2s10s Spread", f"{spread_2s10s:.2f}%", delta=curve_2["label"])
            if spread_3m10s is not None:
                curve_3 = yield_curve_status(spread_3m10s)
                c2.metric("3m10y Spread", f"{spread_3m10s:.2f}%", delta=curve_3["label"],
                          help="The Fed's preferred recession indicator — empirically stronger than 2s10s")

            for sp, label, key2, key10 in [
                (spread_2s10s, "2s10s Spread (10Y minus 2Y)", y2,  y10),
                (spread_3m10s, "3m10y Spread (10Y minus 3M)", y3m, y10),
            ]:
                if key2 is not None and key10 is not None:
                    spread_s = (key10 - key2).dropna()
                    if not spread_s.empty:
                        fig = line_chart(spread_s, label, "%",
                                         hlines=[{"y": 0, "color": "red", "label": "Inversion line"}])
                        st.plotly_chart(fig, use_container_width=True)

            if spread_2s10s is not None and spread_2s10s < 0:
                st.error("🔴 **Yield curve inverted.** This has historically preceded US recessions, "
                         "though with long and variable lags.", icon="⚠️")

            # Multi-line yield chart
            if any(s is not None for s in [y3m, y2, y10, y30]):
                fig_yc = multi_line_chart(
                    {"3M": y3m, "2Y": y2, "10Y": y10, "30Y": y30},
                    "US Treasury Yield Curve — All Tenors", "%"
                )
                st.plotly_chart(fig_yc, use_container_width=True)

            col_a, col_b = st.columns(2)
            if y2 is not None:  chart_col(col_a, y2.dropna(),  "2-Year Treasury Yield",  "%", "2y_yield")
            if y10 is not None: chart_col(col_b, y10.dropna(), "10-Year Treasury Yield", "%", "10y_yield")

            st.markdown("---")

            # ── Real Yields & Breakeven ───────────────────────────────────────
            st.subheader("Real Yields & Inflation Expectations")
            st.caption("Real yields (TIPS) strip out inflation expectations and drive valuations "
                       "for risk assets — positive real yields create real competition for equities.")
            real_10y = _s("real_10y"); breakeven = _s("breakeven_10y")
            r10y_l   = _latest("real_10y"); be_l = _latest("breakeven_10y")

            c1, c2 = st.columns(2)
            if r10y_l is not None:
                c1.metric("10Y Real Yield (TIPS)", f"{r10y_l:.2f}%")
                zscore_badge("real_10y")
            if be_l is not None:
                c2.metric("10Y Breakeven Inflation", f"{be_l:.2f}%")

            col_a, col_b = st.columns(2)
            if real_10y is not None:
                chart_col(col_a, real_10y.dropna(), "10Y TIPS Real Yield", "%",
                          hlines=[{"y": 0, "color": "gray", "label": "Zero (neutral)"}])
            if breakeven is not None:
                chart_col(col_b, breakeven.dropna(), "10Y Breakeven Inflation Rate", "%",
                          hlines=[{"y": 2.0, "color": "orange", "dash": "dot", "label": "2% target"}])

            st.markdown("---")

            # ── Inflation ─────────────────────────────────────────────────────
            st.subheader("Inflation — CPI & PCE")
            st.caption("The Fed officially targets **core PCE** at 2%. CPI and core CPI are "
                       "widely-watched but are not the Fed's primary policy benchmark.")

            cpi = _s("cpi_yoy"); core_cpi = _s("core_cpi_yoy")
            pce = _s("pce_yoy"); core_pce  = _s("core_pce_yoy")
            ppi = _s("ppi_yoy")
            cpi_l      = _latest("cpi_yoy")
            core_cpi_l = _latest("core_cpi_yoy")
            pce_l      = _latest("pce_yoy")
            core_pce_l = _latest("core_pce_yoy")
            ppi_l      = _latest("ppi_yoy")

            c1, c2, c3, c4, c5 = st.columns(5)
            for col, val, lbl in [
                (c1, cpi_l,      "CPI (YoY)"),
                (c2, core_cpi_l, "Core CPI (YoY)"),
                (c3, pce_l,      "PCE (YoY)"),
                (c4, core_pce_l, "Core PCE (YoY)"),
                (c5, ppi_l,      "PPI (YoY)"),
            ]:
                if val is not None:
                    info = cpi_vs_target(val)
                    col.metric(lbl, f"{val:.2f}%",
                               delta=f"{info['gap']:+.2f}pp vs 2%")

            # Combined inflation chart
            fig_inf = multi_line_chart(
                {"CPI": cpi, "Core CPI": core_cpi,
                 "PCE": pce, "Core PCE": core_pce},
                "US Inflation — CPI & PCE (YoY %)", "%"
            )
            fig_inf.add_hline(y=2.0, line_dash="dash", line_color="orange",
                              annotation_text="2% target")
            st.plotly_chart(fig_inf, use_container_width=True)

            col_a, col_b = st.columns(2)
            if pce is not None:
                with col_a:
                    fig_pce = line_chart(pce.dropna(), "PCE Inflation (YoY %)", "%",
                                         hlines=[{"y": 2.0, "color": "orange", "label": "2% target"}])
                    st.plotly_chart(fig_pce, use_container_width=True)
                    st.caption("Core PCE is the Fed's primary inflation target.")
            if ppi is not None:
                with col_b:
                    st.plotly_chart(line_chart(ppi.dropna(), "PPI All Commodities (YoY %)", "%"),
                                    use_container_width=True)
                    st.caption("PPI leads CPI by ~3-6 months — rising PPI is an early warning for consumer inflation.")

            zscore_badge("core_pce_yoy")

            st.markdown("---")

            # ── Labor Market ─────────────────────────────────────────────────
            st.subheader("Labor Market")
            unemployment = _s("unemployment"); nfp = _s("nfp")
            claims       = _s("initial_claims")
            sahm = compute_sahm_rule(unemployment)

            c1, c2, c3, c4 = st.columns(4)
            if _latest("unemployment") is not None:
                trend = series_trend(unemployment, 3)
                c1.metric("Unemployment Rate", f"{_latest('unemployment'):.2f}%",
                          delta=f"{trend:+.2f}pp vs 3m ago" if trend else None)
            if nfp is not None and not nfp.dropna().empty:
                latest_nfp = nfp.dropna()
                mom = latest_nfp.diff().iloc[-1]
                c2.metric("Nonfarm Payrolls (k)", f"{latest_nfp.iloc[-1]:,.0f}", f"{mom:+,.0f} MoM")
            if claims is not None and not claims.dropna().empty:
                trend_c = series_trend(claims, 4)
                c3.metric("Initial Claims", f"{claims.dropna().iloc[-1]:,.0f}",
                          delta=f"{trend_c:+,.0f} vs 4wk ago" if trend_c else None)
                zscore_val = compute_zscore(claims)
                c4.metric("Claims Z-score", f"{zscore_val['zscore']:+.1f}σ" if zscore_val["zscore"] else "N/A",
                          delta=zscore_label(zscore_val["zscore"]))

            if sahm["value"] is not None:
                c1, c2 = st.columns(2)
                sahm_label = "🔴 Triggered" if sahm["triggered"] else "🟢 Not triggered"
                c1.metric("Sahm Rule", f"{sahm['value']:.2f}pp", delta=sahm_label)

            if sahm["triggered"]:
                st.error("🔴 **Sahm Rule triggered** — 3-month avg unemployment ≥ 0.50pp above its "
                         "12-month low. Historically coincides with early-stage US recessions.", icon="🚨")

            col_a, col_b = st.columns(2)
            if unemployment is not None:
                chart_col(col_a, unemployment.dropna(), "Unemployment Rate", "%")
            if claims is not None:
                chart_col(col_b, claims.dropna(), "Initial Jobless Claims", "persons",
                          hlines=[{"y": 300000, "color": "orange", "label": "~300k elevated threshold"}])

            if nfp is not None:
                st.plotly_chart(line_chart(nfp.dropna(), "Nonfarm Payrolls (level, thousands)", "thousands"),
                                use_container_width=True)
            if sahm["series"] is not None:
                fig_sahm = line_chart(sahm["series"].dropna(), "Sahm Rule Indicator", "pp",
                                      hlines=[{"y": 0.50, "color": "red", "label": "Trigger (0.50pp)"}])
                st.plotly_chart(fig_sahm, use_container_width=True)

            st.markdown("---")

            # ── Leading Indicators ────────────────────────────────────────────
            st.subheader("Leading Indicators")
            st.caption("These tend to lead the economic cycle by a few months, "
                       "making them critical for anticipating turns.")
            retail  = _s("retail_sales_yoy"); housing = _s("housing_starts")
            sent    = _s("consumer_sentiment"); m2    = _s("m2_yoy")

            c1, c2, c3, c4 = st.columns(4)
            for col, key, lbl, fmt in [
                (c1, "retail_sales_yoy",   "Retail Sales (YoY %)",   "{:.2f}%"),
                (c2, "housing_starts",     "Housing Starts (k)",     "{:,.0f}"),
                (c3, "consumer_sentiment", "UMich Sentiment",        "{:.1f}"),
                (c4, "m2_yoy",             "M2 (YoY %)",             "{:.2f}%"),
            ]:
                v = _latest(key)
                if v is not None:
                    trend = series_trend(_s(key), 3)
                    col.metric(lbl, fmt.format(v),
                               delta=f"{trend:+.2f} vs 3m ago" if trend else None)

            col_a, col_b = st.columns(2)
            if retail is not None:
                chart_col(col_a, retail.dropna(), "Retail Sales YoY %", "%",
                          hlines=[{"y": 0, "color": "gray", "label": "Zero growth"}])
            if housing is not None:
                chart_col(col_b, housing.dropna(), "Housing Starts (thousands)", "thousands")

            col_a, col_b = st.columns(2)
            if sent is not None:
                chart_col(col_a, sent.dropna(), "UMich Consumer Sentiment", "index")
            if m2 is not None:
                chart_col(col_b, m2.dropna(), "M2 Money Supply (YoY %)", "%",
                          hlines=[{"y": 0, "color": "red", "label": "Contraction"}])

            st.markdown("---")

            # ── Growth Activity ───────────────────────────────────────────────
            st.subheader("Growth Activity (CFNAI & Industrial Production)")
            cfnai = _s("cfnai"); indpro = _s("industrial_prod")
            cfnai_l = _latest("cfnai")

            c1, c2 = st.columns(2)
            if cfnai_l is not None:
                c1.metric("CFNAI (latest)", f"{cfnai_l:.2f}",
                          delta="Above trend" if cfnai_l > 0 else "Below trend")
            if indpro is not None:
                indpro_trend = series_trend(indpro, 3)
                c2.metric("Industrial Production (trend)", f"{_latest('industrial_prod'):.1f}",
                          delta=f"{indpro_trend:+.1f} vs 3m ago" if indpro_trend else None)

            if cfnai is not None:
                fig_cfnai = line_chart(cfnai.dropna(), "Chicago Fed National Activity Index", "index",
                                       hlines=[
                                           {"y": 0,    "color": "gray", "label": "Trend growth"},
                                           {"y": -0.7, "color": "red",  "dash": "dot", "label": "Recession risk zone"},
                                       ])
                st.plotly_chart(fig_cfnai, use_container_width=True)
                st.caption("CFNAI: zero = trend growth; below −0.70 (3m MA) historically signals recession.")

            # ── Credit Spreads ────────────────────────────────────────────────
            st.markdown("---")
            st.subheader("Credit Spreads")
            st.caption("Credit spreads are the bond market's own real-time risk gauge — "
                       "they tend to widen before equities price in the same stress.")
            hy_oas = _s("hy_oas"); ig_oas = _s("ig_oas")
            hy_l = _latest("hy_oas"); ig_l = _latest("ig_oas")
            credit_st = credit_spread_status(hy_l)

            c1, c2 = st.columns(2)
            if hy_l is not None:
                c1.metric("US High Yield OAS", f"{hy_l:.2f}%", delta=credit_st["label"])
                zscore_badge("hy_oas")
            if ig_l is not None:
                c2.metric("US Investment Grade OAS", f"{ig_l:.2f}%")

            if credit_st["status"] in ("elevated", "crisis"):
                st.warning(f"{credit_st['label']} — HY spreads at historically risk-off levels.", icon="📉")

            col_a, col_b = st.columns(2)
            if hy_oas is not None:
                chart_col(col_a, hy_oas.dropna(), "US High Yield OAS", "%",
                          hlines=[{"y": 5, "color": "orange", "label": "Elevated (5%)"},
                                   {"y": 8, "color": "red",    "label": "Crisis (8%)"}])
            if ig_oas is not None:
                chart_col(col_b, ig_oas.dropna(), "US Investment Grade OAS", "%")

        # ====================================================================
        # EURO AREA
        # ====================================================================
        with region_eu:

            # ── ECB & Euro Area aggregates ────────────────────────────────────
            st.subheader("ECB Monetary Policy")
            ecb_rate = _s("ecb_deposit_rate"); ecb_l = _latest("ecb_deposit_rate")
            eu_10y   = _s("eu_10y_yield");     eu_10y_l = _latest("eu_10y_yield")

            c1, c2 = st.columns(2)
            if ecb_l is not None:
                c1.metric("ECB Deposit Facility Rate", f"{ecb_l:.2f}%")
            if eu_10y_l is not None:
                c2.metric("Euro Area 10Y Bond Yield", f"{eu_10y_l:.2f}%")

            col_a, col_b = st.columns(2)
            if ecb_rate is not None:
                chart_col(col_a, ecb_rate.dropna(), "ECB Deposit Facility Rate", "%")
            if eu_10y is not None:
                chart_col(col_b, eu_10y.dropna(), "Euro Area 10Y Gov't Bond Yield", "%",
                          tv_key="eu_10y_yield")

            st.markdown("---")

            # ── Country Sovereign Yields & BTP-Bund Spread ────────────────────
            st.subheader("Sovereign Yields & BTP-Bund Spread")
            st.caption(
                "**BTP-Bund spread** (Italy minus Germany 10Y, in bps) is the most-watched "
                "indicator of Euro Area fragmentation risk. When Italy pays significantly more "
                "than Germany to borrow, markets are questioning euro cohesion — it was the key "
                "signal during the 2010-12 sovereign debt crisis."
            )

            de_10y = _s("de_10y_yield"); it_10y = _s("it_10y_yield")
            fr_10y = _s("fr_10y_yield"); es_10y = _s("es_10y_yield")
            de_l   = _latest("de_10y_yield"); it_l = _latest("it_10y_yield")
            fr_l   = _latest("fr_10y_yield"); es_l = _latest("es_10y_yield")

            c1, c2, c3, c4 = st.columns(4)
            for col, val, lbl, tv_key in [
                (c1, de_l, "Germany (Bund)", "de_10y_yield"),
                (c2, it_l, "Italy (BTP)",    "it_10y_yield"),
                (c3, fr_l, "France (OAT)",   "fr_10y_yield"),
                (c4, es_l, "Spain (Bonos)",  "es_10y_yield"),
            ]:
                if val is not None:
                    col.metric(f"{lbl} 10Y", f"{val:.2f}%")

            # BTP-Bund spread
            btp_bund = compute_btp_bund_spread(it_10y, de_10y)
            if not btp_bund.empty:
                btp_l   = btp_bund.dropna().iloc[-1]
                btp_st  = btp_bund_status(btp_l)
                trend_b = series_trend(btp_bund, 3)
                c1, c2, c3 = st.columns(3)
                c1.metric("BTP-Bund Spread", f"{btp_l:.0f} bps",
                          delta=f"{trend_b:+.0f}bps vs 3m ago" if trend_b else None)
                c2.metric("Status", btp_st["label"])
                if btp_l > 150:
                    c3.metric("⚠️ Watch", "Elevated fragmentation risk")

                if btp_st["status"] in ("elevated", "stress"):
                    st.warning(f"{btp_st['label']} — BTP-Bund at {btp_l:.0f}bps. "
                               "Above 200-250bps has historically triggered ECB intervention.",
                               icon="⚠️")

                btp_fig = line_chart(btp_bund.dropna(), "BTP-Bund Spread (Italy minus Germany 10Y)", "bps",
                                     hlines=[
                                         {"y": 150, "color": "orange", "label": "Elevated (150bps)"},
                                         {"y": 250, "color": "red",    "label": "Crisis risk (250bps)"},
                                     ])
                st.plotly_chart(btp_fig, use_container_width=True)

            # Country yield fan chart
            country_yields = {"Germany": de_10y, "Italy": it_10y,
                              "France": fr_10y, "Spain": es_10y}
            if any(s is not None for s in country_yields.values()):
                fig_cy = multi_line_chart(country_yields, "Euro Area Country 10Y Sovereign Yields", "%")
                st.plotly_chart(fig_cy, use_container_width=True)

            col_a, col_b = st.columns(2)
            if de_10y is not None:
                chart_col(col_a, de_10y.dropna(), "Germany 10Y Bund Yield", "%", "de_10y_yield")
            if it_10y is not None:
                chart_col(col_b, it_10y.dropna(), "Italy 10Y BTP Yield", "%", "it_10y_yield")

            st.markdown("---")

            # ── Euro Area Inflation ───────────────────────────────────────────
            st.subheader("Inflation (HICP)")
            st.caption("HICP is Eurostat's harmonised measure — the ECB targets it at 2%.")
            eu_hicp = _s("eu_hicp"); eu_hicp_l = _latest("eu_hicp")
            eu_cpi_info = cpi_vs_target(eu_hicp_l)

            c1, c2 = st.columns(2)
            if eu_hicp_l is not None:
                c1.metric("Euro Area HICP (YoY)", f"{eu_hicp_l:.2f}%",
                          delta=f"{eu_cpi_info['gap']:+.2f}pp vs 2% target")
                zscore_badge("eu_hicp")

            if eu_cpi_info["status"] in ("above target", "well above target"):
                st.warning(f"🟡 EU HICP **{eu_cpi_info['status']}** "
                           f"({eu_cpi_info['gap']:+.2f}pp vs ECB 2% goal).", icon="📈")
            elif eu_cpi_info["status"] == "below target":
                st.info(f"🔵 EU HICP below target "
                        f"({eu_cpi_info['gap']:+.2f}pp vs ECB 2% goal).", icon="📉")

            if eu_hicp is not None:
                fig_hicp = line_chart(eu_hicp.dropna(), "Euro Area HICP YoY %", "%",
                                      hlines=[{"y": 2.0, "color": "orange", "label": "2% ECB target"}])
                st.plotly_chart(fig_hicp, use_container_width=True)

            st.markdown("---")

            # ── Euro Area Labor Market ────────────────────────────────────────
            st.subheader("Labor Market")
            eu_unemp = _s("eu_unemployment"); eu_unemp_l = _latest("eu_unemployment")
            eur_usd  = _s("eur_usd");         eur_usd_l  = _latest("eur_usd")

            c1, c2 = st.columns(2)
            if eu_unemp_l is not None:
                trend_u = series_trend(eu_unemp, 3)
                c1.metric("Euro Area Unemployment", f"{eu_unemp_l:.2f}%",
                          delta=f"{trend_u:+.2f}pp vs 3m ago" if trend_u else None)
            if eur_usd_l is not None:
                c2.metric("EUR/USD", f"{eur_usd_l:.4f}")

            col_a, col_b = st.columns(2)
            if eu_unemp is not None:
                chart_col(col_a, eu_unemp.dropna(), "Euro Area Unemployment Rate", "%")
            if eur_usd is not None:
                chart_col(col_b, eur_usd.dropna(), "EUR/USD Exchange Rate", "USD per EUR",
                          tv_key="eur_usd")

            # EU Macro regime
            eu_regime = classify_eu_macro_regime(eu_hicp_l, eu_unemp_l)
            if eu_regime["regime"]:
                st.markdown("---")
                st.markdown(f"**EU Macro Regime: {eu_regime['label']}**")
                st.caption(eu_regime["description"])

        # ====================================================================
        # UNITED KINGDOM
        # ====================================================================
        with region_uk:
            st.subheader("Bank of England & UK Rates")
            boe_rate = _s("boe_rate"); boe_l = _latest("boe_rate")
            uk_10y   = _s("uk_10y_yield"); uk_10y_l = _latest("uk_10y_yield")

            c1, c2 = st.columns(2)
            if boe_l is not None:
                c1.metric("BoE Base Rate", f"{boe_l:.2f}%")
            if uk_10y_l is not None:
                c2.metric("UK 10Y Gilt Yield", f"{uk_10y_l:.2f}%")

            col_a, col_b = st.columns(2)
            if boe_rate is not None:
                chart_col(col_a, boe_rate.dropna(), "Bank of England Base Rate", "%")
            if uk_10y is not None:
                chart_col(col_b, uk_10y.dropna(), "UK 10-Year Gilt Yield", "%", "uk_10y_yield")

            st.markdown("---")

            st.subheader("UK Inflation (CPI)")
            uk_cpi = _s("uk_cpi_yoy"); uk_cpi_l = _latest("uk_cpi_yoy")

            if uk_cpi_l is not None:
                uk_cpi_info = cpi_vs_target(uk_cpi_l)
                c1, _ = st.columns(2)
                c1.metric("UK CPI (YoY)", f"{uk_cpi_l:.2f}%",
                          delta=f"{uk_cpi_info['gap']:+.2f}pp vs 2% target")
            if uk_cpi is not None:
                fig_ukcpi = line_chart(uk_cpi.dropna(), "UK CPI (YoY %)", "%",
                                       hlines=[{"y": 2.0, "color": "orange", "label": "2% BoE target"}])
                st.plotly_chart(fig_ukcpi, use_container_width=True)

            st.markdown("---")

            st.subheader("UK Labor Market")
            uk_unemp = _s("uk_unemployment"); uk_unemp_l = _latest("uk_unemployment")
            if uk_unemp_l is not None:
                trend_u = series_trend(uk_unemp, 3)
                c1, _ = st.columns(2)
                c1.metric("UK Unemployment Rate", f"{uk_unemp_l:.2f}%",
                          delta=f"{trend_u:+.2f}pp vs 3m ago" if trend_u else None)
            if uk_unemp is not None:
                col_a, _ = st.columns(2)
                chart_col(col_a, uk_unemp.dropna(), "UK Unemployment Rate", "%")

            st.markdown("---")

            # UK vs EU vs US comparison
            st.subheader("Yield Comparison — US / EU / UK")
            if any(s is not None for s in [_s("10y_yield"), _s("eu_10y_yield"), uk_10y]):
                fig_cmp = multi_line_chart(
                    {"US 10Y": _s("10y_yield"),
                     "DE 10Y (Bund)": _s("de_10y_yield"),
                     "UK 10Y (Gilt)": uk_10y},
                    "10-Year Government Yields — US vs Germany vs UK", "%"
                )
                st.plotly_chart(fig_cmp, use_container_width=True)
                st.caption("Divergences in yield levels signal Fed/ECB/BoE policy divergence "
                           "and drive major FX and cross-border capital flows.")


# ═══════════════════════════════════════════════════════════════════════════════
# MARKETS TAB
# ═══════════════════════════════════════════════════════════════════════════════

with tab_markets:

    benchmark_df      = market_data.get("^GSPC", {}).get("df")
    benchmark_returns = benchmark_df["Close"].pct_change() if benchmark_df is not None else None

    eu_bench_df      = market_data.get("^STOXX50E", {}).get("df")
    eu_bench_returns = eu_bench_df["Close"].pct_change() if eu_bench_df is not None else None

    def snap_grid(tickers: list, ncols: int = 3):
        cols = st.columns(ncols)
        for i, ticker in enumerate(tickers):
            meta = market_data.get(ticker)
            if not meta:
                continue
            snap = latest_snapshot(meta["df"])
            col  = cols[i % ncols]
            if snap:
                last, _, pct, _ = snap
                col.metric(f"{meta['label']}", f"{last:,.2f}", f"{pct:+.2f}%",
                           help=ticker)
            else:
                col.metric(meta["label"], "N/A")

    def chart_grid(tickers: list, ncols: int = 2):
        cols = st.columns(ncols)
        i = 0
        for ticker in tickers:
            meta = market_data.get(ticker)
            if not meta or meta["df"] is None or meta["df"].empty:
                continue
            chart_col(cols[i % ncols], meta["df"]["Close"],
                      f"{meta['label']} ({ticker})", "", ticker)
            i += 1

    def beta_grid(tickers: list, bench_returns: pd.Series, ncols: int = 3):
        if bench_returns is None:
            st.warning("Benchmark data unavailable.")
            return
        cols = st.columns(ncols)
        i = 0
        for ticker in tickers:
            meta = market_data.get(ticker)
            if not meta or meta["df"] is None or meta["df"].empty:
                continue
            beta = compute_beta(meta["df"]["Close"].pct_change(), bench_returns)
            cols[i % ncols].metric(f"{meta['label']}", f"{beta:.2f}" if pd.notna(beta) else "N/A")
            i += 1

    mkt_us, mkt_fi, mkt_comm, mkt_eu, mkt_sector = st.tabs(
        ["🇺🇸 US Equity", "💵 Fixed Income", "🪙 Commodities & FX", "🇪🇺 EU Markets", "📊 Sectors"]
    )

    # ── US Equity ─────────────────────────────────────────────────────────────
    with mkt_us:
        eq_tickers = ["^GSPC", "^IXIC", "^DJI", "IWM", "^VIX"]
        st.subheader("US Equity Snapshot")
        snap_grid(eq_tickers)
        st.markdown("---")
        st.subheader("Historical Charts")
        chart_grid(eq_tickers)
        st.markdown("---")
        st.subheader("Beta vs S&P 500")
        st.caption("Beta measures sensitivity to S&P 500 moves over the selected lookback window.")
        beta_grid(["^IXIC", "^DJI", "IWM", "^VIX"], benchmark_returns)

    # ── Fixed Income ──────────────────────────────────────────────────────────
    with mkt_fi:
        fi_tickers = ["TLT", "SHY", "TIP", "HYG", "LQD"]
        st.subheader("US Fixed Income ETFs")
        snap_grid(fi_tickers)
        st.markdown("---")
        st.subheader("Historical Charts")
        chart_grid(fi_tickers)
        st.markdown("---")
        st.subheader("Beta vs S&P 500 (diversification check)")
        st.caption("Negative beta = bonds moving opposite to stocks = genuine hedge. "
                   "When this turns positive it signals a stock-bond correlation regime shift.")
        beta_grid(fi_tickers, benchmark_returns)

        st.markdown("---")
        # HYG/LQD credit stress proxy
        st.subheader("HYG/LQD Credit Stress Proxy")
        st.caption("HYG underperforming LQD = credit stress widening in real time.")
        hyg_df = market_data.get("HYG", {}).get("df")
        lqd_df = market_data.get("LQD", {}).get("df")
        if hyg_df is not None and lqd_df is not None and not hyg_df.empty and not lqd_df.empty:
            hyg_norm = hyg_df["Close"] / hyg_df["Close"].iloc[0] * 100
            lqd_norm = lqd_df["Close"] / lqd_df["Close"].iloc[0] * 100
            ratio    = hyg_norm / lqd_norm
            fig_r = go.Figure()
            fig_r.add_trace(go.Scatter(x=ratio.index, y=ratio.values, mode="lines",
                                       name="HYG/LQD ratio"))
            fig_r.update_layout(height=280, margin=dict(l=10, r=10, t=30, b=10),
                                 title="HYG / LQD Relative Performance (rebased to 100)",
                                 yaxis_title="Ratio")
            st.plotly_chart(fig_r, use_container_width=True)
            st.caption("Falling = HY underperforming IG = credit risk rising. "
                       "Precedes equity weakness more often than not.")

    # ── Commodities & FX ──────────────────────────────────────────────────────
    with mkt_comm:
        st.subheader("Commodities")
        comm_tickers = ["GC=F", "SI=F", "CL=F", "NG=F", "HG=F"]
        snap_grid(comm_tickers)
        st.caption("Copper (HG) is an especially useful leading growth indicator — "
                   "its wide industrial use makes it a real-time demand gauge for the global economy.")
        chart_grid(comm_tickers)

        st.markdown("---")
        st.subheader("US Dollar & FX")
        fx_tickers = ["DX-Y.NYB", "EURUSD=X", "GBPUSD=X", "JPY=X", "CHF=X"]
        snap_grid(fx_tickers)
        chart_grid(fx_tickers)

    # ── EU Markets ────────────────────────────────────────────────────────────
    with mkt_eu:
        eu_eq = ["^STOXX50E", "^GDAXI", "^FTSE", "^FCHI", "FTSEMIB.MI", "^IBEX"]
        st.subheader("European Equity Indices")
        snap_grid(eu_eq, ncols=3)
        st.markdown("---")
        chart_grid(eu_eq)
        st.markdown("---")
        st.subheader("Beta vs Euro Stoxx 50")
        beta_grid([t for t in eu_eq if t != "^STOXX50E"], eu_bench_returns)

    # ── Sectors ───────────────────────────────────────────────────────────────
    with mkt_sector:
        sector_tickers = ["XLF", "XLE", "XLK", "XLV", "XLU", "XLI"]
        st.subheader("US Sector ETFs (vs S&P 500)")
        st.caption("Sector rotation is one of the clearest real-time signals of where the market "
                   "thinks we are in the cycle: early cycle favors Financials/Industrials; "
                   "late cycle favors Energy/Utilities/Health Care.")
        snap_grid(sector_tickers)

        st.markdown("---")

        # Relative performance chart — all sectors rebased to 100
        rebase_data = {}
        for ticker in sector_tickers:
            df = market_data.get(ticker, {}).get("df")
            lbl = market_data.get(ticker, {}).get("label", ticker)
            if df is not None and not df.empty:
                rebase_data[lbl] = df["Close"] / df["Close"].iloc[0] * 100
        if rebase_data:
            fig_sect = multi_line_chart(rebase_data, "Sector ETF Relative Performance (rebased to 100)", "index")
            st.plotly_chart(fig_sect, use_container_width=True)
            st.caption("Lines above 100 mean the sector has gained from the start of your selected "
                       "lookback window. Divergence between sectors shows rotation.")

        st.markdown("---")
        st.subheader("Beta vs S&P 500")
        beta_grid(sector_tickers, benchmark_returns)

        st.markdown("---")
        st.subheader("Individual Charts")
        chart_grid(sector_tickers)


# ═══════════════════════════════════════════════════════════════════════════════
# CROSS-ASSET TAB
# ═══════════════════════════════════════════════════════════════════════════════

with tab_crossasset:

    st.subheader("Cross-Asset Correlation Matrix")
    st.caption(
        f"Rolling {CORRELATION_WINDOW_DAYS}-trading-day correlation of daily returns. "
        "A current-regime read — correlations shift meaningfully across macro regimes, "
        "and a recent-window matrix catches those shifts faster than a multi-year average."
    )

    corr_matrix = compute_correlation_matrix(market_data, CORRELATION_TICKERS, CORRELATION_WINDOW_DAYS)

    if not corr_matrix.empty:
        labels = [MARKET_TICKERS.get(t, t) for t in corr_matrix.columns]
        heatmap_fig = go.Figure(data=go.Heatmap(
            z=corr_matrix.values,
            x=labels, y=labels,
            colorscale="RdBu", zmid=0, zmin=-1, zmax=1,
            text=corr_matrix.round(2).values,
            texttemplate="%{text}", textfont={"size": 10},
            colorbar=dict(title="Correlation"),
        ))
        heatmap_fig.update_layout(
            height=540, margin=dict(l=10, r=10, t=30, b=10),
            title=f"{CORRELATION_WINDOW_DAYS}-Day Rolling Return Correlation",
        )
        st.plotly_chart(heatmap_fig, use_container_width=True)

        st.markdown("""
**Reading this matrix:**
- **+1 (dark red):** assets moving together — weak diversification
- **−1 (dark blue):** assets moving oppositely — genuine hedge (e.g. stocks vs. bonds in a "normal" regime)
- **~0 (white):** little relationship — true diversification benefit

**Key regime tell:** when **S&P 500 vs TLT flips from negative to positive correlation**, it usually signals
an inflation-driven regime where bonds stop hedging equity drawdowns. When **copper and equities diverge**,
it's often an early warning that growth expectations are cracking.
        """)
    else:
        st.warning("Not enough overlapping data for the correlation matrix.")

    st.markdown("---")

    # ── Recession Probability Detail ──────────────────────────────────────────
    st.subheader("🇺🇸 US Recession Probability Scorecard")
    if fred_data is not None:
        y10_l = _latest("10y_yield"); y2_l = _latest("2y_yield")
        y3m_l = _latest("3m_yield")
        sp2s10s = (y10_l - y2_l)  if y10_l and y2_l  else None
        sp3m10s = (y10_l - y3m_l) if y10_l and y3m_l else None
        sahm    = compute_sahm_rule(_s("unemployment"))
        hy_l    = _latest("hy_oas"); cfnai_l = _latest("cfnai")
        rec     = compute_recession_probability(sp2s10s, sp3m10s, sahm["value"], hy_l, cfnai_l)

        if rec["probability"] is not None:
            c1, c2 = st.columns([1, 2])
            c1.metric("Composite Score", f"{rec['probability']}%", delta=rec["label"])
            with c2:
                st.progress(rec["probability"] / 100)

            col1, col2, col3 = st.columns(3)
            data_points = [
                ("3m10y Spread", f"{sp3m10s:.2f}%" if sp3m10s else "N/A",
                 yield_curve_status(sp3m10s)["label"] if sp3m10s else None),
                ("2s10s Spread", f"{sp2s10s:.2f}%" if sp2s10s else "N/A",
                 yield_curve_status(sp2s10s)["label"] if sp2s10s else None),
                ("Sahm Rule", f"{sahm['value']:.2f}pp" if sahm["value"] else "N/A",
                 "🔴 Triggered" if sahm["triggered"] else "🟢 Clear"),
                ("HY OAS", f"{hy_l:.2f}%" if hy_l else "N/A",
                 credit_spread_status(hy_l)["label"] if hy_l else None),
                ("CFNAI", f"{cfnai_l:.2f}" if cfnai_l else "N/A",
                 "Below trend" if (cfnai_l or 0) < 0 else "Above trend"),
            ]
            for i, (lbl, val, dlt) in enumerate(data_points):
                [col1, col2, col3][i % 3].metric(lbl, val, delta=dlt)

    st.markdown("---")

    # ── Global Yield Comparison ───────────────────────────────────────────────
    st.subheader("Global 10-Year Yields — US vs EU vs UK")
    if fred_data is not None:
        fig_glob = multi_line_chart(
            {"US 10Y":       _s("10y_yield"),
             "Germany Bund": _s("de_10y_yield"),
             "Italy BTP":    _s("it_10y_yield"),
             "France OAT":   _s("fr_10y_yield"),
             "UK Gilt":      _s("uk_10y_yield")},
            "10-Year Government Yields — Global", "%"
        )
        st.plotly_chart(fig_glob, use_container_width=True)
        st.caption("Policy divergence between the Fed, ECB, and BoE drives yield differentials "
                   "that are the fundamental backdrop for USD/EUR and GBP/USD exchange rates.")

    st.markdown("---")

    # ── Inflation Comparison ──────────────────────────────────────────────────
    st.subheader("Inflation Comparison — US vs EU vs UK")
    if fred_data is not None:
        fig_inf_cmp = multi_line_chart(
            {"US CPI":    _s("cpi_yoy"),
             "US Core PCE": _s("core_pce_yoy"),
             "EU HICP":   _s("eu_hicp"),
             "UK CPI":    _s("uk_cpi_yoy")},
            "Inflation — US, EU, UK (YoY %)", "%"
        )
        fig_inf_cmp.add_hline(y=2.0, line_dash="dash", line_color="gray",
                              annotation_text="2% target")
        st.plotly_chart(fig_inf_cmp, use_container_width=True)


st.markdown("---")
st.caption(
    "Built with Streamlit · Data: FRED + Yahoo Finance · "
    "For informational purposes only, not investment advice."
)
