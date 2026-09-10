"""Default invitation HTML template, used when no template_id is provided.

The template text is split across this file and default_template_style.py
purely to keep both under the file-length limit: it is a single HTML/CSS
document cut at the </style> boundary, not independent logic.
"""

from .default_template_style import TEMPLATE_HEAD

_TEMPLATE_BODY = """        </head>
        <body>
            <div class="email-wrapper">
                    <div class="email-header">
                        <h1>Welcome to {platform_name}</h1>
                        <p>You're one step away from joining {company_name}</p>
                    </div>
                    <div class="email-body">
                        <p class="greeting">Hello {user_name},</p>
                        
                        <p class="message">
                            Great news! <strong>{invited_by}</strong> has invited you to join {company_name} on <strong>{platform_name}</strong>.
                            Accept the invitation below to start collaborating with your team.
                        </p>
                        
                        <div class="product-intro">
                            <p>
                                {platform_name} helps teams connect source data, build a linked knowledge graph, and ask grounded questions from one workspace.
                            </p>
                        </div>
                        
                        <div style="text-align:center;">
                            <a href="{registration_short_link}" class="cta-button">Accept Invitation</a>
                        </div>
                        
                        <div class="link-fallback">
                            Can’t click the button? Copy and paste this link into your browser:<br/>
                            <a href="{registration_short_link}">{registration_short_link}</a>
                        </div>
                        
                        <p class="message">
                            If you need assistance, please contact your team administrator.
                        </p>
                        
                        <div class="warning">
                            ⚠️ <strong>Security Notice:</strong> This invitation will expire in {expires_at}.
                        </div>
                    </div>
                    
                    <div class="footer">
                        <p>If you didn’t expect this invitation, you can safely ignore this email.</p>
                        <p class="company-info">© {current_year} {platform_name}. All rights reserved.</p>
                    </div>
            </div>
        </body>
        </html>
        """

_DEFAULT_INVITATION_TEMPLATE = TEMPLATE_HEAD + _TEMPLATE_BODY


class DefaultTemplateMixin:
    """Provide the built-in fallback invitation template."""

    def get_default_invitation_template(self) -> str:
        """
        Get default invitation template if no template_id is provided

        Returns:
            Default HTML invitation template
        """
        return _DEFAULT_INVITATION_TEMPLATE
