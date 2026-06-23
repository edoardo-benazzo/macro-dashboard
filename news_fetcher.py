"""
Macro news fetcher — 14 verified free RSS feeds across 6 categories.
No paid APIs, no scraping — pure RSS only.
"""

import concurrent.futures
import email.utils
import html
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import requests
import streamlit as st

# ── Feed definitions ──────────────────────────────────────────────────────────

FEEDS = [
    # Central Banks
    {"url": "https://www.federalreserve.gov/feeds/press_all.xml",
     "source": "FED",        "default_category": "CENTRAL BANKS"},
    {"url": "https://www.ecb.europa.eu/rss/press.html",
     "source": "ECB",        "default_category": "CENTRAL BANKS"},
    {"url": ("https://news.google.com/rss/search"
             "?q=reuters+economy+central+bank+inflation+monetary+policy"
             "&hl=en-US&gl=US&ceid=US:en"),
     "source": "REUTERS",    "default_category": "MACRO"},
    {"url": "https://feeds.bbci.co.uk/news/business/rss.xml",
     "source": "BBC",        "default_category": "MACRO"},
    # Geopolitical
    {"url": ("https://news.google.com/rss/search"
             "?q=reuters+world+geopolitics+conflict+war+sanctions"
             "&hl=en-US&gl=US&ceid=US:en"),
     "source": "REUTERS",    "default_category": "GEOPOLITICAL"},
    {"url": "https://www.aljazeera.com/xml/rss/all.xml",
     "source": "AL JAZEERA", "default_category": "GEOPOLITICAL"},
    {"url": "https://feeds.bbci.co.uk/news/world/rss.xml",
     "source": "BBC WORLD",  "default_category": "GEOPOLITICAL"},
    {"url": "https://apnews.com/index.rss",
     "source": "AP",         "default_category": "GEOPOLITICAL"},
    # Markets
    {"url": ("https://news.google.com/rss/search"
             "?q=reuters+markets+stocks+bonds+dollar+yields"
             "&hl=en-US&gl=US&ceid=US:en"),
     "source": "REUTERS",    "default_category": "MARKETS"},
    {"url": "https://www.forbes.com/business/feed/",
     "source": "FORBES",     "default_category": "MARKETS"},
    # Tech / AI
    {"url": "https://techcrunch.com/feed",
     "source": "TECHCRUNCH", "default_category": "TECH & AI"},
    {"url": "https://www.theverge.com/rss/index.xml",
     "source": "THE VERGE",  "default_category": "TECH & AI"},
    # Europe
    {"url": "https://www.euractiv.com/feed/",
     "source": "EURACTIV",   "default_category": "MACRO"},
    {"url": "https://rss.dw.com/xml/rss-en-all",
     "source": "DW",         "default_category": "GEOPOLITICAL"},
]

# ── Noise filter ──────────────────────────────────────────────────────────────

_NOISE_KEYWORDS = [
    "form 4", "sec filing", "insider", "earnings per share",
    "quarterly results", "dividend", "buyback", "price target",
    "analyst rating", "stock split",
]


def _is_noise(title: str) -> bool:
    lc = title.lower()
    return any(kw in lc for kw in _NOISE_KEYWORDS)


# ── Auto-classification ───────────────────────────────────────────────────────

_CAT_RULES = [
    ("CENTRAL BANKS", [
        "federal reserve", "fomc", "fed funds", " ecb ", "european central bank",
        "bank of england", "bank of japan", " boe ", " boj ", "rate decision",
        "basis points", "monetary policy", "central bank", "interest rate hike",
        "interest rate cut", "quantitative easing", "quantitative tightening",
        "powell", "lagarde", "rate hike", "rate cut", "fed meeting",
    ]),
    ("GEOPOLITICAL", [
        " war ", "conflict", "sanction", "geopolit", "trade war", "tariff",
        "military ", "troops", "missile", "nato ", "ceasefire", "invasion",
        "armed forces", "nuclear", "coup ", "diplomacy", "attack on",
        "election result", "vote ", "treaty",
    ]),
    ("MACRO", [
        " cpi ", " pce ", " ppi ", "inflation", " gdp ",
        " nfp ", "nonfarm", "payroll", " pmi ", "trade balance",
        "retail sales", "unemployment", "jobs report", "recession",
        "consumer price", "producer price", "economic growth",
        "jobless claims", "jolts", "industrial output", "core inflation",
    ]),
    ("TECH & AI", [
        "artificial intelligence", " ai ", "ai model", "ai chip",
        "nvidia", "openai", "semiconductor", "chipmaker", "chatgpt",
        "machine learning", "deepseek", "anthropic", "google deepmind",
        "large language model", "generative ai", "silicon valley",
    ]),
    ("MARKETS", [
        "s&p 500", "s&p500", "nasdaq", "dow jones", "treasury yield",
        "bond yield", "us dollar", "dollar index", "oil price", "gold price",
        "stock market", "wall street", "equity market", "bear market",
        "bull market", "market rally", "market selloff", "hedge fund",
        "etf ", "commodity prices",
    ]),
]


