"""
All data-fetching logic lives here, isolated from the UI code in app.py.
Streamlit's @st.cache_data decorator means repeated runs within the TTL
window reuse cached results instead of re-hitting the APIs every time.
"""

import datetime as dt

import pandas as pd
import streamlit as st
import yfinance as yf
from fredapi import Fred


# ----------------------------------------------------------------------------
# FRED
# ----------------------------------------------------------------------------

@st.cache_data(ttl=60 * 60 * 6)
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
    {key: {"series": pd.Series, "label": str, "units": str}},
    applying yoy_pct transform where flagged.
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

@st.cache_data(ttl=60 * 15)
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
    Simple beta: cov(stock, benchmark) / var(benchmark), on overlapping dates.
    """
    aligned = pd.concat([stock_returns, benchmark_returns], axis=1).dropna()
    if len(aligned) < 20:
        return float("nan")
    cov = aligned.cov().iloc[0, 1]
    var = aligned.iloc[:, 1].var()
    return cov / var if var else float("nan")


# ----------------------------------------------------------------------------
# Core macro signal calculations
# ----------------------------------------------------------------------------

def compute_sahm_rule(unemployment: pd.Series) -> dict:
    """
    Sahm Rule: 3-month avg unemployment vs its 12-month low.
    Trigger at >= 0.50pp — historically coincides with early-stage recession.
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
    """Compare latest YoY inflation to a 2% target."""
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
    """Classify the 2s10s (or 3m10s) spread."""
    if spread is None or pd.isna(spread):
        return {"status": None, "label": None}
    if spread < 0:
        return {"status": "inverted", "label": "🔴 Inverted"}
    elif spread < 0.25:
        return {"status": "flat", "label": "🟡 Flat"}
    else:
        return {"status": "normal", "label": "🟢 Normal"}


def credit_spread_status(hy_oas_latest: float) -> dict:
    """
    Classify HY OAS into a stress regime.
      < 3.5%  : tight / complacent
      3.5-5%  : normal
      5-8%    : elevated
      > 8%    : crisis
    """
    if hy_oas_latest is None or pd.isna(hy_oas_latest):
        return {"status": None, "label": None}
    if hy_oas_latest > 8:
        return {"status": "crisis",   "label": "🔴 Credit: Crisis-Level"}
    elif hy_oas_latest > 5:
        return {"status": "elevated", "label": "🟠 Credit: Elevated"}
    elif hy_oas_latest > 3.5:
        return {"status": "normal",   "label": "🟡 Credit: Normal"}
    else:
        return {"status": "tight",    "label": "🟢 Credit: Tight"}


def classify_macro_regime(cfnai_latest: float, cpi_yoy_latest: float, target: float = 2.0) -> dict:
    """
    Simplified 2×2 macro regime framework:
                     Inflation > target    Inflation ≤ target
    CFNAI > 0        Reflation             Goldilocks
    CFNAI ≤ 0        Stagflation           Deflation / Recession Risk

    This uses growth LEVEL (CFNAI vs 0) and inflation LEVEL (vs 2%), not
    momentum — a useful first-pass lens, not a precise call.
    """
    if (cfnai_latest is None or pd.isna(cfnai_latest)
            or cpi_yoy_latest is None or pd.isna(cpi_yoy_latest)):
        return {"regime": None, "label": None, "description": None}

    growth_up     = cfnai_latest > 0
    inflation_up  = cpi_yoy_latest > target

    if growth_up and inflation_up:
        return {
            "regime": "reflation",
            "label": "🔥 Reflation",
            "description": "Above-trend growth with above-target inflation. Favors commodities, "
                           "cyclical equities, real assets; headwind for nominal bonds.",
        }
    elif growth_up and not inflation_up:
        return {
            "regime": "goldilocks",
            "label": "✨ Goldilocks",
            "description": "Above-trend growth with contained inflation — the most favorable "
                           "backdrop for risk assets broadly (equities especially).",
        }
    elif not growth_up and inflation_up:
        return {
            "regime": "stagflation",
            "label": "⚠️ Stagflation",
            "description": "Below-trend growth with above-target inflation — hardest regime for "
                           "both equities and nominal bonds; commodities and TIPS hold up better.",
        }
    else:
        return {
            "regime": "deflation_risk",
            "label": "🧊 Deflation / Recession Risk",
            "description": "Below-trend growth with contained or falling inflation. Historically "
                           "favors high-quality government bonds and defensive equity sectors.",
        }


