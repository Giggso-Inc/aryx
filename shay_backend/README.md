# Log Analyzer Backend

A comprehensive FastAPI-based backend for AI-powered log analysis with multi-tenant support, OAuth2 authentication, and sophisticated AI integration capabilities.

## 🚀 Features

- **OAuth2 Authentication** - Google OAuth integration with JWT tokens
- **Multi-tenant Architecture** - Company-based workspace isolation
- **Thread-based Messaging** - Chat-like interface for log analysis
- **File Upload System** - Support for .log, .txt, .json, .xml files
- **AI Integration** - Webhook-based AI processing with multiple providers
- **Role-based Access Control** - Admin, User, Guest roles with scoped permissions
- **Real-time Processing** - Asynchronous AI analysis with status tracking
- **Production Ready** - Docker support, health checks, comprehensive error handling

## 🏗️ Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   React Frontend │    │  FastAPI Backend │    │   PostgreSQL    │
│                 │◄──►│                 │◄──►│    Database     │
│  - Authentication│    │  - API Routes   │    │  - User Data    │
│  - Real-time UI │    │  - WebSockets   │    │  - Messages     │
│  - File Upload  │    │  - Auth Middleware│   │  - Files        │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                                │
                                ▼
                       ┌─────────────────┐
                       │   AI Agents     │
                       │                 │
                       │  - N8N/Pipedream│
                       │  - OpenAI/Claude│
                       │  - Custom Models│
                       └─────────────────┘
```

## 📋 Prerequisites

- Python 3.11+
- PostgreSQL 12+
- Docker & Docker Compose (recommended)
- Google OAuth2 credentials

## 🛠️ Installation

### 1. Clone and Setup

```bash
cd backend
cp env.example .env
# Edit .env with your configuration
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Database Setup

```bash
# Using Docker
docker run --name log-analyzer-db \
  -e POSTGRES_DB=log_analyzer \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=password \
  -p 5432:5432 -d postgres:15

# Or using docker-compose
docker-compose up -d postgres
```

### 4. Environment Configuration

Edit `.env` file with your settings:

```bash
# Required settings
SECRET_KEY="your-super-secret-key"
GOOGLE_CLIENT_ID="your-google-client-id"
GOOGLE_CLIENT_SECRET="your-google-client-secret"
DATABASE_URL="postgresql+asyncpg://postgres:password@localhost:5432/log_analyzer"
```

### 5. Initialize Database

```bash
python -c "from app.core.database import init_db; import asyncio; asyncio.run(init_db())"
```

### 6. Run the Application

```bash
# Development
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Production
uvicorn main:app --host 0.0.0.0 --port 8000
```

## 🐳 Docker Deployment

### Quick Start with Docker Compose

```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f backend

# Stop services
docker-compose down
```

### Production Deployment

```bash
# Build and run with production profile
docker-compose --profile production up -d
```

## 🔌 API Endpoints

### Authentication
- `POST /api/v1/auth/login` - OAuth2 login initiation
- `POST /api/v1/auth/callback` - OAuth2 callback handling
- `POST /api/v1/auth/refresh` - Token refresh
- `GET /api/v1/auth/me` - Current user profile
- `POST /api/v1/auth/logout` - User logout

### Workspaces
- `GET /api/v1/workspaces/` - List workspaces
- `POST /api/v1/workspaces/` - Create workspace
- `GET /api/v1/workspaces/{id}` - Get workspace
- `PUT /api/v1/workspaces/{id}` - Update workspace
- `DELETE /api/v1/workspaces/{id}` - Delete workspace

### Messages & Threads
- `GET /api/v1/messages/threads` - List threads
- `POST /api/v1/messages/threads` - Create thread
- `POST /api/v1/messages/` - Send message (triggers AI)
- `GET /api/v1/messages/{thread_id}` - Get thread messages

### Attachments
- `POST /api/v1/attachments/upload` - Upload file
- `GET /api/v1/attachments/` - List attachments
- `GET /api/v1/attachments/{id}` - Get attachment
- `GET /api/v1/attachments/{id}/download` - Download file
- `DELETE /api/v1/attachments/{id}` - Delete attachment

### AI Agent
- `POST /api/v1/agent/callback` - Receive AI responses
- `POST /api/v1/agent/status` - Status updates
- `GET /api/v1/agent/health` - AI agent health
- `GET /api/v1/agent/stats` - AI statistics
- `POST /api/v1/agent/trigger/{message_id}` - Manual trigger

## 🤖 AI Integration

The backend supports multiple AI integration patterns:

### Webhook-based Processing
1. User sends message → Backend stores message
2. Backend triggers webhook → External AI service
3. AI service processes logs → Sends callback
4. Backend stores AI response → User sees result

