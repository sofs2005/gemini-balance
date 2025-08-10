# Gemini Balance - Gemini API Proxy and Load Balancer

A forked version of the original [Gemini Balance](https://github.com/snailyp/gemini-balance) project with personal modifications and improvements.

## 📖 About

This is a personal fork of the excellent **Gemini Balance** project by [snailyp](https://github.com/snailyp). The original project provides proxy and load balancing functions for the Google Gemini API with key rotation, authentication, model filtering, and status monitoring.

**Original Project**: [https://github.com/snailyp/gemini-balance](https://github.com/snailyp/gemini-balance)

---

## 🚀 Quick Start

### Option 1: Docker Compose (Recommended)

1. **Clone Repository**:
   ```bash
   git clone https://github.com/sofs2005/gemini-balance.git
   cd gemini-balance
   ```

2. **Configure Environment**:
   ```bash
   cp .env.example .env
   # Edit .env file with your settings
   ```

3. **Start Services**:
   ```bash
   docker-compose up -d
   ```

### Option 2: Local Development

1. **Clone and Install**:
   ```bash
   git clone https://github.com/sofs2005/gemini-balance.git
   cd gemini-balance
   pip install -r requirements.txt
   ```

2. **Configure Environment**:
   ```bash
   cp .env.example .env
   # Edit .env file with your settings
   ```

3. **Start Application**:
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```

Access the application at `http://localhost:8000`.

---

## 📝 Configuration

1. **Environment Variables**: Copy `.env.example` to `.env` and configure your settings
2. **API Keys**: Add your Gemini API keys through the web interface at `/keys_status`
3. **Database**: The application will automatically set up the database on first run

## 🔗 API Endpoints

- **Web Interface**: `http://localhost:8000`
- **Key Management**: `http://localhost:8000/keys_status`
- **OpenAI Compatible**: `http://localhost:8000/v1`
- **Gemini Native**: `http://localhost:8000/gemini/v1beta`

## 📄 License

This project follows the same license as the original project. Please refer to the [original repository](https://github.com/snailyp/gemini-balance) for license details.

