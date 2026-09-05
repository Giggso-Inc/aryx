"""
Unique ID generators (UUID4) for the various domain entities.

Split out of app/core/auth.py — see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md.
"""

import uuid


def generate_user_id() -> str:
    """Generate unique user ID"""
    return str(uuid.uuid4())


def generate_company_id() -> str:
    """Generate unique company ID"""
    return str(uuid.uuid4())


def generate_workspace_id() -> str:
    """Generate unique workspace ID"""
    return str(uuid.uuid4())


def generate_message_id() -> str:
    """Generate unique message ID"""
    return str(uuid.uuid4())


def generate_approval_id() -> str:
    """
    Generate a unique approval ID.

    This function creates a new UUID and converts it to a string for use
    as an approval identifier in the database.

    Returns:
        str: A unique UUID string for the approval

    Author: Karthick Chandrasekar
    Date: 19-08-2025
    Version: 1.0.0
    """
    return str(uuid.uuid4())


def generate_attachment_id() -> str:
    """Generate unique attachment ID"""
    return str(uuid.uuid4())


def generate_channel_id() -> str:
    """Generate unique channel ID"""
    return str(uuid.uuid4())


def generate_ai_response_id() -> str:
    """Generate unique AI response ID"""
    return str(uuid.uuid4())
