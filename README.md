# Gemini Balance - Gemini API Proxy and Load Balancer

<p align="center">
  <a href="https://trendshift.io/repositories/13692" target="_blank">
    <img src="https://trendshift.io/api/badge/repositories/13692" alt="snailyp%2Fgemini-balance | Trendshift" style="width: 250px; height: 55px;" width="250" height="55"/>
  </a>
</p>

<p align="center">
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3.9%2B-blue.svg" alt="Python"></a>
  <a href="https://fastapi.tiangolo.com/"><img src="https://img.shields.io/badge/FastAPI-0.100%2B-green.svg" alt="FastAPI"></a>
  <a href="https://www.uvicorn.org/"><img src="https://img.shields.io/badge/Uvicorn-running-purple.svg" alt="Uvicorn"></a>
  <a href="https://t.me/+soaHax5lyI0wZDVl"><img src="https://img.shields.io/badge/Telegram-Group-blue.svg?logo=telegram" alt="Telegram Group"></a>
</p>

> ⚠️ **Important Notice**: This project is licensed under [CC BY-NC 4.0](LICENSE), **commercial resale services are strictly prohibited**.
> The author has never sold services on any platform. If you encounter any sales, they are unauthorized resales. Please do not be deceived.

---

## 📖 Project Introduction

**Gemini Balance** is a Python FastAPI-based application designed to provide proxy and load balancing functions for the Google Gemini API. It allows you to manage multiple Gemini API Keys and implement key rotation, authentication, model filtering, and status monitoring through simple configuration. Additionally, the project integrates image generation and multiple image hosting upload functions, and supports OpenAI API format proxy.

<details>
<summary>📂 View Project Structure</summary>

```plaintext
app/
├── config/       # Configuration management
├── core/         # Core application logic (FastAPI instance creation, middleware, etc.)
├── database/     # Database models and connections
├── domain/       # Business domain objects
├── exception/    # Custom exceptions
├── handler/      # Request handlers
├── log/          # Logging configuration
├── main.py       # Application entry point
├── middleware/   # FastAPI middleware
├── router/       # API routes (Gemini, OpenAI, status pages, etc.)
├── scheduler/    # Scheduled tasks (such as key status checks)
├── service/      # Business logic services (chat, key management, statistics, etc.)
├── static/       # Static files (CSS, JS)
├── templates/    # HTML templates (such as key status pages)
└── utils/        # Utility functions
```
</details>

---

## ✨ Feature Highlights

*   **Multi-Key Load Balancing**: Supports multiple Gemini API Keys with intelligent rotation and load balancing.
*   **OpenAI API Compatibility**: Provides OpenAI-compatible API interface, seamlessly integrating with existing OpenAI applications.
*   **Real-time Key Status Monitoring**: Web interface displays key status, failure counts, and usage statistics in real-time.
*   **Intelligent Failure Handling**: Automatic retry mechanism (`MAX_RETRIES`) and automatic key disabling when failure count exceeds threshold (`MAX_FAILURES`), with scheduled recovery checks (`CHECK_INTERVAL_HOURS`).
*   **Model Filtering and Management**: Supports custom model filtering (`FILTERED_MODELS`) and search model configuration (`SEARCH_MODELS`).
*   **Image Generation Integration**: Integrates `imagen-3.0-generate-002` model and converts it to OpenAI image generation interface format.
*   **Multiple Image Hosting Support**: Supports SM.MS, PicGo, and Cloudflare image hosting for generated images.
*   **Flexible Key Addition**: Supports batch key addition through regex `gemini_key` with automatic deduplication.
*   **Comprehensive API Compatibility**:
    *   **Embeddings Interface**: Perfect adaptation to OpenAI format `embeddings` interface.
    *   **Image Generation Interface**: Converts `imagen-3.0-generate-002` model interface to OpenAI image generation interface format.
*   **Automatic Model List Maintenance**: Automatically fetches and syncs the latest model lists from Gemini and OpenAI, compatible with New API.
*   **Proxy Support**: Supports HTTP/SOCKS5 proxy configuration (`PROXIES`) for use in special network environments.
*   **Docker Support**: Provides Docker images for AMD and ARM architectures for quick deployment.
    *   Image address: `ghcr.io/snailyp/gemini-balance:latest`

---

## 🚀 Quick Start

