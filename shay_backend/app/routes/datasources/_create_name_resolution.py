"""
Name/filename resolution for create.py (POST / — single datasource creation).

Private module: extracted verbatim from the original create_datasource
endpoint body.
"""

import os
from typing import Tuple


def resolve_create_name_and_filename(datasource_data) -> Tuple[str, str]:
    """Resolve (datasource_name, filename) for a new datasource from its create payload.

    Mirrors the original create_datasource logic: name falls back to a
    title-cased filename/URL basename; filename separately falls back through
    filename -> file_url -> location -> a sanitized database/generic name.
    """
    # Auto-generate name from filename if not provided
    datasource_name = datasource_data.name
    if not datasource_name:
        # Get filename (either provided or extract from URL)
        filename = datasource_data.filename
        if not filename and datasource_data.file_url:
            # Extract filename from URL
            filename = os.path.basename(datasource_data.file_url.split('?')[0])  # Remove query params
            if not filename:
                filename = "cloud_file"  # Fallback name

        if filename:
            # Remove extension and replace underscores/hyphens with spaces
            base_filename = os.path.splitext(filename)[0]
            datasource_name = base_filename.replace('_', ' ').replace('-', ' ').title()
        else:
            datasource_name = "Cloud Datasource"  # Default name

    # Get filename (either provided or extract from URL/location) - MUST be done BEFORE generating metadata
    filename = datasource_data.filename
    if not filename:
        if datasource_data.file_url:
            filename = os.path.basename(datasource_data.file_url.split('?')[0])  # Remove query params
            if not filename:
                filename = "cloud_file"  # Fallback name
        elif datasource_data.location:
            # Extract filename from location (gs://, s3://, https://, etc.)
            location = datasource_data.location
            # Remove protocol prefix (gs://, s3://, https://, etc.)
            if "://" in location:
                path_part = location.split("://", 1)[1]
                # Remove bucket name (first part before /)
                if "/" in path_part:
                    file_path = "/".join(path_part.split("/")[1:])
                    filename = os.path.basename(file_path) if file_path else None
                else:
                    filename = None
            else:
                filename = os.path.basename(location)

            if not filename:
                filename = "cloud_file"  # Fallback name
        elif datasource_data.storage_type == "database":
            provider = datasource_data.provider or "database"
            db_name = datasource_data.name or f"{provider}_connection"
            filename = "".join(c for c in db_name if c.isalnum() or c in (' ', '-', '_')).strip()
            if not filename:
                filename = f"{provider}_datasource"
            if not filename.endswith(('.db', '.sql', '.csv')):
                filename = f"{filename}.db"
        else:
            filename = datasource_data.name or "datasource"
            filename = "".join(c for c in filename if c.isalnum() or c in (' ', '-', '_')).strip()
            if not filename:
                filename = "datasource"

    return datasource_name, filename
