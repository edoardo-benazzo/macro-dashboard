"""
All data-fetching logic lives here, isolated from the UI code in app.py.
Streamlit's @st.cache_data decorator means repeated runs within the TTL
window reuse cached results instead of re-hitting the APIs every time
someone loads the page.
"""

import datetime as dt

import pandas as pd
import streamlit as st
import yfinance as yf
from fredapi import Fred


# ----------------------------------------------------------------------------
# FRED
# ----------------------------------------------------------------------------

@st.cache_data(ttl=60 * 60 * 6)  # cache for 6 hours — macro data updates slowly
def get_fred_series(series_id: str, api_key: str, start: str = "2000-01-01") -> pd.Series:
    """Fetch a single FRED series as a pandas Series indexed by date."""
    fred = Fred(api_key=api_key)
    data = fred.get_series(series_id, observation_start=start)
    data.name = series_id
    return data


def yoy_pct_change(series: pd.Series) -> pd.Series:
    """Convert a level series (e.g. CPI index) into year-over-year % change."""
    return series.pct_change(periods=12) * 100


@st.cache_data(ttl=60 * 60 * 6)
def load_all_fred(fred_config: dict, api_key: str, start: str) -> dict:
    """
    Loop through FRED_SERIES from config.py and return a dict of
    {key: pandas Series}, applying yoy_pct transform where flagged.
    """
    results = {}
    for key, meta in fred_config.items():
        series_id, label, units = meta[0], meta[1], meta[2]
        transform = meta[3] if len(meta) > 3 else None
        try:
            raw = get_fred_series(series_id, api_key, start=start)
            if transform == "yoy_pct":
                raw = yoy_pct_change(raw)
            results[key] = {"series": raw, "label": label, "units": units}
        except Exception as e:
            results[key] = {"series": None, "label": label, "units": units, "error": str(e)}
    return results


# ----------------------------------------------------------------------------
# Yahoo Finance
# ----------------------------------------------------------------------------

@st.cache_data(ttl=60 * 15)  # cache for 15 min — market data moves faster
def get_yahoo_history(ticker: str, period: str = "5y") -> pd.DataFrame:
    """Fetch historical OHLC data for a single ticker."""
    df = yf.Ticker(ticker).history(period=period)
    return df


@st.cache_data(ttl=60 * 15)
def load_all_markets(tickers: dict, period: str = "5y") -> dict:
    """
    Loop through MARKET_TICKERS from config.py and return a dict of
    {ticker: {"df": dataframe, "label": str}}.
    """
    results = {}
    for ticker, label in tickers.items():
        try:
            df = get_yahoo_history(ticker, period=period)
            results[ticker] = {"df": df, "label": label, "error": None}
        except Exception as e:
            results[ticker] = {"df": None, "label": label, "error": str(e)}
    return results


def latest_snapshot(df: pd.DataFrame):
    """
    Given an OHLC dataframe, return (latest_close, change_abs, change_pct,
    latest_date) comparing the most recent close to the prior close.
    Returns None if there isn't enough data.
    """
    if df is None or df.empty or len(df) < 2:
        return None
    last = df["Close"].iloc[-1]
    prev = df["Close"].iloc[-2]
    change_abs = last - prev
    change_pct = (change_abs / prev) * 100 if prev else float("nan")
    last_date = df.index[-1].date()
    return last, change_abs, change_pct, last_date


def compute_beta(stock_returns: pd.Series, benchmark_returns: pd.Series) -> float:
    """
    Simple beta calculation: covariance(stock, benchmark) / variance(benchmark),
    on overlapping dates only.
    """
    aligned = pd.concat([stock_returns, benchmark_returns], axis=1).dropna()
    if len(aligned) < 20:  # not enough overlap to be meaningful
        return float("nan")
    cov = aligned.cov().iloc[0, 1]
    var = aligned.iloc[:, 1].var()
    return cov / var if var else float("nan")


# ----------------------------------------------------------------------------
# Macro signal calculations
# ----------------------------------------------------------------------------

def compute_sahm_rule(unemployment: pd.Series) -> dict:
    """
    Sahm Rule recession indicator.

    Definition (Claudia Sahm, used informally by the Fed/NBER as a real-time
    recession signal): take the 3-month moving average of the unemployment
    rate, then compare it to the MINIMUM of that 3-month average over the
    trailing 12 months. If the current 3mo average is 0.50 percentage points
    or more above that 12-month low, the rule is "triggered" — historically
    this has reliably coincided with the early months of a recession.

    Returns a dict with the current indicator value, trigger status, and
    the full historical series (useful for charting).
    """
    if unemployment is None or unemployment.dropna().empty:
        return {"value": None, "triggered": None, "series": None}

    u = unemployment.dropna()
    three_mo_avg = u.rolling(window=3).mean()
    twelve_mo_min = three_mo_avg.rolling(window=12).min()
    sahm_indicator = three_mo_avg - twelve_mo_min

    current_value = sahm_indicator.iloc[-1] if not sahm_indicator.dropna().empty else None
    triggered = (current_value >= 0.50) if current_value is not None and pd.notna(current_value) else None

    return {"value": current_value, "triggered": triggered, "series": sahm_indicator}


