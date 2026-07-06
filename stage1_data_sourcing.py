"""
Stage 1 — Data Sourcing for a daily BTC LightGBM trading strategy.

Builds a single daily dataset (btc_dataset.csv) combining:
  1. BTC daily OHLCV        — Binance via ccxt, fallback to yfinance
  2. Technical indicators   — RSI, Bollinger Bands, ATR/NATR, MACD/PPO,
                              historical + forward returns
  3. Macro (FRED, no key)   — DTWEXBGS, DFII10, M2SL, WALCL
  4. Gold (yfinance GC=F)   — price + BTC/gold ratio
  5. Crypto Fear & Greed    — alternative.me
  6. BTC funding rates      — Binance futures via ccxt

All lower-frequency series (macro, gold, F&G, funding) are forward-filled
onto BTC's daily calendar so that no observation uses information from the
future.
"""

from __future__ import annotations

import io
import time
import warnings
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import requests

warnings.filterwarnings("ignore")

# Analyse from the start of meaningful BTC history.
START_DATE = "2017-01-01"
OUTFILE = "btc_dataset.csv"


# ---------------------------------------------------------------------------
# 1. BTC daily OHLCV
# ---------------------------------------------------------------------------
def fetch_btc_ccxt() -> pd.DataFrame:
    """Daily BTC/USDT OHLCV from Binance via ccxt (paginated)."""
    import ccxt

    ex = ccxt.binance({"enableRateLimit": True})
    symbol, timeframe = "BTC/USDT", "1d"
    since = ex.parse8601(f"{START_DATE}T00:00:00Z")
    limit = 1000
    rows: list[list] = []

    while True:
        batch = ex.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)
        if not batch:
            break
        rows += batch
        since = batch[-1][0] + 1
        if len(batch) < limit:
            break
        time.sleep(ex.rateLimit / 1000)

    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    df["date"] = pd.to_datetime(df["ts"], unit="ms").dt.normalize()
    df = df.drop(columns="ts").drop_duplicates("date").set_index("date").sort_index()
    return df


def fetch_btc_yf() -> pd.DataFrame:
    """Fallback: daily BTC-USD OHLCV from yfinance."""
    import yfinance as yf

    raw = yf.download("BTC-USD", start=START_DATE, auto_adjust=False, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    df = raw.rename(
        columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        }
    )[["open", "high", "low", "close", "volume"]]
    df.index = pd.to_datetime(df.index).normalize()
    df.index.name = "date"
    return df


def fetch_btc() -> pd.DataFrame:
    try:
        df = fetch_btc_ccxt()
        if len(df) < 100:
            raise ValueError("ccxt returned too few rows")
        print(f"[BTC] ccxt/Binance: {len(df)} rows "
              f"({df.index.min().date()} -> {df.index.max().date()})")
        return df
    except Exception as e:  # noqa: BLE001
        print(f"[BTC] ccxt failed ({e}); falling back to yfinance")
        df = fetch_btc_yf()
        print(f"[BTC] yfinance: {len(df)} rows "
              f"({df.index.min().date()} -> {df.index.max().date()})")
        return df


# ---------------------------------------------------------------------------
# 2. Technical indicators (pure-pandas, no TA-Lib dependency)
# ---------------------------------------------------------------------------
def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    # Wilder smoothing
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def bollinger(close: pd.Series, period: int = 20, n_std: float = 2.0):
    mid = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = mid + n_std * std
    lower = mid - n_std * std
    width = (upper - lower) / mid
    pctb = (close - lower) / (upper - lower)
    return mid, upper, lower, width, pctb


def atr_natr(high, low, close, period: int = 14):
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    natr = 100 * atr / close
    return atr, natr


