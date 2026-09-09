"""Template directory setup and file-content helpers for setup_templates.py.

Split out of scripts/setup_templates.py (2026-09; part of the Raven Style
Compliance Plan's Phase 8b line-count reduction) since these two functions
carry most of the original file's bulk as embedded sample-template text,
not logic.
"""

from pathlib import Path

from app.core.config import settings


def setup_template_directory():
    """Set up the template directory and create sample files"""
    print("\n📁 Setting up template directory...")

    template_dir = Path(settings.TEMPLATE_DIR)

    # Create template directory
    if not template_dir.exists():
        template_dir.mkdir(parents=True, exist_ok=True)
        print(f"✅ Created template directory: {template_dir}")
    else:
        print(f"✅ Template directory already exists: {template_dir}")

    # Create sample template files
    sample_files = {
        "welcome_email.html": """<!DOCTYPE html>
<html>
<head>
    <title>Welcome Email</title>
    <style>
        body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
        .container { max-width: 600px; margin: 0 auto; padding: 20px; }
        .header { background-color: #f4f4f4; padding: 20px; text-align: center; }
        .content { padding: 20px; }
        .footer { background-color: #f4f4f4; padding: 10px; text-align: center; font-size: 12px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Welcome to {{company_name}}!</h1>
        </div>
        <div class="content">
            <p>Dear {{user_name}},</p>
            <p>Thank you for joining our platform. We're excited to have you on board!</p>
            <p>Your account has been successfully created and you can now access all our features.</p>
            <p>If you have any questions, please don't hesitate to contact our support team.</p>
            <p>Best regards,<br>The {{company_name}} Team</p>
        </div>
        <div class="footer">
            <p>This email was sent to {{user_email}} on {{signup_date}}</p>
        </div>
    </div>
</body>
</html>""",

        "notification.txt": """Notification: {{notification_type}}

Hello {{user_name}},

{{message_content}}

This notification was sent on {{notification_date}}.

Best regards,
{{company_name}} Team""",

        "email_config.json": """{
  "email_templates": {
    "welcome": {
      "subject": "Welcome to {{company_name}}!",
      "template_file": "welcome_email.html",
      "variables": ["user_name", "company_name", "user_email", "signup_date"],
      "priority": "high"
    },
    "notification": {
      "subject": "{{notification_type}} - {{company_name}}",
      "template_file": "notification.txt",
      "variables": ["user_name", "notification_type", "message_content", "notification_date", "company_name"],
      "priority": "medium"
    }
  },
  "settings": {
    "default_from": "noreply@{{company_domain}}",
    "reply_to": "support@{{company_domain}}",
    "max_retries": 3,
    "timeout": 30
  }
}""",

        "password_reset.html": """<!DOCTYPE html>
<html>
<head>
    <title>Password Reset</title>
    <style>
        body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
        .container { max-width: 600px; margin: 0 auto; padding: 20px; }
        .button { background-color: #007bff; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px; display: inline-block; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Password Reset Request</h1>
        <p>Hello {{user_name}},</p>
        <p>You requested a password reset for your {{company_name}} account.</p>
        <p>Click the button below to reset your password:</p>
        <p><a href="{{reset_link}}" class="button">Reset Password</a></p>
        <p>This link will expire in {{expiry_hours}} hours.</p>
        <p>If you didn't request this reset, please ignore this email.</p>
        <p>Best regards,<br>The {{company_name}} Team</p>
    </div>
</body>
</html>"""
    }

    created_files = []
    for filename, content in sample_files.items():
        file_path = template_dir / filename
        if not file_path.exists():
            file_path.write_text(content, encoding='utf-8')
            created_files.append(filename)

    if created_files:
        print(f"✅ Created {len(created_files)} sample template files:")
        for filename in created_files:
            print(f"   - {filename}")
    else:
        print("✅ All sample template files already exist")

    return True


def test_template_files():
    """Test template file operations"""
    print("\n📄 Testing template files...")

    try:
        template_dir = Path(settings.TEMPLATE_DIR)

        if not template_dir.exists():
            print("❌ Template directory does not exist")
            return False

        # List files
        files = list(template_dir.glob("*"))
        template_files = [f for f in files if f.is_file() and not f.name.startswith('.')]

        print(f"✅ Found {len(template_files)} template files:")
        for file in template_files:
            size = file.stat().st_size
            print(f"   - {file.name} ({size} bytes)")

        # Test reading a file
        if template_files:
            sample_file = template_files[0]
            content = sample_file.read_text(encoding='utf-8')
            print(f"✅ Successfully read {sample_file.name} ({len(content)} characters)")

        return True

    except Exception as e:
        print(f"❌ Template file test failed: {str(e)}")
        return False
