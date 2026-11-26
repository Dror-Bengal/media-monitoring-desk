"""
Data models for the Media Monitor pipeline.
"""

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional
import hashlib


@dataclass
class Article:
    """A single news article flowing through the pipeline."""

    # ── Identity ──
    url: str
    source: str
    bias: str  # Source description from configuration
    source_type: str = ""  # rss or html

    # ── Content ──
    title: str = ""
    content: str = ""
    content_hash: str = ""

    # ── Timestamps ──
    published_at: Optional[datetime] = None
    scraped_at: Optional[datetime] = None

    # ── AI Analysis (filled by analyzer) ──
    urgency: str = ""  # CRITICAL, HIGH, MEDIUM, SKIP
    category: str = ""
    headline: str = ""
    summary: str = ""
    why_it_matters: str = ""
    suggested_action: str = ""  # respond, monitor, counter_narrative, ignore
    is_our_own_content: bool = False
    ai_confidence: float = 0.0
    event_slug: str = ""  # Groups same-event articles for dedup

    def __post_init__(self):
        if not self.scraped_at:
            self.scraped_at = datetime.now(timezone.utc)
        if not self.content_hash and self.content:
            self.compute_hash()

    def compute_hash(self):
        """Generate content hash for deduplication."""
        normalized = self.content.lower().strip()[:500]
        self.content_hash = hashlib.md5(normalized.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict:
        """Convert to dict for MongoDB insertion."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Article":
        """Create Article from MongoDB document."""
        data = dict(data)
        # Only pass known fields
        known = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)
