"""
Central config for the macro dashboard.
Edit the dictionaries below to add/remove series or tickers — nothing else
in the app needs to change.
"""

# ---- US FRED series ---------------------------------------------------------
# key = short internal name, value = (FRED series ID, display label, units[, transform])
US_FRED_SERIES = {
    # Yields & monetary policy
    "fed_funds":     ("FEDFUNDS",   "Effective Fed Funds Rate",          "%"),
    "3m_yield":      ("DGS3MO",     "3-Month Treasury Yield",            "%"),
    "2y_yield":      ("DGS2",       "2-Year Treasury Yield",             "%"),
    "10y_yield":     ("DGS10",      "10-Year Treasury Yield",            "%"),
    "30y_yield":     ("DGS30",      "30-Year Treasury Yield",            "%"),
    "real_10y":      ("DFII10",     "10-Year TIPS Yield (Real)",         "%"),
    "breakeven_10y": ("T10YIE",     "10-Year Breakeven Inflation",       "%"),
    # Inflation
    "cpi_yoy":       ("CPIAUCSL",   "CPI Headline (YoY %)",              "%", "yoy_pct"),
    "core_cpi_yoy":  ("CPILFESL",   "Core CPI (YoY %)",                  "%", "yoy_pct"),
    "pce_yoy":       ("PCEPI",      "PCE Inflation (YoY %)",             "%", "yoy_pct"),
    "core_pce_yoy":  ("PCEPILFE",   "Core PCE Inflation (YoY %)",        "%", "yoy_pct"),
    "ppi_yoy":       ("PPIACO",     "PPI All Commodities (YoY %)",       "%", "yoy_pct"),
    # Labor market
    "unemployment":  ("UNRATE",     "Unemployment Rate",                 "%"),
    "nfp":           ("PAYEMS",     "Nonfarm Payrolls (level, thous.)",  "thousands"),
    "initial_claims":("ICSA",       "Initial Jobless Claims",            "thousands"),
    # Growth & activity
    "cfnai":         ("CFNAI",      "Chicago Fed National Activity Index","index"),
    "industrial_prod":("INDPRO",    "Industrial Production Index",       "index"),
    "retail_sales_yoy":("RSAFS",    "Retail Sales (YoY %)",              "%", "yoy_pct"),
    "housing_starts":("HOUST",      "Housing Starts",                    "thousands"),
    # Consumer
    "consumer_sentiment":("UMCSENT","UMich Consumer Sentiment",          "index"),
    # Money & credit
    "m2_yoy":        ("M2SL",       "M2 Money Supply (YoY %)",           "%", "yoy_pct"),
    "hy_oas":        ("BAMLH0A0HYM2","High Yield Credit Spread (OAS)",   "%"),
    "ig_oas":        ("BAMLC0A0CM", "Investment Grade Credit Spread (OAS)","%"),
    # Module 1 — Market-implied forward signals
    "breakeven_5y":  ("T5YIE",     "5-Year Breakeven Inflation",         "%"),
    "breakeven_5y5y":("T5YIFR",   "5Y5Y Forward Inflation Expectation", "%"),
    "fwd_rate_2y2y": ("THREEFY2", "2-Year Rate, 2 Years Forward",        "%"),
    "fwd_rate_3y2y": ("THREEFY3", "2-Year Rate, 3 Years Forward",        "%"),
}

