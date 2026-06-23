"""
Macro news fetcher — 14 verified free RSS feeds across 6 categories.
No paid APIs, no scraping — pure RSS only.
"""

import concurrent.futures
import email.utils
import hashlib
import html
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import requests
import streamlit as st

# ── Source credibility tier ───────────────────────────────────────────────────
# 1 = wire/institutional  2 = quality press  3 = commentary/general

_SOURCE_TIER: dict[str, int] = {
    "REUTERS":     1,
    "AP":          1,
    "FED":         1,
    "ECB":         1,
    "BBC":         2,
    "BBC WORLD":   2,
    "DW":          2,
    "EURACTIV":    2,
    "AL JAZEERA":  3,
    "FORBES":      3,
    "TECHCRUNCH":  3,
    "THE VERGE":   3,
}

# Colour for source label — tier 1 = bright, tier 2 = mid-grey, tier 3 = dim
SOURCE_TIER_COLOR: dict[int, str] = {1: "#E2E8F0", 2: "#8BA0B8", 3: "#4A607A"}

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
    # Financial noise
    "form 4", "sec filing", "insider", "earnings per share",
    "quarterly results", "dividend", "buyback", "price target",
    "analyst rating", "stock split",
    # Sports / entertainment — not macro news
    "world cup", "soccer", "nba ", "nfl ", "celebrity",
    "lifestyle", "ronaldo", "messi", "premier league",
    "champions league", "super bowl", "wimbledon", "olympics",
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
    # Pad with spaces so space-wrapped keywords match at start/end of text
    text = " " + (title + " " + desc).lower() + " "
    for category, keywords in _CAT_RULES:
        if any(kw in text for kw in keywords):
            return category
    return default


# ── Importance scoring (1 LOW · 2 MEDIUM · 3 HIGH) ───────────────────────────

_HIGH_KW = [
    "fomc", "fed decision", "rate hike", "rate cut", "ecb decision",
    "ecb rate", "ecb meeting", "fed meeting", " cpi ", "inflation print",
    " nfp ", "nonfarm payroll", " gdp ",
    "recession", "default", "sanctions", "war escalation", "nuclear",
    "financial crisis", "bank failure", "emergency", "central bank intervention",
    "yield curve", "debt ceiling", "quantitative easing", "quantitative tightening",
    " qe ", " qt ", "fed chair", "ecb president", " g7 ", " g20 ", " opec ",
    "oil embargo", "tariff announcement", "trade war", "election result",
    "geopolitical crisis", "market crash", "circuit breaker",
]

