"""
Macro news fetcher — 38 direct + curated RSS feeds.
48-hour recency filter, 5-minute cache, up to 300 unique articles.
"""

import concurrent.futures
import datetime
import email.utils
import hashlib
import html
import re
import xml.etree.ElementTree as ET

import requests
import streamlit as st

# ── Source credibility tier ───────────────────────────────────────────────────
_SOURCE_TIER: dict[str, int] = {
    # Tier 1 — wire / institutional
    "REUTERS":         1, "AP":              1, "FED":            1,
    "ECB":             1, "BLOOMBERG":       1,
    # Tier 2 — quality press
    "BBC":             2, "BBC WORLD":       2, "DW":             2,
    "EURACTIV":        2, "WSJ":             2, "FT":             2,
    "CNBC":            2, "MARKETWATCH":     2, "AXIOS":          2,
    "THE ECONOMIST":   2, "POLITICO":        2, "POLITICO EU":    2,
    "FOREIGN POLICY":  2, "CFR":             2,
    # Tier 3 — commentary / general
    "AL JAZEERA":      3, "FORBES":          3, "TECHCRUNCH":     3,
    "THE VERGE":       3, "SEEKING ALPHA":   3, "YAHOO FINANCE":  3,
    "INVESTING.COM":   3, "EURONEWS":        3, "TASS":           3,
    "KYIV INDEPENDENT": 3,
}

SOURCE_TIER_COLOR: dict[int, str] = {
    1: "#E2E8F0",   # wire / institutional — bright white
    2: "#8BA0B8",   # quality press — medium grey
    3: "#4A607A",   # commentary — dim grey
}

