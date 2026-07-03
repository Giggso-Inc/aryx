# API Endpoints - Request & Response Bodies

## Platform Name APIs

### POST `/api/v1/public/companies`

**Request Body:**

```json
{
  "name": "Acme Corporation",
  "domain": "acme.com",
  "contactEmail": "admin@acme.com",
  "userName": "John Doe",
  "industry": "Technology",
  "status": "active",
  "planId": "plan-uuid-here",
  "password": "SecurePassword123!",
  "encrypted": false,
  "platform_name": "Shay Suite",
  "platform_url": "https://app.shay-suite.com"
}
```

**Response Body:**

```json
{
  "success": true,
  "data": {
    "customerId": "550e8400-e29b-41d4-a716-446655440000",
    "companyName": "Acme Corporation",
    "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "tokenId": "token-uuid-here",
    "zohoCustomerId": "zoho-customer-id",
    "planId": "plan-uuid-here",
    "planName": "Free Plan",
    "isDefaultPlan": true
  },
  "message": "Company created and onboarded successfully!",
  "code": 200
}
```

---

### POST `/api/v1/public/resend-verification`

**Request Body:**

```json
{
  "email": "user@example.com",
  "platform_name": "Shay Suite"
}
```

**Response Body:**

```json
{
  "success": true,
  "message": "Verification email has been resent successfully. Please check your inbox.",
  "email_sent": true
}
```

---

### POST `/api/v1/public/notify-api-failure`

**Request Body:**

```json
{
  "api_endpoint": "/api/v1/users",
  "error_message": "Database connection failed",
  "error_type": "DatabaseError",
  "user_id": "user-uuid-here",
  "company_id": "company-uuid-here",
  "request_method": "POST",
  "request_body": "{\"name\": \"test\"}",
  "stack_trace": "Traceback (most recent call last):\n  File \"app.py\", line 1",
  "support_email": "support@example.com",
  "platform_name": "Shay Suite"
}
```

**Response Body:**

```json
{
  "success": true,
  "message": "Error notification email sent successfully to support team.",
  "email_sent": true,
  "support_email": "support@example.com"
}
```

---

### POST `/api/v1/channels/{channel_id}/members`

**Request Body:**

```json
{
  "mail_id": "newuser@example.com",
  "role": "user",
  "permissions": {
    "can_read": true,
    "can_write": true
  },
  "platform_name": "Shay Suite"
}
```

**Response Body:**

```json
{
  "id": "member-uuid-here",
  "channel_id": "channel-uuid-here",
  "user_id": "user-uuid-here",
  "role": "user",
  "is_active": true,
  "permissions": {
    "can_read": true,
    "can_write": true
  },
  "created_at": "2025-01-27T10:30:00Z",
  "updated_at": "2025-01-27T10:30:00Z"
}
```

---

### POST `/api/v1/channels/{channel_id}/members/bulk-csv`

**Request Body:** Multipart form data with CSV file

**CSV File Format:**

```csv
gmail_id,role
user1@example.com,user
user2@example.com,admin
user3@example.com,user
```

**Response Body:**

```json
{
  "items": [
    {
      "id": "member-uuid-1",
      "channel_id": "channel-uuid-here",
      "user_id": "user-uuid-1",
      "role": "user",
      "is_active": true,
      "permissions": null,
      "created_at": "2025-01-27T10:30:00Z",
      "updated_at": "2025-01-27T10:30:00Z"
    },
    {
      "id": "member-uuid-2",
      "channel_id": "channel-uuid-here",
      "user_id": "user-uuid-2",
      "role": "admin",
      "is_active": true,
      "permissions": null,
      "created_at": "2025-01-27T10:30:00Z",
      "updated_at": "2025-01-27T10:30:00Z"
    }
  ],
  "total": 2,
  "message": "Successfully added 2 members to channel",
  "errors": null
}
```

---

### POST `/api/v1/user-auth/invite`

**Request Body:**

```json
{
  "email": "newuser@example.com",
  "company_id": "company-uuid-here",
  "role": "user",
  "user_id": "inviter-uuid-here",
  "template_id": "TMPLT_INVITE_001",
  "platform_name": "Shay Suite"
}
```

**Response Body:**

```json
{
  "message": "Invitation sent successfully (Email sent)",
  "invite_id": "invite-uuid-here",
  "email_id": "newuser@example.com",
  "registration_link": "https://app.shay-suite.com/register?invite=encrypted-token",
  "expires_at": "2025-02-03T10:30:00Z"
}
```

---

### POST `/api/v1/user-auth/bulk-invite`

**Request Body:**

```json
{
  "users": [
    {
      "email": "user1@example.com",
      "company_id": "company-uuid-here",
      "role": "user"
    },
    {
      "email": "user2@example.com",
      "company_id": "company-uuid-here",
      "role": "admin"
    }
  ],
  "template_id": "TMPLT_INVITE_001",
  "user_id": "inviter-uuid-here",
  "platform_name": "Shay Suite"
}
```

**Response Body:**

```json
{
  "message": "Bulk invitations processed successfully",
  "total_invited": 2,
  "successful_invitations": [
    {
      "message": "Invitation sent successfully (Email sent)",
      "invite_id": "invite-uuid-1",
      "email_id": "user1@example.com",
      "registration_link": "https://app.shay-suite.com/register?invite=encrypted-token-1",
      "expires_at": "2025-02-03T10:30:00Z"
    },
    {
      "message": "Invitation sent successfully (Email sent)",
      "invite_id": "invite-uuid-2",
      "email_id": "user2@example.com",
      "registration_link": "https://app.shay-suite.com/register?invite=encrypted-token-2",
      "expires_at": "2025-02-03T10:30:00Z"
    }
  ],
  "failed_invitations": []
}
```

