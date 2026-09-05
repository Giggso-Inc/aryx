"""
Manual dev-only smoke test for the encryption helpers — run directly with
`python -m app.core.encryption_utils.devtest`, never imported by app code.

Split out of app/core/encryption_utils.py — see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md.
Kept in its own file (rather than __init__.py or core.py) so pytest never
sees a `test_*`-named function get collected from a non-test module.
"""

from app.core.encryption_utils.registration import create_encrypted_registration_param, create_registration_url
from app.core.encryption_utils.registration import decrypt_registration_params


def test_encryption() -> dict:
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