# ── Feed definitions ──────────────────────────────────────────────────────────
FEEDS = [
    # ── Central Banks ───────────────────────────────────────────────────
    {"url": "https://www.federalreserve.gov/feeds/press_all.xml",
     "source": "FED",        "default_category": "CENTRAL BANKS"},
    {"url": "https://www.ecb.europa.eu/rss/press.html",
     "source": "ECB",        "default_category": "CENTRAL BANKS"},

    # ── Reuters (direct + Google News for gated sections) ──────────────
    {"url": "https://feeds.reuters.com/reuters/businessNews",
     "source": "REUTERS",    "default_category": "MACRO"},
    {"url": "https://feeds.reuters.com/Reuters/worldNews",
     "source": "REUTERS",    "default_category": "GEOPOLITICAL"},
    {"url": "https://feeds.reuters.com/reuters/financialNews",
     "source": "REUTERS",    "default_category": "MARKETS"},
    {"url": ("https://news.google.com/rss/search?q=when:24h+allinurl:reuters.com"
             "+politics+OR+sanctions+OR+war+OR+conflict+OR+election"
             "&hl=en&gl=US&ceid=US:en"),
     "source": "REUTERS",    "default_category": "GEOPOLITICAL"},

    # ── AP ──────────────────────────────────────────────────────────────
    {"url": "https://apnews.com/index.rss",
     "source": "AP",         "default_category": "GEOPOLITICAL"},
    {"url": "https://apnews.com/apf-businessnews",
     "source": "AP",         "default_category": "MACRO"},
    {"url": "https://apnews.com/world-news",
     "source": "AP",         "default_category": "GEOPOLITICAL"},

    # ── BBC ─────────────────────────────────────────────────────────────
    {"url": "https://feeds.bbci.co.uk/news/business/rss.xml",
     "source": "BBC",        "default_category": "MACRO"},
    {"url": "https://feeds.bbci.co.uk/news/world/rss.xml",
     "source": "BBC WORLD",  "default_category": "GEOPOLITICAL"},
    {"url": "https://feeds.bbci.co.uk/news/world/middle_east/rss.xml",
     "source": "BBC WORLD",  "default_category": "GEOPOLITICAL"},
    {"url": "https://feeds.bbci.co.uk/news/world/asia/rss.xml",
     "source": "BBC WORLD",  "default_category": "GEOPOLITICAL"},
    {"url": "https://feeds.bbci.co.uk/news/world/europe/rss.xml",
     "source": "BBC WORLD",  "default_category": "GEOPOLITICAL"},

    # ── WSJ ─────────────────────────────────────────────────────────────
    {"url": "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
     "source": "WSJ",        "default_category": "MARKETS"},
    {"url": "https://feeds.a.dj.com/rss/RSSEconomy.xml",
     "source": "WSJ",        "default_category": "MACRO"},

    # ── Bloomberg (via Google News — no public RSS) ─────────────────────
    {"url": ("https://news.google.com/rss/search?q=when:24h+site:bloomberg.com"
             "+economy+OR+markets+OR+fed+OR+ecb+OR+inflation"
             "&hl=en&gl=US&ceid=US:en"),
     "source": "BLOOMBERG",  "default_category": "MARKETS"},

    # ── FT (via Google News) ────────────────────────────────────────────
    {"url": ("https://news.google.com/rss/search?q=when:24h+site:ft.com"
             "+economy+OR+markets+OR+inflation+OR+fed+OR+ecb"
             "&hl=en&gl=US&ceid=US:en"),
     "source": "FT",         "default_category": "MACRO"},

    # ── The Economist (via Google News) ─────────────────────────────────
    {"url": ("https://news.google.com/rss/search?q=when:24h+site:economist.com"
             "+economy+OR+finance+OR+markets"
             "&hl=en&gl=US&ceid=US:en"),
     "source": "THE ECONOMIST", "default_category": "MACRO"},

    # ── CNBC ────────────────────────────────────────────────────────────
    {"url": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=20910258",
     "source": "CNBC",       "default_category": "MACRO"},
    {"url": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664",
     "source": "CNBC",       "default_category": "MARKETS"},

    # ── MarketWatch ─────────────────────────────────────────────────────
    {"url": "https://feeds.marketwatch.com/marketwatch/economy-politics/",
     "source": "MARKETWATCH", "default_category": "MACRO"},

    # ── Yahoo Finance ───────────────────────────────────────────────────
    {"url": "https://finance.yahoo.com/news/rssindex",
     "source": "YAHOO FINANCE", "default_category": "MARKETS"},

    # ── Axios Markets ───────────────────────────────────────────────────
    {"url": "https://api.axios.com/feed/markets",
     "source": "AXIOS",      "default_category": "MARKETS"},

    # ── Seeking Alpha Economy ───────────────────────────────────────────
    {"url": "https://seekingalpha.com/feed/economy.xml",
     "source": "SEEKING ALPHA", "default_category": "MACRO"},

    # ── Investing.com (via Google News) ─────────────────────────────────
    {"url": ("https://news.google.com/rss/search?q=when:24h+site:investing.com"
             "+macro+OR+central+bank+OR+inflation+OR+GDP"
             "&hl=en&gl=US&ceid=US:en"),
     "source": "INVESTING.COM", "default_category": "MACRO"},

    # ── Geopolitical ────────────────────────────────────────────────────
    {"url": "https://www.aljazeera.com/xml/rss/all.xml",
     "source": "AL JAZEERA", "default_category": "GEOPOLITICAL"},
    {"url": "https://rss.dw.com/xml/rss-en-all",
     "source": "DW",         "default_category": "GEOPOLITICAL"},
    {"url": "https://www.euractiv.com/feed/",
     "source": "EURACTIV",   "default_category": "MACRO"},
    {"url": "https://www.politico.com/rss/politics08.xml",
     "source": "POLITICO",   "default_category": "GEOPOLITICAL"},
    {"url": "https://www.politico.eu/feed/",
     "source": "POLITICO EU", "default_category": "GEOPOLITICAL"},
    {"url": ("https://news.google.com/rss/search?q=when:24h+site:foreignpolicy.com"
             "&hl=en&gl=US&ceid=US:en"),
     "source": "FOREIGN POLICY", "default_category": "GEOPOLITICAL"},
    {"url": "https://www.cfr.org/rss.xml",
     "source": "CFR",        "default_category": "GEOPOLITICAL"},
    {"url": "https://feeds.feedburner.com/euronews/en/news/",
     "source": "EURONEWS",   "default_category": "GEOPOLITICAL"},
    {"url": "https://tass.com/rss/v2.xml",
     "source": "TASS",       "default_category": "GEOPOLITICAL"},
    {"url": "https://kyivindependent.com/feed/",
     "source": "KYIV INDEPENDENT", "default_category": "GEOPOLITICAL"},

    # ── Tech / AI ───────────────────────────────────────────────────────
    {"url": "https://techcrunch.com/feed",
     "source": "TECHCRUNCH", "default_category": "TECH & AI"},
    {"url": "https://www.theverge.com/rss/index.xml",
     "source": "THE VERGE",  "default_category": "TECH & AI"},
]

