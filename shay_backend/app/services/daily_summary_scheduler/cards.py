"""HTML for the per-notification-type summary "cards" row."""

from typing import Dict

from app.models.email_notify_settings import EmailNotifySettings


class CardsMixin:
    """generate_enabled_cards: one <td> card per enabled type with count > 0."""

    def generate_enabled_cards(
        self,
        email_settings: EmailNotifySettings,
        notification_counts: Dict[str, int]
    ) -> str:
        """
        Generate HTML for enabled notification type cards.

        Args:
            email_settings: Email notification settings
            notification_counts: Dictionary of notification counts

        Returns:
            HTML string for cards
        """
        cards = []

        # Card HTML template
        card_template = """<td class="summary-card" style="display: table-cell; background-color: #F4F6FB; border: 1px solid #D9DEEB; border-radius: 14px; padding: 20px 16px; text-align: center; vertical-align: middle; box-sizing: border-box;">
            <div class="summary-card-number" style="font-size: 28px; font-weight: 700; margin: 0 0 6px 0; padding: 0; color: #0D1B5A; line-height: 1.2;">{count}</div>
            <div class="summary-card-label" style="font-size: 13px; font-weight: 600; margin: 0; padding: 0; color: #0B1430; line-height: 1.4;">{label}</div>
        </td>"""

        # Check each notification type and add card if enabled AND count > 0
        if email_settings.mention_enabled == 1:
            mention_count = notification_counts.get('mentions', 0)
            if mention_count > 0:
                cards.append(card_template.format(
                    count=mention_count,
                    label='Mentions'
                ))

        if email_settings.post_enabled == 1:
            post_count = notification_counts.get('posts', 0)
            if post_count > 0:
                cards.append(card_template.format(
                    count=post_count,
                    label='Posts'
                ))
            # Also add email conversations card when post is enabled (only if count > 0)
            email_conv_count = notification_counts.get('email_conversations', 0)
            if email_conv_count > 0:
                cards.append(card_template.format(
                    count=email_conv_count,
                    label='Email Conversations'
                ))

        if email_settings.reply_enabled == 1:
            reply_count = notification_counts.get('replies', 0)
            if reply_count > 0:
                cards.append(card_template.format(
                    count=reply_count,
                    label='Replies'
                ))

        if email_settings.task_enabled == 1:
            task_count = notification_counts.get('tasks', 0)
            if task_count > 0:
                cards.append(card_template.format(
                    count=task_count,
                    label='Tasks'
                ))

        if email_settings.approval_pending_enabled == 1:
            approval_count = notification_counts.get('approvals', 0)
            if approval_count > 0:
                cards.append(card_template.format(
                    count=approval_count,
                    label='Approvals'
                ))

        if email_settings.meeting_enabled == 1:
            meeting_count = notification_counts.get('meetings', 0)
            if meeting_count > 0:
                cards.append(card_template.format(
                    count=meeting_count,
                    label='Meetings'
                ))

        if email_settings.blocker_enabled == 1:
            blocker_count = notification_counts.get('blockers', 0)
            if blocker_count > 0:
                cards.append(card_template.format(
                    count=blocker_count,
                    label='Blockers'
                ))

        if email_settings.app_enabled == 1:
            app_count = notification_counts.get('apps', 0)
            if app_count > 0:
                cards.append(card_template.format(
                    count=app_count,
                    label='Apps'
                ))

        if email_settings.chat_enabled == 1:
            chat_count = notification_counts.get('chats', 0)
            if chat_count > 0:
                cards.append(card_template.format(
                    count=chat_count,
                    label='Chats'
                ))

        if email_settings.friend_enabled == 1:
            friend_count = notification_counts.get('friends', 0)
            if friend_count > 0:
                cards.append(card_template.format(
                    count=friend_count,
                    label='Friends'
                ))

        # If no cards, return empty string
        if not cards:
            return ""

        return '\n                '.join(cards)
