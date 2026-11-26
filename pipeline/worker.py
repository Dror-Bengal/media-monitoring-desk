"""Collect, classify and deliver. One worker owns a state database at a time."""
from collections import defaultdict
from datetime import datetime, timezone
from hashlib import sha256
import json
import sqlite3

from pipeline.analysis import classify
from pipeline.formatting import format_grouped_alert, _format_grouped_digest_item
from pipeline.models import Article
from pipeline.scrapers.rss_scraper import scrape_rss_sources
from pipeline.scrapers.html_scraper import scrape_html_sources

def open_db(path):
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    db.executescript("""
    CREATE TABLE IF NOT EXISTS articles(
        id INTEGER PRIMARY KEY, fingerprint TEXT UNIQUE NOT NULL, collected INTEGER NOT NULL,
        article TEXT NOT NULL, tier TEXT, queued INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS messages(
        id INTEGER PRIMARY KEY, body TEXT NOT NULL, event TEXT, tier TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS deliveries(
        message INTEGER NOT NULL, channel TEXT NOT NULL, receipt TEXT, attempts INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY(message, channel));
    """)
    return db

def dump(article):
    return json.dumps(article.to_dict(), default=lambda t: t.isoformat(), ensure_ascii=False)

def key(article):
    return sha256(json.dumps([article.url, article.title.strip(), article.content.strip()],
                             ensure_ascii=False).encode()).hexdigest()

def store(db, sources, now):
    enabled = [s for s in sources.get("rss_sources", []) if s.get("enabled", True)]
    scraped = scrape_rss_sources(enabled) + scrape_html_sources(sources.get("html_sources", []))
    with db:
        for article in scraped:
            db.execute("INSERT OR IGNORE INTO articles(fingerprint,collected,article) VALUES(?,?,?)",
                       (key(article), now, dump(article)))
    return len(scraped)

def analyze(db, watchlist, mode):
    failed = 0
    for row in db.execute("SELECT id,article FROM articles WHERE tier IS NULL ORDER BY id").fetchall():
        article = Article.from_dict(json.loads(row["article"]))
        try:
            classify(article, watchlist, mode)
        except (ValueError, KeyError, TypeError, IndexError, OSError):
            failed += 1
            continue
        with db:
            db.execute("UPDATE articles SET article=?, tier=? WHERE id=?", (dump(article),article.urgency,row["id"]))
    return failed

def save_message(db, body, event, tier, channels):
    msg = db.execute("INSERT INTO messages(body,event,tier) VALUES(?,?,?)",(body,event,tier)).lastrowid
    db.executemany("INSERT INTO deliveries(message,channel) VALUES(?,?)", [(msg, c.name) for c in channels])

def fit(text):
    # Leave room for surrogate pairs when providers measure length in UTF-16.
    data = text.encode("utf-16-le")
    if len(data) <= 8000:
        return text
    return data[:7950].decode("utf-16-le", errors="ignore").rstrip() + "…"

def queue(db, now, channels):
    # UTC buckets make restart behaviour independent of the last polling time.
    hour = now - now % 3600
    daily_cutoff = now - ((now - 21 * 3600) % 86400)
    rows = db.execute("""SELECT * FROM articles WHERE queued=0 AND
       (tier='CRITICAL' OR (tier='HIGH' AND collected<?) OR (tier='MEDIUM' AND collected<?))
       ORDER BY collected,id""",(hour, daily_cutoff)).fetchall()
    groups = defaultdict(list)
    for row in rows:
        a = Article.from_dict(json.loads(row["article"]))
        groups[(a.urgency,a.event_slug)].append(a)
    with db:
        digests = defaultdict(list)
        for (tier, event), articles in groups.items():
            if tier == "CRITICAL":
                seen = db.execute("SELECT 1 FROM messages WHERE event=? AND tier='CRITICAL'",(event,)).fetchone()
                save_message(db, fit(format_grouped_alert(articles, is_update=bool(seen))), event, tier, channels)
            else:
                digests[tier].append(_format_grouped_digest_item(articles))
        for tier, items in digests.items():
            title = "Hourly digest" if tier == "HIGH" else "Daily digest"
            heading = f"{title} · {len(items)} stories"
            body = heading
            for item in items:
                item = fit(item)
                candidate = body + "\n\n" + item
                if len(candidate.encode("utf-16-le")) > 8000 and body != heading:
                    save_message(db,body,None,tier,channels)
                    candidate = heading + "\n\n" + item
                body = fit(candidate)
            save_message(db,body,None,tier,channels)
        db.executemany("UPDATE articles SET queued=1 WHERE id=?",[(r["id"],) for r in rows])

def deliver(db, channels):
    by_name = {channel.name: channel for channel in channels}
    failures = 0
    rows = db.execute("""SELECT d.channel,d.message,m.body FROM deliveries d JOIN messages m ON m.id=d.message
                         WHERE receipt IS NULL ORDER BY m.id,d.channel""").fetchall()
    for row in rows:
        dest = by_name.get(row["channel"])
        if dest is None:
            continue
        try:
            receipt = dest.send(row["body"])
        except RuntimeError:
            receipt = None
            failures += 1
        with db:
            db.execute("UPDATE deliveries SET attempts=attempts+1,receipt=? WHERE message=? AND channel=?",
                       (receipt,row["message"],row["channel"]))
    return failures

def cycle(db, sources, watchlist, mode, channels, now=None):
    now = int(datetime.now(timezone.utc).timestamp()) if now is None else now
    fetched = store(db,sources,now)
    analysis_errors = analyze(db,watchlist,mode)
    queue(db,now,channels)
    delivery_errors = deliver(db,channels)
    return {"fetched":fetched, "analysis_errors":analysis_errors, "delivery_errors":delivery_errors}
