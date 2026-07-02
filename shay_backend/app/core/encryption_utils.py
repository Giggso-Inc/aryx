"""
Python encryption utilities for URL parameters
Equivalent to the JavaScript version for backend compatibility
"""

import base64
import os
import urllib.parse
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
from app.core.config import settings

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
        print(f"Encryption error: {e}")
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

def create_encrypted_registration_param(email: str, invite_code: str, company_id: str, role: str) -> str:
    """
    Creates an encrypted URL parameter for registration
    Args:
        email: User's email
        invite_code: Invitation code
        company_id: Company ID
        role: User role
    Returns:
        Encrypted parameter string
    """
    return encrypt_multiple([email, invite_code, company_id, role])

def decrypt_registration_params(encrypted_param: str) -> dict:
    """
    Decrypts registration parameters from URL
    Args:
        encrypted_param: The encrypted parameter from URL
    Returns:
        Dictionary with email, invite_code, company_id, and role
    """
    [email, invite_code, company_id, role] = decrypt_multiple(encrypted_param)
    return {
        'email': email,
        'invite_code': invite_code,
        'company_id': company_id,
        'role': role
    }

def create_registration_url(base_url: str, email: str, invite_code: str, company_id: str, role: str) -> str:
    """
    Creates a registration URL with encrypted parameters
    Args:
        base_url: Base URL for registration
        email: User's email
        invite_code: Invitation code
        company_id: Company ID
        role: User role
    Returns:
        Complete registration URL with URL-encoded encrypted parameter
    """
    encrypted_param = create_encrypted_registration_param(email, invite_code, company_id, role)
    # URL encode the encrypted parameter (equivalent to encodeURIComponent in JavaScript)
    import urllib.parse
    encoded_param = urllib.parse.quote(encrypted_param, safe='')
    return f"{base_url}/register?e={encoded_param}"


def create_password_reset_param(user_id: str, email: str, timestamp: str) -> str:
    """
    Creates an encrypted URL parameter for password reset
    Args:
        user_id: User's ID
        email: User's email
        timestamp: Timestamp when reset was requested
    Returns:
        Encrypted parameter string
    """
    return encrypt_multiple([user_id, email, timestamp])


def decrypt_password_reset_params(encrypted_param: str) -> dict:
    """
    Decrypts password reset parameters from URL
    Args:
        encrypted_param: The encrypted parameter from URL
    Returns:
        Dictionary with user_id, email, and timestamp
    """
    [user_id, email, timestamp] = decrypt_multiple(encrypted_param)
    return {
        'user_id': user_id,
        'email': email,
        'timestamp': timestamp
    }


def create_password_reset_url(base_url: str, user_id: str, email: str, timestamp: str) -> str:
    """
    Creates a password reset URL with encrypted parameters
    Args:
        base_url: Base URL for password reset
        user_id: User's ID
        email: User's email
        timestamp: Timestamp when reset was requested
    Returns:
        Complete password reset URL with URL-encoded encrypted parameter
    """
    encrypted_param = create_password_reset_param(user_id, email, timestamp)
    # URL encode the encrypted parameter
    import urllib.parse
    encoded_param = urllib.parse.quote(encrypted_param, safe='')
    return f"{base_url}/reset-password?token={encoded_param}"


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

def test_encryption():
    """
    Test function for development
    """
    test_data = {
        'email': 'kana@giggso.com',
        'invite_code': 'MpU69ugwzG69r1PCQjvpYPokZQv9HeNt8y9mO2oNYts',
        'company_id': '293792874982-242947924-242342344',
        'role': 'user'
    }
    
    print("Original data:", test_data)
    
    try:
        # Test encryption
        encrypted = create_encrypted_registration_param(
            test_data['email'],
            test_data['invite_code'],
            test_data['company_id'],
            test_data['role']
        )
        print("Encrypted:", encrypted)

        # Test decryption
        decrypted = decrypt_registration_params(encrypted)
        print("Decrypted:", decrypted)

        # Test URL creation
        url = create_registration_url(
            'http://localhost:3000',
            test_data['email'],
            test_data['invite_code'],
            test_data['company_id'],
            test_data['role']
        )
        print("Registration URL:", url)

        return {
            'encrypted': encrypted,
            'decrypted': decrypted,
            'url': url
        }
        
    except Exception as e:
        print(f"Test failed: {e}")
        raise

if __name__ == "__main__":
    # Run the test
    test_encryption()
