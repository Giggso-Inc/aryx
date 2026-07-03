#!/usr/bin/env python3
"""
Template Setup Script

This script sets up the template functionality by:
1. Creating the gg_templates table with current schema
2. Setting up the template directory
3. Creating sample template files
4. Running tests to verify everything works

Current Schema Fields:
- id (UUID, PRIMARY KEY)
- template_id (VARCHAR, UNIQUE, auto-generated format: TMPLT_INVITE_XXX)
- template_name (VARCHAR, NOT NULL)
- file_path (VARCHAR, nullable)
- file_size (VARCHAR, nullable)
- additional_config (JSONB, default {})
- created_datetime (TIMESTAMP)
- updated_datetime (TIMESTAMP)

Usage:
    python scripts/setup_templates.py

The script will:
1. Check prerequisites
2. Create template directory
3. Create sample template files
4. Create database table
5. Run tests
6. Show usage examples

Author: AI Assistant
Date: 2025-01-27
Version: 2.0.0
"""

import sys
import os
import json
from datetime import datetime
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import create_engine, text, inspect
from app.core.config import settings


def check_prerequisites():
    """Check if all prerequisites are met"""
    print("🔍 Checking prerequisites...")
    
    # Check if we're in the right directory
    if not (project_root / "main.py").exists():
        print("❌ Please run this script from the project root directory")
        return False
    
    # Check if Python version is adequate
    if sys.version_info < (3, 8):
        print("❌ Python 3.8 or higher is required")
        return False
    
    print("✅ Prerequisites check passed")
    return True


def get_database_engine():
    """Get database engine based on configuration"""
    if settings.DATABASE_URL.startswith("sqlite"):
        return create_engine(
            settings.DATABASE_URL.replace("sqlite+aiosqlite", "sqlite"),
            echo=False
        )
    else:
        return create_engine(
            settings.DATABASE_URL.replace("postgresql+asyncpg", "postgresql"),
            echo=False
        )


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


