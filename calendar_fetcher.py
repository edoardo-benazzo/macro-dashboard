"""
Economic Calendar
-----------------
Priority order:
  1. Trading Economics API (free key → 30-day forward calendar with consensus)
  2. Static 2025-2026 release schedule (CPI, NFP, PCE, GDP, HICP + CB meetings)
     enriched with FRED actuals for events that have already been released
  3. Pure FRED-derived estimates when no static date is available

Secrets:
  TE_API_KEY = "..."     ← tradingeconomics.com/api (free tier works)
"""

import datetime as dt

import requests
import streamlit as st

# ── Hard-coded central bank meeting dates ──────────────────────────────────────
# Source: federalreserve.gov / ecb.europa.eu / bankofengland.co.uk

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

# ── Static 2025-2026 data release schedule ─────────────────────────────────────
# All dates approximate ± 1-3 days. Sourced from BLS/BEA/Eurostat release calendars.
# Marked approximate=True so the UI shows "~" prefix.
# The FRED enrichment pass will fill in 'actual' and 'prev' values once released.

_STATIC_RELEASES = [
    # ── US CPI (~2nd week each month, 08:30 ET, BLS) ─────────────────────────
    *[{"date": d, "name": "US CPI (YoY)", "country": "US",
       "importance": "high", "impact": "inflation", "fred_key": "cpi_yoy"}
      for d in ["2025-01-15","2025-02-12","2025-03-12","2025-04-10","2025-05-13",
                "2025-06-11","2025-07-15","2025-08-12","2025-09-10","2025-10-15",
                "2025-11-13","2025-12-10",
                "2026-01-15","2026-02-12","2026-03-12","2026-04-09","2026-05-13",
                "2026-06-11","2026-07-15","2026-08-13","2026-09-10","2026-10-14",
                "2026-11-12","2026-12-10"]],
    # ── US Core CPI ──────────────────────────────────────────────────────────
    *[{"date": d, "name": "US Core CPI (YoY)", "country": "US",
       "importance": "high", "impact": "inflation", "fred_key": "core_cpi_yoy"}
      for d in ["2025-01-15","2025-02-12","2025-03-12","2025-04-10","2025-05-13",
                "2025-06-11","2025-07-15","2025-08-12","2025-09-10","2025-10-15",
                "2025-11-13","2025-12-10",
                "2026-01-15","2026-02-12","2026-03-12","2026-04-09","2026-05-13",
                "2026-06-11"]],
    # ── US NFP (~1st Friday each month, 08:30 ET, BLS) ───────────────────────
    *[{"date": d, "name": "US Nonfarm Payrolls", "country": "US",
       "importance": "high", "impact": "growth", "fred_key": "nfp"}
      for d in ["2025-01-10","2025-02-07","2025-03-07","2025-04-04","2025-05-02",
                "2025-06-06","2025-07-03","2025-08-01","2025-09-05","2025-10-03",
                "2025-11-07","2025-12-05",
                "2026-01-09","2026-02-06","2026-03-06","2026-04-03","2026-05-01",
                "2026-06-05","2026-07-02"]],
    # ── US Unemployment Rate (same release as NFP) ────────────────────────────
    *[{"date": d, "name": "US Unemployment Rate", "country": "US",
       "importance": "high", "impact": "labor", "fred_key": "unemployment"}
      for d in ["2025-01-10","2025-02-07","2025-03-07","2025-04-04","2025-05-02",
                "2025-06-06","2025-07-03","2025-08-01","2025-09-05","2025-10-03",
                "2025-11-07","2025-12-05",
                "2026-01-09","2026-02-06","2026-03-06","2026-04-03","2026-05-01",
                "2026-06-05","2026-07-02"]],
    # ── US Core PCE (~last Friday each month, 08:30 ET, BEA) ─────────────────
    *[{"date": d, "name": "US Core PCE (YoY)", "country": "US",
       "importance": "high", "impact": "inflation", "fred_key": "core_pce_yoy"}
      for d in ["2025-01-31","2025-02-28","2025-03-28","2025-04-25","2025-05-30",
                "2025-06-27","2025-07-25","2025-08-29","2025-09-26","2025-10-31",
                "2025-11-26","2025-12-19",
                "2026-01-30","2026-02-27","2026-03-27","2026-04-24","2026-05-29",
                "2026-06-26","2026-07-31"]],
    # ── US GDP Advance (~end of Jan/Apr/Jul/Oct, 08:30 ET, BEA) ─────────────
    *[{"date": d, "name": "US GDP Advance Estimate", "country": "US",
       "importance": "high", "impact": "growth", "fred_key": None}
      for d in ["2025-01-30","2025-04-30","2025-07-30","2025-10-30",
                "2026-01-29","2026-04-29","2026-07-30"]],
    # ── US Retail Sales (~mid-month, 08:30 ET, Census Bureau) ────────────────
    *[{"date": d, "name": "US Retail Sales (MoM)", "country": "US",
       "importance": "medium", "impact": "growth", "fred_key": "retail_sales_yoy"}
      for d in ["2025-01-16","2025-02-14","2025-03-17","2025-04-16","2025-05-15",
                "2025-06-17","2025-07-17","2025-08-15","2025-09-17","2025-10-17",
                "2025-11-14","2025-12-16",
                "2026-01-16","2026-02-13","2026-03-17","2026-04-15","2026-05-15",
                "2026-06-16"]],
    # ── EU HICP Flash (~last day of month, Eurostat) ──────────────────────────
    *[{"date": d, "name": "EU HICP Inflation Flash (YoY)", "country": "EU",
       "importance": "high", "impact": "inflation", "fred_key": "eu_hicp"}
      for d in ["2025-01-31","2025-02-28","2025-03-31","2025-04-30","2025-05-30",
                "2025-06-27","2025-07-31","2025-08-29","2025-09-30","2025-10-31",
                "2025-11-28","2025-12-17",
                "2026-01-30","2026-02-27","2026-03-31","2026-04-30","2026-05-29",
                "2026-06-30"]],
    # ── UK CPI (~2nd Wednesday each month, ONS) ───────────────────────────────
    *[{"date": d, "name": "UK CPI (YoY)", "country": "GB",
       "importance": "high", "impact": "inflation", "fred_key": "uk_cpi_yoy"}
      for d in ["2025-01-15","2025-02-19","2025-03-26","2025-04-16","2025-05-21",
                "2025-06-18","2025-07-16","2025-08-20","2025-09-17","2025-10-15",
                "2025-11-19","2025-12-17",
                "2026-01-21","2026-02-18","2026-03-25","2026-04-15","2026-05-20",
                "2026-06-17"]],
]

