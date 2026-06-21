"""
Central config for the macro dashboard.
Edit the dictionaries below to add/remove series or tickers — nothing else
in the app needs to change.
"""

# ---- US FRED series ---------------------------------------------------------
# key = short internal name, value = (FRED series ID, display label, units)
US_FRED_SERIES = {
    "10y_yield":     ("DGS10",      "10-Year Treasury Yield",            "%"),
    "2y_yield":      ("DGS2",       "2-Year Treasury Yield",             "%"),
    "fed_funds":     ("FEDFUNDS",   "Effective Fed Funds Rate",          "%"),
    "cpi_yoy":       ("CPIAUCSL",   "CPI (Headline, YoY %)",             "%", "yoy_pct"),
    "core_cpi_yoy":  ("CPILFESL",   "Core CPI (YoY %)",                  "%", "yoy_pct"),
    "unemployment":  ("UNRATE",     "Unemployment Rate",                 "%"),
    "nfp":           ("PAYEMS",     "Nonfarm Payrolls (level, thous.)",  "thousands"),
    "real_10y":      ("DFII10",     "10-Year TIPS Yield (Real Yield)",   "%"),
    "breakeven_10y": ("T10YIE",     "10-Year Breakeven Inflation Rate",  "%"),
    "hy_oas":        ("BAMLH0A0HYM2", "High Yield Credit Spread (OAS)",  "%"),
    "ig_oas":        ("BAMLC0A0CM",   "Investment Grade Credit Spread (OAS)", "%"),
    "industrial_prod": ("INDPRO",   "Industrial Production Index",       "index"),
    "cfnai":         ("CFNAI",      "Chicago Fed National Activity Index", "index"),
}

# ---- Europe (Euro Area) FRED series -----------------------------------------
EU_FRED_SERIES = {
    "ecb_deposit_rate": ("ECBDFR",              "ECB Deposit Facility Rate",      "%"),
    "eu_10y_yield":     ("IRLTLT01EZM156N",     "Euro Area 10-Year Gov't Bond Yield", "%"),
    "eu_hicp":          ("CP0000EZ19M086NEST",  "Euro Area HICP (YoY %)",         "%", "yoy_pct"),
    "eu_unemployment":  ("LRHUTTTTEZM156S",     "Euro Area Unemployment Rate",    "%"),
    "eur_usd":          ("DEXUSEU",             "EUR/USD Exchange Rate",          "USD per EUR"),
}

# ---- US Yahoo Finance tickers ------------------------------------------------
US_MARKET_TICKERS = {
    "^GSPC": "S&P 500",
    "^IXIC": "Nasdaq Composite",
    "^DJI":  "Dow Jones Industrial Average",
    "TLT":   "iShares 20+ Yr Treasury Bond ETF",
    "SHY":   "iShares 1-3 Yr Treasury Bond ETF",
    "^VIX":  "CBOE Volatility Index (VIX)",
    "DX-Y.NYB": "US Dollar Index (DXY)",
    "GC=F":  "Gold Futures",
    "CL=F":  "WTI Crude Oil Futures",
    "HYG":   "High Yield Corp Bond ETF (HYG)",
    "LQD":   "Investment Grade Corp Bond ETF (LQD)",
}

# ---- Europe Yahoo Finance tickers --------------------------------------------
EU_MARKET_TICKERS = {
    "^STOXX50E": "Euro Stoxx 50",
    "^GDAXI":    "DAX (Germany)",
    "^FTSE":     "FTSE 100 (UK)",
    "EURUSD=X":  "EUR/USD",
}

# Combined dict — used wherever the app needs "all tickers" regardless of region
MARKET_TICKERS = {**US_MARKET_TICKERS, **EU_MARKET_TICKERS}
FRED_SERIES = {**US_FRED_SERIES, **EU_FRED_SERIES}

# Tickers used for the cross-asset correlation matrix (subset of the above,
# kept smaller so the heatmap stays readable)
CORRELATION_TICKERS = ["^GSPC", "TLT", "GC=F", "DX-Y.NYB", "^VIX", "HYG"]

# Default historical lookback shown on load (years)
DEFAULT_LOOKBACK_YEARS = 5

# Rolling window (trading days) used for the correlation matrix
CORRELATION_WINDOW_DAYS = 60

# ---- TradingView symbol mapping ---------------------------------------------
# Maps our internal ticker/series keys to TradingView's symbol format, used to
# build "Open in TradingView" links next to charts. Not every series has a
# clean TradingView equivalent (e.g. some FRED-only macro series don't trade),
# so this map only covers tradeable instruments.
TRADINGVIEW_SYMBOLS = {
    "^GSPC": "SP:SPX",
    "^IXIC": "NASDAQ:IXIC",
    "^DJI": "DJ:DJI",
    "TLT": "NASDAQ:TLT",
    "SHY": "NASDAQ:SHY",
    "^VIX": "CBOE:VIX",
    "DX-Y.NYB": "TVC:DXY",
    "GC=F": "COMEX:GC1!",
    "CL=F": "NYMEX:CL1!",
    "HYG": "AMEX:HYG",
    "LQD": "AMEX:LQD",
    "^STOXX50E": "INDEX:STOXX50E",
    "^GDAXI": "XETR:DAX",
    "^FTSE": "FOREXCOM:UK100",
    "EURUSD=X": "FX:EURUSD",
    "10y_yield": "TVC:US10Y",
    "2y_yield": "TVC:US02Y",
    "eu_10y_yield": "TVC:DE10Y",
    "eur_usd": "FX:EURUSD",
}


def tradingview_url(symbol_key: str) -> str:
    """
    Build a TradingView chart URL for a given internal ticker/series key.
    Returns None if no mapping exists (caller should hide the link in that case).
    """
    tv_symbol = TRADINGVIEW_SYMBOLS.get(symbol_key)
    if not tv_symbol:
        return None
    return f"https://www.tradingview.com/chart/?symbol={tv_symbol}"