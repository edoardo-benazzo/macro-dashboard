"""
Bitcoin & crypto data fetchers.
Sources: CoinGecko (free, no key), Alternative.me Fear & Greed,
         mempool.space hash rate, Yahoo Finance (BTC price history).
"""

import pandas as pd
import requests
import streamlit as st
import yfinance as yf

_CG_HEADERS = {"User-Agent": "MacroDashboard/2.0", "Accept": "application/json"}


@st.cache_data(ttl=60 * 5)
def fetch_btc_coingecko() -> dict:
    """BTC market data from CoinGecko (free, no key required)."""
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/coins/bitcoin",
            params={"localization": "false", "tickers": "false",
                    "market_data": "true", "community_data": "false",
                    "developer_data": "false"},
            headers=_CG_HEADERS, timeout=10,
        )
        r.raise_for_status()
        md = r.json().get("market_data", {})
        return {
            "price":       md.get("current_price", {}).get("usd"),
            "market_cap":  md.get("market_cap",    {}).get("usd"),
            "volume_24h":  md.get("total_volume",  {}).get("usd"),
            "change_24h":  md.get("price_change_percentage_24h"),
            "change_7d":   md.get("price_change_percentage_7d"),
            "change_30d":  md.get("price_change_percentage_30d"),
            "ath":         md.get("ath",            {}).get("usd"),
            "ath_change":  md.get("ath_change_percentage", {}).get("usd"),
            "circulating": md.get("circulating_supply"),
            "max_supply":  md.get("max_supply"),
        }
    except Exception:
        return {}


@st.cache_data(ttl=60 * 10)
def fetch_crypto_global() -> dict:
    """BTC dominance and total crypto market cap from CoinGecko /global."""
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/global",
            headers=_CG_HEADERS, timeout=10,
        )
        r.raise_for_status()
        data = r.json().get("data", {})
        return {
            "btc_dominance":    data.get("market_cap_percentage", {}).get("btc"),
            "total_market_cap": data.get("total_market_cap",      {}).get("usd"),
            "total_volume_24h": data.get("total_volume",          {}).get("usd"),
        }
    except Exception:
        return {}


@st.cache_data(ttl=60 * 60)
def fetch_fear_greed() -> dict:
    """Crypto Fear & Greed Index — 0 = Extreme Fear, 100 = Extreme Greed."""
    try:
        r = requests.get(
            "https://api.alternative.me/fng/?limit=30",
            headers={"User-Agent": "MacroDashboard/2.0"}, timeout=10,
        )
        r.raise_for_status()
        data = r.json().get("data", [])
        if not data:
            return {}
        latest  = data[0]
        history = [{"date": int(d["timestamp"]), "value": int(d["value"])} for d in data]
        return {
            "value":   int(latest.get("value", 0)),
            "label":   latest.get("value_classification", ""),
            "history": history,
        }
    except Exception:
        return {}


@st.cache_data(ttl=60 * 60)
def fetch_btc_hashrate() -> dict:
    """Hash rate and next difficulty adjustment from mempool.space."""
    result = {}
    try:
        r = requests.get(
            "https://mempool.space/api/v1/mining/hashrate/1m",
            headers={"User-Agent": "MacroDashboard/2.0"}, timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        result["hashrate_ehs"] = data.get("currentHashrate", 0) / 1e18
        result["difficulty"]   = data.get("currentDifficulty")
    except Exception:
        pass
    try:
        r2 = requests.get(
            "https://mempool.space/api/v1/difficulty-adjustment",
            headers={"User-Agent": "MacroDashboard/2.0"}, timeout=10,
        )
        r2.raise_for_status()
        adj = r2.json()
        result["difficulty_change_pct"] = adj.get("difficultyChange")
        result["remaining_blocks"]      = adj.get("remainingBlocks")
    except Exception:
        pass
    return result


@st.cache_data(ttl=60 * 5)
def fetch_btc_history(period: str = "2y") -> pd.DataFrame:
    """BTC-USD OHLCV history from Yahoo Finance."""
    try:
        return yf.Ticker("BTC-USD").history(period=period)
    except Exception:
        return pd.DataFrame()


def compute_btc_technicals(df: pd.DataFrame) -> dict:
    """200D MA, 50D MA, Mayer Multiple, and window stats from price history."""
    if df is None or df.empty:
        return {}
    close  = df["Close"].dropna()
    result = {"price": close.iloc[-1], "close_series": close}

    if len(close) >= 200:
        ma200 = close.rolling(200).mean()
        result["ma200"]        = ma200.iloc[-1]
        result["ma200_series"] = ma200
        result["mayer_multiple"] = round(close.iloc[-1] / ma200.iloc[-1], 3)
        result["mayer_series"]   = close / ma200

    if len(close) >= 50:
        ma50 = close.rolling(50).mean()
        result["ma50"]        = ma50.iloc[-1]
        result["ma50_series"] = ma50

    result["window_high"]     = close.max()
    result["ath_in_window_pct"] = (close.iloc[-1] / close.max() - 1) * 100
    return result


def halving_cycle_info() -> dict:
    """Days since last halving and progress through the current 4-year cycle."""
    import datetime as dt
    LAST_HALVING = dt.date(2024, 4, 19)
    NEXT_HALVING = dt.date(2028, 4, 17)
    today = dt.date.today()
    days_since   = (today - LAST_HALVING).days
    cycle_days   = (NEXT_HALVING - LAST_HALVING).days
    days_to_next = (NEXT_HALVING - today).days
    pct_through  = days_since / cycle_days * 100
    if   days_since < 540:  label = "Early Bull (0–18mo post-halving)"
    elif days_since < 900:  label = "Mid-Cycle (18–30mo)"
    elif days_since < 1260: label = "Late Bull / Distribution (30–42mo)"
    else:                   label = "Bear / Accumulation (42mo+)"
    return {
        "last_halving": LAST_HALVING.isoformat(),
        "next_halving": NEXT_HALVING.isoformat(),
        "days_since":   days_since,
        "days_to_next": days_to_next,
        "pct_through":  round(pct_through, 1),
        "cycle_label":  label,
    }
