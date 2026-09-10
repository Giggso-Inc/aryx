"""
Template-ID helpers: generation, parsing, and validation of the
`TMPLT_<TYPE>_<PLATFORM>_<hex>` template ID format. Pure functions, no DB
or filesystem access, shared by the upload/db-record submodules.
"""

import uuid

# Map template types to prefixes
_TYPE_PREFIXES = {
    'PWD': 'TMPLT_PWD_',
    'INVT': 'TMPLT_INVT_',
    'OTH': 'TMPLT_OTH_'
}

# Map platforms to suffixes
_PLATFORM_SUFFIXES = {
    'BASE': 'BASE_',
    'ZAPT': 'ZAPT_',
    'LOGA': 'LOGA_'
}


def generate_template_id(template_type: str, platform: str = 'BASE') -> str:
    """
    Generate a unique template ID based on template type and platform.

    Args:
        template_type: Template type (PWD, INVT, OTH)
        platform: Platform name (BASE, ZAPT, LOGA)

    Returns:
        str: Generated template ID with appropriate prefix
    """
    if template_type not in _TYPE_PREFIXES:
        raise ValueError(f"Invalid template type: {template_type}. Must be one of: PWD, INVT, OTH")

    if platform not in _PLATFORM_SUFFIXES:
        raise ValueError(f"Invalid platform: {platform}. Must be one of: BASE, ZAPT, LOGA")

    prefix = _TYPE_PREFIXES[template_type]
    platform_suffix = _PLATFORM_SUFFIXES[platform]

    # Generate unique suffix using UUID
    return f"{prefix}{platform_suffix}{uuid.uuid4().hex[:8].upper()}"


def get_template_type_from_id(template_id: str) -> str:
    """
    Extract template type from template ID.

    Args:
        template_id: Template ID (e.g., TMPLT_PWD_BASE_12345678, TMPLT_INVT_ZAPT_12345678)

    Returns:
        str: Template type (PWD, INVT, OTH)
    """
    if template_id.startswith('TMPLT_PWD_'):
        return 'PWD'
    elif template_id.startswith('TMPLT_INVT_'):
        return 'INVT'
    elif template_id.startswith('TMPLT_OTH_'):
        return 'OTH'
    else:
        raise ValueError(f"Unknown template ID format: {template_id}")


def get_platform_from_template_id(template_id: str) -> str:
    """
    Extract platform from template ID.

    Args:
        template_id: Template ID (e.g., TMPLT_PWD_BASE_12345678, TMPLT_INVT_ZAPT_12345678)

    Returns:
        str: Platform name (BASE, ZAPT, LOGA)
    """
    if '_BASE_' in template_id:
        return 'BASE'
    elif '_ZAPT_' in template_id:
        return 'ZAPT'
    elif '_LOGA_' in template_id:
        return 'LOGA'
    else:
        # Default to BASE if no platform is specified in old format
        return 'BASE'


def validate_template_id_for_type(template_id: str, expected_type: str) -> bool:
    """
    Validate that template ID matches the expected type.

    Args:
        template_id: Template ID to validate
        expected_type: Expected template type (PWD, INVT, OTH)

    Returns:
        bool: True if template ID matches expected type
    """
    try:
        actual_type = get_template_type_from_id(template_id)
        return actual_type == expected_type
    except ValueError:
        return False


def validate_template_id_for_platform(template_id: str, expected_platform: str) -> bool:
    """
    Validate that template ID matches the expected platform.

    Args:
        template_id: Template ID to validate
        expected_platform: Expected platform (BASE, ZAPT, LOGA)

    Returns:
        bool: True if template ID matches expected platform
    """
    try:
        actual_platform = get_platform_from_template_id(template_id)
        return actual_platform == expected_platform
    except ValueError:
        return False


def is_valid_template_id_format(template_id: str) -> bool:
    """
    Check if template ID has valid format with platform.

    Args:
        template_id: Template ID to validate

    Returns:
        bool: True if template ID has valid format
    """
    valid_patterns = [
        'TMPLT_PWD_BASE_',
        'TMPLT_PWD_ZAPT_',
        'TMPLT_PWD_LOGA_',
        'TMPLT_INVT_BASE_',
        'TMPLT_INVT_ZAPT_',
        'TMPLT_INVT_LOGA_',
        'TMPLT_OTH_BASE_',
        'TMPLT_OTH_ZAPT_',
        'TMPLT_OTH_LOGA_'
    ]

    return any(template_id.startswith(pattern) for pattern in valid_patterns)
