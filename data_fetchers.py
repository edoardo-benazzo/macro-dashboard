"""
All data-fetching logic lives here, isolated from the UI code in app.py.
"""

import concurrent.futures
import datetime as dt
import math

import pandas as pd
import requests
import streamlit as st
import yfinance as yf
from fredapi import Fred


# ── FRED (macro data — monthly/weekly releases, 6h cache is sufficient) ──────

@st.cache_data(ttl=60 * 60 * 6)
def get_fred_series(series_id: str, api_key: str, start: str = "2000-01-01") -> pd.Series:
    fred = Fred(api_key=api_key)
    data = fred.get_series(series_id, observation_start=start)
    data.name = series_id
    return data


def yoy_pct_change(series: pd.Series) -> pd.Series:
    return series.pct_change(periods=12) * 100


@st.cache_data(ttl=60 * 60 * 6)
def load_all_fred(fred_config: dict, api_key: str, start: str) -> dict:
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


# ── Yahoo Finance (market prices — 25-second cache for auto-refresh) ──────────

@st.cache_data(ttl=25)
def get_yahoo_history(ticker: str, period: str = "5y") -> pd.DataFrame:
    df = yf.Ticker(ticker).history(period=period)
    return df


@st.cache_data(ttl=25)
def load_all_markets(tickers: dict, period: str = "5y") -> dict:
    results = {}
    for ticker, label in tickers.items():
        try:
            df = get_yahoo_history(ticker, period=period)
            results[ticker] = {"df": df, "label": label, "error": None}
        except Exception as e:
            results[ticker] = {"df": None, "label": label, "error": str(e)}
    return results


def latest_snapshot(df: pd.DataFrame):
    if df is None or df.empty or len(df) < 2:
        return None
    try:
        _close = df["Close"].squeeze().dropna()
        last = float(_close.values[-1])
        prev = float(_close.values[-2]) if len(_close) >= 2 else None
        if prev is None or not math.isfinite(last) or not math.isfinite(prev):
            return None
        change_abs = last - prev
        change_pct = (change_abs / prev) * 100 if prev else None
        if change_pct is not None and (math.isnan(change_pct) or math.isinf(change_pct)):
            change_pct = None
        last_date = df.index[-1].date()
        return last, change_abs, change_pct, last_date
    except Exception:
        return None


def compute_beta(stock_returns, benchmark_returns):
    try:
        aligned = pd.concat([stock_returns, benchmark_returns], axis=1).dropna()
        if len(aligned) < 20:
            return None
        cov = aligned.cov().iloc[0, 1]
        var = aligned.iloc[:, 1].var()
        if not var or var == 0:
            return None
        return float(cov / var)
    except Exception:
        return None


# ── Core macro signal calculations ────────────────────────────────────────────

def compute_sahm_rule(unemployment: pd.Series) -> dict:
    if unemployment is None or unemployment.dropna().empty:
        return {"value": None, "triggered": None, "series": None}
    u = unemployment.dropna()
    three_mo_avg   = u.rolling(window=3).mean()
    twelve_mo_min  = three_mo_avg.rolling(window=12).min()
    sahm_indicator = three_mo_avg - twelve_mo_min
    current_value  = sahm_indicator.iloc[-1] if not sahm_indicator.dropna().empty else None
    triggered = (current_value >= 0.50) if current_value is not None and pd.notna(current_value) else None
    return {"value": current_value, "triggered": triggered, "series": sahm_indicator}


def cpi_vs_target(cpi_yoy_latest: float, target: float = 2.0) -> dict:
    if cpi_yoy_latest is None or pd.isna(cpi_yoy_latest):
        return {"gap": None, "status": None}
    gap = cpi_yoy_latest - target
    if gap > 1.0:    status = "well above target"
    elif gap > 0.2:  status = "above target"
    elif gap < -0.2: status = "below target"
    else:            status = "at target"
    return {"gap": gap, "status": status}


def yield_curve_status(spread: float) -> dict:
    if spread is None or pd.isna(spread):
        return {"status": None, "label": None}
    if spread < 0:       return {"status": "inverted", "label": "Inverted"}
    elif spread < 0.25:  return {"status": "flat",     "label": "Flat"}
    else:                return {"status": "normal",   "label": "Normal"}


def credit_spread_status(hy_oas_latest: float) -> dict:
    if hy_oas_latest is None or pd.isna(hy_oas_latest):
        return {"status": None, "label": None}
    if hy_oas_latest > 8:    return {"status": "crisis",   "label": "Crisis-Level"}
    elif hy_oas_latest > 5:  return {"status": "elevated", "label": "Elevated"}
    elif hy_oas_latest > 3.5:return {"status": "normal",   "label": "Normal"}
    else:                    return {"status": "tight",    "label": "Tight"}


def classify_macro_regime(cfnai_latest: float, cpi_yoy_latest: float,
                           target: float = 2.0) -> dict:
    if (cfnai_latest is None or pd.isna(cfnai_latest)
            or cpi_yoy_latest is None or pd.isna(cpi_yoy_latest)):
        return {"regime": None, "label": None, "description": None}
    growth_up    = cfnai_latest > 0
    inflation_up = cpi_yoy_latest > target
    if growth_up and inflation_up:
        return {"regime": "reflation",
                "label": "Reflation",
                "description": "Above-trend growth with above-target inflation. "
                               "Favours commodities, cyclical equities, real assets; "
                               "headwind for nominal bonds."}
    elif growth_up and not inflation_up:
        return {"regime": "goldilocks",
                "label": "Goldilocks",
                "description": "Above-trend growth with contained inflation — "
                               "the most favourable backdrop for risk assets broadly."}
    elif not growth_up and inflation_up:
        return {"regime": "stagflation",
                "label": "Stagflation",
                "description": "Below-trend growth with above-target inflation — "
                               "hardest regime for both equities and nominal bonds."}
    else:
        return {"regime": "deflation_risk",
                "label": "Deflation / Recession Risk",
                "description": "Below-trend growth with contained or falling inflation. "
                               "Historically favours high-quality government bonds and defensive sectors."}


