# Domain-Based Company System with User Invitation

## Overview

This system implements a domain-based company creation model where users with the same email domain automatically belong to the same company. The system also supports user invitations and role-based access control.

## Key Features

### 1. Domain-Based Company Creation
- **Automatic Company Detection**: Users with the same email domain are automatically grouped into the same company
- **First User = Admin**: The first user to sign up with a domain becomes the company admin
- **Subsequent Users = Regular Users**: Later users from the same domain get "user" role by default

### 2. User Invitation System
- **Invitation Creation**: Company admins can invite users by email
- **Invitation Acceptance**: Invited users can accept invitations and join the company
- **Role Assignment**: Admins can specify roles when inviting users
- **Expiration**: Invitations expire after 7 days by default

### 3. Role-Based Access Control
- **Admin**: Full company management, can invite users, manage roles
- **Manager**: Can invite users and manage some company settings
- **User**: Regular user with basic access

## API Endpoints

### Authentication (`/api/v1/auth/`)

#### OAuth Callback with Domain-Based Company Creation
```http
POST /api/v1/auth/callback
```

**Logic:**
1. User signs in via Google OAuth
2. System extracts email domain (e.g., `@acme.com`)
3. Checks if company exists for this domain
4. If no company exists:
   - Creates new company
   - Assigns "admin" role to first user
5. If company exists:
   - Adds user to existing company
   - Assigns "user" role by default

### Companies (`/api/v1/companies/`)

#### Get Current User's Company
```http
GET /api/v1/companies/my
```

#### Get Company by ID
```http
GET /api/v1/companies/{company_id}
```

#### Update Company
```http
PUT /api/v1/companies/{company_id}
```

#### Get Company Statistics
```http
GET /api/v1/companies/{company_id}/stats
```

#### Invite User to Company
```http
POST /api/v1/companies/{company_id}/invite
```

**Request Body:**
```json
{
  "email": "user@acme.com",
  "role": "user",
  "message": "Welcome to our team!"
}
```

#### List Company Invitations
```http
GET /api/v1/companies/{company_id}/invitations
```

#### Accept Invitation
```http
POST /api/v1/companies/invitations/{invitation_id}/accept
```

**Request Body:**
```json
{
  "invitation_id": "invitation-uuid",
  "name": "John Doe",
  "avatar_url": "https://example.com/avatar.jpg"
}
```

### Users (`/api/v1/users/`)

#### List Company Users
```http
GET /api/v1/users/company/{company_id}/users
```

**Query Parameters:**
- `page`: Page number (default: 1)
- `size`: Page size (default: 10)
- `search`: Search by name or email
- `role`: Filter by role

#### Get Company User
```http
GET /api/v1/users/company/{company_id}/users/{user_id}
```

#### Update Company User
```http
PUT /api/v1/users/company/{company_id}/users/{user_id}
```

**Request Body:**
```json
{
  "name": "Updated Name",
  "role": "manager",
  "is_active": true
}
```

#### Remove User from Company
```http
DELETE /api/v1/users/company/{company_id}/users/{user_id}
```

#### Get Company User Statistics
```http
GET /api/v1/users/company/{company_id}/stats
```

## Database Models

### Company Model
```python
class Company(Base):
    id = Column(String(36), primary_key=True)
    name = Column(String(255), nullable=False)
    domain = Column(String(255), unique=True, nullable=True)
    description = Column(Text, nullable=True)
    subscription_plan = Column(String(50), default="free")
    max_users = Column(String(10), default="10")
    max_workspaces = Column(String(10), default="5")
    max_storage_gb = Column(String(10), default="1")
    ai_enabled = Column(Boolean, default=True)
    ai_provider = Column(String(50), default="openai")
```

### Invitation Model
```python
class Invitation(Base):
    id = Column(String(36), primary_key=True)
    email = Column(String(255), nullable=False)
    role = Column(String(50), default="user")
    company_id = Column(String(36), ForeignKey("companies.id"))
    invited_by = Column(String(36), ForeignKey("users.id"))
    status = Column(String(20), default="pending")  # pending, accepted, expired
    message = Column(Text, nullable=True)
    expires_at = Column(DateTime, nullable=False)
```

## User Flow Examples

### Scenario 1: First User from Domain
1. **User A** (john@acme.com) signs in via Google OAuth
2. System creates company "John's Company" with domain "acme.com"
3. User A gets "admin" role
4. User A can now invite other users

### Scenario 2: Subsequent User from Same Domain
1. **User B** (jane@acme.com) signs in via Google OAuth
2. System finds existing company with domain "acme.com"
3. User B gets "user" role automatically
4. User B joins the same company as User A

### Scenario 3: User Invitation
1. **Admin** invites user@acme.com with "manager" role
2. Invitation is created and sent to user@acme.com
3. **User** receives invitation and accepts it
4. User joins company with "manager" role

## Permission Matrix

| Action | Admin | Manager | User |
|--------|-------|---------|------|
| View company details | ✅ | ✅ | ✅ |
| Update company settings | ✅ | ❌ | ❌ |
| Invite users | ✅ | ✅ | ❌ |
| Manage user roles | ✅ | ✅ | ❌ |
| Remove users | ✅ | ❌ | ❌ |
| View company statistics | ✅ | ✅ | ✅ |
| Create workspaces | ✅ | ✅ | ✅ |
| Manage workspaces | ✅ | ✅ | ✅ |

## Security Considerations

1. **Domain Validation**: Only users with matching email domains can join companies
2. **Role Restrictions**: Only admins can assign admin roles
3. **Invitation Expiration**: Invitations expire after 7 days
4. **Self-Removal Prevention**: Users cannot remove themselves from companies
5. **Company Isolation**: Users can only access their own company data

## Configuration

### Environment Variables
```bash
# Company settings
COMPANY_INVITATION_EXPIRY_DAYS=7
COMPANY_DEFAULT_ROLE=user
COMPANY_ADMIN_ROLE=admin
COMPANY_MANAGER_ROLE=manager
```

### Database Migration
The system requires the following new tables:
- `invitations` - For storing user invitations
- Updated `companies` table with domain field
- Updated `users` table with role field

## Error Handling

### Common Error Responses

#### 403 Forbidden
```json
{
  "detail": "Access denied"
}
```

#### 404 Not Found
```json
{
  "detail": "Company not found"
}
```

#### 400 Bad Request
```json
{
  "detail": "User with this email already exists"
}
```

## Testing

### Test Scenarios
1. **Domain-based company creation**
2. **User invitation flow**
3. **Role-based access control**
4. **Invitation expiration**
5. **Company statistics**

### Example Test Data
```python
# Test companies
companies = [
    {"name": "Acme Corp", "domain": "acme.com"},
    {"name": "Tech Startup", "domain": "techstartup.com"}
]

# Test users
users = [
    {"email": "admin@acme.com", "role": "admin"},
    {"email": "user@acme.com", "role": "user"},
    {"email": "manager@acme.com", "role": "manager"}
]
```

## Future Enhancements

1. **Email Notifications**: Send invitation emails
2. **Bulk Invitations**: Invite multiple users at once
3. **Company Templates**: Pre-configured company settings
4. **Advanced Roles**: Custom role definitions
5. **Audit Logging**: Track all company changes
6. **Company Hierarchy**: Parent-child company relationships 