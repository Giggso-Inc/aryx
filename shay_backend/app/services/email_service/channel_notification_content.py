"""HTML/text body builders for channel-member notification emails."""

from datetime import datetime


class ChannelNotificationContentMixin:
    """Builds the two branches (added-user vs admin) of the notification body."""

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
