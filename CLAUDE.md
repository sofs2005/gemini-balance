# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

### Running the Application
- **Local Development**: `uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload`
- **Docker Compose**: `docker-compose up -d` (recommended for production)
- **Docker**: `docker run -d -p 8000:8000 --name gemini-balance -v ./data:/app/data --env-file .env softs2005/gemini-balance:latest`

### Testing
- **Run all tests**: `python tests/test_runner.py`
- **Specific test**: `python -m unittest tests.test_ttl_cache.TestTTLCache.test_ttl_expiration`
- **Individual test file**: `python -m unittest tests.test_key_manager_integration`

### Development Setup
- **Install dependencies**: `pip install -r requirements.txt`
- **Environment setup**: Copy `.env.example` to `.env` and configure
- **Database schema fix**: `python fix_settings_table.py` (use if database schema needs updates)

## Architecture Overview

This is a FastAPI-based Gemini API proxy and load balancer that manages multiple API keys with intelligent routing and monitoring.

### Core Components

**Application Structure** (`app/core/application.py`):
- Central FastAPI app creation with lifespan management
- Database initialization and connection handling
- Settings synchronization between environment and database
- Background scheduler for maintenance tasks

**Configuration System** (`app/config/config.py`):
- Pydantic-based settings with environment variable support
- Dynamic configuration that syncs with database on startup
- Supports both SQLite and MySQL databases
- Complex type parsing for lists, dictionaries, and nested structures

**Key Management** (`app/service/key/key_manager.py`):
- Multi-key load balancing with ValidKeyPool for efficient key rotation
- Failure tracking and automatic key disabling
- Support for both Gemini and Vertex AI API keys
- Background key validation and pool maintenance

### Service Layer Architecture

**Chat Services** (`app/service/chat/`):
- `gemini_chat_service.py`: Handles Gemini API interactions
- `openai_chat_service.py`: Provides OpenAI-compatible API proxy
- `vertex_express_chat_service.py`: Vertex AI platform integration

**Request Handling** (`app/handler/`):
- Stream response optimization and retry logic
- Error processing and message conversion
- Response handling for different API formats

### Database Models

**Key Components** (`app/database/models.py`):
- Settings: Dynamic configuration storage
- API key management and validation tracking
- Request and error logging
- File management and user isolation

### API Endpoints

**Multi-Protocol Support**:
- **Gemini Format**: `/gemini/v1beta/` (native Gemini API)
- **OpenAI Format**: `/hf/v1/` and `/openai/v1/` (OpenAI-compatible)
- **Vertex Express**: Direct Google Vertex AI integration

**Web Interface**:
- `/keys_status` - Real-time key monitoring and management
- `/config` - Dynamic configuration editor
- `/error_logs` - Error log viewer with search/filter

### Advanced Features

**ValidKeyPool System**:
- Intelligent key pool with TTL-based expiration
- Emergency refill mechanism for low key situations
- Different usage limits for Pro vs Non-Pro models
- Background maintenance tasks

**Image Generation**:
- Support for multiple image hosting providers (SM.MS, PicGo, Cloudflare)
- Automatic upload and URL generation
- Configurable models for image generation

**File Management**:
- Complete Files API support for uploads and management
- Automatic cleanup of expired files
- User isolation when enabled

### Configuration Notes

**Environment Variables**: Copy `.env.example` to `.env` and configure:
- Database settings (MySQL recommended for production)
- API keys for Gemini and Vertex AI
- Authentication tokens for admin access
- Model-specific configurations and safety settings
- Image generation and hosting provider settings
- Proxy configurations for network environments

**Database Configuration**: 
- Uses MySQL by default in production
- SQLite for development
- Automatic schema initialization on startup
- Settings are synchronized from environment to database on startup

**Key Pool Configuration**:
- `VALID_KEY_POOL_ENABLED`: Enable intelligent key management
- `VALID_KEY_POOL_SIZE`: Number of keys to keep in rotation
- `KEY_TTL_HOURS`: Time before keys need revalidation
- `POOL_MAINTENANCE_INTERVAL_MINUTES`: How often to check pool health

**Advanced Features Configuration**:
- `STREAM_OPTIMIZER_ENABLED`: Control stream response optimization
- `FAKE_STREAM_ENABLED`: Enable fake streaming for compatibility
- `SAFETY_SETTINGS`: Configure content filtering policies
- `PROXIES`: Configure HTTP/SOCKS5 proxy settings
- `TTS_MODEL`: Text-to-speech model configuration

### Development Patterns

**Error Handling**: Comprehensive error logging with automatic cleanup
**Configuration Changes**: Most configuration changes take effect immediately without restart
**Testing**: Focus on key management and cache functionality in `tests/` directory
- Test files: `test_ttl_cache.py`, `test_key_manager_integration.py`, `test_valid_key_pool.py`
**Logging**: Multi-level logging with automatic retention policies
**Database Models**: Use SQLAlchemy ORM with support for both MySQL and SQLite
**Background Tasks**: APScheduler for key validation, pool maintenance, and file cleanup