### Option 1: Docker Compose (Recommended)

1. **Clone Repository**:
   ```bash
   git clone https://github.com/snailyp/gemini-balance.git
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
   git clone https://github.com/snailyp/gemini-balance.git
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

### Environment Variables

Copy `.env.example` to `.env` and configure your settings. Key configuration items include:

| Configuration Item | Description | Default Value |
|-------------------|-------------|---------------|
| **Database Configuration** | | |
| `DATABASE_TYPE` | Database type: `mysql` or `sqlite` | `mysql` |
| `MYSQL_HOST` | MySQL host address | `localhost` |
| `MYSQL_PORT` | MySQL port | `3306` |
| `MYSQL_USER` | MySQL username | `gemini` |
| `MYSQL_PASSWORD` | MySQL password | `change_me` |
| `MYSQL_DATABASE` | MySQL database name | `default_db` |
| **API Configuration** | | |
| `API_KEYS` | Gemini API Key list (JSON array format) | `["your-api-key"]` |
| `ALLOWED_TOKENS` | Allowed access tokens | `["sk-123456"]` |
| `AUTH_TOKEN` | Admin authentication token | `sk-123456` |
| `BASE_URL` | Gemini API base URL | `https://generativelanguage.googleapis.com/v1beta` |
| `MAX_FAILURES` | Maximum failures allowed per key | `3` |
| `MAX_RETRIES` | Maximum retries for API request failures | `3` |
| `CHECK_INTERVAL_HOURS` | Disabled key recovery check interval (hours) | `1` |
| `TIMEZONE` | Application timezone | `Asia/Shanghai` |
| `TIME_OUT` | Request timeout (seconds) | `300` |
| `PROXIES` | Proxy server list (e.g., `http://user:pass@host:port`) | `[]` |

### Web Interface Configuration

1. **Access Management Interface**: Visit `http://localhost:8000/keys_status`
2. **Add API Keys**: Add your Gemini API keys through the web interface
3. **Monitor Status**: Real-time monitoring of key status and usage statistics

## 🔗 API Endpoints

- **Web Interface**: `http://localhost:8000`
- **Key Management**: `http://localhost:8000/keys_status`
- **OpenAI Compatible**: `http://localhost:8000/v1`
- **Gemini Native**: `http://localhost:8000/gemini/v1beta`

## 🎁 Project Support

If you find this project helpful, you can support me through the following ways:

### 💰 Sponsorship Methods

- **[Afdian](https://afdian.com/a/snaily)** - Continuous support for project development
- **WeChat Appreciation** - Scan the QR code below
- **Alipay** - Scan the QR code below

<div align="center">
  <table>
    <tr>
      <td align="center">
        <img src="https://raw.githubusercontent.com/sofs2005/difytask/refs/heads/main/img/wx.png" alt="WeChat Appreciation Code" width="200"/>
        <br/>
        <strong>WeChat Appreciation</strong>
      </td>
      <td align="center">
        <img src="https://raw.githubusercontent.com/sofs2005/difytask/refs/heads/main/img/zfb.jpg" alt="Alipay Payment Code" width="200"/>
        <br/>
        <strong>Alipay</strong>
      </td>
    </tr>
  </table>
</div>

> 💡 Your support is my motivation to continuously maintain and improve this project!

## 📄 License

This project is licensed under [CC BY-NC 4.0](LICENSE) (Attribution-NonCommercial).

## 💖 Friendly Projects

*   **[OneLine](https://github.com/chengtx809/OneLine)** by [chengtx809](https://github.com/chengtx809) - AI-driven hot event timeline generation tool.

## Sponsors

Special thanks to [DigitalOcean](https://m.do.co/c/b249dd7f3b4c) for providing stable and reliable cloud infrastructure support for this project.

<a href="https://m.do.co/c/b249dd7f3b4c">
  <img src="files/dataocean.svg" alt="DigitalOcean Logo" width="200"/>
</a>

The CDN acceleration and security protection for this project are sponsored by [Tencent EdgeOne](https://edgeone.ai/?from=github).

<a href="https://edgeone.ai/?from=github">
  <img src="https://edgeone.ai/media/34fe3a45-492d-4ea4-ae5d-ea1087ca7b4b.png" alt="EdgeOne Logo" width="200"/>
</a>