def macd_ppo(close, fast=12, slow=26, signal=9):
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    macd_signal = macd.ewm(span=signal, adjust=False).mean()
    macd_hist = macd - macd_signal
    ppo = 100 * (ema_fast - ema_slow) / ema_slow
    ppo_signal = ppo.ewm(span=signal, adjust=False).mean()
    ppo_hist = ppo - ppo_signal
    return macd, macd_signal, macd_hist, ppo, ppo_signal, ppo_hist


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    c, h, l = df["close"], df["high"], df["low"]

    df["rsi_14"] = rsi(c, 14)

    bb_mid, bb_up, bb_lo, bb_w, bb_pctb = bollinger(c, 20, 2)
    df["bb_mid"] = bb_mid
    df["bb_upper"] = bb_up
    df["bb_lower"] = bb_lo
    df["bb_width"] = bb_w
    df["bb_pctb"] = bb_pctb

    atr, natr = atr_natr(h, l, c, 14)
    df["atr_14"] = atr
    df["natr_14"] = natr

    macd, macd_sig, macd_hist, ppo, ppo_sig, ppo_hist = macd_ppo(c, 12, 26, 9)
    df["macd"] = macd
    df["macd_signal"] = macd_sig
    df["macd_hist"] = macd_hist
    df["ppo"] = ppo
    df["ppo_signal"] = ppo_sig
    df["ppo_hist"] = ppo_hist

    # Historical (backward-looking) returns
    for h_ in (1, 5, 10, 21, 42, 63):
        df[f"ret_{h_}d"] = c.pct_change(h_)

    # Forward returns — PREDICTION TARGETS (shifted so row t knows only past)
    for f_ in (1, 5, 21):
        df[f"fwd_ret_{f_}d"] = c.shift(-f_) / c - 1

    return df


# ---------------------------------------------------------------------------
# 3. Macro from FRED (no API key — fredgraph.csv endpoint)
# ---------------------------------------------------------------------------
def fetch_fred(series_id: str, retries: int = 3) -> pd.Series:
    """Fetch a FRED series via fredgraph.csv.

    Shells out to curl rather than using requests/urllib3: FRED sits behind
    Akamai bot detection that stalls the urllib3 TLS fingerprint until the
    read times out, while curl's fingerprint passes through instantly.
    """
    import subprocess

    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    last_exc: Exception | None = None
    text = None
    for attempt in range(retries):
        try:
            proc = subprocess.run(
                ["curl", "-sS", "--max-time", "30", url],
                capture_output=True, text=True, check=True,
            )
            text = proc.stdout
            if text.strip():
                break
        except Exception as e:  # noqa: BLE001
            last_exc = e
        time.sleep(3 * (attempt + 1))
    else:
        raise last_exc or RuntimeError(f"empty response fetching {series_id}")
    df = pd.read_csv(io.StringIO(text))
    # Column names vary: usually ["DATE"/"observation_date", series_id]
    date_col = df.columns[0]
    val_col = df.columns[1]
    df[date_col] = pd.to_datetime(df[date_col])
    s = pd.to_numeric(df[val_col], errors="coerce")
    s.index = df[date_col].dt.normalize()
    s.name = series_id
    return s.dropna()


def fetch_macro() -> pd.DataFrame:
    ids = ["DTWEXBGS", "DFII10", "M2SL", "WALCL"]
    out = {}
    for sid in ids:
        try:
            out[sid] = fetch_fred(sid)
            print(f"[FRED] {sid}: {len(out[sid])} obs")
        except Exception as e:  # noqa: BLE001
            print(f"[FRED] {sid} failed: {e}")
    return pd.DataFrame(out)


