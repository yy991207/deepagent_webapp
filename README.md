# DeepAgents Web 应用
 
 这是一个基于 `deepagents` 的精简版 Web 应用：
- 后端用 FastAPI 提供聊天、文件管理、RAG 检索、播客生成等接口
- 前端用 Vite + React + Tailwind CSS 提供交互界面
- 数据存储主要依赖 MongoDB（聊天记录、上传文件、播客任务/结果等）

## 技术栈概览

### 后端
- FastAPI + Uvicorn（Web API）
- LangChain + LangGraph（对话编排与工具调用）
- LlamaIndex（RAG 检索与向量索引）
- MongoDB（聊天记录、素材、播客任务与结果）
- Celery + Redis（播客生成异步任务）
- OpenSandbox（远程沙箱执行）
- MCP（可选，加载外部工具）

### 前端
- React 18 + Vite 5
- Tailwind CSS 4 + tailwind-merge
- Radix UI + lucide-react

## 主要语言
- 后端语言：Python 3.11
- 前端语言：TypeScript（React + Vite）
 
 ## 你能用它做什么
 - 聊天对话（支持流式输出）
 - 上传/管理文件（存 MongoDB）
 - 基于本地文件或 MongoDB 文档的 RAG 检索（会注入 `<rag_context>`）
 - 生成播客（podcast-creator + TTS，可选 Edge TTS）
 - **远程沙箱执行**：通过 OpenSandbox 在隔离环境中执行代码、操作文件系统

