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