# ── Trading Economics country mapping ─────────────────────────────────────────
_TE_COUNTRY_MAP = {
    "united states": "US",
    "euro area":     "EU",
    "european union":"EU",
    "united kingdom":"GB",
    "germany":       "DE",
    "france":        "FR",
    "italy":         "IT",
    "spain":         "ES",
    "japan":         "JP",
    "china":         "CN",
    "canada":        "CA",
    "australia":     "AU",
}
_TE_IMPORTANCE_MAP = {3: "high", 2: "medium", 1: "low"}

_TE_IMPACT_MAP = {
    "inflation": "inflation", "cpi": "inflation", "pce": "inflation",
    "hicp": "inflation", "ppi": "inflation", "price": "inflation",
    "deflator": "inflation",
    "gdp": "growth", "retail": "growth", "pmi": "growth",
    "production": "growth", "housing": "growth", "sales": "growth",
    "confidence": "growth", "sentiment": "growth", "leading": "growth",
    "payroll": "growth", "nonfarm": "growth", "non farm": "growth",
    "unemploy": "labor", "jobless": "labor", "claims": "labor",
    "employment": "labor",
    "rate decision": "policy", "interest rate": "policy",
    "fomc": "policy", "ecb": "policy", "boe": "policy",
    "monetary policy": "policy",
}