def classify_eu_macro_regime(eu_hicp_latest: float, eu_unemployment_latest: float,
                              eu_unemployment_prev: float = None, target: float = 2.0) -> dict:
    if eu_hicp_latest is None or pd.isna(eu_hicp_latest):
        return {"regime": None, "label": None, "description": None}
    inflation_up = eu_hicp_latest > target
    if eu_unemployment_latest is not None and eu_unemployment_prev is not None:
        growth_up = eu_unemployment_latest < eu_unemployment_prev
    else:
        growth_up = None
    if growth_up is None:
        label = "Inflation Above Target" if inflation_up else "Inflation Near/Below Target"
        return {"regime": "partial", "label": label,
                "description": "Insufficient data for full EU regime classification."}
    if growth_up and inflation_up:
        return {"regime": "reflation",     "label": "EU Reflation",
                "description": "Falling unemployment (improving growth) with above-target HICP."}
    elif growth_up and not inflation_up:
        return {"regime": "goldilocks",    "label": "EU Goldilocks",
                "description": "Falling unemployment with contained HICP — favourable for EU risk assets."}
    elif not growth_up and inflation_up:
        return {"regime": "stagflation",   "label": "EU Stagflation",
                "description": "Rising unemployment with above-target HICP — ECB in a difficult bind."}
    else:
        return {"regime": "deflation_risk","label": "EU Recession Risk",
                "description": "Rising unemployment with below-target HICP — ECB likely to ease."}


# ── Advanced analytics ────────────────────────────────────────────────────────

def compute_zscore(series: pd.Series) -> dict:
    if series is None or series.dropna().empty:
        return {"value": None, "zscore": None, "mean": None, "std": None}
    s      = series.dropna()
    mean   = s.mean()
    std    = s.std()
    latest = s.iloc[-1]
    zscore = (latest - mean) / std if std > 0 else 0.0
    return {"value": latest, "zscore": round(zscore, 2), "mean": mean, "std": std}


def zscore_label(z: float) -> str:
    if z is None or pd.isna(z): return ""
    if z > 2:  return "Extreme High"
    if z > 1:  return "High"
    if z > 0:  return "Above Avg"
    if z > -1: return "Below Avg"
    if z > -2: return "Low"
    return "Extreme Low"


def compute_real_fed_funds(ffr: pd.Series, core_pce: pd.Series) -> pd.Series:
    if ffr is None or core_pce is None:
        return pd.Series(dtype=float)
    aligned = pd.concat([ffr.dropna(), core_pce.dropna()], axis=1).dropna()
    if aligned.empty:
        return pd.Series(dtype=float)
    result = aligned.iloc[:, 0] - aligned.iloc[:, 1]
    result.name = "Real Fed Funds Rate"
    return result


def compute_btp_bund_spread(it_10y: pd.Series, de_10y: pd.Series) -> pd.Series:
    if it_10y is None or de_10y is None:
        return pd.Series(dtype=float)
    aligned = pd.concat([it_10y.dropna(), de_10y.dropna()], axis=1).dropna()
    if aligned.empty:
        return pd.Series(dtype=float)
    spread_bps = (aligned.iloc[:, 0] - aligned.iloc[:, 1]) * 100
    spread_bps.name = "BTP-Bund Spread (bps)"
    return spread_bps


def btp_bund_status(spread_bps: float) -> dict:
    if spread_bps is None or pd.isna(spread_bps):
        return {"status": None, "label": None}
    if spread_bps > 250:   return {"status": "stress",   "label": "Fragmentation Risk"}
    elif spread_bps > 150: return {"status": "elevated", "label": "Elevated"}
    elif spread_bps > 100: return {"status": "normal",   "label": "Normal"}
    else:                  return {"status": "tight",    "label": "Tight"}


_NEUTRAL_RATE = 2.5  # standard long-run neutral Fed Funds assumption


def compute_recession_probability(
    spread_2s10s: float, spread_3m10s: float,
    sahm_value: float, hy_oas: float, cfnai: float,
    fed_funds: float = None,
) -> dict:
    """
    Multi-factor composite recession probability (0-100).
    Each signal scored 0-100, then weighted average.
      3M10Y spread  25% · Sahm Rule  25% · 2S10S  20%
      HY OAS        15% · CFNAI      10% · FFR vs neutral  5%
    """
    signals: list[tuple[int, float]] = []  # (weight, score 0-100)

    if spread_3m10s is not None and pd.notna(spread_3m10s):
        s = 100 if spread_3m10s < 0 else 50 if spread_3m10s <= 0.5 else 0
        signals.append((25, s))

    if sahm_value is not None and pd.notna(sahm_value):
        s = 100 if sahm_value > 0.5 else 60 if sahm_value >= 0.3 else 0
        signals.append((25, s))

    if spread_2s10s is not None and pd.notna(spread_2s10s):
        s = 80 if spread_2s10s < 0 else 40 if spread_2s10s <= 0.25 else 0
        signals.append((20, s))

    if hy_oas is not None and pd.notna(hy_oas):
        s = (100 if hy_oas > 8 else 70 if hy_oas > 5
             else 30 if hy_oas > 3.5 else 0)
        signals.append((15, s))

    if cfnai is not None and pd.notna(cfnai):
        s = 100 if cfnai < -0.7 else 50 if cfnai < 0 else 0
        signals.append((10, s))

    if fed_funds is not None and pd.notna(fed_funds):
        excess = fed_funds - _NEUTRAL_RATE
        s = 80 if excess > 2.0 else 40 if excess > 1.0 else 0
        signals.append((5, s))

    if not signals:
        return {"probability": None, "label": None}

    total_w = sum(w for w, _ in signals)
    prob = round(sum(w * s for w, s in signals) / total_w)

    if prob >= 80:   label = "Very High"
    elif prob >= 60: label = "High"
    elif prob >= 40: label = "Moderate"
    elif prob >= 20: label = "Elevated"
    else:            label = "Low"

    return {"probability": prob, "label": label}


