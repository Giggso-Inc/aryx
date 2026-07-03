"""
In-platform URL shortener: redirect at /redirect/{short_link} and set used_at on first click.
"""

from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.config import settings
from app.models.shortened_url import ShortenedUrl
from app.models.message import Thread

router = APIRouter()


@router.get("/thread/{old_channel_id}/{thread_id}")
async def redirect_thread_link(
    old_channel_id: str,
    thread_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Redirect old thread links to current channel. Self-healing: reads current channel_id from DB.
    """
    result = await db.execute(select(Thread).where(Thread.id == thread_id))
    thread = result.scalar_one_or_none()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    current_url = f"{settings.PLATFORM_URL}/threads/{thread.channel_id}/{thread_id}"
    return RedirectResponse(
        url=current_url,
        status_code=302,
        headers={"Referrer-Policy": "no-referrer"},
    )


@router.get("/resolve/{short_link}")
async def resolve_short_link(
    short_link: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Return original_url for the given short_link. Frontend calls this to get the URL without following redirect.
    """
    result = await db.execute(
        select(ShortenedUrl).where(ShortenedUrl.short_link == short_link)
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Link not found")
    return {"original_url": row.original_url}


@router.get("/{short_link}")
async def redirect_short_link(
    short_link: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Redirect to the original URL and set used_at on first use.
    Uses Referrer-Policy: no-referrer so the final page sees the same referrer
    as when coming from TinyURL (no internal referrer), avoiding frontend expiry logic.
    """
    # Look up the short link (case-sensitive, exact match)
    result = await db.execute(
        select(ShortenedUrl).where(ShortenedUrl.short_link == short_link)
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Link not found")
    # Flag as used on first click (idempotent: only set if still null)
    if row.used_at is None:
        row.used_at = datetime.utcnow()
        await db.commit()
    # Match TinyURL behavior: no referrer when following redirect so frontend sees same as external link
    headers = {"Referrer-Policy": "no-referrer"}
    return RedirectResponse(url=row.original_url, status_code=302, headers=headers)
