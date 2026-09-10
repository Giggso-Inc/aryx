"""
Per-item orchestration for bulk_create_internal.py (POST /internal/bulk).

Private module: extracted verbatim (per-datasource loop body) from the
original create_datasources_bulk_internal endpoint, now split into
lookup / dedupe / metadata / persist steps (see the sibling
_bulk_internal_*.py files) so no single file holds the whole thing.
Expected failures raise BulkItemFailure; expected skips (duplicate-in-
thread, unsupported .ics) raise BulkItemSkipped — both carry the exact
same message text as the original inline per-item try/except.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from ._bulk_internal_dedupe import resolve_filename_and_check_duplicate
from ._bulk_internal_lookup import resolve_thread_channel_and_user
from ._bulk_internal_metadata import build_internal_bulk_enhanced_metadata
from ._bulk_internal_persist import save_internal_bulk_item_with_vault
from ._metadata_helpers import generate_app_filename


async def process_bulk_internal_item(datasource_data, db: AsyncSession) -> dict:
    """Process a single internal/bulk (thread-level) datasource item.

    Returns the created_datasources entry dict. Raises BulkItemFailure for
    an expected failure, or BulkItemSkipped for a duplicate-in-thread /
    unsupported .ics attachment (recorded separately, not as a failure).
    """
    thread, channel, user, thread_uuid = await resolve_thread_channel_and_user(datasource_data, db)

    filename, datasource_name = await resolve_filename_and_check_duplicate(datasource_data, thread, thread_uuid, db)

    # Handle app storage type with no filename - generate meaningful filename first
    # (re-derives filename exactly like the original inline code's second pass)
    if not filename and datasource_data.storage_type == "app":
        filename = generate_app_filename(datasource_data)

    enhanced_metadata = await build_internal_bulk_enhanced_metadata(
        datasource_data, filename, thread, thread_uuid, channel, user, db
    )

    return await save_internal_bulk_item_with_vault(
        datasource_data=datasource_data,
        filename=filename,
        datasource_name=datasource_name,
        enhanced_metadata=enhanced_metadata,
        thread=thread,
        thread_uuid=thread_uuid,
        channel=channel,
        user=user,
        db=db,
    )