# ---- Europe / UK FRED series ------------------------------------------------
EU_FRED_SERIES = {
    # ECB & Euro Area aggregate
    "ecb_deposit_rate": ("ECBDFR",             "ECB Deposit Facility Rate",          "%"),
    "eu_2y_yield":      ("IRLTLT02EZM156N",    "Euro Area 2-Year Gov't Bond Yield",  "%"),
    "eu_10y_yield":     ("IRLTLT01EZM156N",    "Euro Area 10-Year Gov't Bond Yield", "%"),
    "eu_hicp":          ("CP0000EZ19M086NEST", "Euro Area HICP (YoY %)",             "%", "yoy_pct"),
    "eu_unemployment":  ("LRHUTTTTEZM156S",    "Euro Area Unemployment Rate",        "%"),
    "eur_usd":          ("DEXUSEU",            "EUR/USD Exchange Rate",              "USD per EUR"),
    # Country-level sovereign yields (critical for EU sovereign risk)
    "de_10y_yield":     ("IRLTLT01DEM156N",    "Germany 10-Year Bund Yield",         "%"),
    "it_10y_yield":     ("IRLTLT01ITM156N",    "Italy 10-Year BTP Yield",            "%"),
    "fr_10y_yield":     ("IRLTLT01FRM156N",    "France 10-Year OAT Yield",           "%"),
    "es_10y_yield":     ("IRLTLT01ESM156N",    "Spain 10-Year Bonos Yield",          "%"),
    # UK
    "uk_10y_yield":     ("IRLTLT01GBM156N",    "UK 10-Year Gilt Yield",              "%"),
    "uk_unemployment":  ("LRHUTTTTGBM156S",    "UK Unemployment Rate",               "%"),
    "boe_rate":         ("BOERUKM",            "Bank of England Base Rate",          "%"),
    "uk_cpi_yoy":       ("GBRCPIALLMINMEI",    "UK CPI (YoY %)",                     "%", "yoy_pct"),
    "uk_2y_yield":      ("IRLTLT02GBM156N",    "UK 2-Year Gilt Yield",               "%"),
    # Module 4 — Central Bank Tracker (additional banks)
    "boj_rate":         ("IRSTCI01JPM156N",    "BOJ Short-Term Policy Rate",         "%"),
    "jp_2y_yield":      ("IRLTLT02JPM156N",    "Japan 2-Year Government Bond Yield", "%"),
    "jp_cpi_yoy":       ("JPNCPIALLMINMEI",    "Japan CPI (YoY %)",                  "%", "yoy_pct"),
}

# ---- US Yahoo Finance tickers ------------------------------------------------
US_MARKET_TICKERS = {
    # Broad equity indices
    "^GSPC":  "S&P 500",
    "^IXIC":  "Nasdaq Composite",
    "^DJI":   "Dow Jones Industrial Avg",
    "IWM":    "Russell 2000 (Small Cap)",
    # Fixed income
    "TLT":    "20+ Yr Treasury ETF (TLT)",
    "SHY":    "1-3 Yr Treasury ETF (SHY)",
    "TIP":    "TIPS ETF (TIP)",
    # Volatility & dollar
    "^VIX":   "CBOE Volatility Index (VIX)",
    "DX-Y.NYB":"US Dollar Index (DXY)",
    # Commodities
    "GC=F":   "Gold Futures",
    "SI=F":   "Silver Futures",
    "CL=F":   "WTI Crude Oil Futures",
    "NG=F":   "Natural Gas Futures",
    "HG=F":   "Copper Futures",
    # Credit
    "HYG":    "High Yield Corp Bond ETF (HYG)",
    "LQD":    "Inv. Grade Corp Bond ETF (LQD)",
    # US Sector ETFs
    "XLF":    "Financials (XLF)",
    "XLE":    "Energy (XLE)",
    "XLK":    "Technology (XLK)",
    "XLV":    "Health Care (XLV)",
    "XLU":    "Utilities (XLU)",
    "XLI":    "Industrials (XLI)",
}

# ---- Europe Yahoo Finance tickers --------------------------------------------
EU_MARKET_TICKERS = {
    "^STOXX50E": "Euro Stoxx 50",
    "^GDAXI":    "DAX (Germany)",
    "^FTSE":     "FTSE 100 (UK)",
    "^FCHI":     "CAC 40 (France)",
    "FTSEMIB.MI":"FTSE MIB (Italy)",
    "^IBEX":     "IBEX 35 (Spain)",
    # EU FX
    "EURUSD=X":  "EUR/USD",
    "GBPUSD=X":  "GBP/USD",
    "JPY=X":     "USD/JPY",
    "CHF=X":     "USD/CHF",
}

