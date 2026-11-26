from typing import List
from pipeline.models import Article

URGENCY_EMOJI = {"CRITICAL":"❗️🔴❗️","HIGH":"❗️❗️","MEDIUM":"🟡","SKIP":"⚪"}
CATEGORY_LABELS = {"correction":"Public correction","announcement":"Announcement","coverage":"Coverage"}

def format_alert(article: Article) -> str:
    """Format a CRITICAL article into an individual alert message."""
    emoji = URGENCY_EMOJI.get(article.urgency, "❓")
    category = CATEGORY_LABELS.get(article.category, article.category)

    lines = [
        f"{emoji} {article.urgency} — {category}",
        "",
        f"📰 {article.headline or article.title}",
        "",
    ]

    if article.summary:
        lines.append(article.summary)
        lines.append("")

    lines.append(f"Source: {article.source} ({article.bias})")

    short_url = article.url
    lines.extend(["", f"🔗 {short_url}"])

    return "\n".join(lines)


def format_grouped_alert(articles: List[Article], is_update: bool = False) -> str:
    """Format a group of articles about the same event into one alert."""
    if len(articles) == 1 and not is_update:
        return format_alert(articles[0])

    # Use highest urgency from the group
    urgency_rank = {"CRITICAL": 3, "HIGH": 2, "MEDIUM": 1, "SKIP": 0}
    articles = sorted(articles, key=lambda a: urgency_rank.get(a.urgency, 0), reverse=True)
    best = articles[0]

    if is_update:
        emoji = "🔄"
    else:
        emoji = URGENCY_EMOJI.get(best.urgency, "❓")
    category = CATEGORY_LABELS.get(best.category, best.category)

    # Pick the best headline (longest complete one)
    headline = best.headline or best.title
    for a in articles:
        h = a.headline or a.title
        if len(h) > len(headline) and h[-1] not in "abcdefghijklmnopqrstuvwxyz":
            headline = h

    # Pick the best summary (most detailed)
    summary = best.summary or ""
    for a in articles:
        if a.summary and len(a.summary) > len(summary):
            summary = a.summary

    # List all sources
    sources = ", ".join(dict.fromkeys(a.source for a in articles))

    # Use URL from best article
    short_url = best.url

    urgency_label = "UPDATE" if is_update else best.urgency
    lines = [
        f"{emoji} {urgency_label} — {category}",
        "",
        f"📰 {headline}",
        "",
    ]
    if summary:
        lines.append(summary)
        lines.append("")
    lines.append(f"Sources: {sources}")
    lines.extend(["", f"🔗 {short_url}"])

    return "\n".join(lines)


def _format_digest_item(article: Article) -> str:
    """Format a single article for inclusion in a digest."""
    short_url = article.url
    category = CATEGORY_LABELS.get(article.category, "")
    tag = f"[{category}] " if category else ""
    lines = [
        f"📰 {tag}{article.headline or article.title}",
    ]
    if article.summary:
        lines.append(article.summary)
    lines.append(f"Source: {article.source} ({article.bias}) | 🔗 {short_url}")
    return "\n".join(lines)


def _format_grouped_digest_item(articles: List[Article]) -> str:
    """Format a group of same-event articles as one digest item."""
    if len(articles) == 1:
        return _format_digest_item(articles[0])

    # Pick best headline and summary
    best = articles[0]
    headline = best.headline or best.title
    summary = best.summary or ""
    for a in articles:
        h = a.headline or a.title
        if len(h) > len(headline):
            headline = h
        if a.summary and len(a.summary) > len(summary):
            summary = a.summary

    category = CATEGORY_LABELS.get(best.category, "")
    tag = f"[{category}] " if category else ""
    sources = ", ".join(dict.fromkeys(a.source for a in articles))
    short_url = best.url

    lines = [f"📰 {tag}{headline}"]
    if summary:
        lines.append(summary)
    lines.append(f"Sources: {sources} | 🔗 {short_url}")
    return "\n".join(lines)