def compute_positioning_implication(
    regime: dict, rec_prob: int | None,
    sp2s10s: float, sp3m10s: float,
    hy_oas: float, real_10y: float,
    vix: float, fed_funds: float,
) -> list[dict]:
    """Rule-based positioning table derived from real-time signals."""
    rp = rec_prob or 0
    rname = regime.get("regime", "") or ""
    rlabel = regime.get("label", "") or ""

    def _row(asset, signal, rationale):
        return {"asset": asset, "signal": signal, "rationale": rationale}

    rows = []

    # Equities
    if rp >= 60 or rname == "stagflation":
        rows.append(_row("Equities", "Bearish",
                         f"{rlabel} + recession risk {rp}% — defensive positioning"))
    elif rp >= 40 or rname == "reflation":
        rows.append(_row("Equities", "Cautious",
                         f"{rlabel} — elevated rates headwind, selective"))
    elif rname == "goldilocks" and rp < 20:
        rows.append(_row("Equities", "Bullish",
                         "Goldilocks backdrop — above-trend growth, contained inflation"))
    else:
        rows.append(_row("Equities", "Neutral", "Mixed signals — favour quality/defensive"))

    # Gov Bonds
    if sp3m10s is not None and sp3m10s < 0 and rp >= 40:
        rows.append(_row("Gov Bonds (US)", "Bullish",
                         f"Curve inverted ({sp3m10s:.2f}%) + recession risk — duration as hedge"))
    elif sp2s10s is not None and sp2s10s < 0:
        rows.append(_row("Gov Bonds (US)", "Cautious",
                         f"Curve inverted ({sp2s10s:.2f}%) — recession hedge but rate risk"))
    else:
        rows.append(_row("Gov Bonds (US)", "Neutral",
                         "Curve near flat — limited directional edge in duration"))

    # Credit
    if hy_oas is not None and hy_oas > 5:
        rows.append(_row("Credit (HY)", "Bearish",
                         f"HY OAS {hy_oas:.2f}% — spreads elevated, default risk rising"))
    elif hy_oas is not None and hy_oas < 3.5:
        rows.append(_row("Credit (HY)", "Cautious",
                         f"HY OAS {hy_oas:.2f}% — spreads tight, asymmetric downside"))
    else:
        rows.append(_row("Credit (HY)", "Neutral", "Spreads within normal range"))

    # Gold
    if real_10y is not None and real_10y < 0:
        rows.append(_row("Gold", "Bullish",
                         f"Negative real yields ({real_10y:.2f}%) support gold"))
    elif real_10y is not None and real_10y > 2.0:
        rows.append(_row("Gold", "Bearish",
                         f"High real yields ({real_10y:.2f}%) compete with gold"))
    elif rp >= 40:
        rows.append(_row("Gold", "Bullish",
                         f"Recession risk {rp}% — safe-haven bid"))
    else:
        rows.append(_row("Gold", "Neutral", "Real yields near neutral — no strong edge"))

    # Oil
    if rname == "stagflation":
        rows.append(_row("Oil", "Cautious",
                         "Stagflation — supply constrained but demand destruction risk"))
    elif rname == "reflation":
        rows.append(_row("Oil", "Bullish",
                         "Above-trend growth drives commodity/energy demand"))
    elif rp >= 50:
        rows.append(_row("Oil", "Bearish",
                         f"Recession risk {rp}% — demand destruction likely"))
    else:
        rows.append(_row("Oil", "Neutral", "Balanced supply/demand — range-bound"))

    # USD
    if fed_funds is not None and fed_funds > 4.0 and rp < 40:
        rows.append(_row("USD (DXY)", "Bullish",
                         f"High Fed Funds ({fed_funds:.2f}%) — rate differential supportive"))
    elif rp >= 60:
        rows.append(_row("USD (DXY)", "Neutral",
                         "Recession risk — safe-haven bid offset by rate cut pricing"))
    else:
        rows.append(_row("USD (DXY)", "Neutral",
                         "Rate differential supportive, balanced vs growth concerns"))

    # EM Assets
    if fed_funds is not None and fed_funds > 4.5:
        rows.append(_row("EM Assets", "Cautious",
                         f"Strong USD + high US rates ({fed_funds:.2f}%) = EM headwind"))
    elif rp >= 50:
        rows.append(_row("EM Assets", "Bearish",
                         f"Recession risk {rp}% — risk-off, EM capital outflows"))
    elif rname == "goldilocks":
        rows.append(_row("EM Assets", "Bullish",
                         "Goldilocks + contained USD = EM outperformance window"))
    else:
        rows.append(_row("EM Assets", "Cautious", "Selective — country-specific risk"))

    return rows


