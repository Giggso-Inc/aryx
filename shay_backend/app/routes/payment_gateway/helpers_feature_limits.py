"""
Dead-code feature-limit parsers, carried over verbatim from helpers.py.

Note (dead-code finding, documented not fixed — see the "Stated exception /
findings" note in tests/test_payment_gateway_characterization.py):
`parse_features_to_limits` and `extract_price_from_brackets` are defined
here but are not called anywhere in the original payment_gateway.py, nor
imported by any other module in the repo (confirmed by grep before the
split). They are carried over verbatim rather than removed, since removing
unused-but-public module-level functions is a behavior change outside the
scope of this file-split task.
"""

import json
import re
from typing import Any, Dict, Optional


def parse_features_to_limits(features: Any) -> Dict[str, int]:
    """
    Parse features from subscription plan to extract limits.

    Features can be in format like: ["5 Channels", "10 Messages", "5GB Storage"]
    Returns a dictionary with channelLimit, messageLimit, and StorageLimit.
    """
    limits = {
        "channelLimit": 0,
        "messageLimit": 0,
        "StorageLimit": 0
    }

    if not features:
        return limits

    # Handle list format: ["5 Channels", "10 Messages", "5GB Storage"]
    features_list = []
    if isinstance(features, list):
        features_list = features
    elif isinstance(features, dict):
        # If it's a dict, extract values
        features_list = list(features.values())
    elif isinstance(features, str):
        # If it's a string, try to parse as JSON
        try:
            parsed = json.loads(features)
            if isinstance(parsed, list):
                features_list = parsed
            elif isinstance(parsed, dict):
                features_list = list(parsed.values())
        except:
            features_list = [features]

    # Parse each feature string
    for feature in features_list:
        if not isinstance(feature, str):
            continue

        feature_lower = feature.lower()

        # Extract number and unit
        # Pattern: "5 Channels", "10 Messages", "5GB Storage", "5 GB Storage"
        # Try pattern with storage unit first (GB, MB, KB): "5GB Storage" or "5 GB Storage"
        match = re.search(r'(\d+(?:\.\d+)?)\s*([kmg]b)\s*(channel|message|storage)', feature_lower)
        if match:
            number = float(match.group(1))
            unit = match.group(2).lower()
            feature_type = match.group(3)
        else:
            # Try pattern without unit: "5 Channels", "10 Messages"
            match = re.search(r'(\d+(?:\.\d+)?)\s+(channel|message|storage)', feature_lower)
            if match:
                number = float(match.group(1))
                unit = ""
                feature_type = match.group(2)
            else:
                continue

        # Convert to base units
        if feature_type == "channel":
            limits["channelLimit"] = int(number)
        elif feature_type == "message":
            limits["messageLimit"] = int(number)
        elif feature_type == "storage":
            # Convert storage to bytes (GB -> bytes)
            if unit == "gb":
                limits["StorageLimit"] = int(number * 1024 * 1024 * 1024)  # GB to bytes
            elif unit == "mb":
                limits["StorageLimit"] = int(number * 1024 * 1024)  # MB to bytes
            elif unit == "kb":
                limits["StorageLimit"] = int(number * 1024)  # KB to bytes
            else:
                # Assume bytes if no unit
                limits["StorageLimit"] = int(number)

    return limits


def extract_price_from_brackets(addon: Dict[str, Any]) -> Optional[float]:
    """
    Extract price from price_brackets array.

    Zoho API returns price in price_brackets format, not as a direct price field.
    This helper extracts the price from the first price bracket.

    Args:
        addon: Addon data dictionary from Zoho API

    Returns:
        Price as float, or None if not found
    """
    price_brackets = addon.get('price_brackets', [])
    if price_brackets and len(price_brackets) > 0:
        # Get the first price bracket's price
        first_bracket = price_brackets[0]
        if isinstance(first_bracket, dict) and 'price' in first_bracket:
            try:
                return float(first_bracket.get('price', 0))
            except (ValueError, TypeError):
                pass
    # Fallback to direct price field if available
    price = addon.get('price')
    if price is not None:
        try:
            return float(price)
        except (ValueError, TypeError):
            pass
    return None
