"""
RSS Feed Scraper — fetches articles from news RSS feeds.
"""

import logging
from datetime import datetime, timezone
from typing import List

import feedparser
import requests
from bs4 import BeautifulSoup

from pipeline.models import Article

logger = logging.getLogger("media_monitor.rss")

HEADERS = {
    "User-Agent": "MediaMonitor/1.0 (News Aggregator)",
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}


def scrape_single_feed(source: dict) -> List[Article]:
    """Scrape articles from a single RSS source config entry."""
    name = source["name"]
    rss_url = source["rss_url"]
    bias = source.get("bias", "neutral")

    try:
        resp = requests.get(rss_url, timeout=15, headers=HEADERS)
        if resp.status_code != 200:
            logger.warning(f"[{name}] HTTP {resp.status_code} from {rss_url}")
            return []

        feed = feedparser.parse(resp.content)
        if not feed.entries:
            logger.warning(f"[{name}] No entries in feed")
            return []

        articles = []
        for entry in feed.entries:
            # Extract content — try content > summary > description
            content = ""
            if entry.get("content"):
                content = entry.content[0].get("value", "")
            elif entry.get("summary"):
                content = entry.get("summary", "")
            elif entry.get("description"):
                content = entry.get("description", "")

            # Strip HTML from content
            if content and ("<" in content):
                soup = BeautifulSoup(content, "html.parser")
                content = soup.get_text(separator=" ", strip=True)

            # Parse publish date
            published_at = None
            parsed_time = entry.get("published_parsed") or entry.get("updated_parsed")
            if parsed_time:
                try:
                    published_at = datetime(*parsed_time[:6])
                except Exception:
                    pass

            url = entry.get("link", "")
            if not url:
                continue

            article = Article(
                url=url,
                source=name,
                bias=bias,
                source_type="rss",
                title=entry.get("title", "").strip(),
                content=content[:3000],  # Limit content length
                published_at=published_at or datetime.now(timezone.utc),
            )
            article.compute_hash()
            articles.append(article)

        logger.info(f"[{name}] Scraped {len(articles)} articles via RSS")
        return articles

    except requests.exceptions.Timeout:
        logger.warning(f"[{name}] Timeout fetching {rss_url}")
        return []
    except Exception as e:
        logger.error(f"[{name}] RSS error: {e}")
        return []


def scrape_rss_sources(sources: list) -> List[Article]:
    """Scrape all configured RSS sources. Returns flat list of articles."""
    all_articles = []
    for source in sources:
        articles = scrape_single_feed(source)
        all_articles.extend(articles)
    return all_articles
