# 🔐 Encrypted Invitation System

This document explains how the new encrypted invitation system works in the Shay Suite Backend, which provides secure, tamper-proof invitation links for user registration.

## 🎯 Overview

The encrypted invitation system replaces the previous simple `invite_id` approach with a secure, encrypted URL parameter that contains all necessary registration information. This provides several benefits:

- **Security**: Invitation parameters cannot be tampered with
- **Privacy**: Sensitive information is encrypted in transit
- **Completeness**: All registration data is included in one parameter
- **Validation**: Automatic validation of invitation authenticity

## 🔧 How It Works

### 1. **Invitation Creation**
When a user is invited, the system:
1. Creates an invitation record in the database
2. Encrypts the following data:
   - `email_id` - User's email address
   - `invite_code` - Unique invitation UUID
   - `company_id` - Company ID for the user
   - `role` - User role (admin, user, guest)
3. Generates a registration URL with the encrypted parameter

### 2. **URL Format**
The generated URL follows this pattern:
```
{platform_url}/register?e={encrypted_parameter}
```

Example:
```
http://localhost:3000/register?e=eyJpdiI6IjEyMzQ1Njc4OTBhYmNkZWYiLCJkYXRhIjoiZW1haWxAZXhhbXBsZS5jb20kQCRpbnZpdGVfY29kZSRALmNvbXBhbnlfaWQkQHJvbGUiLCJ0YWciOiJ0YWdfZGF0YSJ9
```

### 3. **Registration Process**
When a user clicks the invitation link:
1. Frontend extracts the `e` parameter
2. Calls `/api/v1/user-auth/decrypt-registration?e={encrypted_param}` to decrypt
3. Uses decrypted data to pre-fill the registration form
4. Submits registration with password to `/api/v1/user-auth/register-encrypted`

## 🚀 API Endpoints

### **POST** `/api/v1/user-auth/invite`
Creates an invitation with encrypted registration link.

**Request:**
```json
{
  "email_id": "user@example.com",
  "name": "John Doe",
  "company_id": "uuid-here",
  "role": "user",
  "platform_url": "http://localhost:3000"
}
```

**Response:**
```json
{
  "message": "Invitation sent successfully",
  "invite_id": "uuid-here",
  "email_id": "user@example.com",
  "registration_link": "http://localhost:3000/register?e=encrypted_param_here",
  "expires_at": "2025-01-27T17:00:00"
}
```

**Note**: The `registration_link` now contains an encrypted parameter `e=` that includes all the registration information (email, invite_code, company_id, role) in an encrypted format.

## 🔒 Encryption Details

### **Algorithm**: AES-256-GCM
- **Key Size**: 32 bytes (256 bits)
- **Mode**: GCM (Galois/Counter Mode) for authenticated encryption
- **IV**: 12 bytes random initialization vector
- **Tag**: 16 bytes authentication tag

### **Key Derivation**: PBKDF2-HMAC-SHA256
- **Iterations**: 100,000
- **Salt**: 16 bytes random salt
- **Hash**: SHA-256

### **Data Format**
The encrypted data combines all parameters with a separator:
```
email$@$invite_code$@$company_id$@$role
```

## 🛠️ Configuration

### **Environment Variables**
```bash
# Encryption key (32 characters)
SECRET_KEY=your-secret-key-32-chars-long!!

# Platform URL for invitations
PLATFORM_URL=http://localhost:3000

# Email Configuration (Gmail SMTP)
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USERNAME=newuserpallavi2000@gmail.com
EMAIL_PASSWORD=fvkrijdiyvzeddyx
EMAIL_FROM=newuserpallavi2000@gmail.com
EMAIL_USE_TLS=true
```

### **Dependencies**
```bash
pip install cryptography==41.0.7
pip install emails==0.6.0
```

### **Gmail App Password Setup**
To use Gmail SMTP, you need to generate an App Password:
1. Go to your Google Account settings
2. Enable 2-Step Verification if not already enabled
3. Go to Security > App passwords
4. Generate a new app password for "Mail"
5. Use that password in EMAIL_PASSWORD