def _classify(title: str, desc: str, default: str) -> str:
    text = (title + " " + desc).lower()
    for category, keywords in _CAT_RULES:
        if any(kw in text for kw in keywords):
            return category
    return default


# ── Timestamps ────────────────────────────────────────────────────────────────

def _time_ago(pub: datetime) -> str:
    if pub.tzinfo is None:
        pub = pub.replace(tzinfo=timezone.utc)
    diff = datetime.now(timezone.utc) - pub
    s = int(diff.total_seconds())
    if s < 0:
        return "just now"
    if s < 300:
        return "just now"
    if s < 3600:
        m = s // 60
        return f"{m} min ago"
    if s < 86400:
        h = s // 3600
        return f"{h} hr ago"
    d = s // 86400
    return f"{d} day{'s' if d != 1 else ''} ago"


def _parse_date(date_str: str) -> datetime:
    if not date_str:
        return datetime.now(timezone.utc)
    try:
        return email.utils.parsedate_to_datetime(date_str)
    except Exception:
        pass
    try:
        clean = date_str.strip().replace("Z", "+00:00")
        return datetime.fromisoformat(clean)
    except Exception:
        return datetime.now(timezone.utc)


# ── HTML cleanup ──────────────────────────────────────────────────────────────

def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


# ── Feed parsing ──────────────────────────────────────────────────────────────

_ATOM_NS = "http://www.w3.org/2005/Atom"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; MacroDashboard/3.0; educational)"}


def _make_item(title: str, link: str, pub: datetime,
               source: str, default_cat: str, feed_url: str,
               desc: str = "") -> dict:
    # Strip "Title - Publisher" suffix added by Google News
    if "news.google.com" in feed_url and " - " in title:
        parts = title.rsplit(" - ", 1)
        if len(parts) == 2 and len(parts[1]) < 50:
            title = parts[0].strip()
    category = _classify(title, desc, default_cat)
    return {
        "title":    title,
        "link":     link,
        "pub":      pub,
        "time_ago": _time_ago(pub),
        "source":   source,
        "category": category,
    }


def _parse_feed(url: str, source: str, default_category: str,
                timeout: int = 10) -> list[dict]:
    try:
        resp = requests.get(url, timeout=timeout, headers=_HEADERS)
        resp.raise_for_status()
        content = resp.content
        # Strip UTF-8 BOM
        if content.startswith(b"\xef\xbb\xbf"):
            content = content[3:]

        root = ET.fromstring(content)
        tag  = root.tag
        items: list[dict] = []

        if tag == f"{{{_ATOM_NS}}}feed":
            # Atom 1.0 (e.g. The Verge)
            for entry in root.findall(f"{{{_ATOM_NS}}}entry")[:12]:
                title = _strip_html(entry.findtext(f"{{{_ATOM_NS}}}title", ""))
                link_el = entry.find(f"{{{_ATOM_NS}}}link")
                link = ""
                if link_el is not None:
                    link = link_el.get("href", "") or link_el.text or ""
                pub_str = (entry.findtext(f"{{{_ATOM_NS}}}published") or
                           entry.findtext(f"{{{_ATOM_NS}}}updated") or "")
                desc = _strip_html(
                    entry.findtext(f"{{{_ATOM_NS}}}summary", "") or
                    entry.findtext(f"{{{_ATOM_NS}}}content", "")
                )[:200]
                pub = _parse_date(pub_str)
                if title:
                    items.append(_make_item(title, link, pub, source,
                                            default_category, url, desc))
        else:
            # RSS 2.0
            channel = root.find("channel") or root
            for item in channel.findall("item")[:12]:
                title = _strip_html(item.findtext("title", ""))
                link  = (item.findtext("link", "") or "").strip()
                pub   = _parse_date(item.findtext("pubDate", ""))
                desc  = _strip_html(item.findtext("description", ""))[:200]
                if title:
                    items.append(_make_item(title, link, pub, source,
                                            default_category, url, desc))
        return items
    except Exception:
        return []


# ── Public API ────────────────────────────────────────────────────────────────

@st.cache_data(ttl=60 * 15)
def fetch_all_news() -> list[dict]:
    """Aggregate news from all RSS sources — sorted newest-first, deduplicated."""
    all_items: list[dict] = []

    def _fetch(feed: dict) -> list[dict]:
        return _parse_feed(
            feed["url"], feed["source"], feed["default_category"]
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=7) as ex:
        futures = [ex.submit(_fetch, f) for f in FEEDS]
        for fut in concurrent.futures.as_completed(futures, timeout=25):
            try:
                all_items.extend(fut.result())
            except Exception:
                pass

    # Filter noise, sort newest-first, deduplicate by title slug
    filtered = [a for a in all_items if not _is_noise(a["title"])]
    filtered.sort(key=lambda x: x["pub"], reverse=True)

    seen: set[str] = set()
    unique: list[dict] = []
    for item in filtered:
        slug = re.sub(r"\W+", "", item["title"].lower())[:60]
        if slug and slug not in seen:
            seen.add(slug)
            unique.append(item)

    return unique[:120]
