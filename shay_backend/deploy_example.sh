#!/bin/bash

# Example deployment script showing automated migrations
# This is what happens when you deploy to QA/Production

echo "🚀 Starting deployment..."

# 1. Set environment variables
export ENVIRONMENT="production"
export DATABASE_URL="postgresql+asyncpg://user:password@host:port/dbname"

# 2. Install dependencies
echo "📦 Installing dependencies..."
pip install -r requirements.txt

# 3. Start the application (migrations run automatically)
echo "🔄 Starting application (migrations will run automatically)..."
uvicorn main:app --host 0.0.0.0 --port 8000

# That's it! The application will:
# - Detect it's in production environment
# - Initialize migration system if needed
# - Create initial migration if needed
# - Apply all pending migrations
# - Start the application

echo "✅ Deployment complete!" 