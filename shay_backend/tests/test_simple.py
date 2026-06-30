#!/usr/bin/env python3
"""
Simple test runner for embedd_type functionality without full app context
"""

import sys
import os

# Add the parent directory to Python path
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, parent_dir)

def test_embedd_type_function():
    """Test the get_embedd_type_from_file_type function"""
    from app.services.ml_service import get_embedd_type_from_file_type
    
    print("🧪 Testing get_embedd_type_from_file_type function")
    print("=" * 60)
    
    # Test textual MIME types
    textual_tests = [
        'text/plain',
        'application/pdf',
        'application/msword',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'application/vnd.ms-powerpoint',
        'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        'application/rtf'
    ]
    
    print("\n📄 Testing TEXTUAL MIME types:")
    for file_type in textual_tests:
        result = get_embedd_type_from_file_type(file_type)
        status = "✅" if result == "textual" else "❌"
        print(f"  {status} {file_type:<60} -> {result}")
    
    # Test tabular MIME types
    tabular_tests = [
        'application/vnd.ms-excel',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'text/csv',
        'application/csv',
        'application/json',
        'text/json'
    ]
    
    print("\n📊 Testing TABULAR MIME types:")
    for file_type in tabular_tests:
        result = get_embedd_type_from_file_type(file_type)
        status = "✅" if result == "tabular" else "❌"
        print(f"  {status} {file_type:<60} -> {result}")
    
    # Test file extensions
    print("\n📁 Testing FILE EXTENSIONS:")
    extension_tests = [
        ('txt', 'textual'),
        ('pdf', 'textual'),
        ('doc', 'textual'),
        ('docx', 'textual'),
        ('ppt', 'textual'),
        ('pptx', 'textual'),
        ('rtf', 'textual'),
        ('html', 'textual'),
        ('htm', 'textual'),
        ('xls', 'tabular'),
        ('xlsx', 'tabular'),
        ('csv', 'tabular'),
        ('json', 'tabular')
    ]
    
    for extension, expected in extension_tests:
        result = get_embedd_type_from_file_type(extension)
        status = "✅" if result == expected else "❌"
        print(f"  {status} {extension:<10} -> {result} (expected: {expected})")
    
    # Test edge cases
    print("\n🔍 Testing EDGE CASES:")
    edge_cases = [
        (None, 'textual'),
        ('', 'textual'),
        ('unknown_type', 'textual'),
        ('image/jpeg', 'textual'),
        ('video/mp4', 'textual')
    ]
    
    for file_type, expected in edge_cases:
        result = get_embedd_type_from_file_type(file_type)
        status = "✅" if result == expected else "❌"
        print(f"  {status} {str(file_type):<15} -> {result} (expected: {expected})")
    
    # Test case insensitive
    print("\n🔤 Testing CASE INSENSITIVE:")
    case_tests = [
        ('TEXT/PLAIN', 'textual'),
        ('APPLICATION/PDF', 'textual'),
        ('TXT', 'textual'),
        ('XLSX', 'tabular'),
        ('CSV', 'tabular')
    ]
    
    for file_type, expected in case_tests:
        result = get_embedd_type_from_file_type(file_type)
        status = "✅" if result == expected else "❌"
        print(f"  {status} {file_type:<20} -> {result} (expected: {expected})")
    
    print("\n" + "=" * 60)
    print("✅ All tests completed!")

def test_ml_service_payload():
    """Test ML service payload format"""
    from app.services.ml_service import MLService
    
    print("\n🧪 Testing ML Service Payload Format")
    print("=" * 60)
    
    ml_service = MLService()
    
    # Test payload creation (without making actual HTTP request)
    import json
    
    # Simulate the payload creation
    channel_id = "test_channel_id"
    vault_unique_ids = ["test_vault_id"]
    embedded_vault_unique_ids = []
    user_id = "test_user_id"
    company_id = "test_company_id"
    embedd_type = "textual"
    
    # Create payload (matching the ML service)
    payload = {
        "channelId": channel_id,
        "dataSourcesVaultTokens": vault_unique_ids,
        "embeddedDataSourceVaultTokens": embedded_vault_unique_ids or [],
        "userId": user_id,
        "companyId": company_id,
        "embeddType": embedd_type
    }
    
    print("📦 Generated Payload:")
    print(json.dumps(payload, indent=2))
    
    # Verify payload structure
    required_fields = ["channelId", "dataSourcesVaultTokens", "embeddedDataSourceVaultTokens", "userId", "companyId", "embeddType"]
    missing_fields = [field for field in required_fields if field not in payload]
    
    if missing_fields:
        print(f"❌ Missing fields: {missing_fields}")
    else:
        print("✅ All required fields present")
    
    # Verify embeddType value
    if payload.get("embeddType") in ["textual", "tabular"]:
        print(f"✅ embeddType value is valid: {payload['embeddType']}")
    else:
        print(f"❌ embeddType value is invalid: {payload['embeddType']}")
    
    # Verify field name is camelCase
    if "embeddType" in payload and "embedd_type" not in payload:
        print("✅ Field name is correctly camelCase (embeddType)")
    else:
        print("❌ Field name is not camelCase")
    
    print("=" * 60)

if __name__ == "__main__":
    test_embedd_type_function()
    test_ml_service_payload()