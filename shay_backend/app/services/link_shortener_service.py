import base64
import hashlib
import logging
import time
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.shortened_url import ShortenedUrl

logger = logging.getLogger(__name__)


def _make_short_code(url: str, timestamp: float) -> str:
    """Generate a 7-char URL-safe short code from url + timestamp."""
    to_encode = f"{url}{timestamp}"
    b64 = base64.urlsafe_b64encode(
        hashlib.sha256(to_encode.encode()).digest()
    ).decode()
    return b64[:7].rstrip("=")


class LinkShortenerService:
    """
    Shortens URLs via in-platform DB (gg_shortened_urls). Requires db session.
    When db is None, returns original URL. Falls back to original URL on failure.
    """

    async def shorten(
        self,
        url: str,
        db: Optional[AsyncSession] = None,
        *,
        thread_id: Optional[UUID] = None,
        channel_id: Optional[UUID] = None,
        entity_type: Optional[str] = None,
    ) -> str:
        """
        Shorten a URL. If db is provided, store in gg_shortened_urls and return
        BASE_URL/redirect/{short_link}. Optional thread_id, channel_id, entity_type
        are stored for move-thread and traceability.
        """
        if not url:
            return url

        # No db: cannot shorten in-platform; return original URL
        if db is None:
            return url

        # In-platform: create ShortenedUrl row and return /redirect/{short_link}
        try:
            for _ in range(5):
                ts = time.time()
                short_link = _make_short_code(url, ts)
                # Avoid unique violation: skip if code already exists
                existing = await db.execute(
                    select(ShortenedUrl).where(ShortenedUrl.short_link == short_link)
                )
                if existing.scalar_one_or_none() is not None:
                    continue
                row = ShortenedUrl(
                    short_link=short_link,
                    original_url=url,
                    used_at=None,
                    thread_id=thread_id,
                    channel_id=channel_id,
                    entity_type=entity_type,
                )
                db.add(row)
                # Keep URL shortening inside the caller's transaction so invite flows
                # don't issue nested commits on the same async session.
                await db.flush()
                # Log after DB insertion for debugging / audit
                logger.info(
                    "Short link inserted: short_link=%s original_url=%s",
                    short_link,
                    url[:80] + "..." if len(url) > 80 else url,
                )
                base = settings.BASE_URL.rstrip("/")
                # BASE_URL always contains /api (e.g., https://domain.com/api)
                # So we just append /v1/redirect to avoid duplication
                # Match main.py router prefix /api/v1/redirect so click-through and resolve work like register
                await db.commit()
                return f"{base}/v1/redirect/{short_link}"
            logger.warning("Internal shortener failed (collision?), using original URL")
            return url
        except Exception as exc:
            logger.warning("Internal URL shortening failed, using original link. Error: %s", exc)
            return url


link_shortener_service = LinkShortenerService()
