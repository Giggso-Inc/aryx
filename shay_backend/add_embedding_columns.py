"""
Standalone script to add embedding columns to gg_datasources table
Run this script to add the required columns for the embedding feature
"""

import asyncio
import sys
from sqlalchemy import text
from app.core.database import engine

async def add_embedding_columns():
    """Add embedding columns to gg_datasources table"""
    
    try:
        async with engine.begin() as conn:
            print("Starting migration: Adding embedding columns to gg_datasources table...")
            
            # Check if columns already exist
            check_columns_query = text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'gg_datasources' 
                AND column_name IN ('is_embedding_required', 'embedding_status')
            """)
            
            result = await conn.execute(check_columns_query)
            existing_columns = [row[0] for row in result]
            
            if 'is_embedding_required' in existing_columns and 'embedding_status' in existing_columns:
                print("✅ Columns already exist. Migration not needed.")
                return
            
            # Add is_embedding_required column
            if 'is_embedding_required' not in existing_columns:
                print("Adding is_embedding_required column...")
                await conn.execute(text("""
                    ALTER TABLE gg_datasources 
                    ADD COLUMN is_embedding_required BOOLEAN NOT NULL DEFAULT FALSE
                """))
                print("✅ Added is_embedding_required column")
            else:
                print("✅ is_embedding_required column already exists")
            
            # Add embedding_status column
            if 'embedding_status' not in existing_columns:
                print("Adding embedding_status column...")
                await conn.execute(text("""
                    ALTER TABLE gg_datasources 
                    ADD COLUMN embedding_status INTEGER NOT NULL DEFAULT 0
                """))
                print("✅ Added embedding_status column")
            else:
                print("✅ embedding_status column already exists")
            
            # Create index for embedding_status
            print("Creating index for embedding_status...")
            try:
                await conn.execute(text("""
                    CREATE INDEX idx_datasource_embedding_status 
                    ON gg_datasources(embedding_status)
                """))
                print("✅ Created index idx_datasource_embedding_status")
            except Exception as e:
                if "already exists" in str(e).lower():
                    print("✅ Index idx_datasource_embedding_status already exists")
                else:
                    print(f"⚠️  Warning: Could not create index: {e}")
            
            print("\n🎉 Migration completed successfully!")
            print("Added columns:")
            print("  - is_embedding_required (BOOLEAN, default: FALSE)")
            print("  - embedding_status (INTEGER, default: 0)")
            print("  - Index: idx_datasource_embedding_status")
            
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        sys.exit(1)

async def verify_migration():
    """Verify that the migration was successful"""
    
    try:
        async with engine.begin() as conn:
            print("\n🔍 Verifying migration...")
            
            # Check if columns exist
            check_columns_query = text("""
                SELECT column_name, data_type, column_default, is_nullable
                FROM information_schema.columns 
                WHERE table_name = 'gg_datasources' 
                AND column_name IN ('is_embedding_required', 'embedding_status')
                ORDER BY column_name
            """)
            
            result = await conn.execute(check_columns_query)
            columns = result.fetchall()
            
            if len(columns) == 2:
                print("✅ Both columns found:")
                for col in columns:
                    print(f"  - {col[0]}: {col[1]} (default: {col[2]}, nullable: {col[3]})")
            else:
                print(f"❌ Expected 2 columns, found {len(columns)}")
                return False
            
            # Check if index exists
            check_index_query = text("""
                SELECT indexname 
                FROM pg_indexes 
                WHERE tablename = 'gg_datasources' 
                AND indexname = 'idx_datasource_embedding_status'
            """)
            
            result = await conn.execute(check_index_query)
            index_exists = result.fetchone() is not None
            
            if index_exists:
                print("✅ Index idx_datasource_embedding_status found")
            else:
                print("⚠️  Index idx_datasource_embedding_status not found")
            
            print("\n🎉 Verification completed!")
            return True
            
    except Exception as e:
        print(f"❌ Verification failed: {e}")
        return False

async def main():
    """Main function to run the migration"""
    
    print("=" * 60)
    print("🚀 EMBEDDING COLUMNS MIGRATION SCRIPT")
    print("=" * 60)
    print("This script will add embedding columns to gg_datasources table")
    print("Columns to be added:")
    print("  - is_embedding_required (BOOLEAN, default: FALSE)")
    print("  - embedding_status (INTEGER, default: 0)")
    print("  - Index: idx_datasource_embedding_status")
    print("=" * 60)
    
    # Run the migration
    await add_embedding_columns()
    
    # Verify the migration
    success = await verify_migration()
    
    if success:
        print("\n✅ Migration completed successfully!")
        print("You can now use the embedding feature in your API.")
    else:
        print("\n❌ Migration verification failed!")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())