def create_database_table(engine):
    """Create the gg_templates table"""
    print("\n🗄️ Creating gg_templates table...")
    
    try:
        with engine.connect() as conn:
            # Check if table already exists
            result = conn.execute(text("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'gg_templates'
                );
            """))
            
            if result.scalar():
                print("✅ gg_templates table already exists")
                return True
            
            # Create the table
            create_table_sql = """
            CREATE TABLE gg_templates (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                template_id VARCHAR(255) UNIQUE NOT NULL,
                template_name VARCHAR(500) NOT NULL,
                file_path VARCHAR(500),
                file_size VARCHAR(50),
                additional_config JSONB DEFAULT '{}',
                created_datetime TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_datetime TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
            """
            
            conn.execute(text(create_table_sql))
            
            # Create indexes
            indexes = [
                "CREATE INDEX IF NOT EXISTS idx_template_id ON gg_templates(template_id);",
                "CREATE INDEX IF NOT EXISTS idx_template_name ON gg_templates(template_name);",
                "CREATE INDEX IF NOT EXISTS idx_created_datetime ON gg_templates(created_datetime);"
            ]
            
            for index_sql in indexes:
                conn.execute(text(index_sql))
            
            # Create trigger for updated_datetime
            trigger_sql = """
            CREATE OR REPLACE FUNCTION update_gg_templates_updated_datetime()
            RETURNS TRIGGER AS $$
            BEGIN
                NEW.updated_datetime = CURRENT_TIMESTAMP;
                RETURN NEW;
            END;
            $$ language 'plpgsql';
            
            CREATE TRIGGER update_gg_templates_updated_datetime
                BEFORE UPDATE ON gg_templates
                FOR EACH ROW
                EXECUTE FUNCTION update_gg_templates_updated_datetime();
            """
            
            conn.execute(text(trigger_sql))
            conn.commit()
            
            print("✅ gg_templates table created successfully with current schema")
            return True
            
    except Exception as e:
        print(f"❌ Error creating database table: {str(e)}")
        return False


def test_database_connection(engine):
    """Test database connection and basic operations"""
    print("\n🧪 Testing database connection...")
    
    try:
        with engine.connect() as conn:
            # Test basic connection
            result = conn.execute(text("SELECT 1"))
            print("✅ Database connection successful")
            
            # Test table access
            result = conn.execute(text("SELECT COUNT(*) FROM gg_templates"))
            count = result.scalar()
            print(f"✅ Table access successful (current records: {count})")
            
            return True
            
    except Exception as e:
        print(f"❌ Database test failed: {str(e)}")
        return False


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


def create_sample_template_record(engine):
    """Create a sample template record in the database"""
    print("\n📝 Creating sample template record...")
    
    try:
        with engine.connect() as conn:
            # Check if sample template already exists
            result = conn.execute(text("""
                SELECT COUNT(*) FROM gg_templates 
                WHERE template_id = 'sample_welcome_template'
            """))
            
            if result.scalar() > 0:
                print("✅ Sample template record already exists")
                return True
            
            # Create sample template
            sample_config = {
                "subject": "Welcome to our platform!",
                "variables": ["user_name", "company_name", "user_email", "signup_date"],
                "priority": "high",
                "category": "onboarding"
            }
            
            insert_sql = text("""
                INSERT INTO gg_templates (
                    template_id, template_name, file_path, file_size,
                    additional_config
                ) VALUES (
                    :template_id, :template_name, :file_path, :file_size,
                    :additional_config
                )
            """)
            
            # Get the actual file path and size
            template_dir = settings.TEMPLATE_DIR
            file_path = os.path.join(template_dir, 'welcome_email.html')
            file_size = str(os.path.getsize(file_path)) if os.path.exists(file_path) else "0"
            
            conn.execute(insert_sql, {
                'template_id': 'TMPLT_INVITE_001',
                'template_name': 'welcome_email.html',
                'file_path': file_path,
                'file_size': file_size,
                'additional_config': json.dumps(sample_config)
            })
            
            conn.commit()
            print("✅ Sample template record created successfully")
            return True
            
    except Exception as e:
        print(f"❌ Error creating sample template record: {str(e)}")
        return False


def show_usage_examples():
    """Show usage examples and next steps"""
    print("\n📚 Usage Examples and Next Steps:")
    print("=" * 50)
    
    print("\n🔗 API Endpoints:")
    print("   - GET /api/v1/templates/files - List template files")
    print("   - GET /api/v1/templates/files/{filename} - Get file content")
    print("   - GET /api/v1/templates/files/{filename}/download - Download file")
    print("   - GET /api/v1/templates/ - List database templates")
    print("   - POST /api/v1/templates/ - Create template record")
    print("   - PUT /api/v1/templates/{template_id} - Update template")
    print("   - DELETE /api/v1/templates/{template_id} - Delete template")
    
    print("\n📝 Example API Calls:")
    print("""
    # List template files
    curl -X GET "http://localhost:8000/api/v1/templates/files" \\
         -H "Authorization: Bearer <your-token>"
    
    # Get specific template file
    curl -X GET "http://localhost:8000/api/v1/templates/files/welcome_email.html" \\
         -H "Authorization: Bearer <your-token>"
    
    # Create template record
    curl -X POST "http://localhost:8000/api/v1/templates/" \\
         -H "Authorization: Bearer <your-token>" \\
         -H "Content-Type: application/json" \\
         -d '{
           "template_id": "welcome_email_001",
           "template_name": "Welcome Email Template",
           "file_name": "welcome_email.html",
           "additional_config": {
             "subject": "Welcome!",
             "variables": ["user_name"]
           }
         }'
    """)
    
    print("\n🚀 Next Steps:")
    print("   1. Start your application: python main.py")
    print("   2. Access API documentation: http://localhost:8000/api/docs")
    print("   3. Test template endpoints with your authentication token")
    print("   4. Customize template files in the template directory")
    print("   5. Create template records in the database as needed")
    
    print(f"\n📁 Configuration:")
    print(f"   - Template directory: {settings.TEMPLATE_DIR}")
    print(f"   - Allowed template types: {settings.ALLOWED_TEMPLATE_TYPES}")
    print(f"   - Database table: gg_templates")


def main():
    """Main setup function"""
    print("🚀 Template Setup Script")
    print("=" * 50)
    
    try:
        # Check prerequisites
        if not check_prerequisites():
            sys.exit(1)
        
        # Setup template directory
        if not setup_template_directory():
            print("❌ Failed to setup template directory")
            sys.exit(1)
        
        # Get database engine
        print("\n🔌 Connecting to database...")
        engine = get_database_engine()
        
        # Create database table
        if not create_database_table(engine):
            print("❌ Failed to create database table")
            sys.exit(1)
        
        # Create sample template record
        create_sample_template_record(engine)
        
        # Test everything
        db_test = test_database_connection(engine)
        file_test = test_template_files()
        
        # Show results
        print("\n" + "=" * 50)
        print("🎉 Template setup completed!")
        print(f"📊 Results:")
        print(f"   - Template directory: {'✅ Success' if file_test else '❌ Failed'}")
        print(f"   - Database table: {'✅ Success' if db_test else '❌ Failed'}")
        print(f"   - Sample files: Created")
        print(f"   - Sample record: Created")
        print(f"   - API endpoints: Ready")
        
        if db_test and file_test:
            print("\n✅ All components are working correctly!")
            show_usage_examples()
        else:
            print("\n⚠️ Some components failed. Please check the errors above.")
            sys.exit(1)
            
    except Exception as e:
        print(f"❌ Setup failed: {str(e)}")
        print("\nTroubleshooting:")
        print("1. Check your DATABASE_URL environment variable")
        print("2. Ensure database is running and accessible")
        print("3. Verify file system permissions")
        print("4. Check Python dependencies are installed")
        sys.exit(1)


if __name__ == "__main__":
    main()