# Target countries and minimum importance for TE filter
_TE_COUNTRIES  = "united states,euro area,united kingdom,germany,france,italy,spain"
_TE_MIN_IMP    = 2  # skip importance=1 (low)

# ── Labels ────────────────────────────────────────────────────────────────────

_COUNTRY_LABELS    = {"US": "US", "EU": "EU", "GB": "UK", "DE": "DE", "FR": "FR",
                      "IT": "IT", "ES": "ES", "JP": "JP", "CN": "CN", "CA": "CA"}
_IMPORTANCE_LABELS = {"high": "HIGH", "medium": "MED", "low": "LOW"}


def flag(country: str) -> str:
    return _COUNTRY_LABELS.get(country.upper(), country.upper())


def importance_dot(level: str) -> str:
    return _IMPORTANCE_LABELS.get(level.lower(), level.upper())


# ── Beat/miss signal ──────────────────────────────────────────────────────────

def beat_miss_label(actual, forecast, impact_type: str) -> str | None:
    if actual is None or forecast is None:
        return None
    try:
        a, f = float(actual), float(forecast)
    except (TypeError, ValueError):
        return None
    diff = a - f
    tol  = abs(f) * 0.05 if f else 0.05
    if abs(diff) <= tol:
        return "IN-LINE"
    if impact_type == "inflation":
        return "HOTTER" if diff > 0 else "COOLER"
    elif impact_type == "labor":
        return "MISS" if diff > 0 else "BEAT"
    else:
        return "BEAT" if diff > 0 else "MISS"


def _fmt_val(v, key: str = "", unit: str = "") -> str:
    if v is None:
        return "—"
    try:
        f = float(v)
        if unit:
            return f"{f:.2f}{unit}"
        if key and any(k in key for k in ("nfp", "payroll", "claims", "starts")):
            return f"{f:,.0f}K"
        return f"{f:.2f}%"
    except (TypeError, ValueError):
        return str(v) if str(v) else "—"


def _impact_type_from_text(text: str) -> str:
    lc = text.lower()
    for kw, itype in _TE_IMPACT_MAP.items():
        if kw in lc:
            return itype
    return "growth"


# ── Trading Economics calendar ────────────────────────────────────────────────