# ── Noise blocklist ───────────────────────────────────────────────────────────
_NOISE_KEYWORDS = [
    "form 4", "sec filing", "insider trading", "earnings per share",
    "quarterly results", "dividend", "buyback", "price target",
    "analyst rating", "stock split",
    "world cup", "soccer", "nba ", "nfl ", "mlb ", "nhl ",
    " sports", "celebrity", "entertainment", "lifestyle", "fashion",
    "travel", "food", "recipe", "ronaldo", "messi", "oscar", "grammy",
    "movie", "tv show", "netflix series", "premier league",
    "champions league", "super bowl", "wimbledon", "olympics",
    "football", "basketball", "baseball",
]


def _is_noise(title: str) -> bool:
    lc = title.lower()
    return any(kw in lc for kw in _NOISE_KEYWORDS)


# ── Auto-classification ───────────────────────────────────────────────────────
# Priority order: CENTRAL BANKS > MACRO > GEOPOLITICAL > MARKETS > TECH & AI
# Default for no match: MARKETS
_CAT_RULES = [
    ("CENTRAL BANKS", [
        " fed ", "federal reserve", "fomc", " ecb ", "european central bank",
        " boe ", "bank of england", " boj ", "bank of japan", "central bank",
        "rate decision", "interest rate", "monetary policy", "rate hike",
        "rate cut", "hawkish", "dovish", "basis points",
        "quantitative easing", "quantitative tightening", "jerome powell",
        "christine lagarde", "andrew bailey", "rate meeting", "policy meeting",
        "bond buying", "tapering", "balance sheet",
    ]),
    ("MACRO", [
        "inflation", " cpi ", " pce ", "hicp", " gdp ", "growth", "recession",
        "unemployment", " jobs ", "payroll", " nfp ", "nonfarm", " pmi ",
        "manufacturing", "retail sales", "trade balance", "trade deficit",
        "trade surplus", "fiscal", "budget", "deficit", "sovereign",
        "yield curve", "economic data", "economic growth", "economic slowdown",
        "output", "productivity", "supply chain", "commodity prices",
        "energy prices", "food prices", "housing", "real estate", "mortgage",
        "consumer confidence", " ism ", "industrial production", "factory",
        "export", "import", "current account", "treasury",
    ]),
    ("GEOPOLITICAL", [
        " war ", "conflict", "military", "sanctions", "geopolitical", "election",
        " vote ", "referendum", "coup ", "protest", "unrest", "nuclear", "missile",
        " attack ", "bombing", "ceasefire", "peace deal", "treaty", "diplomat",
        "invasion", "occupation", "territory ", "border", "nato ", "un resolution",
        " g7 ", " g20 ", " opec ", "oil embargo", "trade war", "tariff",
        "alliance", "security", "terrorism", "extremism", "hostage", "crisis",
    ]),
    ("MARKETS", [
        " stock ", "equity", " shares ", " market ", " index ", "rally", "selloff",
        "correction", " bull ", " bear ", "volatility", " vix ", "dollar",
        "currency", "forex", " bonds ", "yield", "spread", "credit",
        "commodity", " oil ", " gold ", "silver", "copper", "bitcoin", "crypto",
        " ipo ", "merger", "acquisition", "earnings", "profit", "revenue",
        "valuation", "hedge fund", "investment bank", "portfolio", " asset ",
        " fund ", " etf ", "derivatives",
    ]),
    ("TECH & AI", [
        "artificial intelligence", " ai ", "machine learning", "semiconductor",
        " chip ", "nvidia", "openai", "google ai", "microsoft ai", "automation",
        "robot", " tech ", "technology", "software", "hardware", "startup",
        "venture capital", "silicon valley", "data center", "computing", "digital",
    ]),
]