def compute_policy_tracker(
    fed_funds: float, us_2y: float,
    ecb_rate: float, eu_2y: float,
) -> dict:
    """
    Infer Fed/ECB next-move direction from 2Y yield vs policy rate.
    Positive spread → market pricing hike; negative → pricing cut.
    """
    fed_spread = (us_2y - fed_funds) if (us_2y is not None and fed_funds is not None) else None
    if fed_spread is not None:
        fed_dir = "CUTS" if fed_spread < -0.25 else "HIKES" if fed_spread > 0.25 else "HOLD"
    else:
        fed_dir = None

    ecb_spread = (eu_2y - ecb_rate) if (eu_2y is not None and ecb_rate is not None) else None
    if ecb_spread is not None:
        ecb_dir = "CUTS" if ecb_spread < -0.25 else "HIKES" if ecb_spread > 0.25 else "HOLD"
    else:
        ecb_dir = None

    return {
        "fed_funds":    fed_funds,
        "fed_spread":   fed_spread,
        "fed_direction": fed_dir,
        "ecb_rate":     ecb_rate,
        "ecb_spread":   ecb_spread,
        "ecb_direction": ecb_dir,
    }


def compute_correlation_matrix(price_data: dict, tickers: list,
                                window_days: int = 60) -> pd.DataFrame:
    returns = {}
    for ticker in tickers:
        df = price_data.get(ticker, {}).get("df")
        if df is not None and not df.empty and "Close" in df.columns:
            returns[ticker] = df["Close"].pct_change()
    if len(returns) < 2:
        return pd.DataFrame()
    returns_df = pd.DataFrame(returns).dropna(how="all")
    return returns_df.tail(window_days).corr()


def series_trend(series: pd.Series, periods: int = 3) -> float | None:
    s = series.dropna() if series is not None else pd.Series(dtype=float)
    if len(s) < periods + 1:
        return None
    return s.iloc[-1] - s.iloc[-(periods + 1)]


# ── Earnings calendar ─────────────────────────────────────────────────────────

_EARNINGS_TICKERS = [
    # Mega-cap tech
    "NVDA", "AAPL", "MSFT", "AMZN", "GOOGL", "META", "TSLA",
    # Financials
    "JPM", "BAC", "GS", "MS", "BLK",
    # Semiconductors
    "AMD", "INTC", "AVGO", "MU", "TSM", "ASML",
    "QCOM", "TXN", "AMAT", "LRCX", "KLAC", "MRVL", "ARM", "SMCI",
    # Energy
    "XOM", "CVX",
    # Healthcare
    "LLY",
    # Payments
    "V", "MA",
    # Consumer / retail
    "WMT", "COST", "HD", "TGT",
    # Media / streaming / platforms
    "DIS", "NFLX", "UBER", "SHOP", "PLTR",
]


def _fetch_one_earnings(ticker: str, today: dt.date) -> dict | None:
    try:
        t = yf.Ticker(ticker)
        info: dict = {}
        earn_date: dt.date | None = None

        # Fetch info once (covers methods 1, 2, and EPS)
        try:
            info = t.info or {}
        except Exception:
            pass

        # Method 1: calendar dict
        try:
            cal = t.calendar
            if cal is not None:
                if hasattr(cal, "to_dict"):
                    cal = cal.to_dict()
                if isinstance(cal, dict):
                    raw_dates = cal.get("Earnings Date", [])
                    if raw_dates:
                        dates_list = (
                            list(raw_dates)
                            if hasattr(raw_dates, "__iter__") and not isinstance(raw_dates, str)
                            else [raw_dates]
                        )
                        raw = dates_list[0]
                        if hasattr(raw, "date"):
                            earn_date = raw.date()
                        elif isinstance(raw, str):
                            earn_date = dt.date.fromisoformat(str(raw)[:10])
        except Exception:
            pass

        # Method 2: info dict keys
        if earn_date is None:
            for key in ("earningsDate", "earningsTimestamp"):
                raw = info.get(key)
                if raw is None:
                    continue
                try:
                    if isinstance(raw, (int, float)):
                        earn_date = dt.date.fromtimestamp(raw)
                    elif hasattr(raw, "date"):
                        earn_date = raw.date()
                    elif isinstance(raw, str):
                        earn_date = dt.date.fromisoformat(str(raw)[:10])
                    if earn_date:
                        break
                except Exception:
                    pass

        # Method 3: earnings_dates DataFrame
        if earn_date is None:
            try:
                ed_df = t.earnings_dates
                if ed_df is not None and not ed_df.empty:
                    future = [d.date() for d in ed_df.index if d.date() >= today]
                    if future:
                        earn_date = min(future)
            except Exception:
                pass

        if earn_date is None:
            return None

        return {
            "ticker":    ticker,
            "name":      info.get("shortName", ticker) or ticker,
            "date":      earn_date,
            "days":      (earn_date - today).days,
            "eps_est":   info.get("forwardEps"),
            "eps_last":  info.get("trailingEps"),
        }
    except Exception:
        return None


@st.cache_data(ttl=60 * 60 * 6)
def get_earnings_calendar() -> list[dict]:
    """Return upcoming earnings for watched tickers, sorted by days until."""
    today = dt.date.today()
    result: list[dict] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        futures = {ex.submit(_fetch_one_earnings, t, today): t for t in _EARNINGS_TICKERS}
        for fut in concurrent.futures.as_completed(futures, timeout=90):
            try:
                r = fut.result()
                if r is not None:
                    result.append(r)
            except Exception:
                pass

    result.sort(key=lambda x: x["days"])
    return result


