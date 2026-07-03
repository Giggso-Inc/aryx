#!/bin/bash

# Deploy with Migrations Script
# This script demonstrates how to automatically run database migrations
# before starting your application in any deployment environment.

set -e  # Exit on any error

# Configuration
APP_NAME="Your Backend App"
DATABASE_WAIT_TIMEOUT=30
MIGRATION_TIMEOUT=60

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to check if database is accessible
check_database_connection() {
    log_info "Testing database connection..."
    
    # Try to connect to database using Python
    python -c "
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

try:
    from app.core.database import engine
    from sqlalchemy import text
    
    with engine.connect() as conn:
        result = conn.execute(text('SELECT 1'))
        print('Database connection successful')
except Exception as e:
    print(f'Database connection failed: {e}')
    sys.exit(1)
" || {
        log_error "Database connection failed"
        return 1
    }
    
    log_success "Database connection successful"
    return 0
}

# Function to wait for database to be ready
wait_for_database() {
    log_info "Waiting for database to be ready..."
    
    local attempts=0
    while [ $attempts -lt $DATABASE_WAIT_TIMEOUT ]; do
        if check_database_connection; then
            log_success "Database is ready"
            return 0
        fi
        
        attempts=$((attempts + 1))
        log_warning "Database not ready yet, waiting... (attempt $attempts/$DATABASE_WAIT_TIMEOUT)"
        sleep 2
    done
    
    log_error "Database did not become ready within $DATABASE_WAIT_TIMEOUT seconds"
    return 1
}

# Function to check current migration status
check_migration_status() {
    log_info "Checking current migration status..."
    
    # Get current revision
    local current_revision
    current_revision=$(alembic current 2>/dev/null || echo "none")
    
    log_info "Current migration revision: $current_revision"
    
    # Check for pending migrations
    local pending_migrations
    pending_migrations=$(alembic check 2>/dev/null || echo "none")
    
    if [ "$pending_migrations" != "none" ]; then
        log_info "Pending migrations found"
        return 0
    else
        log_info "No pending migrations"
        return 1
    fi
}

# Function to run migrations
run_migrations() {
    log_info "Starting database migration process..."
    
    # Check if there are pending migrations
    if ! check_migration_status; then
        log_success "Database is already up to date"
        return 0
    fi
    
    # Show migration history
    log_info "Migration history:"
    alembic history --verbose | head -20
    
    # Run migrations with timeout
    log_info "Running migrations (timeout: ${MIGRATION_TIMEOUT}s)..."
    
    if timeout $MIGRATION_TIMEOUT alembic upgrade head; then
        log_success "Migrations completed successfully!"
        
        # Show new current revision
        local new_revision
        new_revision=$(alembic current 2>/dev/null || echo "unknown")
        log_info "New migration revision: $new_revision"
        
        return 0
    else
        log_error "Migration failed or timed out"
        return 1
    fi
}

# Function to validate application startup
validate_application() {
    log_info "Validating application startup..."
    
    # Check if the application can start (basic validation)
    python -c "
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

try:
    from app.core.database import engine
    from sqlalchemy import text
    
    # Test database operations
    with engine.connect() as conn:
        # Test a simple query
        result = conn.execute(text('SELECT COUNT(*) FROM information_schema.tables'))
        table_count = result.scalar()
        print(f'Database validation successful. Found {table_count} tables.')
        
except Exception as e:
    print(f'Application validation failed: {e}')
    sys.exit(1)
" || {
        log_error "Application validation failed"
        return 1
    }
    
    log_success "Application validation successful"
    return 0
}

# Function to start the application
start_application() {
    log_info "Starting $APP_NAME..."
    
    # Start the application (modify this based on your setup)
    if [ -f "main.py" ]; then
        log_info "Starting with main.py..."
        exec python main.py
    elif [ -f "uvicorn" ]; then
        log_info "Starting with uvicorn..."
        exec uvicorn main:app --host 0.0.0.0 --port 8000
    else
        log_error "No application entry point found"
        return 1
    fi
}

# Function to cleanup on exit
cleanup() {
    log_info "Cleaning up..."
    # Add any cleanup logic here
}

# Main deployment function
main() {
    log_info "Starting deployment process for $APP_NAME..."
    
    # Set up cleanup trap
    trap cleanup EXIT
    
    # Step 1: Wait for database
    if ! wait_for_database; then
        log_error "Failed to connect to database. Exiting."
        exit 1
    fi
    
    # Step 2: Run migrations
    if ! run_migrations; then
        log_error "Failed to run migrations. Exiting."
        exit 1
    fi
    
    # Step 3: Validate application
    if ! validate_application; then
        log_error "Application validation failed. Exiting."
        exit 1
    fi
    
    # Step 4: Start application
    log_success "Deployment completed successfully! Starting application..."
    start_application
}

# Function to show usage
show_usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  -h, --help          Show this help message"
    echo "  -c, --check-only    Only check database and migration status"
    echo "  -m, --migrate-only  Only run migrations, don't start app"
    echo "  -v, --verbose       Enable verbose output"
    echo ""
    echo "Examples:"
    echo "  $0                  # Full deployment with migrations"
    echo "  $0 --check-only     # Check status only"
    echo "  $0 --migrate-only   # Run migrations only"
}

# Parse command line arguments
CHECK_ONLY=false
MIGRATE_ONLY=false
VERBOSE=false

while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            show_usage
            exit 0
            ;;
        -c|--check-only)
            CHECK_ONLY=true
            shift
            ;;
        -m|--migrate-only)
            MIGRATE_ONLY=true
            shift
            ;;
        -v|--verbose)
            VERBOSE=true
            shift
            ;;
        *)
            log_error "Unknown option: $1"
            show_usage
            exit 1
            ;;
    esac
done

# Set verbose mode
if [ "$VERBOSE" = true ]; then
    set -x
fi

# Check if we're in the right directory
if [ ! -f "alembic.ini" ]; then
    log_error "alembic.ini not found. Please run this script from the project root."
    exit 1
fi

# Run based on options
if [ "$CHECK_ONLY" = true ]; then
    log_info "Running in check-only mode..."
    wait_for_database
    check_migration_status
    exit 0
elif [ "$MIGRATE_ONLY" = true ]; then
    log_info "Running in migrate-only mode..."
    wait_for_database
    run_migrations
    exit 0
else
    # Full deployment
    main
fi
