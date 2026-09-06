"""
CSV parsing/validation helper for the bulk-csv channel-members endpoint.

Split out of members_bulk.py during the Raven style-compliance line-count
pass (wave B2) — see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md. Pure
parsing/validation with no DB or request-scoped state, so it splits cleanly.
"""

import csv
import io
from typing import List, Tuple

from fastapi import HTTPException, status, UploadFile


async def parse_bulk_csv_file(csv_file: UploadFile) -> List[Tuple[str, str]]:
    """Validate the uploaded file is a CSV, decode it, and parse+validate
    each row's gmail_id/role.

    Raises HTTPException (400) on any validation failure; returns the list
    of (gmail_id, role) tuples otherwise.
    """
    if not csv_file.filename or not csv_file.filename.lower().endswith(".csv"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must be a CSV file"
        )

    try:
        csv_content = await csv_file.read()
        csv_text = csv_content.decode("utf-8")
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid CSV file content"
        )

    try:
        csv_reader = csv.DictReader(io.StringIO(csv_text))

        if "gmail_id" not in csv_reader.fieldnames or "role" not in csv_reader.fieldnames:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="CSV must contain 'gmail_id' and 'role' columns"
            )

        csv_data: List[Tuple[str, str]] = []
        for row_num, row in enumerate(csv_reader, start=2):  # row 1 is headers
            gmail_id = row.get("gmail_id", "").strip()
            role = row.get("role", "").strip()

            if not gmail_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Row {row_num}: gmail_id cannot be empty"
                )

            if not role:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Row {row_num}: role cannot be empty"
                )

            role_lower = role.lower()
            if role_lower not in ["user", "admin"]:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Row {row_num}: role must be 'User' or 'Admin' (case-insensitive), got '{role}'"
                )

            csv_data.append((gmail_id, role))

    except csv.Error as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid CSV format: {str(e)}"
        )

    if not csv_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CSV file is empty or contains no valid data"
        )

    return csv_data