# ── Module 1: Market-implied forward signals ──────────────────────────────────

def _trend_label(series: pd.Series, periods: int = 4) -> str:
    """Rising / Falling / Stable based on change over last `periods` obs."""
    if series is None or series.dropna().empty:
        return "—"
    s = series.dropna()
    if len(s) < periods + 1:
        return "—"
    chg = s.iloc[-1] - s.iloc[-periods - 1]
    if chg > 0.05:  return "Rising ↑"
    if chg < -0.05: return "Falling ↓"
    return "Stable →"


def _chg_label(val: float | None, period: str) -> str:
    if val is None or pd.isna(val):
        return "—"
    sign = "+" if val >= 0 else ""
    return f"{sign}{val:.2f}pp ({period})"


def compute_inflation_expectations(fred_data: dict) -> dict:
    """
    Module 1: Summarise inflation expectations signals.
    Returns dict with current values, trend labels, 1w/1m changes, interpretation.
    """
    FED_TARGET = 2.0

    def _extract(key: str):
        entry = fred_data.get(key, {})
        s = entry.get("series")
        if s is None or s.dropna().empty:
            return None, None
        s = s.dropna()
        return s, s.iloc[-1]

    be10_s, be10 = _extract("breakeven_10y")
    be5_s,  be5  = _extract("breakeven_5y")
    be55_s, be55 = _extract("breakeven_5y5y")

    def _w_chg(s: pd.Series | None) -> float | None:
        if s is None or len(s) < 2: return None
        return round(s.iloc[-1] - s.iloc[-2], 3)

    def _m_chg(s: pd.Series | None) -> float | None:
        if s is None or len(s) < 5: return None
        return round(s.iloc[-1] - s.iloc[-5], 3)

    gap10 = round(be10 - FED_TARGET, 2) if be10 is not None else None

    # Auto-generated interpretation
    interp_parts = []
    if be10 is not None:
        dir_w = _w_chg(be10_s)
        trend = "rising" if (dir_w or 0) > 0 else "falling" if (dir_w or 0) < 0 else "stable"
        above = "above" if be10 > FED_TARGET else "below"
        interp_parts.append(
            f"The bond market is pricing {be10:.2f}% average inflation over 10 years — "
            f"{above} the Fed's 2% target and {trend} over the past week, "
            f"suggesting markets are becoming {'less' if trend == 'falling' else 'more'} "
            f"confident inflation {'remains' if above == 'above' else 'returns to'} target."
        )
    if be55 is not None:
        anchor = "well-anchored" if be55 < 2.3 else "drifting higher" if be55 < 2.7 else "unanchored"
        interp_parts.append(
            f"The 5Y5Y forward rate ({be55:.2f}%) measures what markets expect inflation to average "
            f"from 5 to 10 years out — currently {anchor}. "
            f"This is the Fed's credibility gauge: persistently above 2.5% signals loss of trust."
        )

    return {
        "be10":       be10,   "be10_s":  be10_s,
        "be5":        be5,    "be5_s":   be5_s,
        "be55":       be55,   "be55_s":  be55_s,
        "gap10":      gap10,
        "be10_trend": _trend_label(be10_s),
        "be5_trend":  _trend_label(be5_s),
        "be55_trend": _trend_label(be55_s),
        "be10_wchg":  _w_chg(be10_s),
        "be10_mchg":  _m_chg(be10_s),
        "be5_wchg":   _w_chg(be5_s),
        "be5_mchg":   _m_chg(be5_s),
        "be55_wchg":  _w_chg(be55_s),
        "be55_mchg":  _m_chg(be55_s),
        "interpretation": " ".join(interp_parts) if interp_parts else None,
    }


def compute_forward_rate_curve(fred_data: dict) -> dict:
    """Module 1: Forward rate curve vs current yields."""
    def _latest_val(key: str) -> float | None:
        entry = fred_data.get(key, {})
        s = entry.get("series")
        if s is None or s.dropna().empty: return None
        return s.dropna().iloc[-1]

    y2   = _latest_val("2y_yield")
    y10  = _latest_val("10y_yield")
    f2y2 = _latest_val("fwd_rate_2y2y")
    f3y2 = _latest_val("fwd_rate_3y2y")

    interp = None
    if f2y2 is not None and y2 is not None:
        diff = f2y2 - y2
        if diff < -0.25:
            interp = (
                f"The forward curve implies the 2Y rate will fall from {y2:.2f}% to ~{f2y2:.2f}% "
                f"over the next 2 years ({diff:+.2f}pp), suggesting the market is pricing meaningful "
                f"rate cuts ahead — consistent with easing cycle expectations."
            )
        elif diff > 0.25:
            interp = (
                f"Forward rates imply the 2Y rate will rise from {y2:.2f}% to ~{f2y2:.2f}% "
                f"over 2 years ({diff:+.2f}pp) — the market is not pricing cuts, "
                f"suggesting a higher-for-longer expectation."
            )
        else:
            interp = (
                f"Forward rates ({f2y2:.2f}%) are roughly flat vs the current 2Y ({y2:.2f}%), "
                f"suggesting the market expects rates to stay near current levels for 2+ years."
            )

    return {
        "y2": y2, "y10": y10, "fwd_2y2": f2y2, "fwd_3y2": f3y2,
        "interpretation": interp,
    }


# ── Module 2: CFTC Commitment of Traders ──────────────────────────────────────

_COT_ASSETS = {
    "EUR/USD":   "EURO FX",
    "10Y Notes": "10-YEAR U.S. TREASURY NOTES",
    "Gold":      "GOLD",
    "Crude Oil": "CRUDE OIL, LIGHT SWEET",
    "S&P 500":   "S&P 500 CONSOLIDATED",
}

