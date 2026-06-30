# Company Signup and Onboarding API Reference

This document provides the complete API reference for company signup and onboarding functionality, matching the Node.js API format.

## Table of Contents

1. [Company Signup](#1-company-signup)
2. [Fetch Plans](#2-fetch-plans)
3. [Auto Login](#3-auto-login)
4. [My Subscription](#4-my-subscription)
5. [Zoho Hosted Page Creation](#5-zoho-hosted-page-creation)
6. [Zoho Subscription Creation](#6-zoho-subscription-creation)
7. [Zoho Webhook](#7-zoho-webhook)

## 1. Company Signup

### POST `/api/v1/public/companies`

Creates a new company with admin user using simplified payload structure.

**Request Body:**
```json
{
  "name": "Acme Corporation",
  "domain": "acme.com",
  "contactEmail": "contact@acme.com",
  "industry": "Technology",
  "status": "active",
  "planId": null,
  "password": "password123"
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "customerId": "543a6d33-2daa-4a94-8918-c5d465619097",
    "companyName": "Acme Corporation",
    "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "tokenId": "01f3d686-64a5-454d-9612-adbb96e07c9d",
    "zohoCustomerId": null,
    "planId": "3ffb3178-5ac3-4470-b208-dd865fb914fb",
    "planName": "Trial",
    "isDefaultPlan": true
  },
  "message": "Company created and onboarded successfully!",
  "code": 200
}
```

**Email Notification:**
- A welcome email is automatically sent to the `contactEmail` address
- The email includes company details, plan information, and app access link
- Email sending is non-blocking - company creation succeeds even if email fails

## 2. Fetch Plans

### GET `/api/v1/public/fetchPlans`

Fetches all available subscription plans for onboarding.

**Response:**
```json
{
  "success": true,
  "data": [
    {
      "name": "Starter",
      "planCode": "starter001",
      "description": "this is starter plan",
      "monthlyPrice": "25.00",
      "planCycles": 1,
      "features": ["300 AI Responses"],
      "isActive": true,
      "sortOrder": 1,
      "createdAt": "2025-08-21T20:24:03.786Z",
      "updatedAt": "2025-08-21T20:24:05.752Z",
      "zohoPlanId": "6808022000000150001",
      "zohoProductId": "6808022000000093214",
      "intervalCount": 1,
      "deletedAt": null,
      "zohoPlanCode": null,
      "zohoProductCode": null,
      "zohoBillingCycle": null,
      "updatedBy": null,
      "intervalUnit": "months",
      "interval": 1,
      "id": "e27ad9b8-27e8-4bd8-a7b0-7126bce7bbcf",
      "createdBy": null,
      "subscriberCount": "0",
      "createdByEmail": "System",
      "createdByRole": "System",
      "createdById": "00000000-0000-0000-0000-000000000000"
    }
  ],
  "message": "Plans fetched successfully",
  "code": 200
}
```

## 3. Auto Login

### POST `/api/v1/public/autoLogin`

Auto-login after successful company creation.

**Request Body:**
```json
{
  "email": "contact@acme.com",
  "password": "password123"
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "token_type": "bearer",
    "user_id": "62bd1ea7-0174-435b-bcca-2f731f4800e5",
    "email_id": "contact@acme.com",
    "role": "admin",
    "company_id": "543a6d33-2daa-4a94-8918-c5d465619097"
  },
  "message": "Login successful",
  "code": 200
}
```

## 4. My Subscription

### GET `/api/v1/public/mySubscription`

Get current company's subscription details.

**Headers:**
```
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

**Response:**
```json
{
  "success": true,
  "data": {
    "name": "Trial",
    "planCode": "trial001",
    "description": "this is trial plan",
    "monthlyPrice": "0.00",
    "planCycles": 3,
    "features": ["100 AI Responses"],
    "isActive": true,
    "sortOrder": 1,
    "createdAt": "2025-08-13T21:57:32.176Z",
    "updatedAt": "2025-08-13T20:24:05.752Z",
    "zohoPlanId": "6808022000000136781",
    "zohoProductId": "6808022000000093214",
    "intervalCount": 1,
    "deletedAt": null,
    "zohoPlanCode": null,
    "zohoProductCode": null,
    "zohoBillingCycle": null,
    "updatedBy": null,
    "intervalUnit": "months",
    "interval": 1,
    "id": "3ffb3178-5ac3-4470-b208-dd865fb914fb",
    "createdBy": null
  },
  "message": "Subscription details fetched successfully",
  "code": 200
}
```

## 5. Zoho Hosted Page Creation

### POST `/api/v1/payment-gateway/zoho/subscriptions/hostedPage/create`

Creates a Zoho hosted payment page for subscription.

**Request Body:**
```json
{
  "plan": {
    "name": "Starter",
    "planCode": "starter001",
    "description": "this is starter plan"
  },
  "redirectUrl": "http://localhost/payment-success",
  "customer": {
    "displayName": "Acme Corp",
    "salutation": "Mr.",
    "firstName": "John",
    "lastName": "Doe",
    "email": "john@acme.com",
    "companyName": "Acme Corporation",
    "phone": "",
    "mobile": "",
    "website": "acme.com",
    "currencyCode": "USD"
  },
  "autoCollect": true
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "hostedPageId": "01f3d686-64a5-454d-9612-adbb96e07c9d",
    "url": "https://zoho.com/hosted-page/01f3d686-64a5-454d-9612-adbb96e07c9d",
    "planId": "e27ad9b8-27e8-4bd8-a7b0-7126bce7bbcf",
    "planName": "Starter",
    "amount": 25.0,
    "companyId": "543a6d33-2daa-4a94-8918-c5d465619097",
    "companyName": "Acme Corporation",
    "expiresAt": "2025-01-28T12:00:00.000Z"
  },
  "message": "Hosted payment page created successfully",
  "code": 200
}
```

## 6. Zoho Subscription Creation

### POST `/api/v1/payment-gateway/zoho/subscriptions/create`

Creates subscriptions for free plans and updates company's subscription plan.

**Request Body:**
```json
{
  "plan_id": "e27ad9b8-27e8-4bd8-a7b0-7126bce7bbcf"
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "subscription_id": "01f3d686-64a5-454d-9612-adbb96e07c9d",
    "plan_id": "e27ad9b8-27e8-4bd8-a7b0-7126bce7bbcf",
    "plan_name": "Starter",
    "company_id": "543a6d33-2daa-4a94-8918-c5d465619097",
    "company_name": "Acme Corporation",
    "status": "active"
  },
  "message": "Subscription created successfully",
  "code": 200
}
```

## 7. Zoho Webhook

### POST `/api/v1/payment-gateway/zoho/webhook/subscription`

Handles Zoho subscription webhooks.

**Request Body:**
```json
{
  "event": "subscription.created",
  "subscription_id": "01f3d686-64a5-454d-9612-adbb96e07c9d",
  "status": "active"
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "webhook_processed": true
  },
  "message": "Webhook processed successfully",
  "code": 200
}
```

## Error Responses

All endpoints return standardized error responses:

```json
{
  "success": false,
  "data": null,
  "message": "Error description",
  "code": 400
}
```

## Authentication

- **Public endpoints** (`/api/v1/public/*`): No authentication required
- **Payment Gateway endpoints** (`/api/v1/payment-gateway/*`): No authentication required (for now)
- **Admin endpoints** (`/api/v1/admin/*`): Require company ID in headers

## Notes

1. **Company Creation**: Automatically assigns a free trial plan
2. **Token Generation**: JWT tokens are generated for API access
3. **Zoho Integration**: Now uses real Zoho API integration with proper configuration
4. **Data Validation**: Handles legacy data inconsistencies gracefully
5. **Response Format**: All responses follow the standardized `SuccessResponse` wrapper
6. **Zoho Configuration**: All Zoho settings are configured in `app/core/config.py`
7. **Email Notifications**: Welcome emails are sent automatically during company onboarding
8. **User Invitations**: Email invitation service available for inviting users to companies

## Email Services

The backend provides comprehensive email functionality for different use cases:

### 1. Welcome Emails (Company Onboarding)
- **Automatic**: Sent when companies are created
- **Content**: Company details, plan information, app access links
- **Template**: Professional HTML and plain text versions

### 2. Invitation Emails (User Management)
- **Purpose**: Invite users to join companies
- **Features**: Individual and bulk invitation support
- **Content**: Company details, role information, registration links

### 3. Email Configuration
To enable all email services, configure the following environment variables in your `.env` file:

```bash
# SMTP Configuration
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASS=your-app-password
SMTP_FROM=noreply@shay.com
SMTP_SECURE=false
```

**Configuration Flow:**
1. **Environment Variables** → Set in `.env` file
2. **Config.py** → Loads from `os.environ.get()` with defaults
3. **Email Service** → Gets configuration from `settings` (config.py)

**Gmail Setup:**
1. Enable 2-factor authentication on your Gmail account
2. Generate an App Password (not your regular password)
3. Use the App Password in `SMTP_PASS`

**Email Features:**
- HTML and plain text email templates
- Professional email design
- Non-blocking email sending
- Comprehensive error handling
- Support for both individual and bulk operations
