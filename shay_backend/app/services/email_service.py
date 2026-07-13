"""
Email service for sending invitations and notifications.

This module provides email functionality using SMTP, specifically configured
for Gmail with app passwords for secure authentication.

Author: AI Assistant
Date: 2025-01-27
Version: 1.0.0
"""

import asyncio
import logging
import re
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional, List, Dict, Any
from datetime import datetime
from urllib.parse import urlsplit
from fastapi import HTTPException

from app.core.config import settings
from app.services.template_service import template_service

logger = logging.getLogger(__name__)


class EmailService:
    """Service for sending emails via SMTP"""
    
    def __init__(self):
        """Initialize email service with configuration"""
        # Get SMTP configuration from config.py
        self.host = settings.SMTP_HOST
        self.port = settings.SMTP_PORT
        self.username = settings.SMTP_USER
        self.password = settings.SMTP_PASS
        self.from_email = settings.SMTP_FROM
        self.use_tls = settings.SMTP_SECURE
        
        # Get default platform name from config
        self.default_platform_name = settings.PLATFORM_NAME
        
        # Get template directory path
        self.template_dir = os.path.join(
            os.path.dirname(__file__),
            '..', '..', 'templates', 'email'
        )

    def _brand_header_tagline(self, platform_name: Optional[str] = None) -> str:
        """Return the short Aryx header line used across email templates."""
        return f"{platform_name or self.default_platform_name} | Linked data, Ask, and graph workspaces"

    def _platform_intro_text(self, platform_name: Optional[str] = None) -> str:
        """Return the standard Aryx product description for onboarding emails."""
        display_name = platform_name or self.default_platform_name or "Aryx"
        return (
            f"{display_name} helps teams ingest data, connect records into a searchable knowledge graph, "
            "and ask grounded questions with confidence."
        )
    
    def _load_template(self, template_name: str) -> str:
        """
        Load HTML template from file
        
        Args:
            template_name: Name of the template file (e.g., 'password_reset.html')
            
        Returns:
            str: Template content as string
            
        Raises:
            FileNotFoundError: If template file doesn't exist
        """
        template_path = os.path.join(self.template_dir, template_name)
        
        try:
            with open(template_path, 'r', encoding='utf-8') as f:
                return f.read()
        except FileNotFoundError:
            print(f"⚠️ Template file not found: {template_path}")
            raise FileNotFoundError(f"Template file not found: {template_name}")
        except Exception as e:
            print(f"❌ Error loading template {template_name}: {e}")
            raise
    
    async def send_template_invitation_email(
        self,
        to_email: str,
        invitation_data: dict,
        template_id: Optional[str] = None,
        platform_url: str = "http://localhost:3000",
        db: Optional[Any] = None
    ) -> bool:
        """
        Send invitation email using template
        
        Args:
            to_email: Recipient email address
            invitation_data: Dictionary containing invitation information
            template_id: Template ID to use (optional)
            platform_url: Base URL for the platform
            db: Database session (required if template_id is provided)
            
        Returns:
            bool: True if email sent successfully, False otherwise
        """
        try:
            # Create message with 'alternative' subtype so email clients show only one version
            msg = MIMEMultipart('alternative')
            msg['From'] = self.from_email
            msg['To'] = to_email
            msg['Subject'] = "Invitation to join Aryx"
            
            # Get template content with fallback logic
            if template_id and db:
                try:
                    template_data = await template_service.get_template_content(template_id, db)
                    template_content = template_data['content']
                except HTTPException as e:
                    if e.status_code == 404:
                        # Template not found, use default fallback
                        print(f"Template {template_id} not found, using default fallback template")
                        template_content = self._get_default_invitation_template()
                    else:
                        raise e
            else:
                template_content = self._get_default_invitation_template()
            
            # Prepare variables for template processing
            user_email = invitation_data.get('email', '')
            user_name = self._resolve_user_name(invitation_data, fallback="There")
            invited_by_display = self._normalize_name(invitation_data.get('invited_by')) or invitation_data.get('invited_by', 'Development User')
            company_name = invitation_data.get('company_name', self.default_platform_name)
            platform_name = self._resolve_platform_name(invitation_data)
            support_email = invitation_data.get('support_email') or self.from_email
            
            template_variables = {
                'company_name': company_name,
                'logo_html': self._get_embedded_logo_html(platform_name, platform_url),
                'user_name': user_name,
                'user_nam': user_name,  # Support common placeholder typo
                'invited_by': invited_by_display,
                'role': invitation_data.get('role', 'user'),
                'registration_link': invitation_data.get('registration_link', ''),
                'registration_short_link': invitation_data.get('registration_short_link') or invitation_data.get('registration_link', ''),
                'invite_id': invitation_data.get('invite_id', ''),
                'expires_at': invitation_data.get('expires_at', ''),
                'email': user_email,
                'smtp_from': self.from_email,  # Add SMTP from email for templates that need it
                'platform_name': platform_name,
                'support_email': support_email,
                'current_year': datetime.utcnow().year
            }
            
            # Process template with variables
            try:
                processed_html = template_service.process_template_content(template_content, template_variables)
            except ValueError as e:
                print(f"Template processing error, using default: {e}")
                processed_html = self._create_invitation_html(invitation_data, platform_url)
            
            # Create plain text body first (should be attached before HTML)
            text_body = self._create_invitation_text(invitation_data, platform_url)
            msg.attach(MIMEText(text_body, 'plain'))
            
            # Create HTML body (attached after plain text - clients will prefer HTML if supported)
            msg.attach(MIMEText(processed_html, 'html'))
            
            # Send email
            return self._send_email(msg)
            
        except Exception as e:
            print(f"Error sending template invitation email: {e}")
            return False
    
    def _normalize_name(self, raw_name: Optional[str]) -> str:
        """
        Normalize a raw name by replacing common separators with spaces and title-casing the result.
        """
        if not raw_name:
            return ""
        cleaned = re.sub(r"[._\-]+", " ", raw_name)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned.title() if cleaned else ""

    def _resolve_user_name(self, invitation_data: Dict[str, Any], fallback: str = "There") -> str:
        """
        Determine the display name for the invited user, preferring explicit names over email-derived ones.
        """
        provided_name = invitation_data.get('user_name')
        normalized_name = self._normalize_name(provided_name)
        if normalized_name:
            return normalized_name

        email = invitation_data.get('email')
        if email and '@' in email:
            local_part = email.split('@')[0]
            email_based_name = self._normalize_name(local_part)
            if email_based_name:
                return email_based_name

        return fallback

    def _resolve_platform_name(self, invitation_data: Dict[str, Any]) -> str:
        """
        Determine the platform name to surface in invitation content.
        Falls back to company name or default platform name from config if not provided.
        """
        raw = invitation_data.get('platform_name')
        if raw and str(raw).strip():
            return str(raw).strip()

        fallback = invitation_data.get('company_name')
        if fallback and str(fallback).strip():
            return str(fallback).strip()

        return self.default_platform_name

    async def send_template_password_reset_email(
        self,
        to_email: str,
        password_reset_data: dict,
        template_id: Optional[str] = None,
        platform_url: str = "http://localhost:3000",
        db: Optional[Any] = None
    ) -> bool:
        """
        Send password reset email using template
        
        Args:
            to_email: Recipient email address
            password_reset_data: Dictionary containing password reset information
            template_id: Template ID to use (optional)
            platform_url: Base URL for the platform
            db: Database session (required if template_id is provided)
            
        Returns:
            bool: True if email sent successfully, False otherwise
        """
        try:
            # Create message with 'alternative' subtype so email clients show only one version
            msg = MIMEMultipart('alternative')
            msg['From'] = self.from_email
            msg['To'] = to_email
            msg['Subject'] = "Password Reset Request"

            platform_name = self._resolve_platform_name(password_reset_data)
            support_email = password_reset_data.get('support_email') or self.from_email

            # Get template content with fallback logic
            if not template_id or not db:
                raise ValueError("Template ID and database session are required for password reset emails")
            
            try:
                template_data = await template_service.get_template_content(template_id, db)
                template_content = template_data['content']
            except HTTPException as e:
                if e.status_code == 404:
                    # Template not found, use default fallback
                    print(f"Template {template_id} not found, using default fallback template")
                    template_content = self._get_default_password_reset_template()
                else:
                    raise e
            
            # Prepare variables for template processing
            user_email = password_reset_data.get('email', '')
            user_name = password_reset_data.get('user_name', '')
            if not user_name:
                user_name = user_email.split('@')[0] if user_email and '@' in user_email else 'there'
            
            template_variables = {
                'logo_html': self._get_embedded_logo_html(platform_name, platform_url),
                'user_name': user_name,
                'user_nam': user_name,  # Common typo in templates
                'email': user_email,
                'reset_url': password_reset_data.get('reset_url', ''),
                'expires_at': password_reset_data.get('expires_at', '1 hour'),
                'platform_name': platform_name,
                'platform_url': platform_url,
                'base_url': platform_url,
                'smtp_from': self.from_email,  # Add SMTP from email for templates that need it
                'support_email': support_email,
                'current_year': datetime.utcnow().year
            }
            
            # Process template with variables
            processed_html = template_service.process_template_content(template_content, template_variables)
            
            # Create plain text body first (should be attached before HTML)
            text_body = self._create_password_reset_text(password_reset_data, platform_url, platform_name, support_email)
            msg.attach(MIMEText(text_body, 'plain'))
            
            # Create HTML body (attached after plain text - clients will prefer HTML if supported)
            msg.attach(MIMEText(processed_html, 'html'))
            
            # Send email
            return self._send_email(msg)
            
        except Exception as e:
            print(f"Error sending template password reset email: {e}")
            return False
    
    def send_password_reset_email(
        self,
        to_email: str,
        password_reset_data: dict,
        platform_url: str = "http://localhost:3000"
    ) -> bool:
        """
        Send password reset email to user using template
        
        Args:
            to_email: Recipient email address
            password_reset_data: Dictionary containing password reset information:
                - user_name: User's name
                - reset_url: Password reset link
                - expires_at: Expiration time (e.g., "1 hour")
                - support_email: Support email address
            platform_url: Base URL for the platform
            
        Returns:
            bool: True if email sent successfully, False otherwise
        """
        try:
            print(f"📧 Preparing password reset email for {to_email}...")
            # Create message with 'alternative' subtype so email clients show only one version
            msg = MIMEMultipart('alternative')
            msg['From'] = self.from_email
            msg['To'] = to_email
            msg['Subject'] = f"Password Reset Request - {self.default_platform_name}"
            
            print(f"📧 Creating email content for {to_email}...")
            # Create plain text body first (should be attached before HTML)
            text_body = self._create_password_reset_text(password_reset_data, platform_url)
            msg.attach(MIMEText(text_body, 'plain'))
            
            # Create HTML body using template (attached after plain text - clients will prefer HTML if supported)
            html_body = self._create_password_reset_html(password_reset_data, platform_url)
            msg.attach(MIMEText(html_body, 'html'))
            
            print(f"📧 Sending password reset email via SMTP to {to_email}...")
            # Send email
            result = self._send_email(msg)
            if result:
                print(f"✅ Password reset email sent successfully to {to_email}")
            else:
                print(f"❌ Failed to send password reset email to {to_email}")
            return result
            
        except Exception as e:
            print(f"❌ Error sending password reset email to {to_email}: {e}")
            import traceback
            print(f"📋 Error traceback: {traceback.format_exc()}")
            return False
    
    def _create_password_reset_html(self, password_reset_data: dict, platform_url: str) -> str:
        """Create HTML version of password reset email using template file"""
        user_email = password_reset_data.get('email', '')
        user_name = password_reset_data.get('user_name', '')
        if not user_name:
            user_name = user_email.split('@')[0] if user_email and '@' in user_email else 'User'
        reset_url = password_reset_data.get('reset_url', '')
        expires_at = password_reset_data.get('expires_at', '1 hour')
        support_email = password_reset_data.get('support_email') or self.from_email
        platform_name = self._resolve_platform_name(password_reset_data)
        current_year = datetime.now().year
        
        # Load template from file
        try:
            template = self._load_template('password_reset.html')
            return template.format(
                logo_html=self._get_embedded_logo_html(platform_name, platform_url),
                user_name=user_name,
                platform_name=platform_name,
                reset_url=reset_url,
                expires_at=expires_at,
                support_email=support_email,
                current_year=current_year
            )
        except FileNotFoundError:
            # Fallback: try to load from template file again or raise error
            print(f"⚠️ Template file password_reset.html not found")
            raise FileNotFoundError("Template file password_reset.html is required")
    
    def _create_password_reset_text(self, password_reset_data: dict, platform_url: str) -> str:
        """Create plain text version of password reset email"""
        user_email = password_reset_data.get('email', '')
        user_name = password_reset_data.get('user_name', '')
        if not user_name:
            user_name = user_email.split('@')[0] if user_email and '@' in user_email else 'User'
        reset_url = password_reset_data.get('reset_url', '')
        expires_at = password_reset_data.get('expires_at', '1 hour')
        platform_name = self._resolve_platform_name(password_reset_data)
        support_email = password_reset_data.get('support_email') or self.from_email
        
        text = f"""
        Password Reset Request - {platform_name}
        =================================
        
        Hello {user_name},
        
        We received a request to reset the password for your {platform_name} workspace.
        Use the secure link below to choose a new password and get back into Aryx.
        
        Reset Link: {reset_url}
        
        IMPORTANT SECURITY INFORMATION:
        - This reset link will expire in {expires_at}
        - If you didn't request this reset, please ignore this email
        - For security, this link can only be used once
        
        Need help regaining access? Contact us at {support_email}.
        
        This email was sent from {platform_name}
        © {datetime.now().year} {platform_name}. All rights reserved.
        """
        
        return text

    def send_verification_email(
        self,
        to_email: str,
        verification_data: dict,
        platform_url: str = "http://localhost:3000"
    ) -> bool:
        """
        Send email verification email to user
        
        Args:
            to_email: Recipient email address
            verification_data: Dictionary containing verification information:
                - company_name: Company name
                - user_name: User's name
                - verification_link: Verification link with token
                - expires_in_hours: Hours until token expires
                - support_email: Support email address
                - platform_name: Platform name
            platform_url: Base URL for the platform
            
        Returns:
            bool: True if email sent successfully, False otherwise
        """
        try:
            platform_name = verification_data.get('platform_name', self.default_platform_name)
            subject = f"Verify Your Email - {platform_name}"
            # [DEBUG] Verification email: confirm platform_name and subject for Zaptag vs generic intro
            print(f"📧 [email_service] send_verification_email: to={to_email}, verification_data.platform_name={verification_data.get('platform_name')!r}, default_platform={self.default_platform_name!r}, subject={subject!r}")
            print(f"📧 Preparing verification email for {to_email}...")
            # Create message with 'alternative' subtype so email clients show only one version
            msg = MIMEMultipart('alternative')
            msg['From'] = self.from_email
            msg['To'] = to_email
            msg['Subject'] = subject

            print(f"📧 Creating email content for {to_email}...")
            # Create plain text body first (should be attached before HTML)
            text_body = self._create_verification_text(verification_data, platform_url)
            msg.attach(MIMEText(text_body, 'plain'))
            
            # Create HTML body (attached after plain text - clients will prefer HTML if supported)
            html_body = self._create_verification_html(verification_data, platform_url)
            msg.attach(MIMEText(html_body, 'html'))
            
            print(f"📧 Sending verification email via SMTP to {to_email}...")
            # Send email
            result = self._send_email(msg)
            if result:
                print(f"✅ Verification email sent successfully to {to_email}")
            else:
                print(f"❌ Failed to send verification email to {to_email}")
            return result
            
        except Exception as e:
            print(f"❌ Error sending verification email to {to_email}: {e}")
            import traceback
            print(f"📋 Error traceback: {traceback.format_exc()}")
            return False
    
    def _create_verification_html(self, verification_data: dict, platform_url: str) -> str:
        """Create HTML version of verification email using template file"""
        company_name = verification_data.get('company_name', 'our platform')
        user_name = verification_data.get('user_name', 'there')
        verification_link = verification_data.get('verification_link', '')
        expires_in_hours = verification_data.get('expires_in_hours', 24)
        support_email = verification_data.get('support_email', self.from_email)
        platform_name = self._resolve_platform_name(verification_data)
        current_year = datetime.now().year
        product_intro_text = self._platform_intro_text(platform_name)

        # Load template from file
        try:
            template = self._load_template('verification.html')
            return template.format(
                logo_html=self._get_embedded_logo_html(platform_name, platform_url),
                company_name=company_name,
                user_name=user_name,
                verification_link=verification_link,
                expires_in_hours=expires_in_hours,
                support_email=support_email,
                platform_name=platform_name,
                current_year=current_year,
                product_intro_text=product_intro_text
            )
        except FileNotFoundError:
            # Fallback: try to load from template file again or raise error
            print(f"⚠️ Template file verification.html not found")
            raise FileNotFoundError("Template file verification.html is required")
    
    def _create_verification_text(self, verification_data: dict, platform_url: str) -> str:
        """Create plain text version of verification email"""
        company_name = verification_data.get('company_name', 'our platform')
        user_name = verification_data.get('user_name', 'there')
        verification_link = verification_data.get('verification_link', '')
        expires_in_hours = verification_data.get('expires_in_hours', 24)
        support_email = verification_data.get('support_email', self.from_email)
        platform_name = self._resolve_platform_name(verification_data)
        product_intro_text = self._platform_intro_text(platform_name)

        text = f"""
        Verify Your Email - {platform_name}
        ============================
        
        Hello {user_name},
        
        Thanks for joining {company_name} on {platform_name}.
        
        {product_intro_text}
        
        Verify your email address to activate your Aryx workspace and continue setup:
        
        {verification_link}
        
        IMPORTANT INFORMATION:
        - This verification link will expire in {expires_in_hours} hours
        - If you didn't create an account, please ignore this email
        - For security, this link can only be used once
        
        If you need help finishing setup, contact us at {support_email}.
        
        This email was sent from {platform_name}
        © 2025 {platform_name}. All rights reserved.
        """
        
        return text

    def send_invitation_email(
        self,
        to_email: str,
        invitation_data: dict,
        platform_url: str = "http://localhost:3000"
    ) -> bool:
        """
        Send invitation email to user
        
        Args:
            to_email: Recipient email address
            invitation_data: Dictionary containing invitation information
            platform_url: Base URL for the platform
            
        Returns:
            bool: True if email sent successfully, False otherwise
        """
        try:
            # Create message with 'alternative' subtype so email clients show only one version
            msg = MIMEMultipart('alternative')
            msg['From'] = self.from_email
            msg['To'] = to_email
            msg['Subject'] = "Invitation to join Aryx"
            
            # Create plain text body first (should be attached before HTML)
            text_body = self._create_invitation_text(invitation_data, platform_url)
            msg.attach(MIMEText(text_body, 'plain'))
            
            # Create HTML body (attached after plain text - clients will prefer HTML if supported)
            html_body = self._create_invitation_html(invitation_data, platform_url)
            msg.attach(MIMEText(html_body, 'html'))
            
            # Send email
            return self._send_email(msg)
            
        except Exception as e:
            print(f"Error sending invitation email: {e}")
            return False
    
    def send_bulk_invitation_emails(
        self,
        invitations: List[dict],
        platform_url: str = "http://localhost:3000"
    ) -> dict:
        """
        Send bulk invitation emails
        
        Args:
            invitations: List of invitation dictionaries
            platform_url: Base URL for the platform
            
        Returns:
            dict: Results of bulk email sending
        """
        results = {
            'successful': [],
            'failed': []
        }
        
        for invitation in invitations:
            try:
                success = self.send_invitation_email(
                    invitation['email_id'],
                    invitation,
                    platform_url
                )
                
                if success:
                    results['successful'].append(invitation['email_id'])
                else:
                    results['failed'].append({
                        'email': invitation['email_id'],
                        'reason': 'Email sending failed'
                    })
                    
            except Exception as e:
                results['failed'].append({
                    'email': invitation['email_id'],
                    'reason': str(e)
                })
        
        return results

    async def send_workspace_access_email(
        self,
        to_email: str,
        workspace_access_data: dict,
        platform_url: str = "http://localhost:3000",
    ) -> bool:
        """Notify an existing user that they were added to a workspace."""
        try:
            msg = MIMEMultipart("alternative")
            msg["From"] = self.from_email
            msg["To"] = to_email
            msg["Subject"] = "You have been added to an Aryx workspace"

            text_body = self._create_workspace_access_text(workspace_access_data, platform_url)
            msg.attach(MIMEText(text_body, "plain"))

            html_body = self._create_workspace_access_html(workspace_access_data, platform_url)
            msg.attach(MIMEText(html_body, "html"))

            return await asyncio.to_thread(self._send_email, msg)
        except Exception:
            logger.exception("Error sending workspace access email")
            return False

    def _create_workspace_access_html(self, workspace_access_data: dict, platform_url: str) -> str:
        """Create HTML for the workspace access notification email."""
        workspace_name = workspace_access_data.get("workspace_name", "your workspace")
        user_name = workspace_access_data.get("user_name") or "there"
        role = workspace_access_data.get("role", "member")
        added_by = workspace_access_data.get("added_by", "A workspace administrator")
        platform_name = workspace_access_data.get("platform_name", self.default_platform_name)
        support_email = workspace_access_data.get("support_email") or self.from_email
        current_year = datetime.now().year

        return f"""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta http-equiv="X-UA-Compatible" content="IE=edge" />
  <title>You have been added to {workspace_name}</title>
</head>
<body style="margin: 0; padding: 24px 12px; background-color: #F4F6FB; color: #0B1430; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, Arial, Helvetica, sans-serif;">
  <div style="max-width: 640px; margin: 0 auto; background-color: #FFFFFF; border: 1px solid #D9DEEB; border-radius: 20px; overflow: hidden; box-shadow: 0 18px 50px rgba(13, 27, 90, 0.10);">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color: #1E3A8A; background-image: linear-gradient(135deg, #0D1B5A 0%, #1E3A8A 60%, #2D7DFF 100%); color: #FFFFFF;">
      <tr>
        <td style="padding: 28px 24px 12px 24px; text-align: center;">{self._get_embedded_logo_html(platform_name, platform_url)}</td>
      </tr>
      <tr>
        <td style="padding: 0 24px 28px 24px; text-align: center;">
          <h1 style="margin: 0; font-size: 28px; line-height: 1.2; font-weight: 700; color: #FFFFFF;">You have been added to a workspace</h1>
          <p style="margin: 10px 0 0 0; font-size: 14px; line-height: 1.5; color: #DCE8FF;">{self._brand_header_tagline(platform_name)}</p>
        </td>
      </tr>
    </table>

    <div style="padding: 36px 32px;">
      <p style="margin: 0 0 16px 0; font-size: 20px; line-height: 1.4; font-weight: 600; color: #0B1430;">Hello {user_name},</p>

      <p style="margin: 0 0 18px 0; font-size: 15px; line-height: 1.8; color: #0B1430;">
        <strong>{added_by}</strong> added you to the <strong>{workspace_name}</strong> workspace in <strong>{platform_name}</strong>.
      </p>

      <div style="margin: 0 0 24px 0; padding: 20px 22px; background-color: #F4F6FB; border: 1px solid #D9DEEB; border-radius: 16px;">
        <p style="margin: 0 0 8px 0; font-size: 14px; line-height: 1.7; color: #0B1430;"><strong style="color: #0D1B5A;">Workspace:</strong> {workspace_name}</p>
        <p style="margin: 0; font-size: 14px; line-height: 1.7; color: #0B1430;"><strong style="color: #0D1B5A;">Role:</strong> {role.capitalize()}</p>
      </div>

      <p style="margin: 0 0 22px 0; font-size: 15px; line-height: 1.8; color: #0B1430;">
        Sign in to open your workspace and start collaborating with your team.
      </p>

      <div style="text-align: center; margin: 0 0 20px 0;">
        <a href="{platform_url}" style="display: inline-block; padding: 14px 30px; border-radius: 999px; background-color: #2D7DFF; color: #FFFFFF; text-decoration: none; font-size: 15px; line-height: 1.4; font-weight: 700;">Open Workspace</a>
      </div>

      <div style="margin: 0 0 24px 0; padding: 16px 18px; background-color: #F8FAFE; border-radius: 14px; border: 1px dashed #BED1F8; font-size: 13px; line-height: 1.7; color: #0B1430; word-break: break-all;">
        If the button does not work, use this link:
        <br />
        <a href="{platform_url}" style="color: #2D7DFF; text-decoration: underline;">{platform_url}</a>
      </div>

      <p style="margin: 0; font-size: 14px; line-height: 1.7; color: #0B1430;">
        Need help getting started? Contact your workspace administrator or <a href="mailto:{support_email}" style="color: #2D7DFF; text-decoration: underline;">{support_email}</a>.
      </p>
    </div>

    <div style="padding: 24px 32px; background-color: #F8FAFE; border-top: 1px solid #D9DEEB; text-align: center;">
      <p style="margin: 0 0 8px 0; font-size: 13px; line-height: 1.6; color: #4A5A7A;">This email was sent from {platform_name}.</p>
      <p style="margin: 0; font-size: 13px; line-height: 1.6; font-weight: 600; color: #0D1B5A;">© {current_year} {platform_name}. All rights reserved.</p>
    </div>
  </div>
</body>
</html>
        """

    def _create_workspace_access_text(self, workspace_access_data: dict, platform_url: str) -> str:
        """Create plain text for the workspace access notification email."""
        workspace_name = workspace_access_data.get("workspace_name", "your workspace")
        user_name = workspace_access_data.get("user_name") or "there"
        role = workspace_access_data.get("role", "member")
        added_by = workspace_access_data.get("added_by", "A workspace administrator")
        platform_name = workspace_access_data.get("platform_name", self.default_platform_name)
        support_email = workspace_access_data.get("support_email") or self.from_email
        current_year = datetime.now().year

        return f"""
        YOU HAVE BEEN ADDED TO {platform_name.upper()}
        ===================

        Hello {user_name},

        {added_by} added you to the {workspace_name} workspace in {platform_name}.

        Workspace: {workspace_name}
        Role: {role}

        Sign in to open your workspace:
        {platform_url}

        If you need help, contact your workspace administrator or {support_email}.

        This email was sent from {platform_name}
        © {current_year} {platform_name}. All rights reserved.
        """
    
    def _create_invitation_html(self, invitation_data: dict, platform_url: str) -> str:
        """Create HTML version of invitation email using template file"""
        company_name = invitation_data.get('company_name', 'our platform')
        registration_link = invitation_data.get('registration_link', '')
        registration_short_link = invitation_data.get('registration_short_link') or registration_link
        user_email = invitation_data.get('email', '')
        user_name = self._resolve_user_name(invitation_data, fallback="There")
        invited_by = self._normalize_name(invitation_data.get('invited_by')) or invitation_data.get('invited_by', 'Development User')
        support_email = invitation_data.get('support_email') or self.from_email
        platform_name = invitation_data.get('platform_name', self.default_platform_name)
        current_year = datetime.now().year
        
        # Load template from file
        try:
            template = self._load_template('invitation.html')
            return template.format(
                logo_html=self._get_embedded_logo_html(platform_name, platform_url),
                company_name=company_name,
                registration_short_link=registration_short_link,
                user_name=user_name,
                invited_by=invited_by,
                support_email=support_email,
                platform_name=platform_name,
                current_year=current_year
            )
        except FileNotFoundError:
            # Fallback: try to load from template file again or raise error
            print(f"⚠️ Template file invitation.html not found")
            raise FileNotFoundError("Template file invitation.html is required")
    
    def _create_invitation_text(self, invitation_data: dict, platform_url: str) -> str:
        """Create plain text version of invitation email"""
        company_name = invitation_data.get('company_name', 'our platform')
        registration_link = invitation_data.get('registration_link', '')
        registration_short_link = invitation_data.get('registration_short_link') or registration_link
        user_name = self._resolve_user_name(invitation_data, fallback="There")
        invited_by = self._normalize_name(invitation_data.get('invited_by')) or invitation_data.get('invited_by', 'Development User')
        support_email = invitation_data.get('support_email') or self.from_email
        platform_name = invitation_data.get('platform_name', self.default_platform_name)
        current_year = datetime.now().year
        
        text = f"""
        WELCOME TO {platform_name.upper()}
        ===================
        
        Hello {user_name},
        
        {invited_by} has invited you to join {company_name} on {platform_name}.
        
        {self._platform_intro_text(platform_name)}
        
        Use this link to accept the invitation and finish setting up your workspace:
        {registration_short_link}
        
        Security Notice:
        - This invitation expires in 7 days
        - The link is unique to you; please do not share it
        
        If you need help, contact your workspace administrator or {support_email}.
        
        If you didn't expect this invitation, you can safely ignore this email.
        
        © {current_year} {platform_name}. All rights reserved.
        """
        
        return text
    
    def _get_default_password_reset_template(self) -> str:
        """Get default password reset template from file"""
        # Use the standard password_reset.html template
        try:
            return self._load_template('password_reset.html')
        except FileNotFoundError:
            raise FileNotFoundError("Template file password_reset.html is required")
    
    def _get_default_invitation_template(self) -> str:
        """Get default invitation template from file"""
        # Use the standard invitation.html template
        try:
            return self._load_template('invitation.html')
        except FileNotFoundError:
            raise FileNotFoundError("Template file invitation.html is required")
    
    def _send_email(self, msg: MIMEMultipart) -> bool:
        """Send email via SMTP"""
        try:
            # Create SMTP connection
            server = smtplib.SMTP(self.host, self.port)
            
            # For Gmail and most modern SMTP servers, we need to start TLS first
            if self.use_tls or self.port == 587:  # Use TLS setting or standard TLS port
                server.starttls()
                print("✅ STARTTLS initiated successfully")
            
            # Try to login if credentials are provided
            if self.username and self.password:
                try:
                    server.login(self.username, self.password)
                    print(f"✅ SMTP authentication successful with {self.username}")
                except smtplib.SMTPAuthenticationError as auth_error:
                    print(f"❌ SMTP authentication failed: {auth_error}")
                    server.quit()
                    return False
                except smtplib.SMTPException as smtp_error:
                    if "AUTH extension not supported" in str(smtp_error):
                        print(f"⚠️ SMTP server doesn't support authentication, continuing without login")
                    else:
                        print(f"❌ SMTP error: {smtp_error}")
                        server.quit()
                        return False
            else:
                print("⚠️ No SMTP credentials provided")
            
            # Send email
            text = msg.as_string()
            server.sendmail(self.from_email, msg['To'], text)
            
            # Close connection
            server.quit()
            
            print(f"✅ Email sent successfully to {msg['To']}")
            return True
            
        except smtplib.SMTPAuthenticationError as e:
            print(f"❌ SMTP authentication failed for {msg['To']}: {e}")
            return False
        except smtplib.SMTPConnectError as e:
            print(f"❌ Failed to connect to SMTP server for {msg['To']}: {e}")
            return False
        except smtplib.SMTPRecipientsRefused as e:
            print(f"❌ Recipient refused for {msg['To']}: {e}")
            return False
        except smtplib.SMTPSenderRefused as e:
            print(f"❌ Sender refused for {msg['To']}: {e}")
            return False
        except smtplib.SMTPDataError as e:
            print(f"❌ Data error for {msg['To']}: {e}")
            return False
        except Exception as e:
            print(f"❌ Failed to send email to {msg['To']}: {e}")
            return False
    
    def test_connection(self) -> bool:
        """Test SMTP connection"""
        try:
            server = smtplib.SMTP(self.host, self.port)
            
            # For Gmail and most modern SMTP servers, we need to start TLS first
            if self.use_tls or self.port == 587:  # Use TLS setting or standard TLS port
                server.starttls()
                print("✅ STARTTLS initiated successfully")
            
            # Try to login if credentials are provided
            if self.username and self.password:
                try:
                    server.login(self.username, self.password)
                    print("✅ SMTP authentication successful")
                except smtplib.SMTPAuthenticationError as auth_error:
                    print(f"❌ SMTP authentication failed: {auth_error}")
                    server.quit()
                    return False
                except smtplib.SMTPException as smtp_error:
                    if "AUTH extension not supported" in str(smtp_error):
                        print("⚠️ SMTP server doesn't support authentication, continuing without login")
                    else:
                        print(f"❌ SMTP error: {smtp_error}")
                        server.quit()
                        return False
            else:
                print("⚠️ No SMTP credentials provided, testing connection only")
            
            server.quit()
            print("✅ SMTP connection test successful")
            return True
            
        except Exception as e:
            print(f"❌ SMTP connection test failed: {e}")
            return False
    
    # NEW: Welcome email functionality for company onboarding
    def _create_welcome_email_template(self, data: Dict[str, Any]) -> str:
        """Create HTML welcome email template for company onboarding using template file"""
        company_name = data.get('companyName', 'Company')
        contact_email = data.get('contactEmail', '')
        plan_name = data.get('planName', 'Plan to be selected')
        monthly_price = data.get('monthlyPrice', 0)
        app_link = data.get('appLink', '#')
        platform_name = data.get('platform_name', self.default_platform_name)
        current_year = datetime.now().year
        
        # Load template from file
        try:
            template = self._load_template('welcome_email.html')
            return template.format(
                logo_html=self._get_embedded_logo_html(platform_name, app_link),
                company_name=company_name,
                contact_email=contact_email,
                plan_name=plan_name,
                monthly_price=monthly_price,
                app_link=app_link,
                platform_name=platform_name,
                current_year=current_year
            )
        except FileNotFoundError:
            # Fallback: try to load from template file again or raise error
            print(f"⚠️ Template file welcome_email.html not found")
            raise FileNotFoundError("Template file welcome_email.html is required")
    
    def _create_text_welcome_email(self, data: Dict[str, Any]) -> str:
        """Create plain text welcome email for company onboarding"""
        company_name = data.get('companyName', 'Company')
        contact_email = data.get('contactEmail', '')
        plan_name = data.get('planName', 'Plan to be selected')
        monthly_price = data.get('monthlyPrice', 0)
        app_link = data.get('appLink', 'N/A')
        
        return f"""
        Welcome to {data.get('platform_name', self.default_platform_name)}!
        
        Hi {company_name},
        
        Your {data.get('platform_name', self.default_platform_name)} workspace is ready.
        
        Your Account Details:
        - Company: {company_name}
        - Plan: {plan_name} - ${monthly_price}/month
        - Email: {contact_email}
        
        Launch Your Workspace:
        {app_link}
        
        Next Steps:
        - Connect a datasource or upload files
        - Review the first entities and relationships Aryx discovers
        - Start asking questions against your workspace
        
        If you have any questions, feel free to reach out to our support team.
        
        Best regards,
        The {data.get('platform_name', self.default_platform_name)} Team
        """
    
    def send_welcome_email(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Send welcome email to new company during onboarding
        
        Args:
            data: Dictionary containing email data
                - companyName: Company name
                - contactEmail: Contact email address
                - planName: Subscription plan name
                - monthlyPrice: Monthly price
                - appLink: Application access link
        
        Returns:
            Dict with success status and message ID
        """
        try:
            # Validate required data
            if not data.get('companyName') or not data.get('contactEmail'):
                raise ValueError('Missing required data: companyName and contactEmail are required')
            
            # Create email content
            html_content = self._create_welcome_email_template(data)
            text_content = self._create_text_welcome_email(data)
            
            # Create message
            msg = MIMEMultipart('alternative')
            platform_name = data.get('platform_name', self.default_platform_name)
            msg['Subject'] = f'Welcome to {platform_name} - Your Workspace Is Ready'
            msg['From'] = self.from_email
            msg['To'] = data['contactEmail']
            
            # Attach both HTML and text versions
            msg.attach(MIMEText(text_content, 'plain'))
            msg.attach(MIMEText(html_content, 'html'))
            
            # Send email using existing SMTP infrastructure
            success = self._send_email(msg)
            
            if success:
                return {
                    'success': True,
                    'messageId': f"welcome_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    'message': 'Welcome email sent successfully'
                }
            else:
                return {
                    'success': False,
                    'error': 'Failed to send email via SMTP',
                    'message': 'Email sending failed'
                }
            
        except ValueError as e:
            # Configuration or data validation error
            return {
                'success': False,
                'error': str(e),
                'message': 'Email configuration error'
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'message': f'Failed to send welcome email: {str(e)}'
            }

    def test_email_sending(self, test_email: str = "test@example.com") -> Dict[str, Any]:
        """Test email sending with current configuration"""
        try:
            # Create a simple test message
            msg = MIMEMultipart()
            msg['From'] = self.from_email
            msg['To'] = test_email
            msg['Subject'] = f'Test Email from {self.default_platform_name}'
            
            body = f"""
            This is a test email from {self.default_platform_name}.
            
            Configuration:
            - Host: {self.host}
            - Port: {self.port}
            - Username: {self.username}
            - From: {self.from_email}
            - TLS: {self.use_tls}
            
            Sent at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
            """
            
            msg.attach(MIMEText(body, 'plain'))
            
            # Try to send the test email
            success = self._send_email(msg)
            
            if success:
                return {
                    'success': True,
                    'message': f'Test email sent successfully to {test_email}',
                    'configuration': {
                        'host': self.host,
                        'port': self.port,
                        'username': self.username,
                        'from_email': self.from_email,
                        'use_tls': self.use_tls
                    }
                }
            else:
                return {
                    'success': False,
                    'message': f'Failed to send test email to {test_email}',
                    'configuration': {
                        'host': self.host,
                        'port': self.port,
                        'username': self.username,
                        'from_email': self.from_email,
                        'use_tls': self.use_tls
                    }
                }
                
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'message': f'Test email failed: {str(e)}',
                'configuration': {
                    'host': self.host,
                    'port': self.port,
                    'username': self.username,
                    'from_email': self.from_email,
                    'use_tls': self.use_tls
                }
            }
    
    def send_channel_member_notification(
        self,
        to_emails: List[str],
        notification_data: dict,
        platform_url: str = "http://localhost:3000"
    ) -> bool:
        """
        Send channel member notification. Content depends on notification_data.send_to_added_user:
        - send_to_added_user True (Accsell/Zaptag added-user email): "You have been added...", View Channel button.
        - Otherwise (original admin email): "A new user has been added...", no View Channel button.

        Args:
            to_emails: Admin emails for admin notification; or [added_user_email] when send_to_added_user=True.
            notification_data: channel_name, user_name, user_email, user_role, added_by, platform_name; channel_id and send_to_added_user=True for added-user email.
            platform_url: Base URL for the platform (used for View Channel link when send_to_added_user=True).
        """
        if not to_emails:
            return True
        
        # [DEBUG] Log raw payload received so we can trace root cause
        raw_send_flag = notification_data.get('send_to_added_user')
        print(f"📧 [email_service] send_channel_member_notification received: keys={list(notification_data.keys())}, send_to_added_user raw={raw_send_flag!r} (type={type(raw_send_flag).__name__})")
        platform_name = notification_data.get('platform_name', self.default_platform_name)
        channel_name = notification_data.get('channel_name', 'the channel')
        user_name = notification_data.get('user_name', 'A user')
        user_email = notification_data.get('user_email', '')
        user_role = notification_data.get('user_role', 'member')
        added_by = notification_data.get('added_by', 'an administrator')
        
        # Compute once so subject and body never diverge (single source of truth for added-user vs admin branch)
        send_to_added_user = self._is_send_to_added_user(notification_data)
        # Log platform_name and branch for debugging (confirm Accsell/Zaptag and added_user vs admin)
        print(f"📧 Channel member email: platform_name={platform_name!r}, send_to_added_user={send_to_added_user} -> {'added_user (You have been added + View Channel)' if send_to_added_user else 'admin (New user added)'}")
        subject = (
            f"You have been added to channel - {channel_name}"
            if send_to_added_user
            else f"New User Added to Channel - {channel_name}"
        )
        # [DEBUG] One-line summary before sending so we can confirm branch and recipients
        channel_id = notification_data.get('channel_id', '')
        print(f"📧 [email_service] send_channel_member_notification: subject={subject!r}, send_to_added_user={send_to_added_user}, to_emails_count={len(to_emails)}, channel_id={channel_id!r}, platform_name={platform_name!r}")
        results = []
        for to_email in to_emails:
            try:
                print(f"📧 Preparing channel member notification email for {to_email}...")
                # Create message with 'alternative' subtype so email clients show only one version
                msg = MIMEMultipart('alternative')
                msg['From'] = self.from_email
                msg['To'] = to_email
                msg['Subject'] = subject
                
                # Pass send_to_added_user explicitly so body uses same branch as subject (no re-read from dict)
                text_body = self._create_channel_member_notification_text(
                    notification_data, platform_url, send_to_added_user=send_to_added_user
                )
                msg.attach(MIMEText(text_body, 'plain'))
                
                # Pass send_to_added_user explicitly so body uses same branch as subject
                html_body = self._create_channel_member_notification_html(
                    notification_data, platform_url, send_to_added_user=send_to_added_user
                )
                msg.attach(MIMEText(html_body, 'html'))
                
                # Send email
                result = self._send_email(msg)
                if result:
                    print(f"✅ Channel member notification email sent successfully to {to_email}")
                else:
                    print(f"❌ Failed to send channel member notification email to {to_email}")
                results.append(result)
            except Exception as e:
                print(f"❌ Error sending channel member notification email to {to_email}: {e}")
                results.append(False)
        
        return all(results)
    
    def _get_platform_logo_url(self, platform_name: Optional[str]) -> Optional[str]:
        """Return logo URL only for accsell and zaptag; other platforms (e.g. prism7) unchanged, return None."""
        slug = (platform_name or '').lower()
        if slug == 'accsell':
            return settings.SHAY_LOGO_URL
        if slug == 'zaptag':
            return settings.ZAPTAG_LOGO_URL
        return None

    def _is_accsell_or_zaptag(self, platform_name: Optional[str]) -> bool:
        """True only for Accsell and Zaptag; limits added-user flow to these platforms, previous flow for others."""
        slug = (platform_name or '').strip().lower()
        return slug in ('accsell', 'zaptag')

    def _is_send_to_added_user(self, notification_data: dict) -> bool:
        """True when email is for the added user (Accsell/Zaptag). Accepts bool True, 1, and strings 'true'/'1' so subject and body stay in sync after JSON/serialization."""
        v = notification_data.get('send_to_added_user')
        # Treat explicit truthy values so serialization (e.g. JSON true -> 1 or "true") doesn't break
        if v is True:
            return True
        if v == 1 or (isinstance(v, str) and v.strip().lower() in ('true', '1')):
            return True
        # [DEBUG] Log when we fall back to False so we can spot missing or wrong values
        if v is not None and v is not False:
            print(f"📧 [email_service] _is_send_to_added_user: raw value={v!r}, type={type(v).__name__} -> False (expected True for added-user email)")
        return False

    def _create_channel_member_notification_html(
        self, notification_data: dict, platform_url: str, *, send_to_added_user: bool
    ) -> str:
        """Create HTML version of channel member notification email; added-user branch: 'You have been added' + View Channel; admin branch: 'A new user has been added' (previous flow)."""
        channel_id = notification_data.get('channel_id')
        # View Channel link uses /channels/ for added-user flow (dev/frontend convention)
        channel_url = f"{platform_url.rstrip('/')}/channels/{channel_id}" if channel_id else ''
        channel_name = notification_data.get('channel_name', 'the channel')
        user_name = notification_data.get('user_name', 'A user')
        user_email = notification_data.get('user_email', '')
        user_role = notification_data.get('user_role', 'member')
        user_role_display = (user_role or 'member').capitalize()
        added_by = notification_data.get('added_by', 'an administrator')
        platform_name = notification_data.get('platform_name', self.default_platform_name)
        current_year = datetime.now().year
        # [DEBUG] Confirm which body branch is used for HTML (value passed from caller so subject and body match)
        print(f"📧 [email_service] _create_channel_member_notification_html: send_to_added_user={send_to_added_user} -> branch={'added_user' if send_to_added_user else 'admin'}, channel_url={'set' if (channel_id and platform_url) else 'empty'}")
        # When send_to_added_user (Accsell/Zaptag): "You have been added...", View Channel button, "You now have access"; else (admin): "A new user has been added...", no button, "The user now has access"
        if send_to_added_user:
            intro_message = f'You have been added to the channel <strong>"{channel_name}"</strong> on {platform_name}.'
            access_paragraph = 'You now have access to this channel and can participate in conversations and collaborate with the team.'
            # Inline styles so "View Channel" text is white and visible in all email clients
            view_channel_block = (
                f'<div style="text-align: center;">'
                f'<a href="{channel_url}" class="cta-button" style="display: inline-block; background-color: #2D7DFF; color: #ffffff !important; text-decoration: none; padding: 14px 32px; border-radius: 50px; font-weight: 600; font-size: 15px;">View Channel</a>'
                f'</div>' if channel_url else ''
            )
        else:
            # Previous flow unchanged: admin email content (no send_to_added_user in notification_data)
            intro_message = f'A new user has been added to the channel <strong>"{channel_name}"</strong> on {platform_name}.'
            access_paragraph = 'The user now has access to this channel and can participate in conversations and collaborate with the team.'
            view_channel_block = ''
        # Header: title/tagline only (logo markup is injected by the shared email helper)
        if send_to_added_user:
            header_content = (
                '<h1 style="margin: 0; font-size: 22px; font-weight: 700; color: #ffffff;">You have been added to the channel</h1>'
                '<p style="margin: 8px 0 0 0; padding: 0; font-size: 14px; color: #ffffff;">' + self._brand_header_tagline(platform_name) + '</p>'
            )
        else:
            header_content = (
                '<h1 style="margin: 0; font-size: 22px; font-weight: 700; color: #ffffff;">New User Added to Channel</h1>'
                '<p style="margin: 8px 0 0 0; padding: 0; font-size: 14px; color: #ffffff;">' + self._brand_header_tagline(platform_name) + '</p>'
            )
        # Page title for HTML <title> so it matches email type (added-user vs admin)
        page_title = "You have been added to the channel" if send_to_added_user else "New User Added to Channel"

        # Load template from file
        try:
            template = self._load_template('channel_member_notification.html')
            return template.format(
                logo_html=self._get_embedded_logo_html(platform_name, platform_url),
                channel_name=channel_name,
                user_name=user_name,
                user_email=user_email,
                user_role=user_role,
                user_role_display=user_role_display,
                added_by=added_by,
                platform_name=platform_name,
                current_year=current_year,
                header_content=header_content,
                intro_message=intro_message,
                access_paragraph=access_paragraph,
                view_channel_block=view_channel_block,
                page_title=page_title
            )
        except FileNotFoundError:
            # Fallback: try to load from template file again or raise error
            print(f"⚠️ Template file channel_member_notification.html not found")
            raise FileNotFoundError("Template file channel_member_notification.html is required")
    
    def _create_channel_member_notification_text(
        self, notification_data: dict, platform_url: str, *, send_to_added_user: bool
    ) -> str:
        """Create plain text version; added-user branch: 'You have been added' + View Channel link; admin branch: previous flow."""
        channel_id = notification_data.get('channel_id')
        # View Channel link uses /channels/ for added-user flow (same as HTML)
        channel_url = f"{platform_url.rstrip('/')}/channels/{channel_id}" if channel_id else ''
        channel_name = notification_data.get('channel_name', 'the channel')
        user_name = notification_data.get('user_name', 'A user')
        user_email = notification_data.get('user_email', '')
        user_role = notification_data.get('user_role', 'member')
        user_role_display = (user_role or 'member').capitalize()
        added_by = notification_data.get('added_by', 'an administrator')
        platform_name = notification_data.get('platform_name', self.default_platform_name)
        # [DEBUG] Confirm which body branch is used for plain text (value passed from caller so subject and body match)
        print(f"📧 [email_service] _create_channel_member_notification_text: send_to_added_user={send_to_added_user} -> branch={'added_user' if send_to_added_user else 'admin'}")
        if send_to_added_user:
            title = f"You have been added to channel - {channel_name}"
            intro_line = f'You have been added to the channel "{channel_name}" on {platform_name}.'
            view_channel_line = f"\n        View channel: {channel_url}\n" if channel_url else ""
            access_line = "You now have access to this channel and can participate in conversations and collaborate with the team."
        else:
            title = f"New User Added to Channel - {channel_name}"
            intro_line = f'A new user has been added to the channel "{channel_name}" on {platform_name}.'
            view_channel_line = ""
            access_line = "The user now has access to this channel and can participate in conversations and collaborate with the team."
        text = f"""
        {title}
        ===========================================
        
        Hello,
        
        {intro_line}
        
        User Details:
        - User Name: {user_name}
        - Email: {user_email}
        - Role: {user_role_display}
        - Added by: {added_by}
        {view_channel_line}
        {access_line}
        
        If you have any questions or concerns, please contact your system administrator.
        
        This email was sent from {platform_name}
        © 2025 {platform_name}. All rights reserved.
        """
        
        return text
    
    def send_error_notification_email(
        self,
        to_email: str,
        error_data: dict,
        platform_url: str = "http://localhost:3000"
    ) -> bool:
        """
        Send error notification email to customer support
        
        Args:
            to_email: Support team email address
            error_data: Dictionary containing error information:
                - api_endpoint: The API endpoint that failed
                - error_message: Error message
                - error_type: Type of error (optional)
                - user_id: User ID who encountered the error (optional)
                - company_id: Company ID (optional)
                - request_method: HTTP method (optional)
                - request_body: Request body (optional)
                - stack_trace: Stack trace (optional)
                - timestamp: Timestamp of the error
            platform_url: Base URL for the platform
            
        Returns:
            bool: True if email sent successfully, False otherwise
        """
        try:
            print(f"📧 Preparing error notification email for {to_email}...")
            # Create message with 'alternative' subtype so email clients show only one version
            msg = MIMEMultipart('alternative')
            msg['From'] = self.from_email
            msg['To'] = to_email
            msg['Subject'] = f"API Failure Alert - {error_data.get('api_endpoint', 'Unknown Endpoint')}"
            
            # Create plain text body first (should be attached before HTML)
            text_body = self._create_error_notification_text(error_data, platform_url)
            msg.attach(MIMEText(text_body, 'plain'))
            
            # Create HTML body (attached after plain text - clients will prefer HTML if supported)
            html_body = self._create_error_notification_html(error_data, platform_url)
            msg.attach(MIMEText(html_body, 'html'))
            
            print(f"📧 Sending error notification email via SMTP to {to_email}...")
            # Send email
            result = self._send_email(msg)
            if result:
                print(f"✅ Error notification email sent successfully to {to_email}")
            else:
                print(f"❌ Failed to send error notification email to {to_email}")
            return result
            
        except Exception as e:
            print(f"❌ Error sending error notification email to {to_email}: {e}")
            import traceback
            print(f"📋 Error traceback: {traceback.format_exc()}")
            return False
    
    def _create_error_notification_html(self, error_data: dict, platform_url: str) -> str:
        """Create HTML version of error notification email using template file"""
        from datetime import timezone
        api_endpoint = error_data.get('api_endpoint', 'Unknown Endpoint')
        error_message = error_data.get('error_message', 'No error message provided')
        error_type = error_data.get('error_type', 'Unknown Error')
        user_id = error_data.get('user_id', 'N/A')
        company_id = error_data.get('company_id', 'N/A')
        request_method = error_data.get('request_method', 'N/A')
        request_body = error_data.get('request_body', 'N/A')
        stack_trace = error_data.get('stack_trace', 'N/A')
        timestamp = error_data.get('timestamp', datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC'))
        platform_name = error_data.get('platform_name', self.default_platform_name)
        current_year = datetime.now().year
        
        # Truncate long fields for display
        if len(error_message) > 500:
            error_message = error_message[:500] + "... (truncated)"
        if len(stack_trace) > 1000:
            stack_trace = stack_trace[:1000] + "... (truncated)"
        if len(str(request_body)) > 500:
            request_body = str(request_body)[:500] + "... (truncated)"
        
        # Load template from file
        try:
            template = self._load_template('error_notification.html')
            return template.format(
                logo_html=self._get_embedded_logo_html(platform_name, platform_url),
                api_endpoint=api_endpoint,
                error_message=error_message,
                error_type=error_type,
                user_id=user_id,
                company_id=company_id,
                request_method=request_method,
                request_body=request_body,
                stack_trace=stack_trace,
                timestamp=timestamp,
                platform_name=platform_name,
                current_year=current_year
            )
        except FileNotFoundError:
            # Fallback: try to load from template file again or raise error
            print(f"⚠️ Template file error_notification.html not found")
            raise FileNotFoundError("Template file error_notification.html is required")
    
    def _create_error_notification_text(self, error_data: dict, platform_url: str) -> str:
        """Create plain text version of error notification email"""
        from datetime import timezone
        api_endpoint = error_data.get('api_endpoint', 'Unknown Endpoint')
        error_message = error_data.get('error_message', 'No error message provided')
        error_type = error_data.get('error_type', 'Unknown Error')
        user_id = error_data.get('user_id', 'N/A')
        company_id = error_data.get('company_id', 'N/A')
        request_method = error_data.get('request_method', 'N/A')
        request_body = error_data.get('request_body', 'N/A')
        stack_trace = error_data.get('stack_trace', 'N/A')
        timestamp = error_data.get('timestamp', datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC'))
        platform_name = error_data.get('platform_name', self.default_platform_name)
        
        text = f"""
        ⚠️ API FAILURE ALERT - {platform_name}
        ======================================
        
        An API failure has been detected and requires your attention.
        
        ERROR DETAILS:
        --------------
        API Endpoint: {api_endpoint}
        HTTP Method: {request_method}
        Error Type: {error_type}
        Timestamp: {timestamp}
        
        ERROR MESSAGE:
        --------------
        {error_message}
        
        REQUEST CONTEXT:
        ----------------
        User ID: {user_id}
        Company ID: {company_id}
        Request Body: {request_body}
        
        STACK TRACE:
        ------------
        {stack_trace}
        
        Please investigate this error and take appropriate action. If this is a recurring issue, 
        consider implementing additional error handling or monitoring.
        
        This is an automated error notification from {platform_name}
        © 2025 {platform_name}. All rights reserved.
        """
        
        return text

    def send_support_request_email(
        self,
        to_email: str,
        support_data: dict,
        platform_url: str = "http://localhost:3000",
    ) -> bool:
        """
        Send support request details to support team (support@giggso.com).

        support_data: name, email, description, subject (optional), ticket_reference, created_at.
        """
        try:
            # Logo via URL only (no MIME attachment) so inbox shows no attachment; set PLATFORM_LOGO_URL or BASE_URL for logo to load
            msg = MIMEMultipart("alternative")
            msg["From"] = self.from_email
            msg["To"] = to_email
            msg["Subject"] = f"Support Request [{support_data.get('ticket_reference', 'N/A')}] - {support_data.get('subject') or 'General'}"
            text_body = self._create_support_request_text(support_data, platform_url)
            msg.attach(MIMEText(text_body, "plain"))
            html_body = self._create_support_request_html(support_data, platform_url)
            msg.attach(MIMEText(html_body, "html"))
            result = self._send_email(msg)
            if result:
                print(f"✅ Support request email sent to {to_email}")
            return result
        except Exception as e:
            print(f"❌ Error sending support request email to {to_email}: {e}")
            return False

    def _replace_placeholders(self, template: str, placeholders: dict) -> str:
        """Replace {key} with value in template. Order by key length desc to avoid partial matches. No .format() so braces in values are safe."""
        for key in sorted(placeholders.keys(), key=len, reverse=True):
            template = template.replace("{" + key + "}", str(placeholders[key]))
        return template

    def _is_public_logo_url(self, value: Optional[str]) -> bool:
        """Return True when a configured logo value is a usable public HTTP(S) URL."""
        if not value:
            return False
        return value.startswith("https://") or value.startswith("http://")

    def _url_origin(self, value: Optional[str]) -> Optional[str]:
        """Return scheme + host origin for a public URL, dropping any path/query."""
        if not self._is_public_logo_url(value):
            return None
        parts = urlsplit(value)
        if not parts.scheme or not parts.netloc:
            return None
        return f"{parts.scheme}://{parts.netloc}"

    def _get_default_logo_url(self, platform_url: Optional[str] = None) -> Optional[str]:
        """Return the shared Aryx logo URL when a public static asset is available."""
        logo_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "static",
            "email",
            "logo.png",
        )
        if not os.path.isfile(logo_path):
            return None

        candidate_bases: List[str] = []
        public_backend_origin = self._url_origin(settings.SHAY_BE_PUBLIC_URL)
        if public_backend_origin:
            candidate_bases.append(public_backend_origin)
        if platform_url:
            platform_origin = self._url_origin(platform_url)
            if platform_origin:
                candidate_bases.append(platform_origin)

        for candidate_base in candidate_bases:
            return f"{candidate_base}/static/email/logo.png"
        return None

    def _get_email_logo_url(
        self, platform_name: Optional[str] = None, platform_url: Optional[str] = None
    ) -> Optional[str]:
        """Return the safest public logo URL for email clients."""
        platform_logo_url = self._get_platform_logo_url(platform_name)
        if self._is_public_logo_url(platform_logo_url):
            return platform_logo_url
        return self._get_default_logo_url(platform_url)

    def _get_embedded_logo_html(
        self, platform_name: Optional[str] = None, platform_url: Optional[str] = None
    ) -> str:
        """Return compact hosted-logo markup for emails without Gmail clipping."""
        brand = (platform_name or self.default_platform_name or "Aryx").strip() or "Aryx"
        logo_url = self._get_email_logo_url(platform_name, platform_url)
        if logo_url:
            return (
                f'<img src="{logo_url}" alt="{brand}" '
                'style="max-width: 180px; max-height: 48px; width: auto; height: auto; display: inline-block;" />'
            )
        return (
            f'<div style="display:inline-block;padding:10px 14px;border-radius:999px;'
            f'background:rgba(255,255,255,0.12);border:1px solid rgba(255,255,255,0.18);'
            f'color:#FFFFFF;font-size:16px;line-height:1;font-weight:700;letter-spacing:0.04em;">'
            f'{brand}</div>'
        )

    def _create_support_request_html(self, support_data: dict, platform_url: str) -> str:
        """Build HTML for support request notification (blue header, info box)."""
        import html as html_module
        name = support_data.get("name", "N/A")
        email = support_data.get("email", "N/A")
        description = (support_data.get("description") or "")[:2000]
        description_escaped = html_module.escape(description)
        subject = support_data.get("subject") or "General"
        ticket_ref = support_data.get("ticket_reference", "N/A")
        created_at = support_data.get("created_at", "")
        company_id = support_data.get("company_id") or "N/A"
        company_name = support_data.get("company_name") or "N/A"
        user_id = support_data.get("user_id") or "N/A"
        platform_name = support_data.get("platform_name", self.default_platform_name)
        current_year = datetime.now().year
        intro_message = f'A new support request has been submitted from {name}. Details are below.'
        placeholders = {
            "logo_html": self._get_embedded_logo_html(platform_name, platform_url),
            "intro_message": intro_message,
            "ticket_ref": ticket_ref,
            "subject": subject,
            "company_id": company_id,
            "company_name": company_name,
            "user_id": user_id,
            "from_name": name,
            "from_email": email,
            "created_at": created_at,
            "description": description_escaped,
            "platform_name": platform_name,
            "current_year": current_year,
        }
        try:
            template = self._load_template("support_request_notification.html")
            return self._replace_placeholders(template, placeholders)
        except FileNotFoundError:
            # Fallback inline HTML (same style as template)
            return f"""
        <!DOCTYPE html><html><head><meta charset="UTF-8"/><title>New Support Request - {platform_name}</title></head>
        <body style="font-family:Segoe UI,sans-serif;background:#F4F6FB;color:#0B1430;margin:0;padding:24px 12px">
        <div style="max-width:640px;margin:0 auto;background:#FFFFFF;border:1px solid #D9DEEB;border-radius:20px;box-shadow:0 18px 50px rgba(13,27,90,.10);overflow:hidden">
        <div style="background:#1E3A8A;background-image:linear-gradient(135deg,#0D1B5A 0%,#1E3A8A 60%,#2D7DFF 100%);color:#fff;text-align:center;padding:24px 20px">
        <h1 style="margin:0 0 8px 0;font-size:28px;font-weight:700;color:#fff">New support request</h1>
        <p style="margin:0;font-size:14px;color:#DCE8FF">Aryx support intake</p>
        </div>
        <div style="padding:36px 32px">
        <p style="font-size:18px;font-weight:600;margin-bottom:16px">Hello,</p>
        <p style="font-size:15px;line-height:1.8;margin-bottom:22px">{intro_message}</p>
        <div style="background:#F4F6FB;border:1px solid #D9DEEB;border-radius:16px;padding:20px;margin:24px 0">
        <p style="margin:8px 0;font-size:14px"><strong style="color:#0D1B5A">Ticket Reference:</strong> {ticket_ref}</p>
        <p style="margin:8px 0;font-size:14px"><strong style="color:#0D1B5A">Subject/Category:</strong> {subject}</p>
        <p style="margin:8px 0;font-size:14px"><strong style="color:#0D1B5A">Company ID:</strong> {company_id}</p>
        <p style="margin:8px 0;font-size:14px"><strong style="color:#0D1B5A">Company Name:</strong> {company_name}</p>
        <p style="margin:8px 0;font-size:14px"><strong style="color:#0D1B5A">User ID:</strong> {user_id}</p>
        <p style="margin:8px 0;font-size:14px"><strong style="color:#0D1B5A">From:</strong> {name} &lt;{email}&gt;</p>
        <p style="margin:8px 0;font-size:14px"><strong style="color:#0D1B5A">Received:</strong> {created_at}</p>
        </div>
        <p style="font-size:15px;margin-bottom:8px"><strong>Description:</strong></p>
        <div style="background:#F8FAFE;border:1px solid #D9DEEB;border-radius:16px;padding:16px;white-space:pre-wrap">{description_escaped}</div>
        <p style="font-size:15px;line-height:1.7;margin-top:22px">If you have any questions or need to follow up, please use the ticket reference above.</p>
        </div>
        <div style="background:#F8FAFE;padding:24px 32px;text-align:center;border-top:1px solid #D9DEEB">
        <p style="margin:0 0 10px 0;font-size:14px">This email was sent from {platform_name}</p>
        <p style="margin:0;font-size:12px;color:#4A5A7A">© {current_year} {platform_name}. All rights reserved.</p>
        </div>
        </div></body></html>
        """

    def _create_support_request_text(self, support_data: dict, platform_url: str) -> str:
        """Build plain text body for support request notification."""
        name = support_data.get("name", "N/A")
        email = support_data.get("email", "N/A")
        description = (support_data.get("description") or "")[:2000]
        subject = support_data.get("subject") or "General"
        ticket_ref = support_data.get("ticket_reference", "N/A")
        created_at = support_data.get("created_at", "")
        company_id = support_data.get("company_id") or "N/A"
        company_name = support_data.get("company_name") or "N/A"
        user_id = support_data.get("user_id") or "N/A"
        platform_name = support_data.get("platform_name", self.default_platform_name)
        return f"""
New Support Request - {platform_name}
{self._brand_header_tagline(platform_name)}

Hello,

A new support request has been submitted from {name}. Details are below.

Ticket Reference: {ticket_ref}
Subject/Category: {subject}
Company ID: {company_id}
Company Name: {company_name}
User ID: {user_id}
From: {name} <{email}>
Received: {created_at}

Description:
-----------
{description}

If you have any questions or need to follow up, please use the ticket reference above.

This email was sent from {platform_name}
© {datetime.now().year} {platform_name}. All rights reserved.
"""

    def send_support_confirmation_email(
        self,
        to_email: str,
        support_data: dict,
        platform_url: str = "http://localhost:3000",
    ) -> bool:
        """
        Send confirmation to user that their support request was received.
        support_data: ticket_reference, name (optional), platform_name (optional).
        """
        try:
            # Logo via URL only (no MIME attachment) so inbox shows no attachment
            msg = MIMEMultipart("alternative")
            msg["From"] = self.from_email
            msg["To"] = to_email
            msg["Subject"] = f"We received your support request - {support_data.get('ticket_reference', '')}"
            text_body = self._create_support_confirmation_text(support_data, platform_url)
            msg.attach(MIMEText(text_body, "plain"))
            html_body = self._create_support_confirmation_html(support_data, platform_url)
            msg.attach(MIMEText(html_body, "html"))
            result = self._send_email(msg)
            if result:
                print(f"✅ Support confirmation email sent to {to_email}")
            return result
        except Exception as e:
            print(f"❌ Error sending support confirmation to {to_email}: {e}")
            return False

    def _create_support_confirmation_html(self, support_data: dict, platform_url: str) -> str:
        """Build HTML for user confirmation (blue header, info box)."""
        name = support_data.get("name", "User")
        ticket_ref = support_data.get("ticket_reference", "N/A")
        platform_name = support_data.get("platform_name", self.default_platform_name)
        support_email = getattr(settings, "SUPPORT_EMAIL", self.from_email)
        current_year = datetime.now().year
        placeholders = {
            "logo_html": self._get_embedded_logo_html(platform_name, platform_url),
            "name": name,
            "ticket_ref": ticket_ref,
            "platform_name": platform_name,
            "support_email": support_email,
            "current_year": current_year,
        }
        try:
            template = self._load_template("support_confirmation.html")
            return self._replace_placeholders(template, placeholders)
        except FileNotFoundError:
            # Fallback: inline styles so blue template renders in all email clients
            return f"""
<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8" /><meta name="viewport" content="width=device-width, initial-scale=1.0" /><meta http-equiv="Content-Type" content="text/html; charset=UTF-8" /></head>
<body style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #F4F6FB; color: #0B1430; margin: 0; padding: 24px 12px;">
  <div style="max-width: 640px; margin: 0 auto; background: #FFFFFF; border: 1px solid #D9DEEB; border-radius: 20px; box-shadow: 0 18px 50px rgba(13,27,90,0.10); overflow: hidden;">
    <div style="background-color: #1E3A8A; background-image: linear-gradient(135deg, #0D1B5A 0%, #1E3A8A 60%, #2D7DFF 100%); color: #ffffff; text-align: center; padding: 24px 20px;">
      <h1 style="margin: 0 0 8px 0; font-size: 28px; font-weight: 700; color: #ffffff;">Support request received</h1>
      <p style="margin: 0; font-size: 14px; color: #DCE8FF;">We have your Aryx request</p>
    </div>
    <div style="padding: 36px 32px;">
      <p style="font-size: 18px; font-weight: 600; margin: 0 0 16px 0;">Hi {name},</p>
      <p style="font-size: 15px; line-height: 1.8; margin: 0 0 22px 0;">We have received your support request and will get back to you as soon as we can.</p>
      <div style="background-color: #F4F6FB; border: 1px solid #D9DEEB; border-radius: 16px; padding: 20px; margin: 24px 0;">
        <p style="margin: 8px 0; font-size: 14px;"><strong style="color: #0D1B5A;">Ticket reference:</strong> {ticket_ref}</p>
      </div>
      <p style="font-size: 15px; line-height: 1.8; margin: 0;">You can use this reference when following up. If you have any urgent questions, reply to this email or contact us at <a href="mailto:{support_email}" style="color: #2D7DFF; text-decoration: underline;">{support_email}</a>.</p>
    </div>
    <div style="background: #F8FAFE; padding: 24px 32px; text-align: center; border-top: 1px solid #D9DEEB;">
      <p style="margin: 0 0 10px 0; font-size: 14px;">This email was sent from {platform_name}</p>
      <p style="margin: 0; font-size: 12px; color: #4A5A7A;">© {current_year} {platform_name}. All rights reserved.</p>
    </div>
  </div>
</body>
</html>
        """

    def _create_support_confirmation_text(self, support_data: dict, platform_url: str) -> str:
        """Build plain text for user confirmation email."""
        name = support_data.get("name", "User")
        ticket_ref = support_data.get("ticket_reference", "N/A")
        platform_name = support_data.get("platform_name", self.default_platform_name)
        support_email = getattr(settings, "SUPPORT_EMAIL", self.from_email)
        return f"""
Hi {name},

We have received your support request and will get back to you as soon as we can.

Ticket reference: {ticket_ref}

You can use this reference when following up. If you have any urgent questions, reply to this email or contact us at {support_email}.

— {platform_name} Support
"""


# Create a singleton instance
email_service = EmailService()