def _classify(title: str, desc: str, default: str) -> str:
    text = " " + (title + " " + desc).lower() + " "
    for category, keywords in _CAT_RULES:
        if any(kw in text for kw in keywords):
            return category
    return "MARKETS"  # never leave uncategorized


# ── Importance scoring (3=HIGH · 2=MED · 1=LOW) ──────────────────────────────
_HIGH_KW = [
    "fomc", "fed decision", "rate hike", "rate cut", "ecb decision",
    "ecb rate", "ecb meeting", " cpi ", "inflation print",
    " nfp ", "nonfarm payroll", " gdp ",
    "recession", "default", "sanctions", "war escalation", "nuclear",
    "financial crisis", "bank failure", "emergency",
    "central bank intervention", "yield curve", "debt ceiling",
    "quantitative easing", "quantitative tightening", " qe ", " qt ",
    "fed chair", "ecb president", " g7 ", " g20 ", " opec ",
    "oil embargo", "tariff announcement", "trade war", "election result",
    "geopolitical crisis", "market crash", "circuit breaker",
    "rate decision", "interest rate", "basis points", "monetary policy",
]

_MEDIUM_KW = [
    " pmi ", "unemployment", "retail sales", "trade balance",
    "earnings beat", "earnings miss", " ipo ", "merger", "acquisition",
    "bond yield", "dollar index", "commodity", "geopolitical tension",
    "protest", "strike", "policy change", "budget", "fiscal",
    "treasury", " imf ", "world bank", " wto ", "brics",
    "oil prices", "energy crisis",
]


def _importance_score(title: str, desc: str = "") -> int:
    text = " " + (title + " " + desc).lower() + " "
    if any(kw in text for kw in _HIGH_KW):
        return 3
    if any(kw in text for kw in _MEDIUM_KW):
        return 2
    return 1


# ── Market impact tags ────────────────────────────────────────────────────────
_IMPACT_RULES: list[tuple[list[str], str]] = [
    # ECB-specific first (before generic rate rules to avoid misclassification)
    (["ecb hikes", "ecb raises", "ecb rate hike", "ecb increases rates"],
     "EUR ↑ · EU Bonds ↓ · EU Equities ↓"),
    (["ecb cuts", "ecb lowers", "ecb rate cut", "ecb reduces rates"],
     "EUR ↓ · EU Bonds ↑ · EU Equities ↑"),
    # Generic central bank
    (["rate cut", "rates cut", "cut rates", "lower rates", "dovish", "pivots",
      "rate reduction", "easing", "accommodative", "slashes rates", "cuts rates"],
     "USD ↓ · Bonds ↑ · Equities ↑ · Gold ↑"),
    (["rate hike", "raises rates", "hike rates", "rate increase", "hawkish",
      "higher for longer", "tightening", "hikes by", "raises by"],
     "USD ↑ · Bonds ↓ · Equities ↓ · Gold ↓"),
    # Inflation
    (["inflation surges", "inflation beats", "inflation above", "cpi above",
      "hot cpi", "hotter than expected", "prices rose more",
      "inflation accelerates", "inflation jumps"],
     "USD ↑ · Bonds ↓ · Gold ↑ · Rate hike risk ↑"),
    (["inflation falls", "inflation cools", "cpi below", "disinflation",
      "inflation slows", "cool cpi", "cooler than expected", "inflation eases"],
     "USD ↓ · Bonds ↑ · Equities ↑ · Gold ↓"),
    # Jobs
    (["jobs beat", "nfp beat", "payroll beat", "strong jobs",
      "employment surges", "jobs above", "payrolls above", "hiring surges"],
     "USD ↑ · Bonds ↓ · Equities mixed"),
    (["jobs miss", "weak jobs", "payroll miss", "unemployment rises",
      "layoffs surge", "jobs below expectations"],
     "USD ↓ · Bonds ↑ · Recession risk ↑"),
    # GDP
    (["gdp beats", "gdp above", "economy grows faster", "strong gdp",
      "economic expansion", "gdp growth accelerates"],
     "USD ↑ · Equities ↑ · Bonds ↓"),
    (["gdp shrinks", "gdp contracts", "recession", "economic contraction",
      "economy contracts", "gdp falls"],
     "USD ↓ · Bonds ↑ · Equities ↓ · Gold ↑"),
    # Oil / OPEC
    (["opec cut", "oil sanctions", "oil embargo", "production cut",
      "oil supply cut", "opec+ cut"],
     "Oil ↑ · Airlines ↓ · Inflation ↑"),
    (["opec raises output", "oil supply increase", "production increase",
      "oil output rises", "opec boosts"],
     "Oil ↓ · Airlines ↑ · Inflation ↓"),
    # Geopolitical
    (["war escalation", "conflict escalates", "military strikes", "invasion",
      "airstrikes", "nuclear threat", "troops advance"],
     "Gold ↑ · Oil ↑ · Risk assets ↓"),
    (["ceasefire", "peace deal", "peace talks", "diplomatic agreement",
      "de-escalation", "truce announced"],
     "Risk assets ↑ · Oil ↓ · Gold ↓"),
    # Trade
    (["trade deal", "tariff removal", "trade agreement",
      "tariffs lifted", "trade truce"],
     "Risk assets ↑ · EM ↑ · USD ↓"),
    (["new tariffs", "tariffs announced", "tariff hike",
      "imposes tariffs", "trade war", "tariff escalation"],
     "USD ↑ · EM ↓ · Supply chain risk ↑"),
    # Banking / credit
    (["bank failure", "bank collapse", "bank runs", "credit crisis",
      "banking crisis", "bank default"],
     "Financials ↓ · Bonds ↑ · Gold ↑"),
]