# Combined dicts — used wherever the app needs all tickers regardless of region
MARKET_TICKERS = {**US_MARKET_TICKERS, **EU_MARKET_TICKERS}
FRED_SERIES    = {**US_FRED_SERIES, **EU_FRED_SERIES}

# Tickers used for the cross-asset correlation matrix
CORRELATION_TICKERS = [
    "^GSPC", "^STOXX50E", "TLT", "GC=F", "CL=F",
    "DX-Y.NYB", "HYG", "HG=F", "^VIX",
]

# Default historical lookback shown on load (years)
DEFAULT_LOOKBACK_YEARS = 5

# Rolling window (trading days) used for the correlation matrix
CORRELATION_WINDOW_DAYS = 60

# ---- TradingView symbol mapping ---------------------------------------------
TRADINGVIEW_SYMBOLS = {
    # US equity indices
    "^GSPC":     "SP:SPX",
    "^IXIC":     "NASDAQ:IXIC",
    "^DJI":      "DJ:DJI",
    "IWM":       "AMEX:IWM",
    # US fixed income ETFs
    "TLT":       "NASDAQ:TLT",
    "SHY":       "NASDAQ:SHY",
    "TIP":       "AMEX:TIP",
    # Volatility & dollar
    "^VIX":      "CBOE:VIX",
    "DX-Y.NYB":  "TVC:DXY",
    # Commodities
    "GC=F":      "COMEX:GC1!",
    "SI=F":      "COMEX:SI1!",
    "CL=F":      "NYMEX:CL1!",
    "NG=F":      "NYMEX:NG1!",
    "HG=F":      "COMEX:HG1!",
    # Credit ETFs
    "HYG":       "AMEX:HYG",
    "LQD":       "AMEX:LQD",
    # Sector ETFs
    "XLF":       "AMEX:XLF",
    "XLE":       "AMEX:XLE",
    "XLK":       "AMEX:XLK",
    "XLV":       "AMEX:XLV",
    "XLU":       "AMEX:XLU",
    "XLI":       "AMEX:XLI",
    # EU equity indices
    "^STOXX50E": "INDEX:STOXX50E",
    "^GDAXI":    "XETR:DAX",
    "^FTSE":     "FOREXCOM:UK100",
    "^FCHI":     "EURONEXT:CAC40",
    "FTSEMIB.MI":"INDEX:FTSEMIB",
    "^IBEX":     "BME:IBEX",
    # FX
    "EURUSD=X":  "FX:EURUSD",
    "GBPUSD=X":  "FX:GBPUSD",
    "JPY=X":     "FX:USDJPY",
    "CHF=X":     "FX:USDCHF",
    # FRED series with tradeable equivalents
    "10y_yield":     "TVC:US10Y",
    "2y_yield":      "TVC:US02Y",
    "30y_yield":     "TVC:US30Y",
    "eu_10y_yield":  "TVC:EU10Y",
    "de_10y_yield":  "TVC:DE10Y",
    "it_10y_yield":  "TVC:IT10Y",
    "fr_10y_yield":  "TVC:FR10Y",
    "es_10y_yield":  "TVC:ES10Y",
    "uk_10y_yield":  "TVC:GB10Y",
    "eur_usd":       "FX:EURUSD",
}


def tradingview_url(symbol_key: str) -> str:
    """
    Build a TradingView chart URL for a given internal ticker/series key.
    Returns None if no mapping exists.
    """
    tv_symbol = TRADINGVIEW_SYMBOLS.get(symbol_key)
    if not tv_symbol:
        return None
    return f"https://www.tradingview.com/chart/?symbol={tv_symbol}"
