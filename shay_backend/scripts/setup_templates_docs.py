"""Usage-example printout for setup_templates.py.

Split out of scripts/setup_templates.py (2026-09; Raven Style Compliance
Plan Phase 8b line-count reduction).
"""

from app.core.config import settings


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
