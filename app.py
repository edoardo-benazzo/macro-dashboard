"""
Macro Dashboard
---------------
Free, self-contained macro + markets dashboard covering the US and Europe.
Data sources: FRED (macro series) + Yahoo Finance (market prices).

Run locally with:
    streamlit run app.py

Requires a free FRED API key, supplied either via:
  - a local file `.streamlit/secrets.toml` with: FRED_API_KEY = "your_key_here"
  - or pasted into the sidebar text box when running (not saved anywhere)
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
    credit_spread_status, classify_macro_regime, compute_correlation_matrix,
)

st.set_page_config(page_title="Macro Dashboard", layout="wide", page_icon="📊")

# ----------------------------------------------------------------------------
# Sidebar — controls
# ----------------------------------------------------------------------------

st.sidebar.title("⚙️ Settings")

lookback_years = st.sidebar.slider(
    "Historical lookback (years)", min_value=1, max_value=10, value=DEFAULT_LOOKBACK_YEARS
)
yahoo_period = f"{lookback_years}y"
fred_start = (dt.date.today() - dt.timedelta(days=365 * lookback_years)).isoformat()

# FRED API key: prefer Streamlit secrets, fall back to manual entry
try:
    fred_api_key = st.secrets["FRED_API_KEY"]
except Exception:
    fred_api_key = None
if not fred_api_key:
    fred_api_key = st.sidebar.text_input(
        "FRED API key", type="password",
        help="Get a free key at https://fred.stlouisfed.org/docs/api/api_key.html"
    )

st.sidebar.markdown("---")
st.sidebar.caption(
    "Data: FRED (macro) + Yahoo Finance (markets). "
    "Cached 6h (macro) / 15min (markets) to keep things fast."
)

st.title("📊 Macro Dashboard")
st.caption(f"Last loaded: {dt.datetime.now().strftime('%Y-%m-%d %H:%M')}")

# Placeholders for regime banner + condition badges, filled in once data loads
regime_placeholder = st.empty()
badge_placeholder = st.empty()


# ----------------------------------------------------------------------------
# Shared helpers
# ----------------------------------------------------------------------------

def line_chart(series: pd.Series, label: str, units: str) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=series.index, y=series.values, mode="lines", name=label))
    fig.update_layout(
        height=280,
        margin=dict(l=10, r=10, t=30, b=10),
        title=label,
        yaxis_title=units,
        showlegend=False,
    )
    return fig


def tv_link(symbol_key: str, label: str = "📊 Open in TradingView"):
    """Render a small TradingView link if a mapping exists for this key."""
    url = tradingview_url(symbol_key)
    if url:
        st.markdown(f"[{label}]({url})")


def chart_with_tv_link(col, series: pd.Series, title: str, units: str, tv_key: str = None):
    """Render a chart in the given column, with an optional TradingView link below it."""
    with col:
        st.plotly_chart(line_chart(series, title, units), use_container_width=True)
        if tv_key:
            tv_link(tv_key)


# ----------------------------------------------------------------------------
# Tabs
# ----------------------------------------------------------------------------

tab_macro, tab_markets, tab_crossasset = st.tabs(["🏛️ Macro", "📈 Markets", "🔀 Cross-Asset"])

# ----------------------------------------------------------------------------
# MACRO TAB
# ----------------------------------------------------------------------------

with tab_macro:
    region_us, region_eu = st.tabs(["🇺🇸 United States", "🇪🇺 Europe"])

    if not fred_api_key:
        st.warning("Enter your free FRED API key in the sidebar to load macro data.")
    else:
        with st.spinner("Loading macro data from FRED..."):
            fred_data = load_all_fred(FRED_SERIES, fred_api_key, fred_start)

        # ====================================================================
        # UNITED STATES
        # ====================================================================
        with region_us:
            # --- Yield snapshot + 2s10s spread ---
            st.subheader("Treasury Yields")
            y10 = fred_data.get("10y_yield", {}).get("series")
            y2 = fred_data.get("2y_yield", {}).get("series")

            spread_now = None
            c1, c2, c3 = st.columns(3)
            if y10 is not None and not y10.empty:
                c1.metric("10-Year Yield", f"{y10.dropna().iloc[-1]:.2f}%")
            if y2 is not None and not y2.empty:
                c2.metric("2-Year Yield", f"{y2.dropna().iloc[-1]:.2f}%")
            if y10 is not None and y2 is not None and not y10.empty and not y2.empty:
                spread_now = (y10.dropna().iloc[-1] - y2.dropna().iloc[-1])
                curve = yield_curve_status(spread_now)
                c3.metric("2s10s Spread", f"{spread_now:.2f}%", delta=curve["label"])

            if spread_now is not None and spread_now < 0:
                st.error(
                    "🔴 **Yield curve is inverted** (10Y yield below 2Y yield). "
                    "This has historically preceded US recessions, though the lag between "
                    "inversion and recession has varied widely — anywhere from several months "
                    "to over a year — so treat this as a watch signal, not a timing tool.",
                    icon="⚠️"
                )

            col_a, col_b = st.columns(2)
            if y10 is not None and not y10.empty:
                chart_with_tv_link(col_a, y10.dropna(), "10-Year Treasury Yield", "%", "10y_yield")
            if y2 is not None and not y2.empty:
                chart_with_tv_link(col_b, y2.dropna(), "2-Year Treasury Yield", "%", "2y_yield")

            if y10 is not None and y2 is not None:
                spread_series = (y10 - y2).dropna()
                spread_fig = line_chart(spread_series, "2s10s Spread (10Y minus 2Y)", "%")
                spread_fig.add_hline(y=0, line_dash="dash", line_color="red", annotation_text="Inversion line")
                st.plotly_chart(spread_fig, use_container_width=True)
                st.caption("Negative values (below the dashed line) indicate an inverted yield curve, "
                           "historically watched as a recession signal.")

            st.markdown("---")

            # --- Inflation ---
            st.subheader("Inflation")
            cpi = fred_data.get("cpi_yoy", {}).get("series")
            core_cpi = fred_data.get("core_cpi_yoy", {}).get("series")

            cpi_latest = cpi.dropna().iloc[-1] if cpi is not None and not cpi.dropna().empty else None
            cpi_target_info = cpi_vs_target(cpi_latest)

            c1, c2 = st.columns(2)
            if cpi_latest is not None:
                c1.metric("CPI (YoY)", f"{cpi_latest:.2f}%",
                          delta=f"{cpi_target_info['gap']:+.2f}pp vs 2% target")
            if core_cpi is not None and not core_cpi.dropna().empty:
                c2.metric("Core CPI (YoY)", f"{core_cpi.dropna().iloc[-1]:.2f}%")

            if cpi_target_info["status"] in ("above target", "well above target"):
                st.warning(
                    f"🟡 CPI is **{cpi_target_info['status']}** "
                    f"({cpi_target_info['gap']:+.2f} percentage points vs. the Fed's 2% goal). "
                    "Persistently elevated inflation is a key input into Fed rate decisions.",
                    icon="📈"
                )
            elif cpi_target_info["status"] == "below target":
                st.info(
                    f"🔵 CPI is **below target** "
                    f"({cpi_target_info['gap']:+.2f} percentage points vs. the Fed's 2% goal).",
                    icon="📉"
                )

            col_a, col_b = st.columns(2)
            if cpi is not None and not cpi.dropna().empty:
                with col_a:
                    cpi_fig = line_chart(cpi.dropna(), "CPI YoY %", "%")
                    cpi_fig.add_hline(y=2.0, line_dash="dash", line_color="orange", annotation_text="2% target")
                    st.plotly_chart(cpi_fig, use_container_width=True)
            if core_cpi is not None and not core_cpi.dropna().empty:
                chart_with_tv_link(col_b, core_cpi.dropna(), "Core CPI YoY %", "%")

            st.markdown("---")

            # --- Labor market ---
            st.subheader("Labor Market")
            unemployment = fred_data.get("unemployment", {}).get("series")
            nfp = fred_data.get("nfp", {}).get("series")

            sahm = compute_sahm_rule(unemployment)

            c1, c2, c3 = st.columns(3)
            if unemployment is not None and not unemployment.dropna().empty:
                c1.metric("Unemployment Rate", f"{unemployment.dropna().iloc[-1]:.2f}%")
            if nfp is not None and not nfp.dropna().empty:
                latest_nfp = nfp.dropna()
                mom_change = latest_nfp.diff().iloc[-1]
                c2.metric("Nonfarm Payrolls (level, k)", f"{latest_nfp.iloc[-1]:,.0f}", f"{mom_change:+,.0f} MoM")
            if sahm["value"] is not None and pd.notna(sahm["value"]):
                sahm_label = "🔴 Triggered" if sahm["triggered"] else "🟢 Not triggered"
                c3.metric("Sahm Rule Indicator", f"{sahm['value']:.2f}pp", delta=sahm_label)

            if sahm["triggered"]:
                st.error(
                    "🔴 **Sahm Rule has triggered** — the 3-month average unemployment rate is "
                    "0.50+ percentage points above its low from the past 12 months. Historically, "
                    "every time this rule has triggered in the US has coincided with the early "
                    "stage of a recession (though it's a real-time indicator, not a guarantee).",
                    icon="🚨"
                )

            col_a, col_b = st.columns(2)
            if unemployment is not None and not unemployment.dropna().empty:
                chart_with_tv_link(col_a, unemployment.dropna(), "Unemployment Rate", "%")
            if nfp is not None and not nfp.dropna().empty:
                chart_with_tv_link(col_b, nfp.dropna(), "Nonfarm Payrolls (level, thousands)", "thousands")

            if sahm["series"] is not None and not sahm["series"].dropna().empty:
                sahm_fig = line_chart(sahm["series"].dropna(), "Sahm Rule Recession Indicator", "percentage points")
                sahm_fig.add_hline(y=0.50, line_dash="dash", line_color="red", annotation_text="Trigger threshold (0.50pp)")
                st.plotly_chart(sahm_fig, use_container_width=True)
                st.caption("Sahm Rule = (3-month avg. unemployment rate) minus (its lowest 3-month avg. "
                           "over the trailing 12 months). A reading at or above 0.50 has historically "
                           "signaled the early months of a US recession.")

            st.markdown("---")

            # --- Fed funds rate ---
            st.subheader("Fed Funds Rate")
            ffr = fred_data.get("fed_funds", {}).get("series")
            if ffr is not None and not ffr.dropna().empty:
                st.metric("Effective Fed Funds Rate", f"{ffr.dropna().iloc[-1]:.2f}%")
                st.plotly_chart(line_chart(ffr.dropna(), "Effective Fed Funds Rate", "%"), use_container_width=True)

            st.markdown("---")

            # --- Real yields & inflation expectations ---
            st.subheader("Real Yields & Inflation Expectations")
            st.caption("Real yields (TIPS) strip out inflation expectations and are what actually drives "
                       "valuations for risk assets — nominal yields alone can be misleading when inflation "
                       "expectations are shifting.")
            real_10y = fred_data.get("real_10y", {}).get("series")
            breakeven = fred_data.get("breakeven_10y", {}).get("series")

            c1, c2 = st.columns(2)
            if real_10y is not None and not real_10y.dropna().empty:
                c1.metric("10-Year Real Yield (TIPS)", f"{real_10y.dropna().iloc[-1]:.2f}%")
            if breakeven is not None and not breakeven.dropna().empty:
                c2.metric("10-Year Breakeven Inflation", f"{breakeven.dropna().iloc[-1]:.2f}%")

            col_a, col_b = st.columns(2)
            if real_10y is not None and not real_10y.dropna().empty:
                chart_with_tv_link(col_a, real_10y.dropna(), "10-Year Real (TIPS) Yield", "%")
            if breakeven is not None and not breakeven.dropna().empty:
                chart_with_tv_link(col_b, breakeven.dropna(), "10-Year Breakeven Inflation Rate", "%")

            st.markdown("---")

            # --- Credit spreads ---
            st.subheader("Credit Spreads")
            st.caption("Credit spreads are the bond market's own risk gauge — they tend to widen ahead of "
                       "or alongside equity selloffs, since credit investors are often quicker to price in "
                       "deteriorating fundamentals.")
            hy_oas = fred_data.get("hy_oas", {}).get("series")
            ig_oas = fred_data.get("ig_oas", {}).get("series")

            hy_latest = hy_oas.dropna().iloc[-1] if hy_oas is not None and not hy_oas.dropna().empty else None
            credit_status = credit_spread_status(hy_latest)

            c1, c2 = st.columns(2)
            if hy_latest is not None:
                c1.metric("High Yield OAS", f"{hy_latest:.2f}%", delta=credit_status["label"])
            if ig_oas is not None and not ig_oas.dropna().empty:
                c2.metric("Investment Grade OAS", f"{ig_oas.dropna().iloc[-1]:.2f}%")

            if credit_status["status"] in ("elevated", "crisis"):
                st.warning(
                    f"{credit_status['label']} — High Yield credit spreads are at levels historically "
                    "associated with rising default risk and risk-off conditions in equity markets.",
                    icon="📉"
                )

            col_a, col_b = st.columns(2)
            if hy_oas is not None and not hy_oas.dropna().empty:
                chart_with_tv_link(col_a, hy_oas.dropna(), "High Yield Credit Spread (OAS)", "%")
            if ig_oas is not None and not ig_oas.dropna().empty:
                chart_with_tv_link(col_b, ig_oas.dropna(), "Investment Grade Credit Spread (OAS)", "%")

            st.markdown("---")

            # --- Growth proxy (CFNAI) ---
            st.subheader("Growth Activity (Chicago Fed National Activity Index)")
            st.caption("CFNAI is a broad, free, real-time proxy for whether the US economy is growing "
                       "above or below its long-run trend rate — zero is trend growth, negative is "
                       "below-trend, positive is above-trend.")
            cfnai = fred_data.get("cfnai", {}).get("series")
            cfnai_latest = cfnai.dropna().iloc[-1] if cfnai is not None and not cfnai.dropna().empty else None

            if cfnai_latest is not None:
                st.metric("CFNAI (latest)", f"{cfnai_latest:.2f}",
                          delta="Above trend" if cfnai_latest > 0 else "Below trend")
            if cfnai is not None and not cfnai.dropna().empty:
                cfnai_fig = line_chart(cfnai.dropna(), "Chicago Fed National Activity Index", "index")
                cfnai_fig.add_hline(y=0, line_dash="dash", line_color="gray", annotation_text="Trend growth")
                cfnai_fig.add_hline(y=-0.7, line_dash="dot", line_color="red", annotation_text="Recession risk zone")
                st.plotly_chart(cfnai_fig, use_container_width=True)

            # --- Fill in the regime banner + condition badges now that we have all US data ---
            regime = classify_macro_regime(cfnai_latest, cpi_latest)
            if regime["regime"]:
                with regime_placeholder.container():
                    st.markdown(f"### US Macro Regime: {regime['label']}")
                    st.caption(regime["description"])

            badges = []
            if spread_now is not None:
                curve = yield_curve_status(spread_now)
                badges.append(curve["label"])
            if cpi_target_info["status"]:
                cpi_badge = {
                    "well above target": "🔴 Inflation Well Above Target",
                    "above target": "🟡 Inflation Above Target",
                    "at target": "🟢 Inflation At Target",
                    "below target": "🔵 Inflation Below Target",
                }.get(cpi_target_info["status"])
                if cpi_badge:
                    badges.append(cpi_badge)
            if sahm["triggered"] is not None:
                badges.append("🔴 Sahm Rule Triggered" if sahm["triggered"] else "🟢 Sahm Rule Not Triggered")
            if credit_status["label"]:
                badges.append(credit_status["label"])

            if badges:
                with badge_placeholder.container():
                    st.markdown(" &nbsp;|&nbsp; ".join(f"**{b}**" for b in badges))
                    st.caption("Quick-glance US macro regime, based on current data below.")

        # ====================================================================
        # EUROPE
        # ====================================================================
        with region_eu:
            st.subheader("ECB Policy Rate")
            st.caption("The Deposit Facility Rate is the rate the ECB currently uses to steer "
                       "monetary policy — the closest European equivalent to the Fed Funds Rate.")
            ecb_rate = fred_data.get("ecb_deposit_rate", {}).get("series")
            if ecb_rate is not None and not ecb_rate.dropna().empty:
                st.metric("ECB Deposit Facility Rate", f"{ecb_rate.dropna().iloc[-1]:.2f}%")
                st.plotly_chart(line_chart(ecb_rate.dropna(), "ECB Deposit Facility Rate", "%"), use_container_width=True)

            st.markdown("---")

            st.subheader("Euro Area 10-Year Government Bond Yield")
            st.caption("The Euro Area equivalent of the US 10-Year Treasury — the long-end "
                       "risk-free benchmark for European fixed income.")
            eu_10y = fred_data.get("eu_10y_yield", {}).get("series")
            if eu_10y is not None and not eu_10y.dropna().empty:
                chart_col, _ = st.columns([1, 1])
                with chart_col:
                    st.metric("Euro Area 10-Year Yield", f"{eu_10y.dropna().iloc[-1]:.2f}%")
                st.plotly_chart(line_chart(eu_10y.dropna(), "Euro Area 10-Year Government Bond Yield", "%"), use_container_width=True)
                tv_link("eu_10y_yield")

            st.markdown("---")

            st.subheader("Inflation (HICP)")
            st.caption("HICP is the Eurostat-harmonized inflation measure — Europe's equivalent "
                       "of US CPI, and the figure the ECB targets directly at 2%.")
            eu_hicp = fred_data.get("eu_hicp", {}).get("series")
            eu_hicp_latest = eu_hicp.dropna().iloc[-1] if eu_hicp is not None and not eu_hicp.dropna().empty else None
            eu_cpi_target_info = cpi_vs_target(eu_hicp_latest)

            if eu_hicp_latest is not None:
                st.metric("Euro Area HICP (YoY)", f"{eu_hicp_latest:.2f}%",
                          delta=f"{eu_cpi_target_info['gap']:+.2f}pp vs 2% target")

            if eu_cpi_target_info["status"] in ("above target", "well above target"):
                st.warning(
                    f"🟡 Euro Area HICP is **{eu_cpi_target_info['status']}** "
                    f"({eu_cpi_target_info['gap']:+.2f} percentage points vs. the ECB's 2% goal).",
                    icon="📈"
                )
            elif eu_cpi_target_info["status"] == "below target":
                st.info(
                    f"🔵 Euro Area HICP is **below target** "
                    f"({eu_cpi_target_info['gap']:+.2f} percentage points vs. the ECB's 2% goal).",
                    icon="📉"
                )

            if eu_hicp is not None and not eu_hicp.dropna().empty:
                eu_hicp_fig = line_chart(eu_hicp.dropna(), "Euro Area HICP YoY %", "%")
                eu_hicp_fig.add_hline(y=2.0, line_dash="dash", line_color="orange", annotation_text="2% target")
                st.plotly_chart(eu_hicp_fig, use_container_width=True)

            st.markdown("---")

            st.subheader("Labor Market")
            eu_unemployment = fred_data.get("eu_unemployment", {}).get("series")
            if eu_unemployment is not None and not eu_unemployment.dropna().empty:
                st.metric("Euro Area Unemployment Rate", f"{eu_unemployment.dropna().iloc[-1]:.2f}%")
                st.plotly_chart(line_chart(eu_unemployment.dropna(), "Euro Area Unemployment Rate", "%"), use_container_width=True)

            st.markdown("---")

            st.subheader("EUR/USD Exchange Rate")
            st.caption("The dollar/euro cross is one of the most direct ways to see Fed vs. ECB "
                       "policy divergence priced by markets in real time.")
            eur_usd = fred_data.get("eur_usd", {}).get("series")
            if eur_usd is not None and not eur_usd.dropna().empty:
                st.metric("EUR/USD", f"{eur_usd.dropna().iloc[-1]:.4f}")
                st.plotly_chart(line_chart(eur_usd.dropna(), "EUR/USD Exchange Rate", "USD per EUR"), use_container_width=True)
                tv_link("eur_usd")

            st.markdown("---")
            st.caption(
                "🇪🇺 Europe coverage is currently Euro Area-wide (HICP, ECB rate, unemployment) "
                "plus UK/Germany equity indices in the Markets tab. Country-level breakdowns "
                "(e.g. Germany-only inflation) can be added — just ask."
            )

# ----------------------------------------------------------------------------
# MARKETS TAB
# ----------------------------------------------------------------------------

with tab_markets:
    market_region_us, market_region_eu = st.tabs(["🇺🇸 United States", "🇪🇺 Europe"])

    with st.spinner("Loading market data from Yahoo Finance..."):
        market_data = load_all_markets(MARKET_TICKERS, period=yahoo_period)

    # Benchmark for beta calc = S&P 500
    benchmark_df = market_data.get("^GSPC", {}).get("df")
    benchmark_returns = benchmark_df["Close"].pct_change() if benchmark_df is not None else None

    us_tickers = ["^GSPC", "^IXIC", "^DJI", "TLT", "SHY", "^VIX", "DX-Y.NYB", "GC=F", "CL=F", "HYG", "LQD"]
    eu_tickers = ["^STOXX50E", "^GDAXI", "^FTSE", "EURUSD=X"]

    def render_market_snapshot_and_charts(tickers: list):
        snap_cols = st.columns(3)
        i = 0
        for ticker in tickers:
            meta = market_data.get(ticker)
            if not meta:
                continue
            df, label = meta["df"], meta["label"]
            snap = latest_snapshot(df)
            col = snap_cols[i % 3]
            if snap:
                last, change_abs, change_pct, last_date = snap
                col.metric(f"{label} ({ticker})", f"{last:,.2f}", f"{change_pct:+.2f}%")
            else:
                col.metric(f"{label} ({ticker})", "N/A")
            i += 1

        st.markdown("---")
        st.subheader("Historical Charts")

        chart_cols = st.columns(2)
        i = 0
        for ticker in tickers:
            meta = market_data.get(ticker)
            if not meta:
                continue
            df, label = meta["df"], meta["label"]
            if df is not None and not df.empty:
                col = chart_cols[i % 2]
                chart_with_tv_link(col, df["Close"], f"{label} ({ticker})", "", ticker)
                i += 1

    with market_region_us:
        st.subheader("Snapshot")
        render_market_snapshot_and_charts(us_tickers)

        st.markdown("---")
        st.subheader("Beta vs S&P 500")
        st.caption("Beta measures sensitivity to S&P 500 moves over the selected lookback window. "
                   "Beta > 1 = more volatile than the market, < 1 = less volatile.")

        if benchmark_returns is not None:
            beta_cols = st.columns(3)
            i = 0
            for ticker in us_tickers:
                if ticker == "^GSPC":
                    continue
                meta = market_data.get(ticker)
                if not meta:
                    continue
                df = meta["df"]
                if df is not None and not df.empty:
                    stock_returns = df["Close"].pct_change()
                    beta = compute_beta(stock_returns, benchmark_returns)
                    col = beta_cols[i % 3]
                    col.metric(f"{meta['label']} ({ticker})", f"{beta:.2f}" if pd.notna(beta) else "N/A")
                    i += 1
        else:
            st.warning("Benchmark (S&P 500) data unavailable — cannot compute beta.")

    with market_region_eu:
        st.subheader("Snapshot")
        render_market_snapshot_and_charts(eu_tickers)

        st.markdown("---")
        st.subheader("Beta vs Euro Stoxx 50")
        st.caption("Beta measures sensitivity to Euro Stoxx 50 moves over the selected lookback window.")

        eu_benchmark_df = market_data.get("^STOXX50E", {}).get("df")
        eu_benchmark_returns = eu_benchmark_df["Close"].pct_change() if eu_benchmark_df is not None else None

        if eu_benchmark_returns is not None:
            beta_cols = st.columns(3)
            i = 0
            for ticker in eu_tickers:
                if ticker == "^STOXX50E":
                    continue
                meta = market_data.get(ticker)
                if not meta:
                    continue
                df = meta["df"]
                if df is not None and not df.empty:
                    stock_returns = df["Close"].pct_change()
                    beta = compute_beta(stock_returns, eu_benchmark_returns)
                    col = beta_cols[i % 3]
                    col.metric(f"{meta['label']} ({ticker})", f"{beta:.2f}" if pd.notna(beta) else "N/A")
                    i += 1
        else:
            st.warning("Benchmark (Euro Stoxx 50) data unavailable — cannot compute beta.")

# ----------------------------------------------------------------------------
# CROSS-ASSET TAB
# ----------------------------------------------------------------------------

with tab_crossasset:
    st.subheader("Cross-Asset Correlation Matrix")
    st.caption(
        f"Rolling {CORRELATION_WINDOW_DAYS}-trading-day correlation of daily returns. "
        "This is a 'current regime' read, not a long-run average — correlations between "
        "asset classes (especially stocks vs. bonds) shift meaningfully across macro regimes, "
        "and a recent-window matrix like this tends to catch those shifts faster than a "
        "multi-year correlation would."
    )

    with st.spinner("Loading cross-asset data..."):
        crossasset_data = load_all_markets(MARKET_TICKERS, period=yahoo_period)

    corr_matrix = compute_correlation_matrix(crossasset_data, CORRELATION_TICKERS, CORRELATION_WINDOW_DAYS)

    if not corr_matrix.empty:
        labels = [MARKET_TICKERS.get(t, t) for t in corr_matrix.columns]
        heatmap_fig = go.Figure(data=go.Heatmap(
            z=corr_matrix.values,
            x=labels,
            y=labels,
            colorscale="RdBu",
            zmid=0,
            zmin=-1,
            zmax=1,
            text=corr_matrix.round(2).values,
            texttemplate="%{text}",
            textfont={"size": 11},
            colorbar=dict(title="Correlation"),
        ))
        heatmap_fig.update_layout(
            height=500,
            margin=dict(l=10, r=10, t=30, b=10),
            title=f"{CORRELATION_WINDOW_DAYS}-Day Rolling Return Correlation",
        )
        st.plotly_chart(heatmap_fig, use_container_width=True)

        st.markdown("""
