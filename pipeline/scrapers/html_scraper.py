"""
HTML Page Scraper — scrapes article lists from news websites.

Each source in sources.json has CSS selectors for:
  - article_list: container for each article
  - title: article title element
  - link: article link element
  - content: article content (on detail page)
  - date: publish date element
"""

import logging
from datetime import datetime, timezone
from typing import List
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from pipeline.models import Article

logger = logging.getLogger("media_monitor.html")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en,*;q=0.5",
}


def scrape_single_html_source(source: dict) -> List[Article]:
    """Scrape article list from a single HTML source."""
    name = source["name"]

    if not source.get("enabled", True):
        logger.debug(f"[{name}] Disabled — skipping")
        return []

    list_page = source.get("list_page", source["url"])
    bias = source.get("bias", "neutral")
    selectors = source.get("selectors", {})

    if not selectors.get("article_list"):
        logger.warning(f"[{name}] No selectors configured — skipping")
        return []

    try:
        resp = requests.get(list_page, timeout=15, headers=HEADERS)
        if resp.status_code != 200:
            logger.warning(f"[{name}] HTTP {resp.status_code} from {list_page}")
            return []

        soup = BeautifulSoup(resp.content, "html.parser")
        article_elements = soup.select(selectors["article_list"])

        if not article_elements:
            logger.warning(f"[{name}] No articles found with selector '{selectors['article_list']}'")
            return []

        articles = []
        for el in article_elements[:15]:  # Limit to 15 per source
            # Extract title
            title_el = el.select_one(selectors.get("title", "h2 a"))
            title = title_el.get_text(strip=True) if title_el else ""

            # Extract link
            link_el = el.select_one(selectors.get("link", "a"))
            href = link_el.get("href", "") if link_el else ""
            if href and not href.startswith("http"):
                href = urljoin(source["url"], href)

            if not href:
                continue

            # Extract date if available
            date_el = el.select_one(selectors.get("date", "time"))
            published_at = None
            if date_el:
                date_text = date_el.get("datetime", "") or date_el.get_text(strip=True)
                # Simple date parsing — production may need dateutil
                try:
                    for fmt in ["%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%d.%m.%Y %H:%M", "%d.%m.%Y"]:
                        try:
                            published_at = datetime.strptime(date_text[:19], fmt)
                            break
                        except ValueError:
                            continue
                except Exception:
                    pass

            article = Article(
                url=href,
                source=name,
                bias=bias,
                source_type="html",
                title=title,
                content="",  # Will be filled by fetch_article_content if needed
                published_at=published_at or datetime.now(timezone.utc),
            )
            articles.append(article)

        # Fetch content for top articles (limit to avoid slow scraping)
        for article in articles[:5]:
            _fetch_article_content(article, selectors.get("content", "div.entry-content"))

        # Compute hashes after content is fetched
        for article in articles:
            if article.content:
                article.compute_hash()

        logger.info(f"[{name}] Scraped {len(articles)} articles via HTML")
        return articles

    except requests.exceptions.Timeout:
        logger.warning(f"[{name}] Timeout fetching {list_page}")
        return []
    except Exception as e:
        logger.error(f"[{name}] HTML scraping error: {e}")
        return []


def _fetch_article_content(article: Article, content_selector: str):
    """Fetch full article content from detail page."""
    try:
        resp = requests.get(article.url, timeout=10, headers=HEADERS)
        if resp.status_code != 200:
            return

        soup = BeautifulSoup(resp.content, "html.parser")
        content_el = soup.select_one(content_selector)
        if content_el:
            article.content = content_el.get_text(separator=" ", strip=True)[:3000]
        else:
            # Fallback: try common content selectors
            for fallback in ["article", "div.article-body", "div.post-content", "div.content", "main"]:
                content_el = soup.select_one(fallback)
                if content_el and len(content_el.get_text(strip=True)) > 100:
                    article.content = content_el.get_text(separator=" ", strip=True)[:3000]
                    break

    except Exception as e:
        logger.debug(f"[{article.source}] Could not fetch content for {article.url}: {e}")


def scrape_html_sources(sources: list) -> List[Article]:
    """Scrape all configured HTML sources. Returns flat list of articles."""
    all_articles = []
    for source in sources:
        articles = scrape_single_html_source(source)
        all_articles.extend(articles)
    return all_articles