@st.cache_data(ttl=60 * 60)  # hourly — TE calendar updates ~daily
def fetch_te_calendar(api_key: str, days_back: int = 14, days_ahead: int = 45) -> list[dict]:
    """
    Fetch 30-day forward (+ recent) economic calendar from Trading Economics.
    Free API key at tradingeconomics.com/api — returns consensus forecasts,
    previous values, and actuals once released.
    """
    today  = dt.date.today()
    d1     = (today - dt.timedelta(days=days_back)).isoformat()
    d2     = (today + dt.timedelta(days=days_ahead)).isoformat()

    try:
        r = requests.get(
            "https://api.tradingeconomics.com/calendar",
            params={
                "c":       api_key,
                "country": _TE_COUNTRIES,
                "d1":      d1,
                "d2":      d2,
            },
            headers={"User-Agent": "MacroDashboard/3.0 (educational)"},
            timeout=15,
        )
        r.raise_for_status()
        raw = r.json()
        if not isinstance(raw, list):
            return []
    except Exception:
        return []

    events = []
    for e in raw:
        # Importance filter
        imp_num = e.get("Importance") or 0
        try:
            imp_num = int(imp_num)
        except (TypeError, ValueError):
            imp_num = 0
        if imp_num < _TE_MIN_IMP:
            continue

        # Country filter & mapping
        country_raw = (e.get("Country") or e.get("OCountry") or "").lower().strip()
        country     = _TE_COUNTRY_MAP.get(country_raw)
        if not country:
            continue

        # Date parsing
        date_raw = e.get("Date") or ""
        try:
            event_date = dt.date.fromisoformat(date_raw[:10])
        except (ValueError, TypeError):
            continue

        # Time (may be empty for day-only releases)
        time_str = date_raw[11:16] if len(date_raw) > 10 else ""

        # Event label
        event_name = (e.get("Event") or e.get("Category") or "").strip()
        category   = (e.get("Category") or "").strip()
        if not event_name:
            continue

        importance  = _TE_IMPORTANCE_MAP.get(imp_num, "medium")
        impact_type = _impact_type_from_text(event_name + " " + category)

        actual   = e.get("Actual")   or None
        forecast = e.get("Forecast") or e.get("TEForecast") or None
        prev     = e.get("Previous") or None
        unit     = (e.get("Unit") or "").strip()
        if unit == "%":
            unit = "%"
        elif unit:
            unit = " " + unit

        # Clean up empty-string values from the API
        if actual   == "": actual   = None
        if forecast == "": forecast = None
        if prev     == "": prev     = None

        events.append({
            "date":         event_date,
            "time_et":      time_str,
            "name":         event_name,
            "country":      country,
            "importance":   importance,
            "impact_type":  impact_type,
            "actual":       actual,
            "actual_fmt":   _fmt_val(actual,   unit=unit),
            "forecast":     forecast,
            "forecast_fmt": _fmt_val(forecast, unit=unit),
            "prev":         prev,
            "prev_fmt":     _fmt_val(prev,     unit=unit),
            "beat_miss":    beat_miss_label(actual, forecast, impact_type),
            "status":       "released" if actual is not None else "upcoming",
            "approximate":  False,
            "source":       "Trading Economics",
        })

    return sorted(events, key=lambda x: x["date"])


# ── Static + FRED fallback ────────────────────────────────────────────────────

def _enrich_with_fred(events: list[dict], fred_data: dict | None) -> list[dict]:
    """
    For each static event that has a fred_key and whose date has passed,
    look up the FRED series and attach the actual value + previous value.
    Also computes a rough beat_miss against any existing forecast.
    """
    if not fred_data:
        return events
    today = dt.date.today()
    enriched = []
    for evt in events:
        fkey = evt.get("fred_key")
        if fkey and evt["date"] <= today and evt.get("actual") is None:
            entry = fred_data.get(fkey, {})
            s = entry.get("series")
            if s is not None and not s.dropna().empty:
                s = s.dropna()
                # Find the FRED observation closest to the event date
                obs_before = s[s.index.date <= evt["date"]]  # type: ignore[misc]
                if not obs_before.empty:
                    actual_val = float(obs_before.iloc[-1])
                    prev_val   = float(obs_before.iloc[-2]) if len(obs_before) >= 2 else None
                    evt = {**evt,
                           "actual":     actual_val,
                           "actual_fmt": _fmt_val(actual_val, key=fkey),
                           "prev":       prev_val,
                           "prev_fmt":   _fmt_val(prev_val, key=fkey),
                           "status":     "released",
                           "beat_miss":  beat_miss_label(actual_val, evt.get("forecast"),
                                                          evt.get("impact_type", "growth"))}
        enriched.append(evt)
    return enriched


