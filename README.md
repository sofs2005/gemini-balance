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

This is a personal fork of the excellent **Gemini Balance** project by [snailyp](https://github.com/snailyp). The original project provides comprehensive Gemini API proxy and load balancing functionality.

**Original Project**: [https://github.com/snailyp/gemini-balance](https://github.com/snailyp/gemini-balance)

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

*   **Multi-Key Load Balancing**: Supports multiple Gemini API Keys with intelligent ValidKeyPool rotation and load balancing.
*   **Visual Configuration with Instant Effect**: Configuration changes through the admin panel take effect immediately without service restart.
*   **Dual Protocol API Compatibility**: Supports both Gemini and OpenAI format CHAT API request forwarding.
    *   OpenAI Base URL: `http://localhost:8000(/hf)/v1`
    *   Gemini Base URL: `http://localhost:8000(/gemini)/v1beta`
*   **Image Chat and Generation**: Supports image conversation and generation through `IMAGE_MODELS` configuration, use `model-name-image` format when calling.
*   **Web Search Integration**: Supports web search through `SEARCH_MODELS` configuration, use `model-name-search` format when calling.
*   **Real-time Key Status Monitoring**: Web interface at `/keys_status` (authentication required) displays key status and usage statistics in real-time.
*   **Detailed Logging System**: Provides comprehensive error logs with search and filtering capabilities.
*   **Flexible Key Addition**: Supports batch key addition through regex `gemini_key` with automatic deduplication.
*   **Intelligent Failure Handling**: Automatic retry mechanism (`MAX_RETRIES`) and automatic key disabling when failure count exceeds threshold (`MAX_FAILURES`).
*   **Comprehensive API Compatibility**:
    *   **Embeddings Interface**: Perfect adaptation to OpenAI format `embeddings` interface.
    *   **Image Generation Interface**: Converts `imagen-3.0-generate-002` model interface to OpenAI image generation interface format.
    *   **Files API**: Full support for file upload and management.
    *   **Vertex Express**: Support for Google Vertex AI platform.
*   **Automatic Model List Maintenance**: Automatically fetches and syncs the latest model lists from Gemini and OpenAI, compatible with New API.
*   **Multiple Image Hosting Support**: Supports SM.MS, PicGo, and Cloudflare image hosting for generated images.
*   **Proxy Support**: Supports HTTP/SOCKS5 proxy configuration (`PROXIES`) for use in special network environments.
*   **Docker Support**: Provides Docker images for AMD and ARM architectures for quick deployment.
    *   Image address: `softs2005/gemini-balance:latest`

---

## 🚀 Quick Start

### Option 1: Using Docker Compose (Recommended)

This is the most recommended deployment method, which can start the application and database with a single command.

1.  **Download `docker-compose.yml`**:
    Get the `docker-compose.yml` file from the project repository.
2.  **Prepare `.env` file**:
    Copy `.env.example` to `.env` and modify the configuration as needed. Pay special attention to setting `DATABASE_TYPE` to `mysql` and filling in the `MYSQL_*` related configurations.
3.  **Start the service**:
    In the directory where `docker-compose.yml` and `.env` are located, run the following command:
    ```bash
    docker-compose up -d
    ```
    This command will start the `gemini-balance` application and the `mysql` database in detached mode.

### Option 2: Using Docker Command

1.  **Pull the image**:
    ```bash
    docker pull softs2005/gemini-balance:latest
    ```
2.  **Prepare `.env` file**:
    Copy `.env.example` to `.env` and modify the configuration as needed.
3.  **Run the container**:
    ```bash
    docker run -d -p 8000:8000 --name gemini-balance \
    -v ./data:/app/data \
    --env-file .env \
    softs2005/gemini-balance:latest
    ```
    *   `-d`: Run in detached mode.
    *   `-p 8000:8000`: Map the container's port 8000 to the host.
    *   `-v ./data:/app/data`: Mount a data volume to persist SQLite data and logs.
    *   `--env-file .env`: Load environment variables from the `.env` file.

### Option 3: Local Run (for Development)

1.  **Clone the repository and install dependencies**:
    ```bash
    git clone https://github.com/sofs2005/gemini-balance.git
    cd gemini-balance
    pip install -r requirements.txt
    ```
2.  **Configure environment variables**:
    Copy `.env.example` to `.env` and modify the configuration as needed.
3.  **Start the application**:
    ```bash
    uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
    ```
    After the application starts, access it at `http://localhost:8000`.

---

## ⚙️ API Endpoints

### Gemini API Format (`/gemini/v1beta`)

This endpoint is directly forwarded to official Gemini API format endpoint, without advanced features.

*   `GET /models`: List available Gemini models.
*   `POST /models/{model_name}:generateContent`: Generate content.
*   `POST /models/{model_name}:streamGenerateContent`: Stream content generation.
*   `POST /models/{model_name}:countTokens`: Count tokens.

#### Hugging Face (HF) Compatible

If you want to use advanced features, like fake streaming, please use this endpoint.

*   `GET /hf/v1/models`: List models.
*   `POST /hf/v1/chat/completions`: Chat completion.
*   `POST /hf/v1/embeddings`: Create text embeddings.

#### Standard OpenAI

This endpoint is directly forwarded to official OpenAI Compatible API format endpoint, without advanced features.

*   `GET /openai/v1/models`: List models.
*   `POST /openai/v1/chat/completions`: Chat completion (Recommended).
*   `POST /openai/v1/embeddings`: Create text embeddings.

### Web Interface

- **Main Interface**: `http://localhost:8000`
- **Key Management**: `http://localhost:8000/keys_status`
- **Configuration**: `http://localhost:8000/config`
- **Error Logs**: `http://localhost:8000/error_logs`

## 🎁 Project Support

If you find this project helpful, you can support me through the following ways:

### 💰 Sponsorship Methods

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