_COT_URL = "https://publicreporting.cftc.gov/resource/6dca-aqww.json"


@st.cache_data(ttl=60 * 60 * 24)
def fetch_cot_data() -> dict:
    """
    CFTC Commitment of Traders — net speculative (non-commercial) positions.
    Source: CFTC public Socrata API. Updates weekly (Tuesday release).
    """
    results = {}
    for label, mkt_substr in _COT_ASSETS.items():
        try:
            r = requests.get(
                _COT_URL,
                params={
                    "$limit": 104,
                    "$order": "report_date_as_yyyy_mm_dd DESC",
                    "$where": f"market_and_exchange_names like '%{mkt_substr}%'",
                    "$select": ("report_date_as_yyyy_mm_dd,"
                                "noncomm_positions_long_all,"
                                "noncomm_positions_short_all,"
                                "open_interest_all"),
                },
                headers={"User-Agent": "MacroDashboard/2.0"},
                timeout=20,
            )
            r.raise_for_status()
            rows = r.json()
            if not rows:
                results[label] = {"error": "No data returned"}
                continue

            dates, longs, shorts, ois = [], [], [], []
            for row in rows:
                try:
                    d   = pd.to_datetime(row["report_date_as_yyyy_mm_dd"])
                    lng = int(float(row.get("noncomm_positions_long_all")  or 0))
                    sht = int(float(row.get("noncomm_positions_short_all") or 0))
                    oi  = int(float(row.get("open_interest_all")           or 0))
                    dates.append(d); longs.append(lng)
                    shorts.append(sht); ois.append(oi)
                except (ValueError, TypeError, KeyError):
                    continue

            if not dates:
                results[label] = {"error": "Could not parse rows"}
                continue

            df = pd.DataFrame({"long": longs, "short": shorts, "oi": ois},
                              index=dates).sort_index()
            df["net"] = df["long"] - df["short"]

            net_now = int(df["net"].iloc[-1])
            window  = df["net"].iloc[-52:] if len(df) >= 52 else df["net"]
            pct_rank = round((window < net_now).sum() / len(window) * 100)

            results[label] = {
                "net":        net_now,
                "net_series": df["net"],
                "long":       int(df["long"].iloc[-1]),
                "short":      int(df["short"].iloc[-1]),
                "oi":         int(df["oi"].iloc[-1]) if df["oi"].iloc[-1] else None,
                "pct_rank":   pct_rank,
                "date":       df.index[-1].date().isoformat(),
            }
        except Exception as e:
            results[label] = {"error": str(e)}
    return results


def compute_cot_signals(cot_data: dict) -> list[dict]:
    """Module 2: Add crowding signal to each COT asset."""
    out = []
    for label, d in cot_data.items():
        if "error" in d:
            out.append({"label": label, "error": d["error"]})
            continue
        p = d["pct_rank"]
        if p >= 80:
            signal, sig_color = "Crowded Long 🔴", "#FF4757"
        elif p <= 20:
            signal, sig_color = "Crowded Short 🔴", "#FF4757"
        else:
            signal, sig_color = "Neutral 🟢", "#00C896"
        out.append({
            "label": label,
            "net": d["net"],
            "long": d["long"],
            "short": d["short"],
            "pct_rank": p,
            "signal": signal,
            "sig_color": sig_color,
            "net_series": d.get("net_series"),
            "date": d.get("date"),
        })
    return out


# ── Module 3: Cross-Asset Divergence Scanner ──────────────────────────────────

