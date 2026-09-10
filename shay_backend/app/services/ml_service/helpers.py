"""
Pure helper functions for ML embedding requests: table-name extraction and
embedd_type classification.

Split out of the former app/services/ml_service.py (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a). These functions
have no HTTP/network dependency, unlike MLService in client.py.
"""

from typing import Any, List


def extract_table_names_from_datasources(datasources: List[Any]) -> List[str]:
    """
    Extracts all table names from a list of datasources (dictionaries or ORM models).

    Args:
        datasources: List of datasource dicts or ORM model objects.
                    Each should have either:
                    - 'config' dict with 'tableName' key, OR
                    - 'datasource_metadata' dict with 'tableName' key

    Returns:
        List of unique table names found.
    """
    table_names = []

    for ds in datasources:
        table_name = None

        # Handle dictionary format
        if isinstance(ds, dict):
            # Check config first
            if "config" in ds and isinstance(ds["config"], dict):
                table_name = ds["config"].get("tableName")
            # Fall back to datasource_metadata
            if not table_name and "datasource_metadata" in ds and isinstance(ds["datasource_metadata"], dict):
                table_name = ds["datasource_metadata"].get("tableName")
        else:
            # Handle ORM model format (e.g., Datasource model)
            if hasattr(ds, "datasource_metadata") and isinstance(ds.datasource_metadata, dict):
                table_name = ds.datasource_metadata.get("tableName")
            elif hasattr(ds, "config") and isinstance(ds.config, dict):
                table_name = ds.config.get("tableName")

        if table_name:
            table_names.append(table_name)

    # Return unique table names
    return list(set(table_names))


def get_embedd_type_from_file_type(file_type: str, storage_type: str = None, provider: str = None) -> str:
    """
    Determine embedd_type based on file_type, storage_type, and provider

    Args:
        file_type: MIME type or file extension
        storage_type: Storage type (e.g., "database", "cloud", "local", "app")
        provider: Provider/database type (e.g., "mysql", "postgresql", "snowflake", etc.)

    Returns:
        "textual" for text-based files, "tabular" for structured data files,
        "tabular" for all database datasources
    """

    if storage_type == "database":
        return "tabular"

    # If no file_type provided and not a database, default to textual
    if not file_type:
        return "textual"

    # Convert to lowercase for case-insensitive comparison
    file_type_lower = file_type.lower()

    # Textual file types
    textual_types = [
        "text/plain", "text/html", "text/css", "text/javascript",
        "application/pdf", "application/msword", "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-powerpoint", "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/rtf", "text/rtf",
    ]

    # Tabular file types
    tabular_types = [
        "application/vnd.ms-excel", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "application/vnd.google-apps.spreadsheet",
        "text/csv", "application/csv", "application/json", "text/json",
    ]

    # Check MIME types first
    is_textual = False
    is_tabular = False

    if file_type_lower in textual_types:
        is_textual = True
    elif file_type_lower in tabular_types:
        is_tabular = True

    # Check file extensions (common patterns) if not already determined
    if not is_textual and not is_tabular:
        if file_type_lower in ["txt", "pdf", "doc", "docx", "ppt", "pptx", "rtf", "html", "htm", "css", "js"]:
            is_textual = True
        elif file_type_lower in ["xls", "xlsx", "csv", "json"]:
            is_tabular = True

    # Determine base embedd_type
    if is_textual:
        return "textual"
    elif is_tabular:
        return "tabular"
    else:
        # Default to textual if file type cannot be determined
        return "textual"
