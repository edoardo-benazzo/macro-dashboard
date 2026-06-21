"""
Central config for the macro dashboard.
Edit the dictionaries below to add/remove series or tickers — nothing else
in the app needs to change.
"""

# ---- FRED series ----------------------------------------------------------
# key = short internal name, value = (FRED series ID, display label, units)
FRED_SERIES = {
    "10y_yield":   ("DGS10",     "10-Year Treasury Yield",          "%"),
    "2y_yield":    ("DGS2",      "2-Year Treasury Yield",           "%"),
    "fed_funds":   ("FEDFUNDS",  "Effective Fed Funds Rate",        "%"),
    "cpi_yoy":     ("CPIAUCSL",  "CPI (Headline, YoY %)",           "%", "yoy_pct"),
    "core_cpi_yoy":("CPILFESL",  "Core CPI (YoY %)",                "%", "yoy_pct"),
    "unemployment":("UNRATE",    "Unemployment Rate",               "%"),
    "nfp":         ("PAYEMS",    "Nonfarm Payrolls (level, thous.)","thousands"),
}

# ---- Yahoo Finance tickers --------------------------------------------------
MARKET_TICKERS = {
    "^GSPC": "S&P 500",
    "^IXIC": "Nasdaq Composite",
    "^DJI":  "Dow Jones Industrial Average",
    "TLT":   "iShares 20+ Yr Treasury Bond ETF",
    "SHY":   "iShares 1-3 Yr Treasury Bond ETF",
    "^VIX":  "CBOE Volatility Index (VIX)",
    "DX-Y.NYB": "US Dollar Index (DXY)",
    "GC=F":  "Gold Futures",
    "CL=F":  "WTI Crude Oil Futures",
}

# Default historical lookback shown on load (years)
DEFAULT_LOOKBACK_YEARS = 5
