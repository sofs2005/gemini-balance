# Gemini Balance - Gemini API 代理和负载均衡器

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

> ⚠️ **重要声明**: 本项目采用 [CC BY-NC 4.0](LICENSE) 协议，**禁止任何形式的商业倒卖服务**。
> 本人从未在任何平台售卖服务，如遇售卖，均为倒卖行为，请勿上当受骗。

---

## 📖 项目简介

**Gemini Balance** 是一个基于 Python FastAPI 构建的应用程序，旨在提供 Google Gemini API 的代理和负载均衡功能。它允许您管理多个 Gemini API Key，并通过简单的配置实现 Key 的轮询、认证、模型过滤和状态监控。此外，项目还集成了图像生成和多种图床上传功能，并支持 OpenAI API 格式的代理。

这是基于 [snailyp](https://github.com/snailyp) 优秀的 **Gemini Balance** 项目的个人分支版本。原项目提供了全面的 Gemini API 代理和负载均衡功能。

**原项目地址**: [https://github.com/snailyp/gemini-balance](https://github.com/snailyp/gemini-balance)

<details>
<summary>📂 查看项目结构</summary>

```plaintext
app/
├── config/       # 配置管理
├── core/         # 核心应用逻辑 (FastAPI 实例创建, 中间件等)
├── database/     # 数据库模型和连接
├── domain/       # 业务领域对象
├── exception/    # 自定义异常
├── handler/      # 请求处理器
├── log/          # 日志配置
├── main.py       # 应用入口
├── middleware/   # FastAPI 中间件
├── router/       # API 路由 (Gemini, OpenAI, 状态页等)
├── scheduler/    # 定时任务 (如 Key 状态检查)
├── service/      # 业务逻辑服务 (聊天, Key 管理, 统计等)
├── static/       # 静态文件 (CSS, JS)
├── templates/    # HTML 模板 (如 Key 状态页)
└── utils/        # 工具函数
```
</details>

---

## ✨ 功能亮点

*   **多 Key 负载均衡**: 支持配置多个 Gemini API Key，通过智能 ValidKeyPool 轮询和负载均衡。
*   **可视化配置即时生效**: 通过管理后台修改配置后，无需重启服务即可生效。
*   **双协议 API 兼容**: 同时支持 Gemini 和 OpenAI 格式的 CHAT API 请求转发。
    *   OpenAI Base URL: `http://localhost:8000(/hf)/v1`
    *   Gemini Base URL: `http://localhost:8000(/gemini)/v1beta`
*   **图文对话与生成**: 通过 `IMAGE_MODELS` 配置支持图文对话和图像生成功能，调用时使用 `模型名-image` 格式。
*   **联网搜索**: 通过 `SEARCH_MODELS` 配置支持联网搜索的模型，调用时使用 `模型名-search` 格式。
*   **Key 状态监控**: 提供 `/keys_status` 页面（需要认证），实时查看各 Key 的状态和使用情况。
*   **详细日志系统**: 提供全面的错误日志，支持搜索和过滤功能。
*   **灵活的密钥添加**: 支持通过正则表达式 `gemini_key` 批量添加密钥，并自动去重。
*   **智能失败处理**: 自动重试机制 (`MAX_RETRIES`) 和失败次数超过阈值时自动禁用密钥 (`MAX_FAILURES`)。
*   **全面的 API 兼容**:
    *   **Embeddings 接口**: 完美适配 OpenAI 格式的 `embeddings` 接口。
    *   **图像生成接口**: 将 `imagen-3.0-generate-002` 模型接口改造为 OpenAI 图像生成接口格式。
    *   **Files API**: 完整支持文件上传和管理功能。
    *   **Vertex Express**: 支持 Google Vertex AI 平台。
*   **自动模型列表维护**: 自动获取并同步 Gemini 和 OpenAI 的最新模型列表，兼容 New API。
*   **多种图床支持**: 支持 SM.MS、PicGo 和 Cloudflare 图床上传生成的图像。
*   **代理支持**: 支持配置 HTTP/SOCKS5 代理 (`PROXIES`)，方便在特殊网络环境下使用。
*   **Docker 支持**: 提供 AMD 和 ARM 架构的 Docker 镜像，方便快速部署。
    *   镜像地址: `softs2005/gemini-balance:latest`

---

## 🚀 快速开始

### 方式一：使用 Docker Compose (推荐)

这是最推荐的部署方式，可以一键启动应用和数据库。

1.  **下载 `docker-compose.yml`**:
    从项目仓库获取 `docker-compose.yml` 文件。
2.  **准备 `.env` 文件**:
    从 `.env.example` 复制一份并重命名为 `.env`，然后根据需求修改配置。特别注意，`DATABASE_TYPE` 应设置为 `mysql`，并填写 `MYSQL_*` 相关配置。
3.  **启动服务**:
    在 `docker-compose.yml` 和 `.env` 文件所在的目录下，运行以下命令：
    ```bash
    docker-compose up -d
    ```
    该命令会以后台模式启动 `gemini-balance` 应用和 `mysql` 数据库。

### 方式二：使用 Docker 命令

1.  **拉取镜像**:
    ```bash
    docker pull softs2005/gemini-balance:latest
    ```
2.  **准备 `.env` 文件**:
    从 `.env.example` 复制一份并重命名为 `.env`，然后根据需求修改配置。
3.  **运行容器**:
    ```bash
    docker run -d -p 8000:8000 --name gemini-balance \
    -v ./data:/app/data \
    --env-file .env \
    softs2005/gemini-balance:latest
    ```
    *   `-d`: 后台运行。
    *   `-p 8000:8000`: 将容器的 8000 端口映射到主机。
    *   `-v ./data:/app/data`: 挂载数据卷以持久化 SQLite 数据和日志。
    *   `--env-file .env`: 加载环境变量配置文件。

### 方式三：本地运行 (适用于开发)

1.  **克隆仓库并安装依赖**:
    ```bash
    git clone https://github.com/sofs2005/gemini-balance.git
    cd gemini-balance
    pip install -r requirements.txt
    ```
2.  **配置环境变量**:
    从 `.env.example` 复制一份并重命名为 `.env`，然后根据需求修改配置。
3.  **启动应用**:
    ```bash
    uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
    ```
    应用启动后，访问 `http://localhost:8000`。

---

## ⚙️ API 端点

### Gemini API 格式 (`/gemini/v1beta`)

*   `GET /models`: 列出可用的 Gemini 模型。
*   `POST /models/{model_name}:generateContent`: 生成内容。
*   `POST /models/{model_name}:streamGenerateContent`: 流式生成内容。
*   `GET /files`: 列出已上传的文件。
*   `POST /files`: 上传文件。

### OpenAI API 格式

#### 兼容 HuggingFace (HF) 格式

*   `GET /hf/v1/models`: 列出模型。
*   `POST /hf/v1/chat/completions`: 聊天补全。
*   `POST /hf/v1/embeddings`: 创建文本嵌入。
*   `POST /hf/v1/images/generations`: 生成图像。

#### 标准 OpenAI 格式

*   `GET /openai/v1/models`: 列出模型。
*   `POST /openai/v1/chat/completions`: 聊天补全 (推荐，速度更快，防截断)。
*   `POST /openai/v1/embeddings`: 创建文本嵌入。
*   `POST /openai/v1/images/generations`: 生成图像。

### Web 界面

- **主界面**: `http://localhost:8000`
- **密钥管理**: `http://localhost:8000/keys_status`
- **配置管理**: `http://localhost:8000/config`
- **错误日志**: `http://localhost:8000/error_logs`



## 🎁 项目支持

如果你觉得这个项目对你有帮助，可以考虑通过以下方式支持我：

### 💰 赞助方式

- **微信赞赏** - 扫描下方二维码
- **支付宝** - 扫描下方二维码

<div align="center">
  <table>
    <tr>
      <td align="center">
        <img src="https://raw.githubusercontent.com/sofs2005/difytask/refs/heads/main/img/wx.png" alt="微信赞赏码" width="200"/>
        <br/>
        <strong>微信赞赏</strong>
      </td>
      <td align="center">
        <img src="https://raw.githubusercontent.com/sofs2005/difytask/refs/heads/main/img/zfb.jpg" alt="支付宝收款码" width="200"/>
        <br/>
        <strong>支付宝</strong>
      </td>
    </tr>
  </table>
</div>

> 💡 你的支持是我持续维护和改进这个项目的动力！

## 📄 许可证

本项目采用 [CC BY-NC 4.0](LICENSE)（署名-非商业性使用）协议。






