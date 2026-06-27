"""
Bitcoin & crypto data fetchers.
Sources: CoinGecko (free, no key), Alternative.me Fear & Greed,
         mempool.space hash rate, blockchain.info, Yahoo Finance.
"""

import datetime as dt
import math

import pandas as pd
import requests
import streamlit as st
import yfinance as yf

_CG_HEADERS = {"User-Agent": "MacroDashboard/2.0", "Accept": "application/json"}

_ANNUAL_ISSUANCE = 164_250   # 3.125 BTC/block × 144 blocks/day × 365
_ATH             = 126_198   # Cycle 5 ATH — Oct 6 2025
_JAN25_HIGH      = 109_350   # Jan 2025 local high
_100K_LEVEL      = 100_000   # psychological level
_CYCLE4_ATH      = 69_044    # Nov 2021 cycle 4 peak
_HALVING_PRICE   = 63_210    # BTC price on halving day Apr 20 2024
_CYCLE_LOW       = 15_476    # Nov 21 2022 cycle low
_REALIZED_PRICE  = 53_300    # approx on-chain cost basis (update periodically)
_MVRV_REALIZED   = 52_000    # realized price used for MVRV calculation


@st.cache_data(ttl=60 * 1)
def fetch_btc_bybit() -> dict:
    """
    Current BTC price from Bybit public API (no key needed). 1-minute cache.
    Falls back to CoinGecko simple price if Bybit is unavailable.
    """
    ts = dt.datetime.now(dt.timezone.utc).isoformat()
    try:
        r = requests.get(
            "https://api.bybit.com/v5/market/tickers",
            params={"category": "spot", "symbol": "BTCUSDT"},
            headers={"User-Agent": "MacroDashboard/2.0"}, timeout=8,
        )
        r.raise_for_status()
        lst = r.json().get("result", {}).get("list", [])
        if lst:
            t = lst[0]
            price = float(t.get("lastPrice", 0) or 0)
            if price > 0:
                pct_raw = float(t.get("price24hPcnt", 0) or 0)
                return {
                    "price":      price,
                    "change_24h": pct_raw * 100,          # Bybit returns decimal fraction
                    "high_24h":   float(t.get("highPrice24h", 0) or 0),
                    "low_24h":    float(t.get("lowPrice24h",  0) or 0),
                    "volume_24h": float(t.get("turnover24h",  0) or 0),
                    "source":     "Bybit",
                    "fetched_at": ts,
                }
    except Exception:
        pass
    # Fallback: CoinGecko simple price
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": "bitcoin", "vs_currencies": "usd",
                    "include_24hr_change": "true", "include_24hr_vol": "true"},
            headers=_CG_HEADERS, timeout=8,
        )
        r.raise_for_status()
        btc = r.json().get("bitcoin", {})
        if btc.get("usd"):
            return {
                "price":      btc["usd"],
                "change_24h": btc.get("usd_24h_change"),
                "volume_24h": btc.get("usd_24h_vol"),
                "source":     "CoinGecko",
                "fetched_at": ts,
            }
    except Exception:
        pass
    return {"fetched_at": ts}


@st.cache_data(ttl=60 * 2)
def fetch_btc_price() -> dict:
    """
    Current BTC price — primary: CoinGecko simple price, fallback: yfinance.
    2-minute cache for near-real-time updates.
    """
    ts = dt.datetime.now(dt.timezone.utc).isoformat()
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={
                "ids":                "bitcoin",
                "vs_currencies":      "usd",
                "include_24hr_change":"true",
                "include_market_cap": "true",
                "include_24hr_vol":   "true",
            },
            headers=_CG_HEADERS, timeout=8,
        )
        r.raise_for_status()
        btc = r.json().get("bitcoin", {})
        if btc.get("usd"):
            return {
                "price":      btc["usd"],
                "change_24h": btc.get("usd_24h_change"),
                "market_cap": btc.get("usd_market_cap"),
                "volume_24h": btc.get("usd_24h_vol"),
                "source":     "CoinGecko",
                "fetched_at": ts,
            }
    except Exception:
        pass
    # Fallback: yfinance
    try:
        hist = yf.Ticker("BTC-USD").history(period="2d")
        if not hist.empty:
            price = float(hist["Close"].iloc[-1])
            prev  = float(hist["Close"].iloc[-2]) if len(hist) > 1 else price
            return {
                "price":      price,
                "change_24h": (price - prev) / prev * 100 if prev else None,
                "market_cap": None,
                "volume_24h": None,
                "source":     "Yahoo Finance",
                "fetched_at": ts,
            }
    except Exception:
        pass
    return {"fetched_at": ts}


