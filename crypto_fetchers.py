"""
Bitcoin & crypto data fetchers.
Sources: CoinGecko (free tier, no key), Alternative.me Fear & Greed,
mempool.space hash rate, and Yahoo Finance (BTC price history + MSTR).
"""

import pandas as pd
import requests
import streamlit as st
import yfinance as yf

# ─────────────────────────────────────────────────────────────────────────────
# CoinGecko — price, market cap, dominance, ATH, supply
# ─────────────────────────────────────────────────────────────────────────────

_CG_HEADERS = {"User-Agent": "MacroDashboard/2.0", "Accept": "application/json"}


@st.cache_data(ttl=60 * 5)  # 5-minute cache
def fetch_btc_coingecko() -> dict:
    """Fetch BTC market data from CoinGecko (free, no key required)."""
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
            "price":        md.get("current_price", {}).get("usd"),
            "market_cap":   md.get("market_cap",    {}).get("usd"),
            "volume_24h":   md.get("total_volume",  {}).get("usd"),
            "change_24h":   md.get("price_change_percentage_24h"),
            "change_7d":    md.get("price_change_percentage_7d"),
            "change_30d":   md.get("price_change_percentage_30d"),
            "ath":          md.get("ath",            {}).get("usd"),
            "ath_change":   md.get("ath_change_percentage", {}).get("usd"),
            "circulating":  md.get("circulating_supply"),
            "max_supply":   md.get("max_supply"),
        }
    except Exception:
        return {}


@st.cache_data(ttl=60 * 15)
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
            "btc_dominance":     data.get("market_cap_percentage", {}).get("btc"),
            "total_market_cap":  data.get("total_market_cap",       {}).get("usd"),
            "total_volume_24h":  data.get("total_volume",           {}).get("usd"),
            "active_cryptos":    data.get("active_cryptocurrencies"),
        }
    except Exception:
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# Alternative.me — Fear & Greed Index
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=60 * 60)  # 1h cache — updates daily
def fetch_fear_greed() -> dict:
    """Crypto Fear & Greed Index (0 = Extreme Fear, 100 = Extreme Greed)."""
    try:
        r = requests.get(
            "https://api.alternative.me/fng/?limit=30",
            headers={"User-Agent": "MacroDashboard/2.0"}, timeout=10,
        )
        r.raise_for_status()
        data = r.json().get("data", [])
        if not data:
            return {}
        latest = data[0]
        history = [{"date": int(d["timestamp"]), "value": int(d["value"])} for d in data]
        return {
            "value": int(latest.get("value", 0)),
            "label": latest.get("value_classification", ""),
            "history": history,
        }
    except Exception:
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# mempool.space — hash rate & difficulty
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=60 * 60)
def fetch_btc_hashrate() -> dict:
    """Current hash rate and next difficulty adjustment from mempool.space."""
    result = {}
    try:
        r = requests.get(
            "https://mempool.space/api/v1/mining/hashrate/1m",
            headers={"User-Agent": "MacroDashboard/2.0"}, timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        result["hashrate_ehs"]   = data.get("currentHashrate", 0) / 1e18  # convert H/s → EH/s
        result["difficulty"]     = data.get("currentDifficulty")
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
        result["estimated_retarget"]    = adj.get("estimatedRetargetDate")
    except Exception:
        pass
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Yahoo Finance — BTC price history + MSTR
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=60 * 15)
def fetch_btc_history(period: str = "2y") -> pd.DataFrame:
    """BTC-USD OHLCV history from Yahoo Finance."""
    try:
        df = yf.Ticker("BTC-USD").history(period=period)
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=60 * 15)
def fetch_mstr_history(period: str = "2y") -> pd.DataFrame:
    """MSTR price history from Yahoo Finance."""
    try:
        df = yf.Ticker("MSTR").history(period=period)
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=60 * 60)
def fetch_mstr_info() -> dict:
    """MSTR shares outstanding and basic info from Yahoo Finance."""
    try:
        info = yf.Ticker("MSTR").info
        return {
            "shares_outstanding": info.get("sharesOutstanding"),
            "market_cap":         info.get("marketCap"),
            "name":               info.get("longName", "Strategy Inc (MSTR)"),
        }
    except Exception:
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# Analytics
# ─────────────────────────────────────────────────────────────────────────────

def compute_btc_technicals(df: pd.DataFrame) -> dict:
    """
    Compute key Bitcoin technical indicators from price history:
    - 200-day moving average & Mayer Multiple (price / 200D MA)
    - 50-day moving average
    - Distance from all-time high within the window
    """
    if df is None or df.empty:
        return {}
    close = df["Close"].dropna()
    result = {}

    if len(close) >= 200:
        ma200 = close.rolling(200).mean()
        result["ma200"]       = ma200.iloc[-1]
        result["ma200_series"] = ma200
        mayer = close.iloc[-1] / ma200.iloc[-1]
        result["mayer_multiple"] = round(mayer, 3)
        result["mayer_series"]   = close / ma200

    if len(close) >= 50:
        ma50 = close.rolling(50).mean()
        result["ma50"]        = ma50.iloc[-1]
        result["ma50_series"] = ma50

    result["price"]       = close.iloc[-1]
    result["close_series"] = close
    result["window_high"] = close.max()
    result["window_low"]  = close.min()
    result["ath_in_window_pct"] = (close.iloc[-1] / close.max() - 1) * 100

    return result


def compute_mstr_nav(
    btc_price: float,
    mstr_price: float,
    btc_holdings: int,
    shares_outstanding: int | None,
) -> dict:
    """
    Strategy Inc (MSTR) NAV premium.

    NAV = BTC holdings × BTC price
    Market Cap = MSTR price × shares outstanding
    Premium = (Market Cap / NAV - 1) × 100
    BTC per Share = BTC holdings / shares outstanding
    """
    if btc_price is None or mstr_price is None or btc_holdings is None:
        return {}
    nav = btc_price * btc_holdings
    btc_per_share = btc_holdings / shares_outstanding if shares_outstanding else None
    mktcap = mstr_price * shares_outstanding if shares_outstanding else None
    premium = ((mktcap / nav) - 1) * 100 if (mktcap and nav) else None
    return {
        "nav":           nav,
        "market_cap":    mktcap,
        "nav_premium":   premium,
        "btc_per_share": btc_per_share,
        "btc_holdings":  btc_holdings,
    }


def halving_cycle_info() -> dict:
    """Days since last halving and % through current 4-year cycle."""
    from datetime import date
    LAST_HALVING = date(2024, 4, 19)   # 4th halving
    NEXT_HALVING = date(2028, 4, 17)   # estimated 5th halving
    today = date.today()
    days_since = (today - LAST_HALVING).days
    cycle_days = (NEXT_HALVING - LAST_HALVING).days
    pct_through = days_since / cycle_days * 100
    days_to_next = (NEXT_HALVING - today).days
    return {
        "last_halving":   LAST_HALVING.isoformat(),
        "next_halving":   NEXT_HALVING.isoformat(),
        "days_since":     days_since,
        "days_to_next":   days_to_next,
        "pct_through":    round(pct_through, 1),
        "cycle_label":    (
            "Early Bull (0-18mo)" if days_since < 540 else
            "Mid-Cycle (18-30mo)" if days_since < 900 else
            "Late Bull / Distribution (30-42mo)" if days_since < 1260 else
            "Bear / Accumulation (42mo+)"
        ),
    }
