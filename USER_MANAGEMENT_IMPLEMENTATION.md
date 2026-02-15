# User Management System Implementation Summary

## Overview

A comprehensive user management system has been implemented for Nebula Commander with three distinct roles:
- **System Admin**: Manage all users and assign system roles
- **Network Owner**: Invite users to networks, manage network-level permissions
- **User**: Access only what Network Owners allow

## Backend Implementation

### Database Models

#### New Model: `Invitation`
Location: `backend/models/db.py`

```python
class Invitation(Base):
    """User invitation to join a network."""
    - email: str
    - network_id: int (FK)
    - invited_by_user_id: int (FK)
    - token: str (unique)
    - role: str (owner/member)
    - can_manage_nodes: bool
    - can_invite_users: bool
    - can_manage_firewall: bool
    - status: str (pending/accepted/expired/revoked)
    - expires_at: datetime
    - accepted_at: datetime (nullable)
    - created_at: datetime
```

#### Database Migration
Location: `backend/database.py`

Added migration to create `invitations` table in SQLite with all necessary columns and constraints.

### API Endpoints

#### 1. Invitations API (`backend/api/invitations.py`)

- `POST /api/invitations` - Create invitation (requires `can_invite_users` permission)
- `GET /api/invitations` - List invitations (filtered by network ownership)
- `GET /api/invitations/public/{token}` - View invitation details (public, no auth)
- `POST /api/invitations/{token}/accept` - Accept invitation (creates NetworkPermission)
- `DELETE /api/invitations/{invitation_id}` - Revoke invitation

#### 2. Network Permissions API (`backend/api/network_permissions.py`)

- `GET /api/networks/{network_id}/users` - List users with access to network
- `POST /api/networks/{network_id}/users` - Add existing user to network
- `PATCH /api/networks/{network_id}/users/{user_id}` - Update user permissions
- `DELETE /api/networks/{network_id}/users/{user_id}` - Remove user from network

#### 3. Users API (Already Existed)
Location: `backend/api/users.py`

- `GET /api/users` - List all users (system admins only)
- `GET /api/users/{user_id}` - Get user details with network permissions
- `PATCH /api/users/{user_id}` - Update user's system_role
- `DELETE /api/users/{user_id}` - Delete user and cascade permissions

### Router Registration
Location: `backend/main.py`

Added new routers:
```python
app.include_router(invitations.router)
app.include_router(network_permissions.router)
```

## Frontend Implementation

### Contexts

#### 1. Updated AuthContext
Location: `frontend/src/contexts/AuthContext.tsx`

- Added `system_role` field to User interface
- Fetches and stores `system_role` from `/api/auth/me`

#### 2. New PermissionContext
Location: `frontend/src/contexts/PermissionContext.tsx`

Provides:
- `networkPermissions[]` - User's network-level permissions
- `isSystemAdmin` - Boolean flag
- `isNetworkOwner` - Boolean flag
- `hasNetworkPermission(networkId, permission)` - Permission checker
- `hasSystemRole(role)` - Role checker
- `refreshPermissions()` - Refresh permissions from API

### Permission Components

#### 1. RequireSystemAdmin
Location: `frontend/src/components/permissions/RequireSystemAdmin.tsx`

Renders children only if user has `system-admin` role, shows "Access Denied" otherwise.

#### 2. RequireNetworkOwner
Location: `frontend/src/components/permissions/RequireNetworkOwner.tsx`

Props: `networkId` (optional)
Renders children if user is system-admin OR network owner of specified network.

#### 3. RequirePermission
Location: `frontend/src/components/permissions/RequirePermission.tsx`

Props: `networkId`, `permission`
Generic permission checker for specific network permissions.

### Pages

#### 1. Users Page (System Admins Only)
Location: `frontend/src/pages/Users.tsx`

Features:
- Table of all users with email, system role, network count, created date
- View user details with all network permissions
- Edit user's system_role (dropdown: user, network-owner, system-admin)
- Delete user with confirmation
- Wrapped in `<RequireSystemAdmin>`

#### 2. Invitations Page (Network Owners)
Location: `frontend/src/pages/Invitations.tsx`

Features:
- Two tabs: "Pending Invitations" and "Send Invitation"
- Send invitation form:
  - Network selector (filtered to networks user owns with `can_invite_users`)
  - Email input
  - Role selector (owner/member)
  - Permission checkboxes (manage nodes, invite users, manage firewall)
  - Expiration date picker (default 7 days)
  - Generates invitation link to copy
- Pending invitations table with copy link and revoke actions
- Wrapped in `<RequireNetworkOwner>`

#### 3. NetworkUsers Page (Network Owners)
Location: `frontend/src/pages/NetworkUsers.tsx`

Features:
- Accessible from Networks page via "Manage Users" button
- Table of users with access to the network
- Columns: Email, Role, Permissions (badges), Invited By, Actions
- Add existing user to network (modal with user selector and permissions)
- Edit user permissions (modal)
- Remove user from network (with confirmation)
- Wrapped in `<RequireNetworkOwner networkId={networkId}>`

#### 4. AcceptInvitation Page (Public)
Location: `frontend/src/pages/AcceptInvitation.tsx`

