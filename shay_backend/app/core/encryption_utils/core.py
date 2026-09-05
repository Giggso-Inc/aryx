"""
Core AES-GCM encrypt/decrypt primitives — the base every other helper in
this package builds on.

Split out of app/core/encryption_utils.py — see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md.
"""

import base64
import logging
import os
import urllib.parse
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
from app.core.config import settings

logger = logging.getLogger(__name__)

SEPARATOR = '$@$'


def _secret_key() -> bytes:
    """Load the AES key from env-backed settings and validate its shape."""
    key = (settings.SHAY_TOKEN_ENCRYPTION_KEY or "").strip()
    if not key:
        raise ValueError("SHAY_TOKEN_ENCRYPTION_KEY is required")
    if len(key) != 64:
        raise ValueError("SHAY_TOKEN_ENCRYPTION_KEY must be a 64-character hex string")
    return bytes.fromhex(key)

def encrypt(data: str) -> str:
    """
    Encrypts data using AES encryption
    Args:
        data: The data to encrypt
    Returns:
        Encrypted string in base64 format
    """
    try:
        # Convert string to bytes
        data_bytes = data.encode('utf-8')

        # Generate a random IV
        iv = os.urandom(12)

        # Create cipher
        cipher = Cipher(algorithms.AES(_secret_key()), modes.GCM(iv), backend=default_backend())
        encryptor = cipher.encryptor()

        # Encrypt the data
        encrypted_data = encryptor.update(data_bytes) + encryptor.finalize()

        # Get the tag
        tag = encryptor.tag

        # Combine IV, encrypted data, and tag
        combined = iv + encrypted_data + tag

        # Convert to base64
        return base64.b64encode(combined).decode('utf-8')

    except Exception as e:
        logger.error("Encryption failed: %s", e, exc_info=True)
        raise Exception("Encryption failed")

def decrypt(encrypted_data: str) -> str:
    """
    Decrypts data using AES decryption
    Args:
        encrypted_data: The encrypted data to decrypt
    Returns:
        Decrypted string
    """
    try:
        # Convert from base64
        combined = base64.b64decode(encrypted_data)

        # Extract IV, encrypted data, and tag
        iv = combined[:12]
        encrypted = combined[12:-16]
        tag = combined[-16:]

        # Create cipher
        cipher = Cipher(algorithms.AES(_secret_key()), modes.GCM(iv, tag), backend=default_backend())
        decryptor = cipher.decryptor()

        # Decrypt the data
        decrypted_data = decryptor.update(encrypted) + decryptor.finalize()

        # Convert back to string
        return decrypted_data.decode('utf-8')

    except Exception as e:
        print(f"Decryption error: {e}")
        raise Exception("Decryption failed")

def encrypt_multiple(values: list[str]) -> str:
    """
    Encrypts multiple values and combines them with a separator
    Args:
        values: List of values to encrypt
    Returns:
        Encrypted string with all values
    """
    combined = SEPARATOR.join(values)
    return encrypt(combined)

def decrypt_multiple(encrypted_data: str) -> list[str]:
    """
    Decrypts a combined string and splits it into multiple values
    Args:
        encrypted_data: The encrypted data containing multiple values
    Returns:
        List of decrypted values
    """
    decrypted = decrypt(encrypted_data)
    return decrypted.split(SEPARATOR)


def decrypt_urlsafe_token(token: str) -> str:
    """
    Decrypt a token that may have been URL encoded and converted to URL-safe base64.
    """
    candidates: list[str] = []
    for raw in (token, urllib.parse.unquote(token)):
        if not raw:
            continue
        candidates.append(raw)
        normalized = raw.replace('-', '+').replace('_', '/')
        padding = "=" * ((4 - (len(normalized) % 4)) % 4)
        candidates.append(normalized + padding)

    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            return decrypt(candidate)
        except Exception:
            continue
    raise ValueError("Invalid encrypted token")