---

## App Filter APIs

### GET `/api/v1/apps`

**Query Parameters:**
- `subCategory` (optional): Filter by subcategory - "Cloud Drive" or "Datasource" (case-insensitive)
- `category` (optional): Filter by category
- `is_active` (optional): Filter by active status
- `is_public` (optional): Filter by public status
- `search` (optional): Search in app name, key, description, or category
- `page` (optional): Page number (default: 1)
- `size` (optional): Page size (default: 10, max: 100)

**Example Request:**
```
GET /api/v1/apps?subCategory=Cloud Drive
GET /api/v1/apps?subCategory=datasource&is_active=true
GET /api/v1/apps?category=Email&subCategory=Datasource
```

**Response Body:**

```json
{
  "apps": [
    {
      "id": "app-uuid-here",
      "app_name": "Google Drive",
      "app_key": "google_drive",
      "app_description": "Google Drive cloud storage integration",
      "app_image": "https://example.com/google-drive.png",
      "is_active": true,
      "is_public": true,
      "version": "1.0.0",
      "category": "Storage",
      "sub_category": "Cloud Drive",
      "tags": ["cloud", "storage", "google"],
      "created_at": "2025-01-27T10:30:00Z",
      "updated_at": "2025-01-27T10:30:00Z"
    },
    {
      "id": "app-uuid-2",
      "app_name": "Gmail",
      "app_key": "gmail",
      "app_description": "Gmail email service integration",
      "app_image": "https://example.com/gmail.png",
      "is_active": true,
      "is_public": true,
      "version": "1.0.0",
      "category": "Email",
      "sub_category": "Datasource",
      "tags": ["email", "google", "communication"],
      "created_at": "2025-01-27T10:30:00Z",
      "updated_at": "2025-01-27T10:30:00Z"
    }
  ],
  "total": 2,
  "page": 1,
  "size": 10,
  "pages": 1
}
```

---

### POST `/api/v1/apps`

**Request Body:**

```json
{
  "app_name": "New App",
  "app_key": "new_app",
  "app_description": "Description of the new app",
  "app_image": "https://example.com/app-image.png",
  "is_active": true,
  "is_public": true,
  "version": "1.0.0",
  "category": "Productivity",
  "sub_category": "Datasource",
  "tags": ["productivity", "tools"]
}
```

**Response Body:**

```json
{
  "id": "app-uuid-here",
  "app_name": "New App",
  "app_key": "new_app",
  "app_description": "Description of the new app",
  "app_image": "https://example.com/app-image.png",
  "is_active": true,
  "is_public": true,
  "version": "1.0.0",
  "category": "Productivity",
  "sub_category": "Datasource",
  "tags": ["productivity", "tools"],
  "created_at": "2025-01-27T10:30:00Z",
  "updated_at": "2025-01-27T10:30:00Z"
}
```

---

### GET `/api/v1/apps/{app_id}`

**Response Body:**

```json
{
  "id": "app-uuid-here",
  "app_name": "Google Drive",
  "app_key": "google_drive",
  "app_description": "Google Drive cloud storage integration",
  "app_image": "https://example.com/google-drive.png",
  "is_active": true,
  "is_public": true,
  "version": "1.0.0",
  "category": "Storage",
  "sub_category": "Cloud Drive",
  "tags": ["cloud", "storage", "google"],
  "created_at": "2025-01-27T10:30:00Z",
  "updated_at": "2025-01-27T10:30:00Z"
}
```

---

### PUT `/api/v1/apps/{app_id}`

**Request Body:**

```json
{
  "app_name": "Updated App Name",
  "sub_category": "Cloud Drive",
  "is_active": false
}
```

**Response Body:**

```json
{
  "id": "app-uuid-here",
  "app_name": "Updated App Name",
  "app_key": "google_drive",
  "app_description": "Google Drive cloud storage integration",
  "app_image": "https://example.com/google-drive.png",
  "is_active": false,
  "is_public": true,
  "version": "1.0.0",
  "category": "Storage",
  "sub_category": "Cloud Drive",
  "tags": ["cloud", "storage", "google"],
  "created_at": "2025-01-27T10:30:00Z",
  "updated_at": "2025-01-27T11:00:00Z"
}
```

---

### GET `/api/v1/apps/stats`

**Response Body:**

```json
{
  "total_apps": 50,
  "active_apps": 45,
  "public_apps": 40,
  "categories": ["Email", "Storage", "Productivity"],
  "recent_apps": [
    {
      "id": "app-uuid-1",
      "app_name": "Recent App 1",
      "app_description": "Description",
      "app_image": "https://example.com/app1.png",
      "is_active": true,
      "is_public": true,
      "version": "1.0.0",
      "category": "Productivity",
      "sub_category": "Datasource",
      "tags": ["productivity"],
      "created_at": "2025-01-27T10:30:00Z",
      "updated_at": "2025-01-27T10:30:00Z"
    }
  ]
}
```

---

## Notes

### Platform Name Parameter
- All `platform_name` parameters are optional
- If not provided, system uses default from configuration
- Used for email personalization and branding

### SubCategory Filter
- Valid values: `"Cloud Drive"` or `"Datasource"`
- Filter is case-insensitive (e.g., `"cloud drive"`, `"CLOUD DRIVE"`, `"Cloud Drive"` all work)
- Can be combined with other filters (`category`, `is_active`, etc.)
- Cloud Drive apps: Google Drive, SharePoint, Dropbox, OneDrive, Box
- All other apps default to "Datasource"