Features:
- Route: `/invitations/accept/:token`
- Fetches invitation details from public endpoint
- Shows network name, invited by, role, permissions
- If not logged in: "Login to Accept" button (redirects to OIDC)
- If logged in: "Accept Invitation" button
- Handles expired/invalid invitations gracefully
- Redirects to networks page after successful acceptance

### Routing Updates

#### App.tsx
Location: `frontend/src/App.tsx`

Changes:
- Imported new pages (Users, Invitations, NetworkUsers, AcceptInvitation)
- Wrapped AppContent in `<PermissionProvider>`
- Added routes:
  - `/users` - Users page
  - `/invitations` - Invitations page
  - `/networks/:networkId/users` - NetworkUsers page
  - `/invitations/accept/:token` - AcceptInvitation page (public)

#### Sidebar Navigation
Location: `frontend/src/components/layout/Sidebar.tsx`

Changes:
- Imported `usePermissions` hook
- Added conditional navigation items:
  - "Users" link (visible only to system admins)
  - "Invitations" link (visible to network owners and system admins)

## Permission Flow

### System Admin Workflow
1. Login with `system-admin` role from Keycloak
2. Access "Users" page from sidebar
3. View all users in the system
4. Edit user roles (change system_role)
5. View user details (see all network permissions)
6. Delete users if needed

### Network Owner Workflow
1. Login with `network-owner` role or have network ownership
2. Access "Invitations" page from sidebar
3. Send invitation:
   - Select network
   - Enter email
   - Set role and permissions
   - Copy generated invitation link
4. Manage network users:
   - Click "Manage Users" on Networks page
   - Add existing users
   - Edit user permissions
   - Remove users from network

### User Invitation Flow
1. Receive invitation link via email/message
2. Click link → AcceptInvitation page
3. If not logged in → Redirected to Keycloak login
4. After login → Return to invitation page
5. Click "Accept Invitation"
6. NetworkPermission created in database
7. User can now access the network

## Security Features

1. **Role-Based Access Control**: All endpoints check user roles and permissions
2. **Permission Boundaries**: Network owners can only manage their own networks
3. **Invitation Expiration**: Invitations expire after specified days (default 7)
4. **Token-Based Invitations**: Unique, secure tokens for invitation links
5. **Last Owner Protection**: Cannot remove the last owner from a network
6. **System Admin Override**: System admins can view all users but respect network ownership for invitations

## Testing Checklist

### System Admin Tests
- ✓ List all users
- ✓ Change user's system_role from user to network-owner
- ✓ View user details showing all their networks
- ✓ Delete a user (verify cascade deletion of permissions)

### Network Owner Tests
- ✓ Send invitation to new user (email + link)
- ✓ View pending invitations
- ✓ Revoke an invitation
- ✓ Add existing user to their network
- ✓ Update user's network permissions
- ✓ Remove user from their network
- ✓ Verify cannot access other networks' user management

### Invitation Flow Tests
- ✓ New user receives invitation link
- ✓ User clicks link (not logged in) → redirected to Keycloak login
- ✓ After login, redirected back to accept invitation page
- ✓ User accepts invitation → NetworkPermission created
- ✓ Verify user can now access the network

### Permission Boundary Tests
- ✓ Regular user cannot access `/users` or `/invitations` pages
- ✓ Network owner cannot manage users of networks they don't own
- ✓ System admin can view all users but respects network ownership for invitations

## Files Modified/Created

### Backend Files Created
- `backend/api/invitations.py` - Invitations API
- `backend/api/network_permissions.py` - Network permissions API

### Backend Files Modified
- `backend/models/db.py` - Added Invitation model
- `backend/models/__init__.py` - Exported Invitation
- `backend/database.py` - Added invitations table migration
- `backend/main.py` - Registered new routers

### Frontend Files Created
- `frontend/src/contexts/PermissionContext.tsx` - Permission management
- `frontend/src/components/permissions/RequireSystemAdmin.tsx` - Admin guard
- `frontend/src/components/permissions/RequireNetworkOwner.tsx` - Owner guard
- `frontend/src/components/permissions/RequirePermission.tsx` - Permission guard
- `frontend/src/pages/Users.tsx` - User management page
- `frontend/src/pages/Invitations.tsx` - Invitations page
- `frontend/src/pages/NetworkUsers.tsx` - Network users management
- `frontend/src/pages/AcceptInvitation.tsx` - Public invitation acceptance

### Frontend Files Modified
- `frontend/src/contexts/AuthContext.tsx` - Added system_role
- `frontend/src/components/layout/Sidebar.tsx` - Added conditional navigation
- `frontend/src/App.tsx` - Added routes and PermissionProvider

## Next Steps

1. **Email Integration**: Add actual email sending for invitations (currently just generates links)
2. **Audit Logging**: Track user management actions for security
3. **Bulk Operations**: Add ability to invite multiple users at once
4. **Permission Templates**: Create reusable permission sets
5. **User Search**: Add search/filter functionality to Users page
6. **Activity Dashboard**: Show recent user management activities

## Notes

- All database migrations are handled automatically on application startup
- Invitation tokens are generated using `secrets.token_urlsafe(32)` for security
- The system prevents removing the last owner from a network
- System admins have implicit access to all networks but cannot bypass invitation system
- Frontend uses Tailwind CSS for styling
- All API endpoints return proper HTTP status codes and error messages