**Reading this matrix:**
- **Close to +1 (dark red):** assets moving together — diversification between them is weak right now
- **Close to -1 (dark blue):** assets moving oppositely — classic hedging relationship (e.g. stocks vs. bonds in a "normal" regime)
- **Close to 0 (white):** little relationship currently — genuine diversification benefit

A useful regime tell: when **stocks and bonds (S&P 500 vs. TLT) shift from negative to positive correlation**,
it often signals a shift toward an inflation-driven regime, where bonds stop being a reliable equity hedge.
        """)
    else:
        st.warning("Not enough overlapping data to compute the correlation matrix yet.")

    st.markdown("---")
    st.subheader("Credit Market Stress Proxy")
    st.caption(
        "HYG (high yield corporate bonds) vs. LQD (investment grade corporate bonds) — when HYG "
        "underperforms LQD, it's a free, real-time proxy for widening credit stress, similar in "
        "spirit to the official FRED OAS series but updating live throughout the trading day."
    )

    hyg_df = crossasset_data.get("HYG", {}).get("df")
    lqd_df = crossasset_data.get("LQD", {}).get("df")

    if hyg_df is not None and lqd_df is not None and not hyg_df.empty and not lqd_df.empty:
        hyg_norm = hyg_df["Close"] / hyg_df["Close"].iloc[0] * 100
        lqd_norm = lqd_df["Close"] / lqd_df["Close"].iloc[0] * 100
        ratio = hyg_norm / lqd_norm

        ratio_fig = go.Figure()
        ratio_fig.add_trace(go.Scatter(x=ratio.index, y=ratio.values, mode="lines", name="HYG/LQD ratio"))
        ratio_fig.update_layout(
            height=320,
            margin=dict(l=10, r=10, t=30, b=10),
            title="HYG / LQD Relative Performance (rebased to 100 at start of window)",
            yaxis_title="Ratio (rebased)",
        )
        st.plotly_chart(ratio_fig, use_container_width=True)
        st.caption("A falling line means high yield bonds are underperforming investment grade bonds — "
                   "i.e., credit markets are pricing in more risk. A rising line means credit risk "
                   "appetite is improving.")
    else:
        st.warning("HYG/LQD data unavailable.")

st.markdown("---")
st.caption(
    "Built with Streamlit · Data from FRED and Yahoo Finance · "
    "For informational purposes only, not investment advice."
)