@st.cache_data(ttl=60 * 2)
def fetch_btc_coingecko() -> dict:
    """BTC market data from CoinGecko (free, no key required). 2-minute cache."""
    ts = dt.datetime.now(dt.timezone.utc).isoformat()
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
            "change_1y":   md.get("price_change_percentage_1y"),
            "ath":         md.get("ath",            {}).get("usd"),
            "ath_change":  md.get("ath_change_percentage", {}).get("usd"),
            "circulating": md.get("circulating_supply"),
            "max_supply":  md.get("max_supply"),
            "fetched_at":  ts,
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
        raw_hr = data.get("currentHashrate", 0) or 0
        hr_ehs = raw_hr / 1e18
        result["hashrate_ehs"] = hr_ehs if not math.isnan(hr_ehs) else None
        diff = data.get("currentDifficulty")
        result["difficulty"] = diff if diff is not None else None
    except Exception:
        pass
    try:
        r2 = requests.get(
            "https://mempool.space/api/v1/difficulty-adjustment",
            headers={"User-Agent": "MacroDashboard/2.0"}, timeout=10,
        )
        r2.raise_for_status()
        adj = r2.json()
        dc = adj.get("difficultyChange")
        rb = adj.get("remainingBlocks")
        result["difficulty_change_pct"] = dc if (dc is not None and not (isinstance(dc, float) and math.isnan(dc))) else None
        result["remaining_blocks"] = rb
    except Exception:
        pass
    return result


@st.cache_data(ttl=60 * 10)
def fetch_blockchain_info() -> dict:
    """On-chain stats from blockchain.info public API (free, no key). 10-min cache."""
    try:
        r = requests.get(
            "https://api.blockchain.info/stats",
            headers={"User-Agent": "MacroDashboard/2.0"}, timeout=10,
        )
        r.raise_for_status()
        d = r.json()
        total_btc = (d.get("totalbc") or 0) / 1e8  # satoshis → BTC
        n_tx      = d.get("n_tx")
        fees_btc  = (d.get("total_fees_btc") or 0) / 1e8
        price     = d.get("market_price_usd")
        avg_fee_usd = (fees_btc / n_tx * price) if (n_tx and price and n_tx > 0) else None
        return {
            "total_btc":   total_btc,
            "n_tx_24h":    n_tx,
            "avg_fee_usd": avg_fee_usd,
        }
    except Exception:
        return {}


@st.cache_data(ttl=60 * 60)
def fetch_btc_cg_history(days: int = 365) -> pd.Series:
    """Daily BTC/USD close prices from CoinGecko market_chart. 1-hour cache."""
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart",
            params={"vs_currency": "usd", "days": str(days), "interval": "daily"},
            headers=_CG_HEADERS, timeout=15,
        )
        r.raise_for_status()
        prices = r.json().get("prices", [])
        if not prices:
            return pd.Series(dtype=float)
        df = pd.DataFrame(prices, columns=["ts", "price"])
        df["date"] = pd.to_datetime(df["ts"], unit="ms").dt.normalize()
        df = df.drop_duplicates("date").set_index("date")["price"]
        return df.sort_index()
    except Exception:
        return pd.Series(dtype=float)


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
    """4-year cycle position, phase label, and progress."""
    LAST_HALVING       = dt.date(2024, 4, 20)   # block 840,000
    LAST_HALVING_BLOCK = 840_000
    NEXT_HALVING       = dt.date(2028, 4, 17)   # estimated
    today        = dt.date.today()
    days_since   = (today - LAST_HALVING).days
    cycle_days   = (NEXT_HALVING - LAST_HALVING).days
    days_to_next = max(0, (NEXT_HALVING - today).days)
    pct_through  = min(100.0, days_since / cycle_days * 100)

    if   days_since < 365:  label = "Early Bull"
    elif days_since < 548:  label = "Bull Market Peak Zone"
    elif days_since < 730:  label = "Post-Peak / Early Bear"
    elif days_since < 1095: label = "Bear Market"
    else:                   label = "Pre-Halving Accumulation"

    return {
        "last_halving":        LAST_HALVING.isoformat(),
        "last_halving_block":  LAST_HALVING_BLOCK,
        "next_halving":        NEXT_HALVING.isoformat(),
        "days_since":          days_since,
        "days_to_next":        days_to_next,
        "pct_through":         round(pct_through, 1),
        "cycle_label":         label,
    }


def compute_s2f(circulating: float) -> dict:
    """Stock-to-Flow ratio and PlanB model implied price."""
    if not circulating or circulating <= 0:
        return {}
    sf = circulating / _ANNUAL_ISSUANCE
    implied = math.exp(3.31 * math.log(sf) - 1.84)
    return {"ratio": round(sf, 1), "implied_price": round(implied, -2)}
