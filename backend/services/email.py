"""Email service for sending invitation emails."""
import logging
from typing import Optional
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

import aiosmtplib
from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..config import settings

logger = logging.getLogger(__name__)

# Initialize Jinja2 environment
jinja_env = Environment(
    loader=FileSystemLoader("backend/templates/email"),
    autoescape=select_autoescape(['html', 'xml'])
)


async def send_invitation_email(
    invitation_id: int,
    to_email: str,
    network_name: str,
    invited_by_email: str,
    invitation_token: str,
    role: str,
    permissions: dict,
    expires_at: str,
    base_url: str
) -> bool:
    """
    Send invitation email to user.
    Returns True if sent successfully, False otherwise.
    """
    from ..database import AsyncSessionLocal
    from ..models import Invitation
    
    if not settings.smtp_enabled:
        logger.info(f"SMTP disabled, skipping email to {to_email}")
        # Update to not_sent
        async with AsyncSessionLocal() as session:
            invitation = await session.get(Invitation, invitation_id)
            if invitation:
                invitation.email_status = "not_sent"
                await session.commit()
        return False
    
    try:
        # Render HTML template
        template = jinja_env.get_template("invitation.html")
        invitation_link = f"{base_url}/invitations/accept/{invitation_token}"
        
        html_content = template.render(
            to_email=to_email,
            network_name=network_name,
            invited_by_email=invited_by_email,
            invitation_link=invitation_link,
            role=role,
            permissions=permissions,
            expires_at=expires_at,
        )
        
        # Create plain text version
        text_content = f"""
You've been invited to join the Nebula network: {network_name}

Invited by: {invited_by_email}
Role: {role}

Click the link below to accept the invitation:
{invitation_link}

This invitation expires on {expires_at}.

---
Nebula Commander
"""
        
        # Create message
        message = MIMEMultipart("alternative")
        message["Subject"] = f"Invitation to join {network_name}"
        message["From"] = f"{settings.smtp_from_name} <{settings.smtp_from_email}>"
        message["To"] = to_email
        
        # Attach both plain text and HTML
        message.attach(MIMEText(text_content, "plain"))
        message.attach(MIMEText(html_content, "html"))
        
        # Send email
        await aiosmtplib.send(
            message,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_username,
            password=settings.smtp_password,
            use_tls=settings.smtp_use_tls,
        )
        
        logger.info(f"Invitation email sent to {to_email}")
        
        # Update status to "sent"
        async with AsyncSessionLocal() as session:
            invitation = await session.get(Invitation, invitation_id)
            if invitation:
                invitation.email_status = "sent"
                invitation.email_sent_at = datetime.utcnow()
                invitation.email_error = None
                await session.commit()
        
        return True
        
    except Exception as e:
        logger.error(f"Failed to send invitation email to {to_email}: {e}")
        
        # Update status to "failed"
        async with AsyncSessionLocal() as session:
            invitation = await session.get(Invitation, invitation_id)
            if invitation:
                invitation.email_status = "failed"
                invitation.email_error = str(e)[:512]
                await session.commit()
        
        return False
