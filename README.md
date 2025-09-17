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

<<<<<<< HEAD
- **Main Interface**: `http://localhost:8000`
- **Key Management**: `http://localhost:8000/keys_status`
- **Configuration**: `http://localhost:8000/config`
- **Error Logs**: `http://localhost:8000/error_logs`
=======
<details>
<summary>📋 View Full Configuration List</summary>

| Configuration Item | Description | Default Value |
| :--- | :--- | :--- |
| **Database** | | |
| `DATABASE_TYPE` | `mysql` or `sqlite` | `mysql` |
| `SQLITE_DATABASE` | Path for SQLite database file | `default_db` |
| `MYSQL_HOST` | MySQL host address | `localhost` |
| `MYSQL_SOCKET` | MySQL socket address | `/var/run/mysqld/mysqld.sock` |
| `MYSQL_PORT` | MySQL port | `3306` |
| `MYSQL_USER` | MySQL username | `your_db_user` |
| `MYSQL_PASSWORD` | MySQL password | `your_db_password` |
| `MYSQL_DATABASE` | MySQL database name | `defaultdb` |
| **API** | | |
| `API_KEYS` | **Required**, list of Gemini API keys | `[]` |
| `ALLOWED_TOKENS` | **Required**, list of access tokens | `[]` |
| `AUTH_TOKEN` | Super admin token, defaults to the first of `ALLOWED_TOKENS` | `sk-123456` |
| `ADMIN_SESSION_EXPIRE` | Admin session expiration time in seconds (5 minutes to 24 hours) | `3600` |
| `TEST_MODEL` | Model for testing key validity | `gemini-2.5-flash-lite` |
| `IMAGE_MODELS` | Models supporting image generation | `["gemini-2.0-flash-exp", "gemini-2.5-flash-image-preview"]` |
| `SEARCH_MODELS` | Models supporting web search | `["gemini-2.5-flash","gemini-2.5-pro"]` |
| `FILTERED_MODELS` | Disabled models | `[]` |
| `TOOLS_CODE_EXECUTION_ENABLED` | Enable code execution tool | `false` |
| `SHOW_SEARCH_LINK` | Display search result links in response | `true` |
| `SHOW_THINKING_PROCESS` | Display model's thinking process | `true` |
| `THINKING_MODELS` | Models supporting thinking process | `[]` |
| `THINKING_BUDGET_MAP` | Budget map for thinking function (model:budget) | `{}` |
| `URL_NORMALIZATION_ENABLED` | Enable smart URL routing | `false` |
| `URL_CONTEXT_ENABLED` | Enable URL context understanding | `false` |
| `URL_CONTEXT_MODELS` | Models supporting URL context | `[]` |
| `BASE_URL` | Gemini API base URL | `https://generativelanguage.googleapis.com/v1beta` |
| `MAX_FAILURES` | Max failures allowed per key | `3` |
| `MAX_RETRIES` | Max retries for failed API requests | `3` |
| `CHECK_INTERVAL_HOURS` | Interval (hours) to re-check disabled keys | `1` |
| `TIMEZONE` | Application timezone | `Asia/Shanghai` |
| `TIME_OUT` | Request timeout (seconds) | `300` |
| `PROXIES` | List of proxy servers | `[]` |
| **Logging & Security** | | |
| `LOG_LEVEL` | Log level: `DEBUG`, `INFO`, `WARNING`, `ERROR` | `INFO` |
| `ERROR_LOG_RECORD_REQUEST_BODY` | Record request body in error logs (may contain sensitive information) | `false` |
| `AUTO_DELETE_ERROR_LOGS_ENABLED` | Auto-delete error logs | `true` |
| `AUTO_DELETE_ERROR_LOGS_DAYS` | Error log retention period (days) | `7` |
| `AUTO_DELETE_REQUEST_LOGS_ENABLED`| Auto-delete request logs | `false` |
| `AUTO_DELETE_REQUEST_LOGS_DAYS` | Request log retention period (days) | `30` |
| `SAFETY_SETTINGS` | Content safety thresholds (JSON string) | `[{"category": "HARM_CATEGORY_HARASSMENT", "threshold": "OFF"}, ...]` |
| **TTS** | | |
| `TTS_MODEL` | TTS model name | `gemini-2.5-flash-preview-tts` |
| `TTS_VOICE_NAME` | TTS voice name | `Zephyr` |
| `TTS_SPEED` | TTS speed | `normal` |
| **Image Generation** | | |
| `PAID_KEY` | Paid API Key for advanced features | `your-paid-api-key` |
| `CREATE_IMAGE_MODEL` | Image generation model | `imagen-3.0-generate-002` |
| `UPLOAD_PROVIDER` | Image upload provider: `smms`, `picgo`, `cloudflare_imgbed`, `aliyun_oss` | `smms` |
| `OSS_ENDPOINT` | Aliyun OSS public endpoint | `oss-cn-shanghai.aliyuncs.com` |
| `OSS_ENDPOINT_INNER` | Aliyun OSS internal endpoint (intra-VPC) | `oss-cn-shanghai-internal.aliyuncs.com` |
| `OSS_ACCESS_KEY` | Aliyun AccessKey ID | `LTAI5txxxxxxxxxxxxxxxx` |
| `OSS_ACCESS_KEY_SECRET` | Aliyun AccessKey Secret | `yXxxxxxxxxxxxxxxxxxxxxx` |
| `OSS_BUCKET_NAME` | Aliyun OSS bucket name | `your-bucket-name` |
| `OSS_REGION` | Aliyun OSS region | `cn-shanghai` |
| `SMMS_SECRET_TOKEN` | SM.MS API Token | `your-smms-token` |
| `PICGO_API_KEY` | PicoGo API Key | `your-picogo-apikey` |
| `PICGO_API_URL` | PicoGo API Server URL | `https://www.picgo.net/api/1/upload` |
| `CLOUDFLARE_IMGBED_URL` | CloudFlare ImgBed upload URL | `https://xxxxxxx.pages.dev/upload` |
| `CLOUDFLARE_IMGBED_AUTH_CODE`| CloudFlare ImgBed auth key | `your-cloudflare-imgber-auth-code` |
| `CLOUDFLARE_IMGBED_UPLOAD_FOLDER`| CloudFlare ImgBed upload folder | `""` |
| **Stream Optimizer** | | |
| `STREAM_OPTIMIZER_ENABLED` | Enable stream output optimization | `false` |
| `STREAM_MIN_DELAY` | Minimum stream output delay | `0.016` |
| `STREAM_MAX_DELAY` | Maximum stream output delay | `0.024` |
| `STREAM_SHORT_TEXT_THRESHOLD`| Short text threshold | `10` |
| `STREAM_LONG_TEXT_THRESHOLD` | Long text threshold | `50` |
| `STREAM_CHUNK_SIZE` | Stream output chunk size | `5` |
| **Fake Stream** | | |
| `FAKE_STREAM_ENABLED` | Enable fake streaming | `false` |
| `FAKE_STREAM_EMPTY_DATA_INTERVAL_SECONDS` | Heartbeat interval for fake streaming (seconds) | `5` |