# ---------------------------------------------------------------------------
# 4. Gold (yfinance GC=F)
# ---------------------------------------------------------------------------
def fetch_gold() -> pd.Series:
    import yfinance as yf

    raw = yf.download("GC=F", start=START_DATE, auto_adjust=False, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    s = pd.to_numeric(raw["Close"].squeeze(), errors="coerce")
    s.index = pd.to_datetime(s.index).normalize()
    s.name = "gold"
    print(f"[GOLD] GC=F: {s.dropna().shape[0]} obs")
    return s.dropna()


# ---------------------------------------------------------------------------
# 5. Crypto Fear & Greed Index (alternative.me)
# ---------------------------------------------------------------------------
def fetch_fear_greed() -> pd.Series:
    url = "https://api.alternative.me/fng/?limit=0&format=json"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    data = r.json()["data"]
    df = pd.DataFrame(data)
    df["date"] = pd.to_datetime(df["timestamp"].astype(int), unit="s").dt.normalize()
    s = pd.to_numeric(df["value"], errors="coerce")
    s.index = df["date"]
    s.name = "fear_greed"
    s = s.sort_index()
    print(f"[F&G] {s.dropna().shape[0]} obs "
          f"({s.index.min().date()} -> {s.index.max().date()})")
    return s.dropna()


# ---------------------------------------------------------------------------
# 6. BTC funding rates (Binance futures via ccxt)
# ---------------------------------------------------------------------------
def fetch_funding() -> pd.Series:
    """Perpetual funding rate history (paginated), aggregated to daily mean."""
    try:
        import ccxt

        ex = ccxt.binance({"enableRateLimit": True, "options": {"defaultType": "future"}})
        symbol = "BTC/USDT:USDT"
        since = ex.parse8601(f"{START_DATE}T00:00:00Z")
        limit = 1000
        rows: list[dict] = []

        while True:
            batch = ex.fetch_funding_rate_history(symbol, since=since, limit=limit)
            if not batch:
                break
            rows += batch
            since = batch[-1]["timestamp"] + 1
            if len(batch) < limit:
                break
            time.sleep(ex.rateLimit / 1000)

        if not rows:
            raise ValueError("no funding rows")

        fr = pd.DataFrame(
            {
                "date": [pd.to_datetime(x["timestamp"], unit="ms").normalize() for x in rows],
                "funding": [x["fundingRate"] for x in rows],
            }
        )
        s = fr.groupby("date")["funding"].mean()
        s.name = "funding_rate"
        print(f"[FUNDING] {s.shape[0]} daily obs "
              f"({s.index.min().date()} -> {s.index.max().date()})")
        return s
    except Exception as e:  # noqa: BLE001
        print(f"[FUNDING] failed: {e}")
        return pd.Series(dtype=float, name="funding_rate")


# ---------------------------------------------------------------------------
# Assemble
# ---------------------------------------------------------------------------
def main() -> None:
    btc = fetch_btc()
    btc = add_indicators(btc)

    macro = fetch_macro()
    gold = fetch_gold()
    fng = fetch_fear_greed()
    funding = fetch_funding()

    # BTC's daily calendar is the master index.
    cal = btc.index

    def align_ffill(obj) -> pd.DataFrame | pd.Series:
        """Reindex a lower-frequency series/frame onto BTC days, forward-filling.

        Forward-fill only: value at day t is the most recent *past* observation,
        so no future information leaks into the row.
        """
        return obj.reindex(cal.union(obj.index)).sort_index().ffill().reindex(cal)

    df = btc.copy()

    macro_aligned = align_ffill(macro)
    for col in macro_aligned.columns:
        df[col] = macro_aligned[col]

    df["gold"] = align_ffill(gold)
    df["btc_gold_ratio"] = df["close"] / df["gold"]

    df["fear_greed"] = align_ffill(fng)
    df["funding_rate"] = align_ffill(funding)

    df.index.name = "date"
    df.to_csv(OUTFILE)

    print(f"\n[DONE] {OUTFILE}: {df.shape[0]} rows x {df.shape[1]} cols")
    print(f"[DONE] range: {df.index.min().date()} -> {df.index.max().date()}")
    print(f"[DONE] columns: {list(df.columns)}")
    generated = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"[DONE] generated at {generated}")


if __name__ == "__main__":
    main()
