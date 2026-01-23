# DeepAgents Web 应用
 
 这是一个基于 `deepagents` 的精简版 Web 应用：
 - 后端用 FastAPI 提供聊天、文件管理、RAG 检索、播客生成等接口
 - 前端用 Vite + Preact 提供简单的交互界面
 - 数据存储主要依赖 MongoDB（聊天记录、上传文件、播客任务/结果等）
 
 ## 你能用它做什么
 - 聊天对话（支持流式输出）
 - 上传/管理文件（存 MongoDB）
 - 基于本地文件或 MongoDB 文档的 RAG 检索（会注入 `<rag_context>`）
 - 生成播客（podcast-creator + TTS，可选 Edge TTS）
 
 ## 项目结构（以当前仓库为准）
 
 ```text
 deepagents-webapp/
 ├── backend/
 │   ├── api/
 │   │   ├── web_app.py                 # FastAPI 应用入口（uvicorn 启动的 app）
 │   │   └── routers/                   # 各业务路由：chat、sources、podcast、filesystem 等
 │   ├── config/
 │   │   └── deepagents_settings.py     # 运行时配置（从环境变量读取）+ create_model()
 │   ├── database/
 │   │   └── mongo_manager.py           # MongoDB 访问封装 + 分布式锁
 │   ├── middleware/
 │   │   ├── rag_middleware.py          # RAG 中间件（LlamaIndex）
 │   │   └── podcast_middleware.py      # 播客生成任务
 │   ├── prompts/
 │   │   ├── chat_prompts.py            # 聊天相关 prompt 统一管理
 │   │   └── memory_summary_prompts.py  # memory 总结 prompt
 │   ├── services/                      # 业务服务层（chat、source、opensandbox 等）
 │   ├── utils/                         # 工具函数（snowflake、tools 等）
 │   └── main.py                        #（如存在）后端模块入口/调试入口
 ├── frontend/
 │   ├── src/
 │   └── package.json
 ├── skills/                            # deepagents skills（会同步到 sandbox 的 /workspace/skills/skills）
 ├── doc/                               # 工作记录等文档
 ├── .env                               # 本地环境变量（启动时会被加载）
 ├── requirements.txt                   # Python 依赖
 ├── start_web_stack.sh                 # 一键启动/停止/看日志
 └── uvicorn_log_config.yaml            # uvicorn 日志配置
 ```
 
 ## 环境要求
 - Python 3.11+
 - Node.js 18+
 - MongoDB 5.0+
 - 建议使用 conda 环境：`deepagent`
 
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
 
 示例：
 ```bash
 # MongoDB
 MONGODB_URI=mongodb://127.0.0.1:27017
 DEEPAGENTS_MONGO_DB=deepagents_web
 
 # LLM（OpenAI 兼容接口）
 OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
 OPENAI_API_KEY=你的key
 OPENAI_MODEL=qwen-turbo
 OPENAI_TEMPERATURE=0.7
 ```
 
 ### 可选（用到对应能力再配）
 - `TAVILY_API_KEY`：开启联网搜索工具
 
 ### RAG 相关（可选）
 - `RAG_ENABLED`：是否启用（默认按代码逻辑）
 - `RAG_TOP_K`：召回条数
 - `RAG_PROVIDER`：embedding 提供商（dashscope/openai/huggingface 等，按你代码支持为准）
 
 ### 播客相关（可选）
 - `DEEPAGENTS_PODCAST_RUNS_COLLECTION`
 - `DEEPAGENTS_PODCAST_RESULTS_COLLECTION`
 - `DEEPAGENTS_PODCAST_SPEAKER_PROFILES_COLLECTION`
 - `DEEPAGENTS_PODCAST_EPISODE_PROFILES_COLLECTION`
 - `DEEPAGENTS_LOCKS_COLLECTION`
 - `PODCAST_TTS_PROVIDER`：比如 `edge`/`openai-compatible`
 - `PODCAST_TTS_MODEL`

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
 
 默认端口：
 - 后端：`http://127.0.0.1:7777`
 - 前端：`http://127.0.0.1:5173`
 
 日志位置：
 - `.runtime/logs/backend.log`
 - `.runtime/logs/frontend.log`
 
 ## 接口大概有哪些（给你快速对照）
 
 你可以从 `backend/api/routers/` 里看全量，这里只列常用的：
 - **聊天**：`/api/chat/stream`
 - **聊天记忆统计**：`GET /api/chat/memory/stats`
 - **聊天记忆总结**：`POST /api/chat/memory/summary`
 - **文件/素材**：`/api/sources/*`
 - **播客**：`/api/podcast/*`
 
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