def _market_impact(title: str, desc: str = "") -> str | None:
    text = " " + (title + " " + desc).lower() + " "
    for triggers, impact in _IMPACT_RULES:
        if any(kw in text for kw in triggers):
            return impact
    return None


# ── Time helpers ──────────────────────────────────────────────────────────────
def _time_ago(pub: datetime.datetime) -> str:
    if pub.tzinfo is None:
        pub = pub.replace(tzinfo=datetime.timezone.utc)
    s = int((datetime.datetime.now(datetime.timezone.utc) - pub).total_seconds())
    if s < 300:
        return "just now"
    if s < 3600:
        return f"{s // 60} min ago"
    if s < 86400:
        return f"{s // 3600} hr ago"
    d = s // 86400
    return f"{d} day{'s' if d != 1 else ''} ago"


def _parse_date(date_str: str) -> datetime.datetime | None:
    """Return timezone-aware datetime or None if unparseable."""
    if not date_str:
        return None
    try:
        return email.utils.parsedate_to_datetime(date_str)
    except Exception:
        pass
    try:
        return datetime.datetime.fromisoformat(
            date_str.strip().replace("Z", "+00:00")
        )
    except Exception:
        return None


# ── HTML cleanup ──────────────────────────────────────────────────────────────
def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _clean_title(title: str, feed_url: str) -> str:
    """Strip 'Article Title - Publisher' suffix from Google News feeds."""
    if "news.google.com" in feed_url and " - " in title:
        parts = title.rsplit(" - ", 1)
        if len(parts) == 2 and len(parts[1]) < 50:
            return parts[0].strip()
    return title


# ── Deduplication (≥60% word overlap within 3h → same story) ─────────────────
_STOP_WORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "in", "on", "at",
    "to", "of", "and", "or", "for", "with", "s", "its", "by", "as",
})


def _word_set(title: str) -> frozenset[str]:
    words = re.findall(r"\b\w+\b", title.lower())
    return frozenset(w for w in words if w not in _STOP_WORDS and len(w) > 1)


def _deduplicate(articles: list[dict]) -> list[dict]:
    articles = sorted(
        articles,
        key=lambda a: (_SOURCE_TIER.get(a["source"], 4), -a["pub"].timestamp()),
    )
    kept: list[dict] = []
    counts: dict[int, int] = {}

    for art in articles:
        ws = _word_set(art["title"])
        dupe_of = None
        for idx, k in enumerate(kept):
            if abs((art["pub"] - k["pub"]).total_seconds()) > 10_800:
                continue
            ks = _word_set(k["title"])
            shorter = min(len(ws), len(ks))
            if shorter and len(ws & ks) / shorter >= 0.60:
                dupe_of = idx
                break
        if dupe_of is not None:
            counts[dupe_of] = counts.get(dupe_of, 1) + 1
        else:
            kept.append(art)
            counts[len(kept) - 1] = 1

    for idx, art in enumerate(kept):
        art["source_count"] = counts.get(idx, 1)
    return kept


