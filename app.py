"""
Macro Dashboard
---------------
Free, self-contained macro + markets dashboard.
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

from config import FRED_SERIES, MARKET_TICKERS, DEFAULT_LOOKBACK_YEARS
from data_fetchers import load_all_fred, load_all_markets, latest_snapshot, compute_beta

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

# ----------------------------------------------------------------------------
# Helper: line chart for a single series
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


def snapshot_metric(col, label, value, change_pct, units=""):
    if value is None:
        col.metric(label, "N/A")
    else:
        col.metric(label, f"{value:,.2f}{units}", f"{change_pct:+.2f}%")


# ----------------------------------------------------------------------------
# Tabs
# ----------------------------------------------------------------------------

tab_macro, tab_markets = st.tabs(["🏛️ Macro", "📈 Markets"])

# ----------------------------------------------------------------------------
# MACRO TAB
# ----------------------------------------------------------------------------

with tab_macro:
    if not fred_api_key:
        st.warning("Enter your free FRED API key in the sidebar to load macro data.")
    else:
        with st.spinner("Loading macro data from FRED..."):
            fred_data = load_all_fred(FRED_SERIES, fred_api_key, fred_start)

        # --- Yield snapshot + 2s10s spread ---
        st.subheader("Treasury Yields")
        y10 = fred_data.get("10y_yield", {}).get("series")
        y2 = fred_data.get("2y_yield", {}).get("series")

        c1, c2, c3 = st.columns(3)
        if y10 is not None and not y10.empty:
            c1.metric("10-Year Yield", f"{y10.dropna().iloc[-1]:.2f}%")
        if y2 is not None and not y2.empty:
            c2.metric("2-Year Yield", f"{y2.dropna().iloc[-1]:.2f}%")
        if y10 is not None and y2 is not None and not y10.empty and not y2.empty:
            spread = (y10.dropna().iloc[-1] - y2.dropna().iloc[-1])
            inverted = spread < 0
            c3.metric("2s10s Spread", f"{spread:.2f}%", delta="Inverted ⚠️" if inverted else "Normal")

        col_a, col_b = st.columns(2)
        if y10 is not None and not y10.empty:
            col_a.plotly_chart(line_chart(y10.dropna(), "10-Year Treasury Yield", "%"), use_container_width=True)
        if y2 is not None and not y2.empty:
            col_b.plotly_chart(line_chart(y2.dropna(), "2-Year Treasury Yield", "%"), use_container_width=True)

        if y10 is not None and y2 is not None:
            spread_series = (y10 - y2).dropna()
            st.plotly_chart(line_chart(spread_series, "2s10s Spread (10Y minus 2Y)", "%"), use_container_width=True)
            st.caption("Negative values (below the zero line) indicate an inverted yield curve, "
                       "historically watched as a recession signal.")

        st.markdown("---")

        # --- Inflation ---
        st.subheader("Inflation")
        cpi = fred_data.get("cpi_yoy", {}).get("series")
        core_cpi = fred_data.get("core_cpi_yoy", {}).get("series")

        c1, c2 = st.columns(2)
        if cpi is not None and not cpi.dropna().empty:
            c1.metric("CPI (YoY)", f"{cpi.dropna().iloc[-1]:.2f}%")
        if core_cpi is not None and not core_cpi.dropna().empty:
            c2.metric("Core CPI (YoY)", f"{core_cpi.dropna().iloc[-1]:.2f}%")

        col_a, col_b = st.columns(2)
        if cpi is not None:
            col_a.plotly_chart(line_chart(cpi.dropna(), "CPI YoY %", "%"), use_container_width=True)
        if core_cpi is not None:
            col_b.plotly_chart(line_chart(core_cpi.dropna(), "Core CPI YoY %", "%"), use_container_width=True)

        st.markdown("---")

        # --- Labor market ---
        st.subheader("Labor Market")
        unemployment = fred_data.get("unemployment", {}).get("series")
        nfp = fred_data.get("nfp", {}).get("series")

        c1, c2 = st.columns(2)
        if unemployment is not None and not unemployment.dropna().empty:
            c1.metric("Unemployment Rate", f"{unemployment.dropna().iloc[-1]:.2f}%")
        if nfp is not None and not nfp.dropna().empty:
            latest_nfp = nfp.dropna()
            mom_change = latest_nfp.diff().iloc[-1]
            c2.metric("Nonfarm Payrolls (level, k)", f"{latest_nfp.iloc[-1]:,.0f}", f"{mom_change:+,.0f} MoM")

        col_a, col_b = st.columns(2)
        if unemployment is not None:
            col_a.plotly_chart(line_chart(unemployment.dropna(), "Unemployment Rate", "%"), use_container_width=True)
        if nfp is not None:
            col_b.plotly_chart(line_chart(nfp.dropna(), "Nonfarm Payrolls (level, thousands)", "thousands"), use_container_width=True)

        st.markdown("---")

        # --- Fed funds rate ---
        st.subheader("Fed Funds Rate")
        ffr = fred_data.get("fed_funds", {}).get("series")
        if ffr is not None and not ffr.dropna().empty:
            st.metric("Effective Fed Funds Rate", f"{ffr.dropna().iloc[-1]:.2f}%")
            st.plotly_chart(line_chart(ffr.dropna(), "Effective Fed Funds Rate", "%"), use_container_width=True)

# ----------------------------------------------------------------------------
# MARKETS TAB
# ----------------------------------------------------------------------------

with tab_markets:
    with st.spinner("Loading market data from Yahoo Finance..."):
        market_data = load_all_markets(MARKET_TICKERS, period=yahoo_period)

    # Benchmark for beta calc = S&P 500
    benchmark_df = market_data.get("^GSPC", {}).get("df")
    benchmark_returns = benchmark_df["Close"].pct_change() if benchmark_df is not None else None

    st.subheader("Snapshot")
    snap_cols = st.columns(3)
    i = 0
    for ticker, meta in market_data.items():
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
    for ticker, meta in market_data.items():
        df, label = meta["df"], meta["label"]
        if df is not None and not df.empty:
            fig = line_chart(df["Close"], f"{label} ({ticker})", "")
            chart_cols[i % 2].plotly_chart(fig, use_container_width=True)
        i += 1

    st.markdown("---")
    st.subheader("Beta vs S&P 500")
    st.caption("Beta measures sensitivity to S&P 500 moves over the selected lookback window. "
               "Beta > 1 = more volatile than the market, < 1 = less volatile.")

    if benchmark_returns is not None:
        beta_cols = st.columns(3)
        i = 0
        for ticker, meta in market_data.items():
            if ticker == "^GSPC":
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

st.markdown("---")
st.caption(
    "Built with Streamlit · Data from FRED and Yahoo Finance · "
    "For informational purposes only, not investment advice."
)
