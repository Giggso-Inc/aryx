"""
Name/filename resolution for bulk_create.py's per-item loop.

Private module: used only by _bulk_create_item.py.
"""

import os

from ._metadata_helpers import generate_app_filename


def resolve_bulk_name_and_filename(datasource_data):
    """Resolve (datasource_name, filename) exactly like the original bulk-create loop."""
    # Auto-generate name from filename if not provided
    datasource_name = datasource_data.name
    if not datasource_name:
        filename = datasource_data.filename
        if not filename and datasource_data.file_url:
            filename = os.path.basename(datasource_data.file_url.split('?')[0])
            if not filename:
                filename = "cloud_file"

        if filename:
            base_filename = os.path.splitext(filename)[0]
            datasource_name = base_filename.replace('_', ' ').replace('-', ' ').title()
        else:
            # Handle app storage type with no filename
            if datasource_data.storage_type == "app":
                app_type = getattr(datasource_data, 'app_type', 'unknown')
                datasource_name = f"{app_type.title()} Datasource"
            else:
                datasource_name = "Cloud Datasource"

    filename = datasource_data.filename
    if not filename and datasource_data.file_url:
        filename = os.path.basename(datasource_data.file_url.split('?')[0])
        if not filename:
            filename = "cloud_file"

    # Handle app storage type with no filename - generate meaningful filename first
    if not filename and datasource_data.storage_type == "app":
        filename = generate_app_filename(datasource_data)

    return datasource_name, filename
