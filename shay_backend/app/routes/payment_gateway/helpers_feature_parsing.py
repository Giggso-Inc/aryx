"""
Channel/message/storage limit parsers for subscription_plan.features JSON.

Extracted from helpers.py (Raven style compliance, wave B). Used by
subscription_validation.py and subscription_details_usage.py.
"""

import re
from typing import Any


def _parse_channel_limit_from_features(features: Any) -> int:
    """
    Parse channel limit from subscription_plan features JSON.
    Features format example: ["4 Channels", "10GB Storage"] or ["Unlimited Channels"]
    Returns the numeric limit, -1 for unlimited, or 0 if not found.
    """
    if features is None:
        return 0
    if isinstance(features, list):
        for item in features:
            if isinstance(item, str):
                # Check for "Unlimited Channels" first
                if re.search(r"unlimited\s+channels?", item, re.IGNORECASE):
                    return -1  # -1 indicates unlimited
                # Check for numeric channel limit
                m = re.search(r"(\d+)\s*Channels?", item, re.IGNORECASE)
                if m:
                    return int(m.group(1))
    if isinstance(features, dict):
        for k, v in features.items():
            if "channel" in str(k).lower():
                if isinstance(v, str) and re.search(r"unlimited", v, re.IGNORECASE):
                    return -1  # -1 indicates unlimited
                elif isinstance(v, (int, float)):
                    return int(v)
    return 0


def _parse_message_limit_from_features(features: Any) -> int:
    """
    Parse message limit (per channel) from subscription_plan features JSON.
    Features format example: ["4 Channels", "50 messages", "10GB Storage"] or ["Unlimited Messages"]
    Returns the numeric limit per channel, -1 for unlimited, or 0 if not found.
    """
    if features is None:
        return 0
    if isinstance(features, list):
        for item in features:
            if isinstance(item, str):
                # Check for "Unlimited Messages" first
                if re.search(r"unlimited\s+messages?", item, re.IGNORECASE):
                    return -1  # -1 indicates unlimited
                # Check for numeric message limit (handles "2000 Messages per Channel" pattern)
                m = re.search(r"(\d+)\s*Messages?", item, re.IGNORECASE)
                if m:
                    return int(m.group(1))
    if isinstance(features, dict):
        for k, v in features.items():
            if "message" in str(k).lower():
                if isinstance(v, str) and re.search(r"unlimited", v, re.IGNORECASE):
                    return -1  # -1 indicates unlimited
                elif isinstance(v, (int, float)):
                    return int(v)
    return 0


def _parse_storage_limit_from_features(features: Any) -> int:
    """
    Parse storage limit (in bytes) from subscription_plan features JSON.
    Features format example: ["4 Channels", "10GB Storage"] or ["Unlimited Storage"]
    Supports: GB, MB, KB, B (case-insensitive)
    Returns the limit in bytes, -1 for unlimited, or 0 if not found.
    """
    if features is None:
        return 0

    if isinstance(features, list):
        for item in features:
            if isinstance(item, str):
                # Check for "Unlimited Storage" first
                if re.search(r"unlimited\s+storage", item, re.IGNORECASE):
                    return -1  # -1 indicates unlimited
                # Match patterns like "10GB Storage", "10 GB", "10GB", "200 MB Data Storage per Channel", etc.
                m = re.search(r"(\d+(?:\.\d+)?)\s*(GB|MB|KB|B).*?Storage", item, re.IGNORECASE)
                if m:
                    size_value = float(m.group(1))
                    unit = m.group(2).upper()

                    # Convert to bytes
                    if unit == "GB":
                        return int(size_value * 1024 * 1024 * 1024)
                    elif unit == "MB":
                        return int(size_value * 1024 * 1024)
                    elif unit == "KB":
                        return int(size_value * 1024)
                    elif unit == "B":
                        return int(size_value)

    if isinstance(features, dict):
        for k, v in features.items():
            if "storage" in str(k).lower():
                if isinstance(v, str) and re.search(r"unlimited", v, re.IGNORECASE):
                    return -1  # -1 indicates unlimited
                elif isinstance(v, (int, float)):
                    # Assume bytes if numeric
                    return int(v)
                elif isinstance(v, str):
                    # Parse string like "10GB"
                    m = re.search(r"(\d+(?:\.\d+)?)\s*(GB|MB|KB|B)", v, re.IGNORECASE)
                    if m:
                        size_value = float(m.group(1))
                        unit = m.group(2).upper()
                        if unit == "GB":
                            return int(size_value * 1024 * 1024 * 1024)
                        elif unit == "MB":
                            return int(size_value * 1024 * 1024)
                        elif unit == "KB":
                            return int(size_value * 1024)
                        elif unit == "B":
                            return int(size_value)
    return 0