def cpi_vs_target(cpi_yoy_latest: float, target: float = 2.0) -> dict:
    """
    Compare latest YoY CPI print to the Fed's long-run 2% inflation target.
    Returns the gap and a simple status label.
    """
    if cpi_yoy_latest is None or pd.isna(cpi_yoy_latest):
        return {"gap": None, "status": None}
    gap = cpi_yoy_latest - target
    if gap > 1.0:
        status = "well above target"
    elif gap > 0.2:
        status = "above target"
    elif gap < -0.2:
        status = "below target"
    else:
        status = "at target"
    return {"gap": gap, "status": status}


def yield_curve_status(spread: float) -> dict:
    """
    Classify the 2s10s spread into a simple status. Inversion (spread < 0)
    has historically preceded US recessions, though with long and variable
    lags, so this is a watch signal, not a precise timing tool.
    """
    if spread is None or pd.isna(spread):
        return {"status": None, "label": None}
    if spread < 0:
        return {"status": "inverted", "label": "🔴 Curve Inverted"}
    elif spread < 0.25:
        return {"status": "flat", "label": "🟡 Curve Flat"}
    else:
        return {"status": "normal", "label": "🟢 Curve Normal"}


# ----------------------------------------------------------------------------
# Credit, real yields, and growth-regime calculations
# ----------------------------------------------------------------------------

def credit_spread_status(hy_oas_latest: float) -> dict:
    """
    Classify the High Yield OAS (option-adjusted spread) level into a rough
    stress regime. These thresholds are commonly-cited rules of thumb, not
    precise scientific cutoffs:
      < 3.5%  : tight / complacent credit conditions
      3.5-5%  : normal
      5-8%    : elevated stress
      > 8%    : crisis-level stress (seen in 2008, March 2020)
    """
    if hy_oas_latest is None or pd.isna(hy_oas_latest):
        return {"status": None, "label": None}
    if hy_oas_latest > 8:
        return {"status": "crisis", "label": "🔴 Credit Stress: Crisis-Level"}
    elif hy_oas_latest > 5:
        return {"status": "elevated", "label": "🟠 Credit Stress: Elevated"}
    elif hy_oas_latest > 3.5:
        return {"status": "normal", "label": "🟡 Credit Spreads: Normal"}
    else:
        return {"status": "tight", "label": "🟢 Credit Spreads: Tight"}


def classify_macro_regime(cfnai_latest: float, cpi_yoy_latest: float, target: float = 2.0) -> dict:
    """
    A simplified 2x2 macro regime classifier, the same basic framework
    macro investors use to think about asset allocation:

                        Inflation Rising        Inflation Falling
    Growth Rising       Reflation                Goldilocks
    Growth Falling      Stagflation              Deflation/Recession risk

    Growth proxy: CFNAI (above 0 = above-trend growth, below 0 = below-trend)
    Inflation proxy: whether CPI YoY is above or below the Fed's 2% target

    This is a simplification — real regime calls use growth/inflation
    MOMENTUM (rate of change) too, not just levels — but it's a reasonable
    first-pass lens for a dashboard.
    """
    if cfnai_latest is None or pd.isna(cfnai_latest) or cpi_yoy_latest is None or pd.isna(cpi_yoy_latest):
        return {"regime": None, "label": None, "description": None}

    growth_up = cfnai_latest > 0
    inflation_up = cpi_yoy_latest > target

    if growth_up and inflation_up:
        return {
            "regime": "reflation",
            "label": "🔥 Reflation",
            "description": "Above-trend growth with above-target inflation. Historically favors "
                            "commodities, cyclical equities, and real assets over nominal bonds.",
        }
    elif growth_up and not inflation_up:
        return {
            "regime": "goldilocks",
            "label": "✨ Goldilocks",
            "description": "Above-trend growth with contained inflation. Historically the most "
                            "favorable backdrop for risk assets broadly (equities especially).",
        }
    elif not growth_up and inflation_up:
        return {
            "regime": "stagflation",
            "label": "⚠️ Stagflation",
            "description": "Below-trend growth with above-target inflation. Historically the hardest "
                            "regime for both stocks and bonds; commodities and inflation-protected "
                            "assets have tended to hold up better.",
        }
    else:
        return {
            "regime": "deflation_risk",
            "label": "🧊 Deflation / Recession Risk",
            "description": "Below-trend growth with contained or falling inflation. Historically "
                            "favors high-quality government bonds and defensive equity sectors.",
        }


def compute_correlation_matrix(price_data: dict, tickers: list, window_days: int = 60) -> pd.DataFrame:
    """
    Build a rolling-window correlation matrix of daily returns across the
    given tickers. price_data is the dict returned by load_all_markets()
    (i.e. {ticker: {"df": dataframe, "label": str}}).

    Uses the most recent `window_days` trading days of returns, which is
    standard for a "current regime" cross-asset correlation read (as
    opposed to a multi-year correlation, which would smooth over regime
    changes).
    """
    returns = {}
    for ticker in tickers:
        df = price_data.get(ticker, {}).get("df")
        if df is not None and not df.empty and "Close" in df.columns:
            returns[ticker] = df["Close"].pct_change()

    if len(returns) < 2:
        return pd.DataFrame()

    returns_df = pd.DataFrame(returns).dropna(how="all")
    recent = returns_df.tail(window_days)
    corr = recent.corr()
    return corr