### Supported AI Platforms
- **N8N** - Visual workflow automation
- **Pipedream** - Serverless integration
- **OpenAI** - Direct GPT model integration
- **Anthropic** - Claude model integration
- **Custom AI Services** - Extensible webhook architecture

### AI Configuration
```bash
# Add to .env
OPENAI_API_KEY="your-openai-api-key"
N8N_WEBHOOK_URL="https://your-n8n-instance.com/webhook/log-analysis"
PIPEDREAM_WEBHOOK_URL="https://your-pipedream-url.com"
```

## 🔐 Security Features

- **OAuth2 Authentication** - Google OAuth with secure token handling
- **JWT Tokens** - Stateless authentication with refresh mechanism
- **Role-based Access** - Admin, User, Guest roles with scoped permissions
- **Multi-tenant Security** - Company isolation and data protection
- **Input Validation** - Pydantic schema validation
- **File Upload Security** - Extension and size validation
- **CORS Protection** - Configurable cross-origin policies

## 📊 Database Schema

### Core Tables
- **users** - User accounts with role-based permissions
- **companies** - Multi-tenant company management
- **workspaces** - Channel-based workspace organization
- **messages** - Thread-based messaging with AI integration
- **attachments** - File management with security controls
- **ai_responses** - AI analysis results and metadata

### Design Principles
- **No Foreign Keys** - Application-managed relationships for flexibility
- **Optimized Indexing** - Performance-focused database design
- **Partitioning Ready** - Scalable table structure for high volume
- **Migration Support** - Database versioning and schema management

## 🧪 Testing

```bash
# Run tests
pytest

# Run with coverage
pytest --cov=app

# Run specific test
pytest tests/test_auth.py
```

## 📈 Monitoring

### Health Checks
- `GET /health` - Application health
- `GET /api/v1/agent/health` - AI agent health
- `GET /api/v1/attachments/health/storage` - Storage health

### Metrics
- Request rate and response times
- Database connection pool usage
- File upload success/failure rates
- AI agent response times
- Error rates by endpoint

## 🚀 Production Deployment

### Environment Variables
```bash
# Production settings
DEBUG=false
SECRET_KEY="secure-random-production-key"
DATABASE_URL="postgresql://user:pass@prod-db:5432/log_analyzer"

# OAuth2 production settings
GOOGLE_CLIENT_ID="prod-client-id"
GOOGLE_CLIENT_SECRET="prod-client-secret"
GOOGLE_REDIRECT_URI="https://yourdomain.com/api/v1/sso/google/callback"

# Security settings
CORS_ORIGINS="https://yourdomain.com,https://app.yourdomain.com"
```

### Docker Production
```bash
# Build production image
docker build -t log-analyzer-backend:v1.0.0 .

# Run with production config
docker run -d \
  --name log-analyzer-backend \
  -p 8000:8000 \
  --env-file .env.production \
  --restart unless-stopped \
  log-analyzer-backend:v1.0.0
```

### Kubernetes Deployment
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: log-analyzer-backend
spec:
  replicas: 3
  selector:
    matchLabels:
      app: log-analyzer-backend
  template:
    metadata:
      labels:
        app: log-analyzer-backend
    spec:
      containers:
      - name: backend
        image: log-analyzer-backend:v1.0.0
        ports:
        - containerPort: 8000
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: db-secret
              key: url
```

## 🔧 Development

### Project Structure
```
backend/
├── app/
│   ├── core/              # Core configuration and utilities
│   ├── models/            # SQLAlchemy database models
│   ├── routes/            # FastAPI route handlers
│   ├── schemas/           # Pydantic request/response schemas
│   ├── middleware/        # Authentication and security middleware
│   └── services/          # Business logic services
├── tests/                 # Test suite
├── uploads/               # File upload directory
├── main.py               # Application entry point
├── requirements.txt      # Python dependencies
├── Dockerfile           # Container configuration
├── docker-compose.yml   # Development environment
├── env.example          # Environment configuration template
└── README.md           # This file
```

### Code Quality
```bash
# Format code
black app/
isort app/

# Lint code
flake8 app/

# Type checking
mypy app/
```

## 📚 Documentation

- **API Documentation**: http://localhost:8000/docs
- **ReDoc Documentation**: http://localhost:8000/redoc
- **OpenAPI Schema**: http://localhost:8000/openapi.json

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Ensure all tests pass
6. Submit a pull request

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🆘 Support

For support and questions:
- Create an issue on GitHub
- Check the documentation at `/docs`
- Review the health check endpoints

## 🎯 Roadmap

- [ ] WebSocket support for real-time updates
- [ ] Advanced analytics dashboard
- [ ] Machine learning model integration
- [ ] Mobile API optimization
- [ ] Advanced caching with Redis
- [ ] Multi-region deployment support 
