# Email Invitation System Implementation

## Overview

Email functionality has been added to the invitation system. When network owners create invitations, HTML emails are automatically sent to the invited users with a link to accept the invitation.

## Implementation Details

### 1. Dependencies Added

**File:** `backend/requirements.txt`

```
aiosmtplib>=3.0.0  # Async SMTP client
jinja2>=3.1.0      # Template engine for HTML emails
```

### 2. Configuration

**File:** `backend/config.py`

Added SMTP settings to the `Settings` class:
- `smtp_enabled`: Enable/disable email sending (default: False)
- `smtp_host`: SMTP server hostname
- `smtp_port`: SMTP server port (default: 587)
- `smtp_username`: SMTP authentication username
- `smtp_password`: SMTP authentication password
- `smtp_password_file`: Optional file path for password (more secure)
- `smtp_use_tls`: Enable TLS encryption (default: True)
- `smtp_from_email`: Sender email address
- `smtp_from_name`: Sender display name

Added `load_smtp_password()` helper function to load password from file if specified.

### 3. Email Service

**File:** `backend/services/email.py`

Created email service with:
- Jinja2 template rendering
- HTML and plain text email generation
- Async SMTP sending with `aiosmtplib`
- Error handling and logging
- Graceful degradation if SMTP is disabled

**Function:** `send_invitation_email()`
- Parameters: to_email, network_name, invited_by_email, invitation_token, role, permissions, expires_at, base_url
- Returns: bool (True if sent successfully)
- Logs all email operations

### 4. Email Template

**File:** `backend/templates/email/invitation.html`

Professional HTML email template with:
- Responsive design (mobile-friendly)
- Clean, modern styling
- Network details (name, invited by, role)
- Permission badges (visual indicators)
- Prominent "Accept Invitation" button
- Expiration warning
- Footer with disclaimer

### 5. API Integration

**File:** `backend/api/invitations.py`

Updated `create_invitation()` endpoint:
- Added `BackgroundTasks` dependency
- Queues email sending as background task (non-blocking)
- Determines base URL from OIDC redirect URI
- Formats expiration date for email
- Email failures don't block invitation creation

### 6. Configuration Files

**Files:**
- `docker/env.d/backend` - Added SMTP configuration section
- `docker/env.d.example/backend` - Added example SMTP configuration with comments

Configuration includes:
- Enable/disable flag
- SMTP server settings
- Credentials (with secret file option)
- Sender information
- Examples for multiple providers (Gmail, SendGrid, Mailgun, Office 365)

### 7. Documentation

**File:** `docker/README.md`

Added comprehensive "Email Configuration (Optional)" section:
- Gmail setup instructions (with App Password guidance)
- Configuration examples for SendGrid, Mailgun, Office 365
- Security best practices (secret files, Docker secrets)
- MailHog testing setup for local development
- How the email flow works

## How to Enable Email

### Quick Setup (Gmail)

1. **Generate App Password:**
   - Enable 2FA on your Google account
   - Go to https://myaccount.google.com/apppasswords
   - Create an app password for "Nebula Commander"

2. **Configure in `docker/env.d/backend`:**
   ```bash
   NEBULA_COMMANDER_SMTP_ENABLED=true
   NEBULA_COMMANDER_SMTP_HOST=smtp.gmail.com
   NEBULA_COMMANDER_SMTP_PORT=587
   NEBULA_COMMANDER_SMTP_USERNAME=your-email@gmail.com
   NEBULA_COMMANDER_SMTP_PASSWORD=your-16-char-app-password
   NEBULA_COMMANDER_SMTP_USE_TLS=true
   NEBULA_COMMANDER_SMTP_FROM_EMAIL=noreply@yourdomain.com
   NEBULA_COMMANDER_SMTP_FROM_NAME=Nebula Commander
   ```

3. **Rebuild and restart:**
   ```bash
   docker compose down
   docker compose up --build
   ```

### Testing Without Real Emails (MailHog)

For development/testing:

```bash
# Start MailHog
docker run -d -p 1025:1025 -p 8025:8025 mailhog/mailhog

# Configure Nebula Commander
NEBULA_COMMANDER_SMTP_ENABLED=true
NEBULA_COMMANDER_SMTP_HOST=host.docker.internal  # or your host IP
NEBULA_COMMANDER_SMTP_PORT=1025
NEBULA_COMMANDER_SMTP_USE_TLS=false

# View emails at http://localhost:8025
```

## Email Flow

```
1. Network Owner creates invitation
   ↓
2. Invitation saved to database
   ↓
3. API returns immediately (non-blocking)
   ↓
4. Background task sends email
   ↓
5. User receives email
   ↓
6. User clicks "Accept Invitation" button
   ↓
7. User is redirected to AcceptInvitation page
   ↓
8. User accepts → NetworkPermission created
```

## Error Handling

- **SMTP Disabled**: Invitations work normally, link shown in UI
- **Email Fails**: Error logged, invitation still created, link available in UI
- **Invalid Credentials**: Logged as error, doesn't crash application
- **Network Issues**: Timeout handled gracefully

## Features

- ✅ Background task processing (non-blocking)
- ✅ HTML and plain text email versions
- ✅ Professional email template
- ✅ Configurable SMTP providers
- ✅ Secure password handling (file-based secrets)
- ✅ Graceful degradation
- ✅ Comprehensive logging
- ✅ Multiple provider support

## Files Created/Modified

### Created
- `backend/services/email.py` - Email service
- `backend/templates/email/invitation.html` - HTML email template

### Modified
- `backend/requirements.txt` - Added email dependencies
- `backend/config.py` - Added SMTP configuration
- `backend/api/invitations.py` - Added background email task
- `docker/env.d/backend` - Added SMTP settings
- `docker/env.d.example/backend` - Added example SMTP configuration
- `docker/README.md` - Added email configuration documentation

## Next Steps (Optional Enhancements)

1. **Email Templates**: Add more email types (welcome, password reset, etc.)
2. **Email Queue**: Use Celery or Redis for more robust background processing
3. **Email Tracking**: Track email delivery status and opens
4. **Email Preferences**: Allow users to opt-out of certain emails
5. **Bulk Invitations**: Send multiple invitations at once
6. **Email Verification**: Verify email addresses before sending