## 📱 Frontend Integration

The frontend can now extract the encrypted parameter from the invitation URL and use it as needed. The encrypted parameter contains all the registration information in a secure, tamper-proof format.

### **Example Usage**
```javascript
// Get the 'e' parameter from URL
const urlParams = new URLSearchParams(window.location.search);
const encryptedParam = urlParams.get('e');

if (encryptedParam) {
  // The encrypted parameter contains: email, invite_code, company_id, role
  // You can use this to pre-fill forms or validate the invitation
  console.log('Encrypted registration parameter:', encryptedParam);
  
  // Store or use the encrypted parameter as needed
  // The actual decryption can be handled by your frontend encryption utilities
}
```

**Note**: This system provides the encrypted registration link in the invitation email. The frontend can use the encrypted parameter for validation or pass it to your existing registration system.

## 🧪 Testing

### **Test Email System**
```bash
# Test the complete email system
python test_email_system.py

# Test via API endpoint
curl -X GET "http://localhost:8000/api/v1/user-auth/test-email"
```

### **Test Encryption Only**
```bash
cd app/core
python encryption_utils.py
```

### **Expected Output**
```
🔐 Testing Encryption Utilities
==================================================
📧 Test Data:
  email: kana@giggso.com
  invite_code: MpU69ugwzG69r1PCQjvpYPokZQv9HeNt8y9mO2oNYts
  company_id: 293792874982-242947924-242342344
  role: user

🔒 Testing Encryption...
✅ Encrypted: [encrypted_string]
✅ Registration URL: http://localhost:3000/register?e=[encrypted_string]

🎯 Expected URL format:
  http://localhost:3000/register?e=[encrypted_string]

📝 Encrypted parameter (e=):
  [encrypted_string]

✅ All tests passed!
```

**Note**: The system only encrypts the data. Decryption is handled by your frontend encryption utilities or can be implemented separately as needed.

## 🔐 Security Considerations

### **Key Management**
- Store encryption keys securely
- Rotate keys periodically
- Use environment variables for production

### **URL Security**
- Encrypted parameters are tamper-proof
- GCM mode provides authentication
- Parameters cannot be modified without detection

### **Invitation Expiration**
- Invitations expire after 7 days
- Used invitations are marked as such
- Prevents replay attacks

## 🚨 Troubleshooting

### **Common Issues**

1. **Encryption Failed**
   - Check if cryptography package is installed
   - Verify SECRET_KEY is 32 characters
   - Check for encoding issues

2. **Decryption Failed**
   - Verify the encrypted parameter is complete
   - Check if the parameter was modified
   - Ensure the same encryption key is used

3. **Invalid Parameter Format**
   - Verify the 'e' parameter exists in URL
   - Check if the parameter is base64 encoded
   - Ensure no URL encoding issues

### **Debug Mode**
Enable debug logging in your environment:
```bash
DEBUG=true
LOG_LEVEL=DEBUG
```

## 🔄 Migration from Old System

### **Backward Compatibility**
The old invitation system (`/api/v1/user-auth/register?invite_id={id}`) is still supported for existing invitations.

### **New Invitations**
All new invitations will use the encrypted system automatically, generating secure registration links with encrypted parameters.

### **Database Changes**
No database schema changes are required. The existing `invitations` table works with both systems.

### **What Changed**
- **Before**: Invitation links contained simple `invite_id` parameters
- **After**: Invitation links contain encrypted `e=` parameters with all registration data
- **Benefit**: Enhanced security and tamper-proof invitation links

## 📚 Additional Resources

- [Cryptography Documentation](https://cryptography.io/)
- [AES-GCM Security](https://en.wikipedia.org/wiki/Galois/Counter_Mode)
- [PBKDF2 Key Derivation](https://en.wikipedia.org/wiki/PBKDF2)

## 🤝 Support

For questions or issues with the encrypted invitation system, please:
1. Check the logs for error messages
2. Verify the encryption configuration
3. Test with the provided test script
4. Contact the development team