_MEDIUM_KW = [
    " pmi ", "unemployment", "retail sales", "trade balance",
    "earnings beat", "earnings miss", " ipo ", "merger", "acquisition",
    "interest rate", "bond yield", "dollar index", "commodity", "equity",
    "geopolitical tension", "protest", "strike", "policy change",
    "budget", "fiscal", "treasury", " imf ", "world bank", " wto ", "brics",
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
    # ECB-specific rules checked BEFORE generic rate cut/hike to avoid misclassification
    (["ecb hikes", "ecb raises", "ecb rate hike", "ecb increases rates"],
     "EUR ↑ · EU Bonds ↓ · EU Equities ↓"),
    (["ecb cuts", "ecb lowers", "ecb rate cut", "ecb reduces rates"],
     "EUR ↓ · EU Bonds ↑ · EU Equities ↑"),
    # Generic central bank rules
    (["rate cut", "rates cut", "cut rates", "lower rates", "dovish", "pivots",
      "rate reduction", "easing", "accommodative", "slashes rates", "cuts rates"],
     "USD ↓ · Bonds ↑ · Equities ↑ · Gold ↑"),
    (["rate hike", "raises rates", "hike rates", "rate increase", "hawkish",
      "higher for longer", "tightening", "hikes by", "raises by"],
     "USD ↑ · Bonds ↓ · Equities ↓ · Gold ↓"),
    (["inflation surges", "inflation beats", "inflation above", "cpi above", "hot cpi",
      "hotter than expected", "prices rose more", "inflation accelerates", "inflation jumps"],
     "USD ↑ · Bonds ↓ · Gold ↑ · Rate hike risk ↑"),
    (["inflation falls", "inflation cools", "cpi below", "disinflation",
      "inflation slows", "cool cpi", "cooler than expected", "inflation eases"],
     "USD ↓ · Bonds ↑ · Equities ↑ · Gold ↓"),
    (["jobs beat", "nfp beat", "payroll beat", "strong jobs", "employment surges",
      "jobs above", "payrolls above", "hiring surges"],
     "USD ↑ · Bonds ↓ · Equities mixed"),
    (["jobs miss", "weak jobs", "payroll miss", "unemployment rises",
      "layoffs surge", "jobs below expectations"],
     "USD ↓ · Bonds ↑ · Recession risk ↑"),
    (["gdp beats", "gdp above", "economy grows faster", "strong gdp",
      "economic expansion", "gdp growth accelerates"],
     "USD ↑ · Equities ↑ · Bonds ↓"),
    (["gdp shrinks", "gdp contracts", "recession", "economic contraction",
      "economy contracts", "gdp falls"],
     "USD ↓ · Bonds ↑ · Equities ↓ · Gold ↑"),
    (["opec cut", "oil sanctions", "oil embargo", "production cut",
      "oil supply cut", "opec+ cut"],
     "Oil ↑ · Airlines ↓ · EM ↓ · Inflation ↑"),
    (["opec raises output", "oil supply increase", "production increase",
      "oil output rises", "opec boosts"],
     "Oil ↓ · Airlines ↑ · Inflation ↓"),
    (["war escalation", "conflict escalates", "military strikes", "invasion",
      "airstrikes", "nuclear threat", "troops advance"],
     "Gold ↑ · Oil ↑ · Risk assets ↓ · USD ↑"),
    (["ceasefire", "peace deal", "peace talks", "diplomatic agreement",
      "de-escalation", "truce announced"],
     "Risk assets ↑ · Oil ↓ · Gold ↓"),
    # Trade deal checked BEFORE tariff to avoid false match on "deal that removes tariffs"
    (["trade deal", "tariff removal", "trade agreement", "tariffs lifted",
      "trade truce"],
     "Risk assets ↑ · EM ↑ · USD ↓"),
    (["new tariffs", "tariffs announced", "tariff hike", "imposes tariffs",
      "trade war", "trade conflict", "tariff escalation"],
     "USD ↑ · EM ↓ · Supply chain risk ↑"),
    (["bank failure", "bank collapse", "bank runs", "credit crisis",
      "banking crisis", "bank default"],
     "Financials ↓ · Bonds ↑ · Gold ↑"),
    (["earnings beat", "profits beat", "revenue beat", "earnings above"],
     "Equities ↑ · Sector ↑"),
    (["earnings miss", "profits miss", "revenue miss", "earnings below"],
     "Equities ↓ · Sector ↓"),
]


def _market_impact(title: str, desc: str = "") -> str | None:
    text = " " + (title + " " + desc).lower() + " "
    for triggers, impact in _IMPACT_RULES:
        if any(kw in text for kw in triggers):
            return impact
    return None


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
        return datetime.fromisoformat(date_str.strip().replace("Z", "+00:00"))
    except Exception:
        return datetime.now(timezone.utc)


# ── HTML cleanup ──────────────────────────────────────────────────────────────

def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


# ── Deduplication ─────────────────────────────────────────────────────────────

_STOP_WORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "in", "on", "at",
    "to", "of", "and", "or", "for", "with", "s", "its", "by", "as",
})


def _word_set(title: str) -> frozenset[str]:
    words = re.findall(r"\b\w+\b", title.lower())
    return frozenset(w for w in words if w not in _STOP_WORDS and len(w) > 1)


