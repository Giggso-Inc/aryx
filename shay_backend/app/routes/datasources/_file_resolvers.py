"""
File-path / URL / media-type resolution helpers for datasource downloads.

Private module: used by processing.py (download endpoint) and re-exported
via app/routes/datasources/__init__.py where external callers need them.
"""

import os
from typing import Optional
from urllib.parse import unquote, urlparse

# Supported database provider types (no file to view/download; table/collection references only)
DATASOURCE_DATABASE_PROVIDERS = frozenset({
    "mysql", "postgresql", "sqlserver", "oracle", "mongodb", "dynamodb", "redshift", "snowflake"
})

# Extension -> media type for all supported upload formats (csv, xlsx, xls, json, pdf, docx, doc, txt, pptx, ppt)
# Ensures download/view API returns correct Content-Type for every supported file format
_FALLBACK_MEDIA_TYPES = {
    "csv": "text/csv",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "xls": "application/vnd.ms-excel",
    "json": "application/json",
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "doc": "application/msword",
    "txt": "text/plain",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "ppt": "application/vnd.ms-powerpoint",
}


def get_storage_file_path_for_deletion(datasource) -> Optional[str]:
    """
    Extract file path for storage deletion when datasource was uploaded by our system.
    Returns path only when we own the file (from upload, from-upload, from-upload/bulk).
    file_path in config indicates file was stored via our file storage service.
    """
    # Check config first - set when we upload via from-upload or from-upload/bulk
    config = datasource.config if isinstance(datasource.config, dict) else {}
    file_path = config.get("file_path")
    # Fallback: check datasource_metadata for file_path (some flows store it there)
    if not file_path and datasource.datasource_metadata:
        meta = datasource.datasource_metadata
        if isinstance(meta, dict):
            credentials = meta.get("credentials", {})
            if isinstance(credentials, dict):
                file_path = credentials.get("file_path")
    return file_path


def get_media_type_for_download(datasource) -> str:
    """
    Resolve Content-Type for streaming a datasource file (e.g. from our S3/local storage).
    Supports all UI-supported formats: csv, xlsx, xls, json, pdf, docx, doc, txt, pptx, ppt.
    Uses file_type when it looks like a MIME type; otherwise infers from filename for view=1.
    """
    # Prefer stored file_type if it looks like a MIME type (contains "/")
    ft = getattr(datasource, "file_type", None)
    if ft and isinstance(ft, str) and "/" in ft.strip():
        return ft.strip()
    # Infer from filename for tabular and common types
    fn = getattr(datasource, "filename", None) or ""
    if isinstance(fn, str):
        ext = os.path.splitext(fn)[1].lstrip(".").lower()
        if ext in _FALLBACK_MEDIA_TYPES:
            return _FALLBACK_MEDIA_TYPES[ext]
    return "application/octet-stream"


def _get_google_drive_file_id(datasource) -> Optional[str]:
    """Extract Google Drive file_id from datasource config or metadata (for building view URL)."""
    # From config: top-level file_id or connection_settings.account.file_id
    config = datasource.config if isinstance(datasource.config, dict) else {}
    fid = config.get("file_id")
    if fid and isinstance(fid, str) and fid.strip():
        return fid.strip()
    conn = config.get("connection_settings")
    if isinstance(conn, dict):
        account = conn.get("account") if isinstance(conn.get("account"), dict) else {}
        fid = (account.get("file_id") or conn.get("file_id"))
        if fid and isinstance(fid, str) and fid.strip():
            return fid.strip()
    # From config.credentials.additional_config (if present on config)
    creds = config.get("credentials")
    if isinstance(creds, dict):
        add = creds.get("additional_config")
        if isinstance(add, dict):
            fid = add.get("file_id")
            if fid and isinstance(fid, str) and fid.strip():
                return fid.strip()
    # From datasource_metadata.credentials.additional_config
    meta = datasource.datasource_metadata if isinstance(getattr(datasource, "datasource_metadata", None), dict) else {}
    creds = meta.get("credentials")
    if isinstance(creds, dict):
        add = creds.get("additional_config")
        if isinstance(add, dict):
            fid = add.get("file_id")
            if fid and isinstance(fid, str) and fid.strip():
                return fid.strip()
    return None


def get_external_view_url_for_datasource(datasource) -> Optional[str]:
    """
    Resolve a view/download URL for datasources that reference external content.
    - App storage (Google Drive, SharePoint, etc.): file_url on model, or from config/connection_settings,
      or for Google Drive build URL from file_id when only file_id is stored.
    - Cloud storage: file_url on model or in config.
    - Database storage: no file URL (returns None); caller should return appropriate response.
    """
    # Prefer top-level file_url on the datasource
    if datasource.file_url and isinstance(datasource.file_url, str) and datasource.file_url.strip():
        return datasource.file_url.strip()
    # Resolve from config (app or cloud may store URL only in config)
    config = datasource.config if isinstance(datasource.config, dict) else {}
    # Direct file_url in config (e.g. cloud with URL in config)
    if config:
        url = config.get("file_url") or config.get("fileUrl")
        if url and isinstance(url, str) and url.strip():
            return url.strip()
        # App storage: try connection_settings (Google Drive webViewLink/webContentLink, etc.)
        conn = config.get("connection_settings")
        if isinstance(conn, dict):
            account = conn.get("account") if isinstance(conn.get("account"), dict) else {}
            for key in ("webViewLink", "web_content_link", "webContentLink", "url", "viewUrl", "view_url", "alternateLink"):
                val = account.get(key) or conn.get(key)
                if val and isinstance(val, str) and val.strip():
                    return val.strip()
    # Google Drive: if only file_id is stored (no link), build standard view URL
    app_type = (getattr(datasource, "app_type", None) or "").lower().replace(" ", "")
    if app_type in ("google_drive", "googledrive", "googledrives"):
        file_id = _get_google_drive_file_id(datasource)
        if file_id:
            return f"https://drive.google.com/file/d/{file_id}/view"
    return None
