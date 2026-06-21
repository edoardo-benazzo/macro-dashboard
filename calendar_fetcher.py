"""
Economic Calendar
-----------------
Sources (all free):
  1. Hard-coded FOMC & ECB meeting schedules for 2025-2026
  2. FRED series last-observation dates → estimated next release dates
  3. FinnHub (optional free key at finnhub.io) → adds consensus forecasts,
     exact release times, and proper beat/miss classification

Without FinnHub: exact FOMC/ECB dates + approximate US & EU release dates + actuals
With FINNHUB_API_KEY in secrets.toml: full professional calendar with consensus
"""

import datetime as dt
import requests
import streamlit as st

# ── Hard-coded central bank meeting dates ──────────────────────────────────────
# Source: federalreserve.gov and ecb.europa.eu (rate decision announcement day)

FOMC_DATES = [
    "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18",
    "2025-07-30", "2025-09-17", "2025-10-29", "2025-12-10",
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-10",
    "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09",
]

ECB_DATES = [
    "2025-01-30", "2025-03-06", "2025-04-17", "2025-06-05",
    "2025-07-24", "2025-09-11", "2025-10-30", "2025-12-18",
    "2026-01-29", "2026-03-05", "2026-04-16", "2026-06-04",
    "2026-07-23", "2026-09-10", "2026-10-29", "2026-12-17",
]

BOE_DATES = [
    "2025-02-06", "2025-03-20", "2025-05-08", "2025-06-19",
    "2025-08-07", "2025-09-18", "2025-11-06", "2025-12-18",
    "2026-02-05", "2026-03-19", "2026-05-07", "2026-06-18",
    "2026-08-06", "2026-09-17", "2026-11-05", "2026-12-17",
]

# ── FRED series → calendar config ──────────────────────────────────────────────
# next_release_days: days from last FRED observation date to estimated next release
# (monthly obs dates are first of month; interval accounts for release lag)
# impact_type: "inflation" | "growth" | "labor"
# For inflation: actual > estimate = 🔴 hawkish surprise
# For growth/labor: actual > estimate = 🟢 upside surprise

FRED_RELEASE_CONFIG = {
    "US CPI (YoY)":          {"key": "cpi_yoy",        "interval": 70, "impact": "inflation",  "importance": "high",   "country": "US"},
    "US Core CPI (YoY)":     {"key": "core_cpi_yoy",   "interval": 70, "impact": "inflation",  "importance": "high",   "country": "US"},
    "US PCE (YoY)":          {"key": "pce_yoy",         "interval": 65, "impact": "inflation",  "importance": "high",   "country": "US"},
    "US Core PCE (YoY)":     {"key": "core_pce_yoy",   "interval": 65, "impact": "inflation",  "importance": "high",   "country": "US"},
    "US PPI (YoY)":          {"key": "ppi_yoy",         "interval": 45, "impact": "inflation",  "importance": "medium", "country": "US"},
    "US NFP":                {"key": "nfp",              "interval": 35, "impact": "growth",     "importance": "high",   "country": "US"},
    "US Unemployment Rate":  {"key": "unemployment",    "interval": 35, "impact": "labor",      "importance": "high",   "country": "US"},
    "US Initial Claims":     {"key": "initial_claims",  "interval": 7,  "impact": "labor",      "importance": "medium", "country": "US"},
    "US Retail Sales (YoY)": {"key": "retail_sales_yoy","interval": 45, "impact": "growth",     "importance": "medium", "country": "US"},
    "US Housing Starts":     {"key": "housing_starts",  "interval": 50, "impact": "growth",     "importance": "medium", "country": "US"},
    "US Consumer Sentiment": {"key": "consumer_sentiment","interval":35,"impact": "growth",     "importance": "medium", "country": "US"},
    "EU HICP (YoY)":         {"key": "eu_hicp",         "interval": 60, "impact": "inflation",  "importance": "high",   "country": "EU"},
    "EU Unemployment Rate":  {"key": "eu_unemployment", "interval": 65, "impact": "labor",      "importance": "medium", "country": "EU"},
    "UK CPI (YoY)":          {"key": "uk_cpi_yoy",      "interval": 45, "impact": "inflation",  "importance": "high",   "country": "GB"},
    "UK Unemployment Rate":  {"key": "uk_unemployment", "interval": 50, "impact": "labor",      "importance": "medium", "country": "GB"},
}

# ── Impact coloring ────────────────────────────────────────────────────────────

_COUNTRY_FLAGS = {"US": "🇺🇸", "EU": "🇪🇺", "GB": "🇬🇧", "DE": "🇩🇪", "FR": "🇫🇷",
                   "JP": "🇯🇵", "CN": "🇨🇳", "CA": "🇨🇦", "AU": "🇦🇺"}
