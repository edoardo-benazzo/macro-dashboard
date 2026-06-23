"""
Macro news fetcher — pulls from free RSS feeds, classifies each headline
by market impact, and labels it MACRO or GEOPOLITICAL.
No API key required.
"""

import html
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import requests
import streamlit as st

# ── RSS feed sources ──────────────────────────────────────────────────────────

FEEDS = [
    # Macro / markets
    {"url": "https://feeds.reuters.com/reuters/businessNews",        "source": "REUTERS",     "category": "MACRO"},
    {"url": "https://www.cnbc.com/id/20910258/device/rss/rss.html",  "source": "CNBC",        "category": "MACRO"},
    {"url": "https://feeds.content.dowjones.io/public/rss/mw_marketpulse", "source": "MARKETWATCH", "category": "MACRO"},
    {"url": "https://www.investing.com/rss/news.rss",                "source": "INVESTING",   "category": "MACRO"},
    # Geopolitical
    {"url": "https://feeds.bbci.co.uk/news/world/rss.xml",           "source": "BBC WORLD",   "category": "GEOPOLITICAL"},
    {"url": "https://feeds.reuters.com/reuters/worldNews",           "source": "REUTERS",     "category": "GEOPOLITICAL"},
    {"url": "https://www.theguardian.com/world/rss",                 "source": "GUARDIAN",    "category": "GEOPOLITICAL"},
]

# ── Impact classification ─────────────────────────────────────────────────────

IMPACT_CATEGORIES = {
    "hawkish": {
        "keywords": [
            "rate hike", "hike rates", "tighten", "tightening", "hawkish",
            "higher for longer", "rate increase", "restrictive", "inflation fight",
            "keep rates high", "raise rates",
        ],
        "label": "HAWKISH", "css_class": "badge-hawkish",
    },
    "dovish": {
        "keywords": [
            "rate cut", "cut rates", "easing", "dovish", "pivot", "pause policy",
            "lower rates", "rate reduction", "accommodative", "stimulus package",
            "quantitative easing", "qe",
        ],
        "label": "DOVISH", "css_class": "badge-dovish",
    },
    "risk_off": {
        "keywords": [
            "recession", "contraction", "selloff", "sell-off", "market crash",
            "crisis", "downturn", "warning sign", "uncertainty", "slump", "fear",
            "volatility spike", "flight to safety",
        ],
        "label": "RISK-OFF", "css_class": "badge-risk-off",
    },
    "risk_on": {
        "keywords": [
            "rally", "surge", "bull market", "beat expectations", "strong growth",
            "better than expected", "recovery", "rebound", "record high", "boom",
            "risk appetite", "equities rise",
        ],
        "label": "RISK-ON", "css_class": "badge-risk-on",
    },
    "inflation": {
        "keywords": [
            "inflation", "cpi", "pce", "hicp", "price pressure", "price index",
            "prices rose", "prices fell", "consumer prices", "producer prices",
            "ppi", "cost of living", "price stability",
        ],
        "label": "INFLATION", "css_class": "badge-inflation",
    },
    "fed": {
        "keywords": [
            "federal reserve", " fed ", "fomc", "powell", "rate decision",
            "monetary policy", "fed chair", "fed meeting", "federal open market",
        ],
        "label": "FED", "css_class": "badge-fed",
    },
    "ecb": {
        "keywords": [
            "ecb", "european central bank", "lagarde", "eurozone", "euro area",
            "frankfurt", "deposit rate", "bce",
        ],
        "label": "ECB", "css_class": "badge-ecb",
    },
    "labor": {
        "keywords": [
            "jobs report", "employment", "unemployment", "payroll", "jobless claims",
            "labor market", "hiring", "layoffs", "nonfarm", "initial claims",
            "job openings", "jolts",
        ],
        "label": "LABOR", "css_class": "badge-labor",
    },
    "geopolitical": {
        "keywords": [
            "war", "sanctions", "geopolitical", "military", "trade war", "tariff",
            "escalation", "nato", "conflict", "weapons", "diplomatic",
        ],
        "label": "GEO-RISK", "css_class": "badge-geo",
    },
    "crypto": {
        "keywords": [
            "bitcoin", " btc ", "crypto", "cryptocurrency", "digital asset",
            "blockchain", "halving", "spot etf", "ethereum", "defi", "stablecoin",
        ],
        "label": "CRYPTO", "css_class": "badge-btc",
    },
}


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _time_ago(pub: datetime) -> str:
    """Return a human-readable elapsed time string, e.g. '34 minutes ago' or '2 hours ago'."""
    if pub.tzinfo is None:
        pub = pub.replace(tzinfo=timezone.utc)
    diff = datetime.now(timezone.utc) - pub
    s = int(diff.total_seconds())
    if s < 60:
        return "just now"
    if s < 3600:
        m = s // 60
        return f"{m} minute ago" if m == 1 else f"{m} minutes ago"
    if s < 86400:
        h = s // 3600
        return f"{h} hour ago" if h == 1 else f"{h} hours ago"
    d = s // 86400
    return f"{d} day ago" if d == 1 else f"{d} days ago"


def _parse_date(date_str: str) -> datetime:
    import email.utils
    try:
        return email.utils.parsedate_to_datetime(date_str)
    except Exception:
        return datetime.now(timezone.utc)


def _classify(title: str, description: str) -> list[str]:
    text = (title + " " + description).lower()
    matches = []
    for cat_key, cat in IMPACT_CATEGORIES.items():
        if any(kw in text for kw in cat["keywords"]):
            matches.append(cat_key)
    return matches[:4]


def _parse_feed(url: str, source: str, category: str, timeout: int = 8) -> list[dict]:
    try:
        resp = requests.get(
            url, timeout=timeout,
            headers={"User-Agent": "MacroDashboard/2.0 (educational)"}
        )
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        channel = root.find("channel")
        if channel is None:
            return []
        items = []
        for item in channel.findall("item")[:12]:
            title = _strip_html(item.findtext("title",       ""))
            desc  = _strip_html(item.findtext("description", ""))[:280]
            link  = (item.findtext("link", "") or "").strip()
            pub   = _parse_date(item.findtext("pubDate", ""))
            if not title:
                continue
            items.append({
                "source":   source,
                "category": category,
                "title":    title,
                "desc":     desc,
                "link":     link,
                "pub":      pub,
                "time_ago": _time_ago(pub),
                "tags":     _classify(title, desc),
            })
        return items
    except Exception:
        return []


@st.cache_data(ttl=60 * 30)
def fetch_all_macro_news() -> list[dict]:
    """Aggregate news from all RSS sources, sorted newest-first, deduplicated."""
    all_items = []
    for feed in FEEDS:
        all_items.extend(_parse_feed(feed["url"], feed["source"], feed["category"]))
    all_items.sort(key=lambda x: x["pub"], reverse=True)
    seen, unique = set(), []
    for item in all_items:
        slug = re.sub(r"\W+", "", item["title"].lower())[:60]
        if slug not in seen:
            seen.add(slug)
            unique.append(item)
    return unique[:60]
