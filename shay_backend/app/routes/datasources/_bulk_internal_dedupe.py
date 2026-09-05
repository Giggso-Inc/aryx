"""
Filename/name resolution, .ics skip, and duplicate-in-thread detection for
the internal/bulk per-item loop.

Private module: used only by _bulk_internal_create_item.py.
"""

import logging
import os

from sqlalchemy import String, and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.expression import literal

from app.models.datasource import Datasource

from ._bulk_internal_skip import BulkItemSkipped

logger = logging.getLogger(__name__)


def _resolve_early_filename(datasource_data):
    filename = datasource_data.filename
    if not filename and datasource_data.file_url:
        filename = os.path.basename(datasource_data.file_url.split('?')[0])
        if not filename:
            filename = "cloud_file"
    return filename


def _is_ics_attachment(filename, datasource_data) -> bool:
    fn_lower = (filename or "").strip().lower()
    if fn_lower.endswith(".ics"):
        return True
    if datasource_data.file_url:
        path_part = datasource_data.file_url.split("?")[0].rstrip("/")
        if path_part:
            last_segment = path_part.split("/")[-1]
            return last_segment.lower().endswith(".ics")
    return False


def _resolve_datasource_name(datasource_data, filename) -> str:
    if datasource_data.name:
        return datasource_data.name
    if filename:
        base_filename = os.path.splitext(filename)[0]
        return base_filename.replace('_', ' ').replace('-', ' ').title()
    if getattr(datasource_data, 'storage_type', None) == "app":
        app_type = getattr(datasource_data, 'app_type', 'unknown')
        return f"{app_type.title()} Datasource"
    return "Cloud Datasource"


async def resolve_filename_and_check_duplicate(datasource_data, thread, thread_uuid, db: AsyncSession):
    """Resolve (filename, datasource_name), skipping .ics attachments and
    duplicates (same filename/name already in this thread) via BulkItemSkipped.
    """
    filename = _resolve_early_filename(datasource_data)

    if _is_ics_attachment(filename, datasource_data):
        skip_name = datasource_data.name or filename or "Unknown"
        raise BulkItemSkipped(
            skip_name, "unsupported_extension",
            "Attachments with .ics extension are not supported in bulk API"
        )

    datasource_name = _resolve_datasource_name(datasource_data, filename)

    # Check for duplicate ONLY within the same thread: use (filename, thread_id) for precision.
    # Same filename in SAME thread = duplicate (skip). Same filename in DIFFERENT thread = process.
    # Filename is the actual file identity; name can collide across different files (e.g. Report.pdf vs Report.docx).
    filename_for_check = (filename or "").strip() or None
    duplicate_check_key = filename_for_check if filename_for_check else datasource_name
    if duplicate_check_key:
        match_column = Datasource.filename == filename_for_check if filename_for_check else Datasource.name == datasource_name
        duplicate_stmt = select(Datasource).where(
            and_(
                match_column,
                Datasource.channel_id == thread.channel_id,
                Datasource.datasource_metadata.isnot(None),
                Datasource.datasource_metadata.op("?")(literal("thread_id", type_=String())),
                Datasource.datasource_metadata.op("->>")(literal("thread_id", type_=String())) == literal(str(thread_uuid), type_=String())
            )
        ).limit(1)
        duplicate_result = await db.execute(duplicate_stmt)
        existing_datasource = duplicate_result.scalar_one_or_none()

        if existing_datasource:
            logger.info(
                f"⏭️ Skipping duplicate datasource: {datasource_name} (filename={filename_for_check or 'N/A'} "
                f"already exists in thread {thread_uuid})"
            )
            raise BulkItemSkipped(
                datasource_name, "already_exists",
                f"Datasource '{datasource_name}' already exists in this thread (skipped)"
            )

    return filename, datasource_name