def build_static_calendar(fred_data: dict | None) -> list[dict]:
    """
    Build calendar from the static release schedule + hard-coded CB meetings.
    Enrich past events with FRED actuals.
    """
    today  = dt.date.today()
    events = []

    # Static data releases
    for cfg in _STATIC_RELEASES:
        d = dt.date.fromisoformat(cfg["date"])
        events.append({
            "date":        d,
            "name":        cfg["name"],
            "country":     cfg["country"],
            "importance":  cfg["importance"],
            "impact_type": cfg["impact"],
            "fred_key":    cfg.get("fred_key"),
            "actual":      None,
            "actual_fmt":  "—",
            "forecast":    None,
            "forecast_fmt":"—",
            "prev":        None,
            "prev_fmt":    "—",
            "beat_miss":   None,
            "status":      "released" if d <= today else "upcoming",
            "approximate": True,
            "source":      "Static schedule",
        })

    # Central bank meetings (exact dates)
    for date_str in FOMC_DATES:
        d = dt.date.fromisoformat(date_str)
        events.append({
            "date": d, "name": "FOMC Rate Decision",
            "country": "US", "importance": "high", "impact_type": "policy",
            "fred_key": None,
            "actual": None, "actual_fmt": "—",
            "forecast": None, "forecast_fmt": "—",
            "prev": None, "prev_fmt": "—",
            "beat_miss": None,
            "status": "released" if d <= today else "upcoming",
            "approximate": False, "source": "Fed",
        })
    for date_str in ECB_DATES:
        d = dt.date.fromisoformat(date_str)
        events.append({
            "date": d, "name": "ECB Rate Decision",
            "country": "EU", "importance": "high", "impact_type": "policy",
            "fred_key": None,
            "actual": None, "actual_fmt": "—",
            "forecast": None, "forecast_fmt": "—",
            "prev": None, "prev_fmt": "—",
            "beat_miss": None,
            "status": "released" if d <= today else "upcoming",
            "approximate": False, "source": "ECB",
        })
    for date_str in BOE_DATES:
        d = dt.date.fromisoformat(date_str)
        events.append({
            "date": d, "name": "BoE Rate Decision",
            "country": "GB", "importance": "high", "impact_type": "policy",
            "fred_key": None,
            "actual": None, "actual_fmt": "—",
            "forecast": None, "forecast_fmt": "—",
            "prev": None, "prev_fmt": "—",
            "beat_miss": None,
            "status": "released" if d <= today else "upcoming",
            "approximate": False, "source": "BoE",
        })

    # Enrich past events with FRED actuals
    events = _enrich_with_fred(events, fred_data)

    # Deduplicate by (date, name) keeping latest-enriched version
    seen: dict[tuple, dict] = {}
    for evt in events:
        key = (evt["date"], evt["name"])
        if key not in seen or evt.get("actual") is not None:
            seen[key] = evt
    return sorted(seen.values(), key=lambda x: x["date"])


# ── Public API ────────────────────────────────────────────────────────────────

def get_calendar(
    fred_data: dict | None,
    te_api_key: str | None = None,
) -> tuple[list, list, list]:
    """
    Returns (today_events, upcoming_events, recent_events).

    Strategy:
      1. Trading Economics API if key provided → full 30-day forward calendar
         with real consensus forecasts. Falls back to static if TE returns empty.
      2. Static schedule + FRED enrichment otherwise.
    """
    today = dt.date.today()
    te_events: list[dict] = []

    if te_api_key:
        te_events = fetch_te_calendar(te_api_key)

    if te_events:
        events = te_events
        # Merge in any static CB meeting dates not covered by TE
        static = build_static_calendar(fred_data)
        cb_names = {"FOMC Rate Decision", "ECB Rate Decision", "BoE Rate Decision"}
        te_keys  = {(e["date"], e["name"]) for e in te_events}
        for s in static:
            if s["name"] in cb_names and (s["date"], s["name"]) not in te_keys:
                events.append(s)
        events = sorted(events, key=lambda x: x["date"])
    else:
        events = build_static_calendar(fred_data)

    today_evts    = [e for e in events if e["date"] == today]
    upcoming_evts = [e for e in events if e["date"] > today]
    recent_evts   = sorted(
        [e for e in events
         if e.get("status") == "released"
         and e["date"] < today
         and (today - e["date"]).days <= 30],
        key=lambda x: x["date"], reverse=True,
    )
    return today_evts, upcoming_evts[:40], recent_evts[:25]