def compute_divergence_scanner(
    market_data: dict,
    fred_data: dict,
) -> list[dict]:
    """
    Scan for cross-asset divergences using 1-month changes.
    market_data: dict from load_all_markets
    fred_data: dict from load_all_fred
    Returns list of divergence signals.
    """

    def _mkt_chg_pct(ticker: str, days: int = 21) -> float | None:
        df = (market_data.get(ticker) or {}).get("df")
        if df is None or df.empty or len(df) < days + 1:
            return None
        c = df["Close"].dropna()
        if len(c) < days + 1:
            return None
        return (c.iloc[-1] / c.iloc[-days - 1] - 1) * 100

    def _fred_chg(key: str, periods: int = 1) -> float | None:
        entry = fred_data.get(key, {})
        s = entry.get("series")
        if s is None or s.dropna().empty:
            return None
        s = s.dropna()
        if len(s) < periods + 1:
            return None
        return s.iloc[-1] - s.iloc[-periods - 1]

    def _fred_latest(key: str) -> float | None:
        entry = fred_data.get(key, {})
        s = entry.get("series")
        if s is None or s.dropna().empty:
            return None
        return s.dropna().iloc[-1]

    now_label = dt.date.today().strftime("%b %d")
    results = []

    # 1. USD/Rates Divergence
    dxy_chg  = _mkt_chg_pct("DX-Y.NYB", 21)
    us2y_chg = _fred_chg("2y_yield", 2)
    eu2y_chg = _fred_chg("eu_2y_yield", 2)
    diff_chg = None
    if us2y_chg is not None and eu2y_chg is not None:
        diff_chg = us2y_chg - eu2y_chg

    if dxy_chg is not None and diff_chg is not None:
        if dxy_chg > 0.5 and diff_chg < -0.1:
            sev = "Red" if abs(diff_chg) > 0.3 else "Amber"
            desc = (f"DXY strengthening (+{dxy_chg:.1f}% this month) while US–EU rate differential "
                    f"is narrowing ({diff_chg:+.2f}pp). Historically USD weakens when rate advantage "
                    f"erodes. Potential reversal risk for USD longs.")
        elif dxy_chg < -0.5 and diff_chg > 0.1:
            sev = "Amber"
            desc = (f"DXY weakening ({dxy_chg:.1f}% this month) despite rate differential widening "
                    f"({diff_chg:+.2f}pp). Rate support not translating to USD strength — "
                    f"watch for catch-up rally.")
        else:
            sev = "Green"
            desc = "USD direction broadly consistent with rate differential movement."
    else:
        sev, desc = "Grey", "Insufficient data for USD/rates comparison."
    results.append({
        "name": "USD / Rate Differential",
        "status": sev, "description": desc,
        "first_seen": now_label if sev in ("Red", "Amber") else None,
    })

    # 2. Equity/Credit Divergence
    sp_chg = _mkt_chg_pct("^GSPC", 21)
    hy_chg = _fred_chg("hy_oas", 2)

    if sp_chg is not None and hy_chg is not None:
        if sp_chg > 2.0 and hy_chg > 0.2:
            sev = "Red" if sp_chg > 5.0 and hy_chg > 0.5 else "Amber"
            desc = (f"S&P 500 up {sp_chg:.1f}% while HY credit spreads widened "
                    f"{hy_chg:+.2f}pp. Credit typically leads equity corrections — "
                    f"this divergence historically resolves via equity weakness.")
        elif sp_chg < -2.0 and hy_chg < -0.1:
            sev = "Green"
            desc = f"Equity and credit risk-off in sync (S&P {sp_chg:.1f}%, HY OAS {hy_chg:+.2f}pp)."
        else:
            sev = "Green"
            desc = "Equities and credit spreads broadly aligned."
    else:
        sev, desc = "Grey", "Insufficient data."
    results.append({
        "name": "Equity / Credit",
        "status": sev, "description": desc,
        "first_seen": now_label if sev in ("Red", "Amber") else None,
    })

    # 3. Gold/Real Rates Divergence
    gold_chg  = _mkt_chg_pct("GC=F", 21)
    real_chg  = _fred_chg("real_10y", 2)
    real_10y  = _fred_latest("real_10y")

    if gold_chg is not None and real_chg is not None:
        if gold_chg < -2.0 and real_chg < -0.1:
            sev = "Red" if gold_chg < -5.0 else "Amber"
            desc = (f"Gold falling ({gold_chg:.1f}%) while real yields also falling "
                    f"({real_chg:+.2f}pp). Gold typically rises when real yields fall — "
                    f"this divergence suggests supply/positioning pressure or USD strength "
                    f"overriding the traditional relationship.")
        elif gold_chg > 2.0 and real_chg > 0.15:
            sev = "Amber"
            desc = (f"Gold rising ({gold_chg:+.1f}%) despite real yields rising "
                    f"({real_chg:+.2f}pp). Historically gold underperforms in rising real rate "
                    f"environments — geopolitical/safe-haven demand may be driving this.")
        else:
            sev = "Green"
            desc = "Gold and real yields broadly aligned (inverse relationship intact)."
    else:
        sev, desc = "Grey", "Insufficient data."
    results.append({
        "name": "Gold / Real Rates",
        "status": sev, "description": desc,
        "first_seen": now_label if sev in ("Red", "Amber") else None,
    })

    # 4. Oil/Growth Divergence
    oil_chg   = _mkt_chg_pct("CL=F", 21)
    cfnai_now = _fred_latest("cfnai")

    if oil_chg is not None and cfnai_now is not None:
        if oil_chg > 5.0 and cfnai_now < -0.2:
            sev = "Red" if oil_chg > 10.0 and cfnai_now < -0.5 else "Amber"
            desc = (f"Oil up {oil_chg:.1f}% while CFNAI signals below-trend growth ({cfnai_now:.2f}). "
                    f"Supply-driven oil rally into a growth slowdown typically precedes demand "
                    f"destruction and eventual price reversal.")
        elif oil_chg < -5.0 and cfnai_now > 0.2:
            sev = "Amber"
            desc = (f"Oil falling ({oil_chg:.1f}%) despite above-trend growth (CFNAI {cfnai_now:.2f}). "
                    f"Unusual — may signal supply glut or demand shift. Watch for correction.")
        else:
            sev = "Green"
            desc = "Oil price broadly consistent with growth trajectory."
    else:
        sev, desc = "Grey", "Insufficient data."
    results.append({
        "name": "Oil / Growth",
        "status": sev, "description": desc,
        "first_seen": now_label if sev in ("Red", "Amber") else None,
    })

    # 5. Inflation Expectations Divergence
    be10_now  = _fred_latest("breakeven_10y")
    be10_chg  = _fred_chg("breakeven_10y", 4)
    cpi_now   = _fred_latest("cpi_yoy")

    if be10_now is not None and cpi_now is not None:
        if be10_chg is not None and be10_chg < -0.1 and cpi_now > 3.0:
            sev = "Red" if be10_chg < -0.3 else "Amber"
            desc = (f"10Y breakeven falling ({be10_chg:+.2f}pp over 1M) while CPI remains "
                    f"elevated at {cpi_now:.2f}%. Market is pricing disinflation ahead — "
                    f"but if CPI stays sticky this becomes a mispricing opportunity "
                    f"(breakevens likely to reverse higher).")
        elif be10_chg is not None and be10_chg > 0.2 and cpi_now < 2.5:
            sev = "Amber"
            desc = (f"Breakevens rising ({be10_chg:+.2f}pp over 1M) while CPI is relatively "
                    f"contained at {cpi_now:.2f}%. Market may be overpricing reflation risk — "
                    f"watch for breakeven compression if CPI prints cool.")
        else:
            sev = "Green"
            desc = "Inflation expectations broadly consistent with actual CPI trend."
    else:
        sev, desc = "Grey", "Insufficient data."
    results.append({
        "name": "Inflation Expectations / CPI",
        "status": sev, "description": desc,
        "first_seen": now_label if sev in ("Red", "Amber") else None,
    })

    return results