_IMPORTANCE_DOT = {"high": "🔴", "medium": "🟡", "low": "⚪"}


def beat_miss_label(actual, forecast, impact_type: str) -> str | None:
    """
    Returns colored label based on whether the actual beat or missed expectations.
    For inflation:  actual > forecast = 🔴 HOTTER  (hawkish, bad for bonds/risk)
    For inflation:  actual < forecast = 🟢 COOLER  (dovish, good for bonds)
    For growth/jobs: actual > forecast = 🟢 BEAT
    For growth/jobs: actual < forecast = 🔴 MISS
    For labor (unemployment): inverted — higher = bad
    """
    if actual is None or forecast is None:
        return None
    try:
        a, f = float(actual), float(forecast)
    except (TypeError, ValueError):
        return None
    diff = a - f
    tol  = abs(f) * 0.05 if f else 0.05  # 5% relative tolerance = "in-line"
    if abs(diff) <= tol:
        return "⚪ IN-LINE"
    if impact_type == "inflation":
        return "🔴 HOTTER" if diff > 0 else "🟢 COOLER"
    elif impact_type == "labor":
        return "🔴 MISS" if diff > 0 else "🟢 BEAT"   # higher unemployment = bad
    else:
        return "🟢 BEAT" if diff > 0 else "🔴 MISS"


def _fmt_val(v, key: str = "") -> str:
    """Format a numeric value for display."""
    if v is None:
        return "—"
    try:
        f = float(v)
        if "nfp" in key or "claims" in key or "starts" in key:
            return f"{f:,.0f}"
        return f"{f:.2f}%"
    except (TypeError, ValueError):
        return str(v)


# ── FRED-based calendar (no extra key needed) ──────────────────────────────────

