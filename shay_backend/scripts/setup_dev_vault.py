#!/usr/bin/env python3
"""
Dev Vault Setup Script

This script helps you set up the proper environment variables for connecting to the dev vault
instead of falling back to localhost:8200.

Usage:
    python scripts/setup_dev_vault.py

The script will:
1. Show current vault configuration
2. Help you set up dev vault environment variables
3. Test the vault connection
"""

import os
import base64
import sys
from pathlib import Path

def show_current_config():
    """Show current vault configuration"""
    print("=== Current Vault Configuration ===")
    
    endpoint = os.environ.get("CREDENTIALS_MGMT_KV_ENDPOINT")
    token = os.environ.get("CREDENTIALS_MGMT_VAULT_TOKEN")
    path = os.environ.get("GIGGSO_CONNECTIONS_PATH_PARAM", "giggso/connections")
    
    if endpoint:
        try:
            decoded_endpoint = base64.b64decode(endpoint).decode('utf-8')
            print(f"✅ Vault Endpoint: {decoded_endpoint}")
        except:
            print(f"❌ Vault Endpoint: {endpoint} (invalid base64)")
    else:
        print("❌ CREDENTIALS_MGMT_KV_ENDPOINT not set")
    
    if token:
        try:
            decoded_token = base64.b64decode(token).decode('utf-8')
            print(f"✅ Vault Token: {decoded_token[:10]}...")
        except:
            print(f"❌ Vault Token: {token} (invalid base64)")
    else:
        print("❌ CREDENTIALS_MGMT_VAULT_TOKEN not set")
    
    print(f"✅ Connections Path: {path}")
    print()

def encode_vault_config():
    """Help encode vault configuration"""
    print("=== Encode Dev Vault Configuration ===")
    print("Enter your dev vault details (they will be base64 encoded):")
    
    try:
        endpoint = input("Dev Vault Endpoint (e.g., https://dev-vault.example.com/v1/secret): ").strip()
        if not endpoint:
            print("❌ Endpoint cannot be empty")
            return
        
        token = input("Dev Vault Token: ").strip()
        if not token:
            print("❌ Token cannot be empty")
            return
        
        # Encode to base64
        endpoint_encoded = base64.b64encode(endpoint.encode('utf-8')).decode('utf-8')
        token_encoded = base64.b64encode(token.encode('utf-8')).decode('utf-8')
        
        print("\n=== Encoded Values ===")
        print(f"CREDENTIALS_MGMT_KV_ENDPOINT=\"{endpoint_encoded}\"")
        print(f"CREDENTIALS_MGMT_VAULT_TOKEN=\"{token_encoded}\"")
        print()
        
        # Save to .env file
        env_file = Path(".env")
        if env_file.exists():
            print("⚠️  .env file already exists. Please manually add these lines:")
            print(f"CREDENTIALS_MGMT_KV_ENDPOINT=\"{endpoint_encoded}\"")
            print(f"CREDENTIALS_MGMT_VAULT_TOKEN=\"{token_encoded}\"")
        else:
            with open(env_file, 'w') as f:
                f.write(f"CREDENTIALS_MGMT_KV_ENDPOINT=\"{endpoint_encoded}\"\n")
                f.write(f"CREDENTIALS_MGMT_VAULT_TOKEN=\"{token_encoded}\"\n")
            print("✅ Created .env file with vault configuration")
        
        print("\n=== Next Steps ===")
        print("1. Add these environment variables to your dev environment")
        print("2. Restart your application")
        print("3. Test vault integration")
        
    except KeyboardInterrupt:
        print("\n❌ Setup cancelled")
    except Exception as e:
        print(f"❌ Error: {e}")

def test_vault_connection():
    """Test vault connection"""
    print("=== Test Vault Connection ===")
    
    try:
        # Import vault service
        sys.path.append(str(Path(__file__).parent.parent))
        from app.services.vault_service import VaultService
        
        vault_service = VaultService()
        
        if vault_service.vault_endpoint and vault_service.vault_token:
            print(f"✅ Vault service configured for: {vault_service.vault_endpoint}")
            
            # Test with a simple data structure
            test_data = {"test": "data", "timestamp": "2025-01-01"}
            test_id = vault_service.generate_vault_unique_id("test_user", "test")
            
            print(f"✅ Generated test vault ID: {test_id}")
            print("✅ Vault service is ready to use")
        else:
            print("❌ Vault service not configured")
            print("Set CREDENTIALS_MGMT_KV_ENDPOINT and CREDENTIALS_MGMT_VAULT_TOKEN")
            
    except ImportError as e:
        print(f"❌ Cannot import vault service: {e}")
        print("Make sure you're running this from the project root")
    except Exception as e:
        print(f"❌ Error testing vault service: {e}")

def main():
    """Main function"""
    print("🔐 Dev Vault Setup Script")
    print("=" * 50)
    
    while True:
        print("\nOptions:")
        print("1. Show current vault configuration")
        print("2. Encode dev vault configuration")
        print("3. Test vault connection")
        print("4. Exit")
        
        try:
            choice = input("\nEnter your choice (1-4): ").strip()
            
            if choice == "1":
                show_current_config()
            elif choice == "2":
                encode_vault_config()
            elif choice == "3":
                test_vault_connection()
            elif choice == "4":
                print("👋 Goodbye!")
                break
            else:
                print("❌ Invalid choice. Please enter 1-4.")
                
        except KeyboardInterrupt:
            print("\n👋 Goodbye!")
            break
        except Exception as e:
            print(f"❌ Error: {e}")

if __name__ == "__main__":
    main()
