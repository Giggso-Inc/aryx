"""
Shared response-building helpers for the gg_datasources package: media-type /
file-path / external-URL resolution for downloads, and the GGDatasource ->
GGDatasourceResponse mapper used by every other submodule in this package.
"""

import os
from typing import Optional

from app.models.gg_datasource import GGDatasource
from app.schemas.gg_datasource import GGDatasourceResponse

_FALLBACK_MEDIA_TYPES = {
    "csv":  "text/csv",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "xls":  "application/vnd.ms-excel",
    "json": "application/json",
    "pdf":  "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "doc":  "application/msword",
    "txt":  "text/plain",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "ppt":  "application/vnd.ms-powerpoint",
}

DATASOURCE_DATABASE_PROVIDERS = frozenset({
    "mysql", "postgresql", "sqlserver", "oracle", "mongodb",
    "dynamodb", "redshift", "snowflake",
})


def _get_media_type(ds: GGDatasource) -> str:
    ft = getattr(ds, "file_type", None)
    if ft and isinstance(ft, str) and "/" in ft.strip():
        return ft.strip()
    fn = getattr(ds, "filename", None) or ""
    if isinstance(fn, str):
        ext = os.path.splitext(fn)[1].lstrip(".").lower()
        if ext in _FALLBACK_MEDIA_TYPES:
            return _FALLBACK_MEDIA_TYPES[ext]
    return "application/octet-stream"


def _get_storage_file_path(ds: GGDatasource) -> Optional[str]:
    """Return stored file_path if we own the file (from upload endpoints)."""
    config = ds.config if isinstance(ds.config, dict) else {}
    path = config.get("file_path")
    if not path and ds.datasource_metadata:
        meta = ds.datasource_metadata
        if isinstance(meta, dict):
            creds = meta.get("credentials", {})
            if isinstance(creds, dict):
                path = creds.get("file_path")
    return path


def _get_google_drive_file_id(ds: GGDatasource) -> Optional[str]:
    config = ds.config if isinstance(ds.config, dict) else {}
    fid = config.get("file_id")
    if fid:
        return fid.strip()
    conn = config.get("connection_settings")
    if isinstance(conn, dict):
        account = conn.get("account") if isinstance(conn.get("account"), dict) else {}
        fid = account.get("file_id") or conn.get("file_id")
        if fid:
            return fid.strip()
    return None


def _get_external_view_url(ds: GGDatasource) -> Optional[str]:
    if ds.file_url and ds.file_url.strip():
        return ds.file_url.strip()
    config = ds.config if isinstance(ds.config, dict) else {}
    if config:
        url = config.get("file_url") or config.get("fileUrl")
        if url:
            return url.strip()
        conn = config.get("connection_settings")
        if isinstance(conn, dict):
            account = conn.get("account") if isinstance(conn.get("account"), dict) else {}
            for key in ("webViewLink", "web_content_link", "webContentLink", "url"):
                val = account.get(key) or conn.get(key)
                if val:
                    return val.strip()
    app_type = (getattr(ds, "app_type", None) or "").lower().replace(" ", "")
    if app_type in ("google_drive", "googledrive", "googledrives"):
        fid = _get_google_drive_file_id(ds)
        if fid:
            return f"https://drive.google.com/file/d/{fid}/view"
    return None


def _to_response(ds: GGDatasource) -> GGDatasourceResponse:
    return GGDatasourceResponse(
        id=str(ds.id),
        level=ds.level,
        workspace_id=str(ds.workspace_id) if ds.workspace_id else None,
        channel_id=str(ds.channel_id)     if ds.channel_id   else None,
        thread_id=str(ds.thread_id)       if ds.thread_id    else None,
        message_id=str(ds.message_id)     if ds.message_id   else None,
        added_by=str(ds.added_by)         if ds.added_by     else None,
        name=ds.name,
        filename=ds.filename,
        storage_type=ds.storage_type,
        provider=ds.provider,
        app_type=ds.app_type,
        config=ds.config,
        datasource_metadata=ds.datasource_metadata,
        vault_unique_id=str(ds.vault_unique_id) if ds.vault_unique_id else None,
        file_size=ds.file_size,
        file_type=ds.file_type,
        file_url=ds.file_url,
        log_type=ds.log_type,
        is_active=ds.is_active,
        is_connected=ds.is_connected,
        is_processed=ds.is_processed,
        processing_status=ds.processing_status,
        error_message=ds.error_message,
        is_embedding_required=ds.is_embedding_required,
        embedding_status=ds.embedding_status,
        last_processed_at=ds.last_processed_at,
        processing_time=ds.processing_time,
        record_count=ds.record_count,
        created_at=ds.created_at,
        updated_at=ds.updated_at,
    )