# ── Module 4: Extended Central Bank Tracker ───────────────────────────────────

_NEXT_FOMC_DATES = [
    dt.date(2025, 7, 30),
    dt.date(2025, 9, 17),
    dt.date(2025, 10, 29),
    dt.date(2025, 12, 10),
    dt.date(2026, 1, 28),
    dt.date(2026, 3, 18),
    dt.date(2026, 4, 29),
    dt.date(2026, 6, 17),
    dt.date(2026, 7, 29),
    dt.date(2026, 9, 16),
    dt.date(2026, 10, 28),
    dt.date(2026, 12, 9),
]


def next_fomc_date() -> dt.date | None:
    today = dt.date.today()
    future = [d for d in _NEXT_FOMC_DATES if d >= today]
    return future[0] if future else None


def _policy_stance(real_rate: float | None, neutral: float = 0.0) -> str:
    if real_rate is None:
        return "—"
    if real_rate > neutral + 0.5:   return "Restrictive"
    if real_rate < neutral - 0.5:   return "Accommodative"
    return "Neutral"


def compute_cb_tracker_extended(fred_data: dict) -> dict:
    """
    Module 4: Policy tracker for Fed, ECB, BOE, BOJ.
    Returns dict with all four banks' current rate, market-implied move,
    real rate, and policy stance.
    """
    def _latest(key: str) -> float | None:
        entry = fred_data.get(key, {})
        s = entry.get("series")
        if s is None or s.dropna().empty: return None
        return s.dropna().iloc[-1]

    fed  = _latest("fed_funds")
    us2y = _latest("2y_yield")
    cpi  = _latest("cpi_yoy")
    core_pce = _latest("core_pce_yoy")

    ecb   = _latest("ecb_deposit_rate")
    eu2y  = _latest("eu_2y_yield")
    hicp  = _latest("eu_hicp")

    boe   = _latest("boe_rate")
    uk2y  = _latest("uk_2y_yield")
    uk_cpi = _latest("uk_cpi_yoy")

    boj   = _latest("boj_rate")
    jp2y  = _latest("jp_2y_yield")
    jp_cpi = _latest("jp_cpi_yoy")

    def _implied_move(policy: float | None, yr2: float | None) -> str | None:
        if policy is None or yr2 is None: return None
        spread = yr2 - policy
        if spread < -0.25: return "CUTS"
        if spread > 0.25:  return "HIKES"
        return "HOLD"

    def _real_rate(nom: float | None, infl: float | None) -> float | None:
        if nom is None or infl is None: return None
        return round(nom - infl, 2)

    fed_real  = _real_rate(fed,  core_pce or cpi)
    ecb_real  = _real_rate(ecb,  hicp)
    boe_real  = _real_rate(boe,  uk_cpi)
    boj_real  = _real_rate(boj,  jp_cpi)

    # Fed 5Y history for timeline chart
    def _series(key: str):
        e = fred_data.get(key, {})
        s = e.get("series")
        return s.dropna() if (s is not None and not s.dropna().empty) else None

    return {
        "fed": {
            "rate": fed, "2y": us2y,
            "implied_move": _implied_move(fed, us2y),
            "real_rate": fed_real,
            "stance": _policy_stance(fed_real),
            "neutral": 2.5,
            "next_meeting": next_fomc_date(),
            "series": _series("fed_funds"),
        },
        "ecb": {
            "rate": ecb, "2y": eu2y,
            "implied_move": _implied_move(ecb, eu2y),
            "real_rate": ecb_real,
            "stance": _policy_stance(ecb_real),
            "neutral": 2.0,
            "series": _series("ecb_deposit_rate"),
        },
        "boe": {
            "rate": boe, "2y": uk2y,
            "implied_move": _implied_move(boe, uk2y),
            "real_rate": boe_real,
            "stance": _policy_stance(boe_real),
            "neutral": 2.0,
            "series": _series("boe_rate"),
        },
        "boj": {
            "rate": boj, "2y": jp2y,
            "implied_move": _implied_move(boj, jp2y),
            "real_rate": boj_real,
            "stance": _policy_stance(boj_real, neutral=-1.0),
            "neutral": 0.0,
            "ycc_note": "Ultra-loose → gradual normalisation since 2024. Monitoring 10Y cap.",
            "series": _series("boj_rate"),
        },
    }


# ── Module 5: Journal helpers (called from pages/) ────────────────────────────

@st.cache_data(ttl=60 * 2)
def fetch_price_return_4w(ticker: str, from_date: str) -> float | None:
    """Fetch 4-week return for a ticker starting from a given date (YYYY-MM-DD)."""
    try:
        start  = dt.date.fromisoformat(from_date)
        end    = start + dt.timedelta(weeks=4)
        df     = yf.Ticker(ticker).history(start=str(start), end=str(end + dt.timedelta(days=5)))
        if df is None or df.empty or len(df) < 2:
            return None
        first  = float(df["Close"].iloc[0])
        last   = float(df["Close"].iloc[-1])
        return round((last / first - 1) * 100, 2) if first > 0 else None
    except Exception:
        return None