### OpenSandbox 远程沙箱
- **服务来源**：[OpenSandbox](https://github.com/alibaba/OpenSandbox.git)（阿里巴巴开源的远程沙箱服务）
- **工作目录**：`/workspace`（沙箱内的统一工作空间）
- **默认镜像**：`sandbox-registry.cn-zhangjiakou.cr.aliyuncs.com/opensandbox/code-interpreter:latest`
- **环境变量**：
  - `OPENSANDBOX_DOMAIN`/`SANDBOX_DOMAIN`：沙箱服务地址（默认 `localhost:8080`）
  - `OPENSANDBOX_API_KEY`/`SANDBOX_API_KEY`：API 密钥
  - `OPENSANDBOX_IMAGE`/`SANDBOX_IMAGE`：自定义 Docker 镜像
  - `OPENSANDBOX_REQUEST_TIMEOUT_SECONDS`/`SANDBOX_REQUEST_TIMEOUT_SECONDS`：请求超时（默认 10 秒）

 
 ## 项目结构（以当前仓库为准）
 
 ```text
 deepagents-webapp/
 ├── backend/
 │   ├── api/
 │   │   ├── web_app.py                 # FastAPI 应用入口（uvicorn 启动的 app）
 │   │   └── routers/
 │   │       ├── chat_router.py         # 聊天相关路由
 │   │       ├── sources_router.py      # 文件/素材管理路由
 │   │       ├── podcast_router.py      # 播客生成路由
 │   │       ├── agent_router.py        # Agent API 路由（任务提交/状态/回调）
 │   │       └── filesystem_router.py   # 文件系统操作路由
 │   ├── celery_scheduler/              # Celery 任务调度模块
 │   │   ├── __init__.py                # Celery app 导出
 │   │   ├── celery_app.py              # Celery 应用配置
 │   │   ├── config.py                  # Celery 配置（broker、backend 等）
 │   │   ├── registry/                  # Agent 注册表（管理可用 Agent）
 │   │   ├── storage/                   # 任务存储（MongoDB 持久化）
 │   │   └── tasks/                     # Celery 任务定义
 │   ├── config/
 │   │   └── deepagents_settings.py     # 运行时配置（从环境变量读取）+ create_model()
 │   ├── database/
 │   │   └── mongo_manager.py           # MongoDB 访问封装 + 分布式锁
 │   ├── middleware/
 │   │   ├── rag_middleware.py          # RAG 中间件（LlamaIndex）
 │   │   └── podcast_middleware.py      # 播客生成中间件
 │   ├── prompts/
 │   │   ├── chat_prompts.py            # 聊天相关 prompt 统一管理
 │   │   └── memory_summary_prompts.py  # memory 总结 prompt
 │   ├── services/
 │   │   ├── chat_service.py            # 聊天业务逻辑
 │   │   ├── source_service.py          # 文件/素材业务逻辑
 │   │   ├── opensandbox_service.py     # OpenSandbox 远程沙箱服务
 │   │   └── podcast_agent_service.py   # 播客 Agent 独立服务（FastAPI，端口 8888）
 │   ├── utils/                         # 工具函数（snowflake、tools 等）
 │   └── main.py                        #（如存在）后端模块入口/调试入口
 ├── frontend/
 │   ├── src/
 │   │   └── ui/
 │   │       ├── App.tsx                # 主应用组件
 │   │       └── types/                 # TypeScript 类型定义
 │   └── package.json
 ├── skills/                            # deepagents skills（会同步到 sandbox 的 /workspace/skills/skills）
 ├── scripts/                           # 辅助脚本（测试、调试等）
 ├── plans/                             # 设计文档和实现计划
 ├── doc/                               # 工作记录等文档
 ├── .env                               # 本地环境变量（启动时会被加载）
 ├── .runtime/                          # 运行时目录（自动生成）
 │   ├── pids/                          # 各服务 PID 文件
 │   └── logs/                          # 各服务日志文件
 ├── requirements.txt                   # Python 依赖
 ├── start_web_stack.sh                 # 一键启动/停止/看日志（支持单服务管理）
 └── uvicorn_log_config.yaml            # uvicorn 日志配置
 ```
 
## 环境要求
 - Python 3.11+
 - Node.js 18+
 - MongoDB 5.0+
 - Redis 6.0+（Celery 消息队列需要）
 - 建议使用 conda 环境：`deepagent`

## Docker 部署
1. 准备好根目录的 `.env`，至少包含 `OPENAI_API_KEY`、`OPENAI_BASE_URL`、`OPENAI_MODEL`。
2. 在项目根目录执行：`docker compose up -d --build`。
3. 前端访问地址：`http://localhost:8081`（8080 已留给 OpenSandbox）。
4. 后端 API 地址：`http://localhost:7777`。
5. 如果不需要播客相关能力，可以在 `docker-compose.yml` 里注释 `worker`、`beat`、`podcast-agent` 三个服务。

### Docker 端口映射
- 前端：`8081 -> 80`
- 后端：`7777 -> 7777`
- MongoDB：`27018 -> 27017`
- Redis：`6380 -> 6379`
- Podcast Agent：`8888 -> 8888`

### Docker 内置存储说明
- `docker-compose.yml` 内部强制使用容器内的 `mongo:27017`（不走 `.env` 的 `MONGODB_URI`）。
- 如果你想接外部 MongoDB/Redis，需要手动修改 `docker-compose.yml` 的对应环境变量。

### Docker + OpenSandbox（必读）
当前后端在容器内访问 OpenSandbox，默认指向宿主机 `host.docker.internal:8080`，并跳过健康检查：
- `OPENSANDBOX_DOMAIN` / `SANDBOX_DOMAIN`：`host.docker.internal:8080`
- `SANDBOX_SKIP_HEALTH_CHECK=1`

如果你用本机 OpenSandbox server，需要满足两点：
1. OpenSandbox server 监听地址必须是 `0.0.0.0`，确保容器能访问到服务端口。
2. OpenSandbox server 需要返回 **容器可访问的 execd 端点**，已通过 `router.domain` 实现。示例（在 `~/.sandbox.toml`）：  
   ```toml
   [router]
   domain = "host.docker.internal"
   ```
   说明：此项依赖 OpenSandbox server 对 `router.domain` 的支持，我们已在本机 OpenSandbox server 做过补丁。

### Docker + RAG Embedding 配置
为了避免 DashScope 兼容接口缺失 `text-embedding-3-small` 导致索引构建失败，Docker 默认强制：
- `RAG_EMBEDDING_PROVIDER=dashscope`
- `RAG_DASHSCOPE_EMBEDDING_MODEL=text-embedding-v2`
请确保 `.env` 中有 `DASHSCOPE_API_KEY` 或 `OPENAI_API_KEY` 可用于 embedding 调用。
 
 ## 安装依赖
 
 ### 1) 后端依赖
 ```bash
 conda activate deepagent
 pip install -r requirements.txt
 ```
 
 ### 2) 前端依赖
 ```bash
 cd frontend
 npm install
 ```
 
 ## 配置环境变量（.env）
 
 后端启动时会在 `backend/api/web_app.py` 里执行 `load_dotenv()`，所以把配置写到项目根目录的 `.env` 即可。
 
 ### 必配（跑起来必须要的）
- `MONGODB_URI`
- `DEEPAGENTS_MONGO_DB`
- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`（如果你走 OpenAI 兼容接口，比如通义千问兼容模式）
- `OPENAI_MODEL`

### MongoDB（可选补充）
- `DEEPAGENTS_MONGO_URL`：Celery/播客链路读取 MongoDB 的兜底配置（默认走 `MONGODB_URI`）
 
 示例：
 ```bash
 # MongoDB
 MONGODB_URI=mongodb://127.0.0.1:27017
 DEEPAGENTS_MONGO_DB=deepagents_web
 DEEPAGENTS_MONGO_URL=mongodb://127.0.0.1:27017/deepagents_web
 
 # LLM（OpenAI 兼容接口）
OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
OPENAI_API_BASE=https://api.openai.com/v1
OPENAI_API_KEY=你的key
OPENAI_MODEL=qwen-turbo
OPENAI_TEMPERATURE=0.7
 ```
 
 ### 可选（用到对应能力再配）
 - `TAVILY_API_KEY`：开启联网搜索工具
 
### RAG 相关（可选）
- `RAG_EMBEDDING_PROVIDER`：embedding 提供商（`dashscope`/`openai`/`hf`）
- `RAG_DASHSCOPE_EMBEDDING_MODEL`：DashScope embedding 模型（默认 `text-embedding-v2`）
- `RAG_HF_EMBEDDING_MODEL`：HuggingFace embedding 模型（默认 `BAAI/bge-small-zh-v1.5`）
- `OPENAI_EMBEDDING_MODEL`：OpenAI embedding 模型（默认 `text-embedding-3-small`）

#### RAG 使用注意
- 只有在消息里“附带来源”时才会强制 RAG，否则可能直接 `no hits`。
- 当前默认只索引这些类型：`.md .txt .py .rst .json .yaml .yml`。
- 如果用 DashScope 兼容接口，请优先设 `RAG_EMBEDDING_PROVIDER=dashscope`，并确保 `DASHSCOPE_API_KEY` 可用。
 
 ### 播客相关（可选）
 - `DEEPAGENTS_DATA_DIR`：数据目录（播客音频存放位置）
 - `DEEPAGENTS_PODCAST_RUNS_COLLECTION`
 - `DEEPAGENTS_PODCAST_RESULTS_COLLECTION`
 - `DEEPAGENTS_PODCAST_SPEAKER_PROFILES_COLLECTION`
 - `DEEPAGENTS_PODCAST_EPISODE_PROFILES_COLLECTION`
 - `DEEPAGENTS_LOCKS_COLLECTION`
 - `PODCAST_LLM_PROVIDER`：LLM 提供商（`openai`/`openai-compatible`）
 - `PODCAST_LLM_MODEL`：LLM 模型名
 - `PODCAST_OUTLINE_PROVIDER`/`PODCAST_OUTLINE_MODEL`：大纲生成配置
 - `PODCAST_TRANSCRIPT_PROVIDER`/`PODCAST_TRANSCRIPT_MODEL`：对话生成配置
 - `PODCAST_TTS_PROVIDER`：TTS 提供商（`edge`/`dashscope`/`qwen3-tts`）
 - `PODCAST_TTS_MODEL`：TTS 模型（dashscope 时为 `qwen3-tts-flash-realtime`）
 - `OPENAI_COMPATIBLE_BASE_URL`：OpenAI 兼容接口地址（播客 LLM 使用）
 - `OPENAI_COMPATIBLE_API_KEY`：OpenAI 兼容接口密钥

 ### 模型分流（可选）
 - `ROUTER_LLM_ENABLED`：是否启用分流（`1/true/yes/on`）
 - `ROUTER_LLM_MODEL`：分流模型名（默认 `qwen-flash`）
 - `ROUTER_LLM_FLASH_MODEL`：主模型 flash 档
 - `ROUTER_LLM_PLUS_MODEL`：主模型 plus 档
 - `ROUTER_LLM_MAX_MODEL`：主模型 max 档
 - `ROUTER_LLM_TEMPERATURE`：分流温度（默认 0.1）
 - `ROUTER_LLM_PROMPT`：分流提示词（可用 `\n` 代表换行）

 ### 聊天记忆压缩（可选）
 - `DEEPAGENTS_CHAT_MEMORY_MAX_CHARS`：触发总结的字数阈值（默认 5000）
 - `DEEPAGENTS_CHAT_MEMORY_SUMMARY_MAX_CHARS`：总结输出最大字数（默认 500）
 - `DEEPAGENTS_CHAT_MEMORY_SUMMARY_LOCK_TTL_SECONDS`：总结锁 TTL（默认 120 秒）

#### Edge TTS 音色配置（PODCAST_TTS_PROVIDER=edge 时）
- `PODCAST_EDGE_TTS_VOICE_DEFAULT`：默认音色（默认 `zh-CN-XiaoxiaoNeural`）
- `PODCAST_EDGE_TTS_VOICE_ALT`：备选音色（默认 `zh-CN-YunyangNeural`）

#### Qwen3-TTS 音色配置（PODCAST_TTS_PROVIDER=dashscope 时）
- `PODCAST_QWEN3_TTS_VOICE_DEFAULT`：默认音色（默认 `Cherry`，女声）
- `PODCAST_QWEN3_TTS_VOICE_ALT`：备选音色（默认 `Ethan`，男声）
- 需要配置 `DASHSCOPE_API_KEY`（可复用 RAG embedding 的配置）
- 更多音色参考：[Qwen3-TTS 文档](https://help.aliyun.com/zh/model-studio/qwen-tts)

### MCP（可选）
- `DEEPAGENTS_MCP_ENABLED`：是否启用 MCP（默认启用，设为 `0/false/no/off` 禁用）

#### MCP 配置文件
- **位置**：`.deepagents/mcp.json`
- **格式**：
  ```json
  {
    "mcpServers": {
      "server_name": {
        "transport": "stdio|sse|websocket|http",
        "command": "...",
        "args": ["..."]
      }
    }
  }
- **示例（filesystem）**：
  ```json
  {
    "mcpServers": {
      "filesystem": {
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "."]
      }
    }
  }
- **依赖**：需安装 `langchain-mcp-adapters`（已在 requirements.txt 中声明）
- **验证**：启动服务后发起聊天，观察后端日志是否出现 `MCP tools loaded | tools_count=...`
 
 ## 启动与停止

 统一使用根目录脚本：
 ```bash
 bash start_web_stack.sh start
 bash start_web_stack.sh status
 bash start_web_stack.sh logs
 bash start_web_stack.sh stop
 ```

### 服务架构

系统包含以下服务组件：

| 服务 | 端口 | 说明 |
|------|------|------|
| 后端 (backend) | 7777 | FastAPI 主服务 |
| 前端 (frontend) | 5173 | Vite + React 开发服务器 |
| Celery Worker | - | 任务队列工作进程 |
| Celery Beat | - | 定时任务调度器 |
| Podcast Agent | 8888 | 播客生成执行服务 |

### 服务管理命令

```bash
# 启动全部服务
./start_web_stack.sh start

# 启动单个服务
./start_web_stack.sh start backend
./start_web_stack.sh start frontend
./start_web_stack.sh start celery          # Worker + Beat
./start_web_stack.sh start celery-worker   # 仅 Worker
./start_web_stack.sh start celery-beat     # 仅 Beat
./start_web_stack.sh start podcast-agent   # 播客生成服务

# 停止服务（同上，把 start 换成 stop）
./start_web_stack.sh stop
./start_web_stack.sh stop celery

# 重启服务（同上，把 start 换成 restart）
./start_web_stack.sh restart podcast-agent

# 查看服务状态
./start_web_stack.sh status

# 查看日志（交互式菜单）
./start_web_stack.sh logs

# 查看全部日志（合并）
./start_web_stack.sh logs-all
```

### 播客生成架构（投递 + Callback 模式）

```
API → Celery Worker（快速投递）→ Podcast Agent（异步执行）→ Callback
```

- **Celery Worker**：接收播客生成请求，快速投递到 Podcast Agent
- **Podcast Agent**：独立进程执行播客生成（LLM 大纲 + TTS 语音合成）
- **Callback**：生成完成后回调通知 API 更新状态

### Celery/Redis 环境变量

```bash
# Redis 配置
REDIS_HOST=localhost             # Redis 地址（默认 localhost）
REDIS_PORT=6379                  # Redis 端口（默认 6379）
REDIS_PASSWORD=                  # Redis 密码（可选）
CELERY_BROKER_DB=0               # Broker 使用的 Redis DB（默认 0）
CELERY_BACKEND_DB=1              # Backend 使用的 Redis DB（默认 1）

# 或直接配置完整 URL
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1

# Worker 配置
CELERY_WORKER_CONCURRENCY=4      # Worker 并发数（默认 4）
CELERY_WORKER_PREFETCH_MULTIPLIER=1 # Worker 预取数（默认 1）
CELERY_TASK_TIME_LIMIT=1800      # 任务硬超时秒数（默认 30 分钟）
CELERY_TASK_SOFT_TIME_LIMIT=1500 # 任务软超时秒数（默认 25 分钟）
CELERY_RESULT_EXPIRES=3600       # 结果过期时间（默认 1 小时）
CELERY_TIMEZONE=Asia/Shanghai    # 时区（默认 Asia/Shanghai）

# Podcast Agent 配置
PODCAST_AGENT_HOST=0.0.0.0       # 服务地址（默认 0.0.0.0）
PODCAST_AGENT_PORT=8888          # 服务端口（默认 8888）
```

 默认端口：
 - 后端：`http://127.0.0.1:7777`
 - 前端：`http://127.0.0.1:5173`
 - Podcast Agent：`http://127.0.0.1:8888`

 日志位置：
 - `.runtime/logs/backend.log`
 - `.runtime/logs/frontend.log`
 - `.runtime/logs/celery_worker.log`
 - `.runtime/logs/celery_beat.log`
 - `.runtime/logs/podcast_agent.log`
 
 ## 接口大概有哪些（给你快速对照）

 你可以从 `backend/api/routers/` 里看全量，这里只列常用的：
 - **聊天**：`/api/chat/stream`
 - **聊天记忆统计**：`GET /api/chat/memory/stats`
 - **聊天记忆总结**：`POST /api/chat/memory/summary`
 - **文件/素材**：`/api/sources/*`
 - **播客**：`/api/podcast/*`
 - **Agent API**（任务调度）：
   - `POST /api/agent/run`：提交任务（通过 Celery 投递到 Agent）
   - `GET /api/agent/task/{task_id}/poll`：轮询任务状态
   - `POST /api/agent/callback`：Agent 执行完成后的回调接口
 
 ## 常见问题
 
 ### 1) uvicorn 日志出现 `KeyError: 'client_addr'`
 现象一般是 `uvicorn_log_config.yaml` 里 formatter 用了 `%(client_addr)s`，但某些日志记录不带这个字段。
 
 处理方式（选一种就行）：
 - 方案 A：改 log config，把 formatter 里 `client_addr` 相关字段去掉
 - 方案 B：给 uvicorn access logger 单独配 formatter，不要复用同一个 formatter
 
 ### 2) 生成 PDF 中文变成方块
 这个是 reportlab 默认字体不支持中文导致的。
 你已经在 `backend/prompts/chat_prompts.py` 里补了“PDF 中文支持”说明，按提示注册 CID 字体或下载中文字体即可。
 
 ## 备注
 - 项目里会使用 `.deepagents/` 存放一些运行时数据（比如 RAG 的索引文件）。
 - 播客生成的音频文件会落到 `data/` 目录（具体以 `DEEPAGENTS_DATA_DIR` 或代码逻辑为准）。