# ── Article identity ──────────────────────────────────────────────────────────
def article_id(art: dict) -> str:
    key = (art.get("title", "") + art.get("source", "")).encode()
    return hashlib.md5(key).hexdigest()[:10]


# ── Feed parsing ──────────────────────────────────────────────────────────────
_ATOM_NS = "http://www.w3.org/2005/Atom"
_HEADERS  = {"User-Agent": "Mozilla/5.0 (compatible; MacroDashboard/3.0; educational)"}


def _make_item(title: str, link: str, pub: datetime.datetime,
               source: str, default_cat: str, desc: str = "") -> dict:
    return {
        "title":         title,
        "link":          link,
        "pub":           pub,
        "time_ago":      _time_ago(pub),
        "source":        source,
        "source_tier":   _SOURCE_TIER.get(source, 3),
        "category":      _classify(title, desc, default_cat),
        "importance":    _importance_score(title, desc),
        "market_impact": _market_impact(title, desc),
        "source_count":  1,
    }


def _parse_feed(url: str, source: str, default_category: str,
                cutoff: datetime.datetime, timeout: int = 10) -> list[dict]:
    try:
        resp = requests.get(url, timeout=timeout, headers=_HEADERS)
        resp.raise_for_status()
        content = resp.content
        if content.startswith(b"\xef\xbb\xbf"):
            content = content[3:]

        root = ET.fromstring(content)
        items: list[dict] = []

        if root.tag == f"{{{_ATOM_NS}}}feed":
            for entry in root.findall(f"{{{_ATOM_NS}}}entry")[:15]:
                title = _strip_html(entry.findtext(f"{{{_ATOM_NS}}}title", ""))
                title = _clean_title(title, url)
                link_el = entry.find(f"{{{_ATOM_NS}}}link")
                link = link_el.get("href", "") if link_el is not None else ""
                pub_str = (entry.findtext(f"{{{_ATOM_NS}}}published") or
                           entry.findtext(f"{{{_ATOM_NS}}}updated") or "")
                pub = _parse_date(pub_str)
                if pub is None or pub < cutoff:
                    continue
                desc = _strip_html(
                    entry.findtext(f"{{{_ATOM_NS}}}summary", "") or
                    entry.findtext(f"{{{_ATOM_NS}}}content", "")
                )[:200]
                if title and not _is_noise(title):
                    items.append(_make_item(title, link, pub, source, default_category, desc))
        else:
            channel = root.find("channel") or root
            for item in channel.findall("item")[:15]:
                title = _strip_html(item.findtext("title", ""))
                title = _clean_title(title, url)
                link  = (item.findtext("link", "") or "").strip()
                pub   = _parse_date(item.findtext("pubDate", ""))
                if pub is None or pub < cutoff:
                    continue
                desc  = _strip_html(item.findtext("description", ""))[:200]
                if title and not _is_noise(title):
                    items.append(_make_item(title, link, pub, source, default_category, desc))
        return items
    except Exception:
        return []


# ── Public API ────────────────────────────────────────────────────────────────
@st.cache_data(ttl=60 * 5)
def fetch_all_news() -> dict:
    """
    Fetch, filter (48h), deduplicate, and score articles from 38 feeds.
    Returns {"articles": [...], "fetched_at": ISO timestamp string}.
    Articles sorted HIGH → MED → LOW, newest first within each tier.
    """
    cutoff = (
        datetime.datetime.now(datetime.timezone.utc) -
        datetime.timedelta(hours=48)
    )

    all_items: list[dict] = []

    def _fetch(feed: dict) -> list[dict]:
        return _parse_feed(
            feed["url"], feed["source"], feed["default_category"], cutoff
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as ex:
        futures = [ex.submit(_fetch, f) for f in FEEDS]
        for fut in concurrent.futures.as_completed(futures, timeout=30):
            try:
                all_items.extend(fut.result())
            except Exception:
                pass

    unique = _deduplicate(all_items)
    unique.sort(key=lambda a: (-a["importance"], -a["pub"].timestamp()))

    return {
        "articles":   unique[:300],
        "fetched_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