def build_from_fred(fred_data: dict) -> list[dict]:
    """
    Derive upcoming + recent calendar events purely from FRED data already loaded.
    Uses last observation date + typical release interval to estimate next release.
    """
    today = dt.date.today()
    events = []

    for name, cfg in FRED_RELEASE_CONFIG.items():
        entry = fred_data.get(cfg["key"]) if fred_data else None
        if not entry:
            continue
        series = entry.get("series")
        if series is None or series.dropna().empty:
            continue

        s = series.dropna()
        # Last observation date (first of month for monthly series)
        last_obs = s.index[-1].date()
        last_val = s.iloc[-1]
        prev_val = s.iloc[-2] if len(s) >= 2 else None

        interval = cfg["interval"]

        # Estimated next release (advance past any already-passed estimates)
        est_next = last_obs + dt.timedelta(days=interval)
        while est_next <= today:
            est_next += dt.timedelta(days=interval)

        # Upcoming event
        events.append({
            "date":        est_next,
            "name":        name,
            "country":     cfg["country"],
            "importance":  cfg["importance"],
            "impact_type": cfg["impact"],
            "actual":      None,
            "forecast":    None,
            "prev":        last_val,
            "prev_fmt":    _fmt_val(last_val, cfg["key"]),
            "status":      "upcoming",
            "approximate": True,
            "source":      "FRED",
        })

        # Recent release (if last update was within 21 days)
        # Approximate "release date" = last_obs + interval/2 (midpoint heuristic)
        approx_release = last_obs + dt.timedelta(days=interval // 2)
        if (today - approx_release).days <= 21:
            events.append({
                "date":        approx_release,
                "name":        name,
                "country":     cfg["country"],
                "importance":  cfg["importance"],
                "impact_type": cfg["impact"],
                "actual":      last_val,
                "actual_fmt":  _fmt_val(last_val, cfg["key"]),
                "forecast":    None,
                "prev":        prev_val,
                "prev_fmt":    _fmt_val(prev_val, cfg["key"]),
                "beat_miss":   None,
                "status":      "released",
                "approximate": True,
                "source":      "FRED",
            })

    # ── Add FOMC, ECB, BoE meetings ────────────────────────────────────────
    for date_str in FOMC_DATES:
        d = dt.date.fromisoformat(date_str)
        status = "released" if d <= today else "upcoming"
        events.append({
            "date": d, "name": "FOMC Rate Decision",
            "country": "US", "importance": "high", "impact_type": "policy",
            "actual": None, "forecast": None, "prev": None, "prev_fmt": "—",
            "status": status, "approximate": False, "source": "Fed",
        })

    for date_str in ECB_DATES:
        d = dt.date.fromisoformat(date_str)
        status = "released" if d <= today else "upcoming"
        events.append({
            "date": d, "name": "ECB Rate Decision",
            "country": "EU", "importance": "high", "impact_type": "policy",
            "actual": None, "forecast": None, "prev": None, "prev_fmt": "—",
            "status": status, "approximate": False, "source": "ECB",
        })

    for date_str in BOE_DATES:
        d = dt.date.fromisoformat(date_str)
        status = "released" if d <= today else "upcoming"
        events.append({
            "date": d, "name": "BoE Rate Decision",
            "country": "GB", "importance": "high", "impact_type": "policy",
            "actual": None, "forecast": None, "prev": None, "prev_fmt": "—",
            "status": status, "approximate": False, "source": "BoE",
        })

    return sorted(events, key=lambda x: x["date"])


# ── FinnHub calendar (optional — free API key at finnhub.io) ──────────────────

@st.cache_data(ttl=60 * 15)
def fetch_finnhub_calendar(api_key: str, days_back: int = 7, days_ahead: int = 45) -> list[dict]:
    """
    Fetch economic calendar from FinnHub with consensus forecasts.
    Filters to high/medium impact events in US, EU, GB.
    """
    today = dt.date.today()
    from_d = (today - dt.timedelta(days=days_back)).isoformat()
    to_d   = (today + dt.timedelta(days=days_ahead)).isoformat()
    try:
        r = requests.get(
            "https://finnhub.io/api/v1/calendar/economic",
            params={"from": from_d, "to": to_d, "token": api_key},
            headers={"User-Agent": "MacroDashboard/2.0"},
            timeout=12,
        )
        r.raise_for_status()
        raw = r.json().get("economicCalendar", [])
    except Exception:
        return []

    target_countries = {"US", "EU", "GB", "DE", "FR", "IT", "ES"}
    target_impacts   = {"high", "medium"}

    IMPACT_MAP = {
        "cpi":        "inflation", "pce":   "inflation", "hicp": "inflation",
        "inflation":  "inflation", "ppi":   "inflation", "price": "inflation",
        "gdp":        "growth",    "retail": "growth",   "pmi":  "growth",
        "production": "growth",    "housing": "growth",  "sales": "growth",
        "unemploy":   "labor",     "payroll": "growth",  "jobs":  "growth",
        "claims":     "labor",     "employment": "labor",
    }

    events = []
    for e in raw:
        country = (e.get("country") or "").upper()
        impact  = (e.get("impact")  or "low").lower()
        if country not in target_countries or impact not in target_impacts:
            continue
        event_name = e.get("event", "")
        time_str   = e.get("time", "")
        try:
            event_date = dt.date.fromisoformat(time_str[:10])
        except (ValueError, TypeError):
            continue

        # Determine impact_type from event name keywords
        name_lc = event_name.lower()
        impact_type = next(
            (v for k, v in IMPACT_MAP.items() if k in name_lc), "growth"
        )
        actual   = e.get("actual")
        forecast = e.get("estimate")
        prev     = e.get("prev")
        unit     = e.get("unit") or ""

        def _fv(v):
            if v is None: return "—"
            try: return f"{float(v):.2f}{unit}"
            except: return str(v)

        events.append({
            "date":        event_date,
            "time_et":     time_str[11:16] if len(time_str) > 10 else "",
            "name":        event_name,
            "country":     country,
            "importance":  impact,
            "impact_type": impact_type,
            "actual":      actual,
            "actual_fmt":  _fv(actual),
            "forecast":    forecast,
            "forecast_fmt":_fv(forecast),
            "prev":        prev,
            "prev_fmt":    _fv(prev),
            "beat_miss":   beat_miss_label(actual, forecast, impact_type),
            "status":      "released" if actual is not None else "upcoming",
            "approximate": False,
            "source":      "FinnHub",
        })

    return sorted(events, key=lambda x: x["date"])


def get_calendar(fred_data: dict | None, finnhub_key: str | None = None) -> tuple[list, list, list]:
    """
    Returns (today_events, upcoming_events, recent_events) sorted and filtered.
    Uses FinnHub if key provided, otherwise FRED + hard-coded schedule.
    """
    today = dt.date.today()

    if finnhub_key:
        events = fetch_finnhub_calendar(finnhub_key)
    elif fred_data:
        events = build_from_fred(fred_data)
    else:
        events = build_from_fred({})

    today_evts    = [e for e in events if e["date"] == today]
    upcoming_evts = [e for e in events if e["date"] > today]
    recent_evts   = sorted(
        [e for e in events if e["status"] == "released" and
         (today - e["date"]).days <= 21 and e["date"] < today],
        key=lambda x: x["date"], reverse=True,
    )

    return today_evts, upcoming_evts[:30], recent_evts[:20]


def flag(country: str) -> str:
    return _COUNTRY_FLAGS.get(country.upper(), "🌐")


def importance_dot(level: str) -> str:
    return _IMPORTANCE_DOT.get(level.lower(), "⚪")