def classify_eu_macro_regime(eu_hicp_latest: float, eu_unemployment_latest: float,
                              eu_unemployment_prev: float = None, target: float = 2.0) -> dict:
    """
    EU regime classifier using HICP vs 2% ECB target and unemployment direction.
    Unemployment direction acts as a growth proxy (rising = deteriorating).
    """
    if eu_hicp_latest is None or pd.isna(eu_hicp_latest):
        return {"regime": None, "label": None, "description": None}

    inflation_up = eu_hicp_latest > target
    # Use unemployment direction as growth proxy if available
    if eu_unemployment_latest is not None and eu_unemployment_prev is not None:
        growth_up = eu_unemployment_latest < eu_unemployment_prev
    else:
        growth_up = None  # unknown

    if growth_up is None:
        label = "🟡 Inflation Above Target" if inflation_up else "🟢 Inflation Near/Below Target"
        return {"regime": "partial", "label": label,
                "description": "Insufficient data for full EU regime classification."}

    if growth_up and inflation_up:
        return {"regime": "reflation", "label": "🔥 EU Reflation",
                "description": "Falling unemployment (growth improving) with above-target HICP."}
    elif growth_up and not inflation_up:
        return {"regime": "goldilocks", "label": "✨ EU Goldilocks",
                "description": "Falling unemployment with contained HICP — favorable for EU risk assets."}
    elif not growth_up and inflation_up:
        return {"regime": "stagflation", "label": "⚠️ EU Stagflation",
                "description": "Rising unemployment with above-target HICP — ECB in a difficult bind."}
    else:
        return {"regime": "deflation_risk", "label": "🧊 EU Recession Risk",
                "description": "Rising unemployment with below-target HICP — ECB likely to ease."}


# ----------------------------------------------------------------------------
# Advanced analytics
# ----------------------------------------------------------------------------

def compute_zscore(series: pd.Series) -> dict:
    """
    Z-score of the latest reading vs the full available history.
    Tells you how unusual the current level is relative to its own history.
    Returns {"value": latest, "zscore": z, "mean": mean, "std": std}.
    """
    if series is None or series.dropna().empty:
        return {"value": None, "zscore": None, "mean": None, "std": None}
    s = series.dropna()
    mean = s.mean()
    std  = s.std()
    latest = s.iloc[-1]
    zscore = (latest - mean) / std if std > 0 else 0.0
    return {"value": latest, "zscore": round(zscore, 2), "mean": mean, "std": std}


def zscore_label(z: float) -> str:
    """Human-readable label for a z-score."""
    if z is None or pd.isna(z):
        return ""
    if z > 2:   return "🔴 Extreme High"
    if z > 1:   return "🟠 High"
    if z > 0:   return "🟡 Above Avg"
    if z > -1:  return "🟢 Below Avg"
    if z > -2:  return "🔵 Low"
    return "🟣 Extreme Low"


def compute_real_fed_funds(ffr: pd.Series, core_pce: pd.Series) -> pd.Series:
    """Real FFR = nominal FFR minus core PCE YoY (monthly, aligned on index)."""
    if ffr is None or core_pce is None:
        return pd.Series(dtype=float)
    aligned = pd.concat([ffr.dropna(), core_pce.dropna()], axis=1).dropna()
    if aligned.empty:
        return pd.Series(dtype=float)
    result = aligned.iloc[:, 0] - aligned.iloc[:, 1]
    result.name = "Real Fed Funds Rate"
    return result


def compute_btp_bund_spread(it_10y: pd.Series, de_10y: pd.Series) -> pd.Series:
    """
    BTP-Bund spread: Italy 10Y minus Germany 10Y, in basis points.
    The key sovereign-risk barometer for the Euro Area — a proxy for
    fragmentation risk and ECB credibility.
    """
    if it_10y is None or de_10y is None:
        return pd.Series(dtype=float)
    aligned = pd.concat([it_10y.dropna(), de_10y.dropna()], axis=1).dropna()
    if aligned.empty:
        return pd.Series(dtype=float)
    spread_bps = (aligned.iloc[:, 0] - aligned.iloc[:, 1]) * 100
    spread_bps.name = "BTP-Bund Spread (bps)"
    return spread_bps


