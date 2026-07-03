# Database Testing Guide for Log Analyzer Backend

## 🎯 **Overview**

This guide provides comprehensive testing procedures for the Log Analyzer Backend database functionality. The application uses SQLite for development and PostgreSQL for production.

## 📊 **Database Schema**

### **Tables Created:**
1. **`users`** - User authentication and management
2. **`companies`** - Multi-tenant company support
3. **`workspaces`** - Channel-based workspace management
4. **`threads`** - Thread organization for messages
5. **`messages`** - User and AI messages
6. **`attachments`** - File upload and management
7. **`ai_responses`** - AI analysis results storage

## 🧪 **Testing Methods**

### **Method 1: Direct Database Testing (Recommended)**

Run the comprehensive database test script:

```bash
python test_database_only.py
```

**Expected Output:**
```
✅ Found 7 tables
✅ Test data inserted successfully!
✅ Database operations test completed successfully!
✅ All queries executed successfully
```

### **Method 2: API Endpoint Testing**

1. Start the server:
```bash
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

2. Test API endpoints:
```bash
python test_db.py
```

3. Visit interactive docs:
```
http://localhost:8000/docs
```

### **Method 3: Manual SQLite Inspection**

If SQLite3 is installed:
```bash
sqlite3 log_analyzer.db
.tables
.schema users
SELECT COUNT(*) FROM users;
.quit
```

## 🔍 **Test Results Summary**

### **✅ Database Structure Test**
- **Tables Created:** 7/7 ✅
- **Schema Validation:** All columns present ✅
- **Indexes Created:** All required indexes present ✅

### **✅ Data Insertion Test**
- **Companies:** 1 row inserted ✅
- **Users:** 1 row inserted ✅
- **Workspaces:** 1 row inserted ✅
- **Threads:** 1 row inserted ✅
- **Messages:** 1 row inserted ✅
- **Attachments:** 1 row inserted ✅
- **AI Responses:** 1 row inserted ✅

### **✅ Query Performance Test**
- **Simple Queries:** All working ✅
- **Complex Joins:** All working ✅
- **Aggregation Queries:** All working ✅

## 🚀 **Environment Setup for DevOps**

### **Development Environment (SQLite)**
```bash
# Database URL
DATABASE_URL="sqlite+aiosqlite:///./log_analyzer.db"

# Dependencies
pip install -r requirements.txt

# Initialize database
python setup_dev.py

# Test database
python test_database_only.py
```

### **Production Environment (PostgreSQL)**
```bash
# Database URL
DATABASE_URL="postgresql+asyncpg://user:password@localhost:5432/log_analyzer"

# Dependencies
pip install -r requirements.txt

# Run migrations
alembic upgrade head

# Test database
python test_database_only.py
```

## 📋 **Key Test Scenarios**

### **1. Database Initialization**
- ✅ Tables created with correct schema
- ✅ Indexes created for performance
- ✅ Foreign key relationships established

### **2. Data Operations**
- ✅ INSERT operations work correctly
- ✅ SELECT queries return expected results
- ✅ UPDATE operations modify data properly
- ✅ DELETE operations remove data safely

### **3. Relationship Testing**
- ✅ Company → Users relationship
- ✅ Company → Workspaces relationship
- ✅ Workspace → Threads relationship
- ✅ Thread → Messages relationship
- ✅ Message → AI Responses relationship

### **4. Performance Testing**
- ✅ Complex JOIN queries execute
- ✅ Aggregation queries work
- ✅ Index usage is optimal

## 🔧 **Troubleshooting**

### **Common Issues:**

1. **Database Connection Error**
   ```bash
   # Check if database file exists
   ls -la log_analyzer.db
   
   # Recreate database
   python setup_dev.py
   ```

2. **Import Errors**
   ```bash
   # Install missing dependencies
   pip install -r requirements.txt
   ```

3. **Schema Issues**
   ```bash
   # Reset database
   rm log_analyzer.db
   python setup_dev.py
   ```

## 📊 **Monitoring Queries**

### **Database Health Check:**
```sql
-- Check table counts
SELECT 'users' as table_name, COUNT(*) as count FROM users
UNION ALL
SELECT 'companies', COUNT(*) FROM companies
UNION ALL
SELECT 'workspaces', COUNT(*) FROM workspaces
UNION ALL
SELECT 'threads', COUNT(*) FROM threads
UNION ALL
SELECT 'messages', COUNT(*) FROM messages
UNION ALL
SELECT 'attachments', COUNT(*) FROM attachments
UNION ALL
SELECT 'ai_responses', COUNT(*) FROM ai_responses;
```

### **Performance Monitoring:**
```sql
-- Check recent activity
SELECT 
    'messages' as table_name,
    COUNT(*) as total,
    MAX(created_at) as latest_activity
FROM messages
UNION ALL
SELECT 
    'ai_responses',
    COUNT(*),
    MAX(created_at)
FROM ai_responses;
```

## 🎯 **Success Criteria**

✅ **All tests pass**
✅ **Database operations complete successfully**
✅ **API endpoints return expected responses**
✅ **Data relationships work correctly**
✅ **Performance is acceptable**

## 📞 **Support**

For database-related issues:
1. Check the test output for specific errors
2. Verify environment variables are set correctly
3. Ensure all dependencies are installed
4. Review the application logs for detailed error messages

---

**Last Updated:** July 28, 2025
**Version:** 1.0.0
**Environment:** Development (SQLite) / Production (PostgreSQL) 