"""Database engine + gg_templates table/record helpers for setup_templates.py.

Split out of scripts/setup_templates.py (2026-09; Raven Style Compliance
Plan Phase 8b line-count reduction).
"""

import json
import os

from sqlalchemy import create_engine, text

from app.core.config import settings


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