</details>

---

## 🤝 Contributing

Pull Requests or Issues are welcome.

[![Contributors](https://contrib.rocks/image?repo=snailyp/gemini-balance)](https://github.com/snailyp/gemini-balance/graphs/contributors)

## ⭐ Star History

[![Star History Chart](https://api.star-history.com/svg?repos=snailyp/gemini-balance&type=Date)](https://star-history.com/#snailyp/gemini-balance&Date)

## 🎉 Special Thanks

*   [PicGo](https://www.picgo.net/)
*   [SM.MS](https://smms.app/)
*   [CloudFlare-ImgBed](https://github.com/MarSeventh/CloudFlare-ImgBed)

## 🙏 Our Supporters

A special shout-out to [DigitalOcean](https://m.do.co/c/b249dd7f3b4c) for providing the rock-solid and dependable cloud infrastructure that keeps this project humming!

<a href="https://m.do.co/c/b249dd7f3b4c">
  <img src="files/dataocean.svg" alt="DigitalOcean Logo" width="200"/>
</a>

CDN acceleration and security protection for this project are sponsored by [Tencent EdgeOne](https://edgeone.ai/?from=github).

<a href="https://edgeone.ai/?from=github">
  <img src="https://edgeone.ai/media/34fe3a45-492d-4ea4-ae5d-ea1087ca7b4b.png" alt="EdgeOne Logo" width="200"/>
</a>

## 💖 Friendly Projects

*   **[OneLine](https://github.com/chengtx809/OneLine)** by [chengtx809](https://github.com/chengtx809) - AI-driven hot event timeline generation tool.
>>>>>>> 5f6eba6 (feat: 增加配置页面的picgo 自定义url, 处理自定义picgo的返回结果)

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