def btp_bund_status(spread_bps: float) -> dict:
    """
    Classify the BTP-Bund spread:
      < 100 bps : calm / tight
      100-150   : normal
      150-250   : elevated
      > 250     : stress / fragmentation risk
    """
    if spread_bps is None or pd.isna(spread_bps):
        return {"status": None, "label": None}
    if spread_bps > 250:
        return {"status": "stress",    "label": "🔴 BTP-Bund: Fragmentation Risk"}
    elif spread_bps > 150:
        return {"status": "elevated",  "label": "🟠 BTP-Bund: Elevated"}
    elif spread_bps > 100:
        return {"status": "normal",    "label": "🟡 BTP-Bund: Normal"}
    else:
        return {"status": "tight",     "label": "🟢 BTP-Bund: Tight"}


def compute_recession_probability(
    spread_2s10s: float,
    spread_3m10s: float,
    sahm_value: float,
    hy_oas: float,
    cfnai: float,
) -> dict:
    """
    Composite US recession probability score (0-100), weighted across five
    commonly-used leading indicators. Not a formal model — a weighted
    rule-of-thumb dashboard signal.

    Weights: 3m10s spread (30%), 2s10s spread (20%), Sahm Rule (25%),
             HY OAS (15%), CFNAI (10%).
    """
    score = 0.0
    weight_used = 0.0

    # 3m10y spread — the classic Fed recession predictor
    if spread_3m10s is not None and pd.notna(spread_3m10s):
        w = 30
        weight_used += w
        if spread_3m10s < -1.0:   score += w
        elif spread_3m10s < -0.5: score += w * 0.75
        elif spread_3m10s < 0:    score += w * 0.50
        elif spread_3m10s < 0.25: score += w * 0.20

    # 2s10s spread
    if spread_2s10s is not None and pd.notna(spread_2s10s):
        w = 20
        weight_used += w
        if spread_2s10s < -0.5:   score += w
        elif spread_2s10s < 0:    score += w * 0.65
        elif spread_2s10s < 0.25: score += w * 0.20

    # Sahm Rule
    if sahm_value is not None and pd.notna(sahm_value):
        w = 25
        weight_used += w
        if sahm_value >= 0.50:    score += w
        elif sahm_value >= 0.30:  score += w * 0.60
        elif sahm_value >= 0.20:  score += w * 0.30
        elif sahm_value >= 0.10:  score += w * 0.10

    # HY OAS
    if hy_oas is not None and pd.notna(hy_oas):
        w = 15
        weight_used += w
        if hy_oas > 8:            score += w
        elif hy_oas > 5:          score += w * 0.70
        elif hy_oas > 4:          score += w * 0.40
        elif hy_oas > 3.5:        score += w * 0.15

    # CFNAI
    if cfnai is not None and pd.notna(cfnai):
        w = 10
        weight_used += w
        if cfnai < -0.70:         score += w
        elif cfnai < -0.35:       score += w * 0.60
        elif cfnai < 0:           score += w * 0.25

    if weight_used == 0:
        return {"probability": None, "label": None}

    prob = round((score / weight_used) * 100)

    if prob >= 70:    label = "🔴 High"
    elif prob >= 40:  label = "🟠 Elevated"
    elif prob >= 20:  label = "🟡 Low-to-Moderate"
    else:             label = "🟢 Low"

    return {"probability": prob, "label": label}


def compute_correlation_matrix(price_data: dict, tickers: list, window_days: int = 60) -> pd.DataFrame:
    """
    Rolling-window correlation matrix of daily returns across the given tickers.
    Uses the most recent `window_days` trading days, standard for a current-regime read.
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
    return recent.corr()


def series_trend(series: pd.Series, periods: int = 3) -> float | None:
    """Change in the series over the last `periods` observations (MoM or QoQ delta)."""
    s = series.dropna() if series is not None else pd.Series(dtype=float)
    if len(s) < periods + 1:
        return None
    return s.iloc[-1] - s.iloc[-(periods + 1)]