def _deduplicate(articles: list[dict]) -> list[dict]:
    """Word-overlap dedup — keeps highest-tier source version of each story."""
    # Best tier first, then newest within same tier
    articles = sorted(
        articles,
        key=lambda a: (_SOURCE_TIER.get(a["source"], 4), -a["pub"].timestamp()),
    )

    kept: list[dict] = []
    counts: dict[int, int] = {}

    for art in articles:
        ws = _word_set(art["title"])
        dupe_of = None
        for idx, kept_art in enumerate(kept):
            if abs((art["pub"] - kept_art["pub"]).total_seconds()) > 10_800:
                continue
            ks = _word_set(kept_art["title"])
            shorter = min(len(ws), len(ks))
            if shorter == 0:
                continue
            if len(ws & ks) / shorter >= 0.60:
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
    """Stable short hash for session-state keying."""
    key = (art.get("title", "") + art.get("source", "")).encode()
    return hashlib.md5(key).hexdigest()[:10]


# ── Feed parsing ──────────────────────────────────────────────────────────────

_ATOM_NS = "http://www.w3.org/2005/Atom"
_HEADERS  = {"User-Agent": "Mozilla/5.0 (compatible; MacroDashboard/3.0; educational)"}


def _make_item(title: str, link: str, pub: datetime,
               source: str, default_cat: str, feed_url: str,
               desc: str = "") -> dict:
    # Strip "Title - Publisher" suffix added by Google News
    if "news.google.com" in feed_url and " - " in title:
        parts = title.rsplit(" - ", 1)
        if len(parts) == 2 and len(parts[1]) < 50:
            title = parts[0].strip()
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
                timeout: int = 10) -> list[dict]:
    try:
        resp = requests.get(url, timeout=timeout, headers=_HEADERS)
        resp.raise_for_status()
        content = resp.content
        if content.startswith(b"\xef\xbb\xbf"):
            content = content[3:]

        root = ET.fromstring(content)
        items: list[dict] = []

        if root.tag == f"{{{_ATOM_NS}}}feed":
            # Atom 1.0 (e.g. The Verge)
            for entry in root.findall(f"{{{_ATOM_NS}}}entry")[:12]:
                title = _strip_html(entry.findtext(f"{{{_ATOM_NS}}}title", ""))
                link_el = entry.find(f"{{{_ATOM_NS}}}link")
                link = link_el.get("href", "") if link_el is not None else ""
                pub_str = (entry.findtext(f"{{{_ATOM_NS}}}published") or
                           entry.findtext(f"{{{_ATOM_NS}}}updated") or "")
                desc = _strip_html(
                    entry.findtext(f"{{{_ATOM_NS}}}summary", "") or
                    entry.findtext(f"{{{_ATOM_NS}}}content", "")
                )[:200]
                pub = _parse_date(pub_str)
                if title:
                    items.append(_make_item(title, link, pub,
                                            source, default_category, url, desc))
        else:
            # RSS 2.0
            channel = root.find("channel") or root
            for item in channel.findall("item")[:12]:
                title = _strip_html(item.findtext("title", ""))
                link  = (item.findtext("link", "") or "").strip()
                pub   = _parse_date(item.findtext("pubDate", ""))
                desc  = _strip_html(item.findtext("description", ""))[:200]
                if title:
                    items.append(_make_item(title, link, pub,
                                            source, default_category, url, desc))
        return items
    except Exception:
        return []


# ── Public API ────────────────────────────────────────────────────────────────

@st.cache_data(ttl=60 * 15)
def fetch_all_news() -> list[dict]:
    """Fetch, deduplicate, score, and sort articles from all 14 RSS feeds."""
    all_items: list[dict] = []

    def _fetch(feed: dict) -> list[dict]:
        return _parse_feed(feed["url"], feed["source"], feed["default_category"])

    with concurrent.futures.ThreadPoolExecutor(max_workers=7) as ex:
        futures = [ex.submit(_fetch, f) for f in FEEDS]
        for fut in concurrent.futures.as_completed(futures, timeout=25):
            try:
                all_items.extend(fut.result())
            except Exception:
                pass

    # Filter noise
    filtered = [a for a in all_items if not _is_noise(a["title"])]

    # Word-overlap dedup, keeping best-tier source
    unique = _deduplicate(filtered)

    # Sort: HIGH first, then MEDIUM, then LOW; newest-first within each tier
    unique.sort(key=lambda a: (-a["importance"], -a["pub"].timestamp()))

    return unique[:120]
