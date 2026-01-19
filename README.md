# DeepAgents Web 应用（精简版）

基于 DeepAgents 框架的 Web 应用，通过 pip 安装核心库，只保留 Web 应用相关的自定义代码。

## 项目结构

```
deepagents-webapp/
├── backend/                    # 后端代码（自定义部分）
│   ├── web_app.py             # Web 应用主入口
│   ├── mongo_manager.py       # MongoDB 管理
│   ├── podcast_middleware.py  # 播客生成
│   ├── rag_middleware.py      # RAG 检索
│   ├── logging_config.py      # 日志配置
│   └── tools.py               # 自定义工具
├── frontend/                   # 前端代码
│   ├── src/ui/
│   │   ├── App.tsx
│   │   └── styles.css
│   ├── index.html
│   ├── package.json
│   └── vite.config.ts
├── .env                        # 环境变量
├── requirements.txt            # Python 依赖
├── start_web_stack.sh          # 启动脚本
├── uvicorn_log_config.yaml     # 日志配置
└── README.md
```

## 快速开始

### 1. 环境要求

- Python 3.11+
- Node.js 18+
- MongoDB 5.0+
- Conda 环境：deepagent

### 2. 安装依赖

```bash
# 激活 conda 环境
conda activate deepagent

# 安装 Python 依赖
pip install -r requirements.txt

# 安装前端依赖
cd frontend
npm install
cd ..
```

### 3. 配置环境变量

编辑 `.env` 文件：

```bash
# 阿里云通义千问 API 配置
OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
OPENAI_API_KEY=your-api-key
OPENAI_MODEL=qwen-turbo

# Tavily API 配置
TAVILY_API_KEY=your-tavily-key

# MongoDB 配置
MONGODB_URI=mongodb://127.0.0.1:27017
DEEPAGENTS_MONGO_DB=deepagents_web
```

### 4. 启动服务

```bash
# 启动服务
bash start_web_stack.sh start

# 查看日志
bash start_web_stack.sh logs

# 停止服务
bash start_web_stack.sh stop
```

### 5. 访问应用

打开浏览器访问：http://localhost:5173

## 技术栈

### 后端
- **核心框架**：DeepAgents（通过 pip 安装）
- **Web 框架**：FastAPI + Uvicorn
- **AI 框架**：LangChain + LangGraph
- **LLM**：阿里云通义千问（qwen-turbo）
- **数据库**：MongoDB
- **向量检索**：LlamaIndex + DashScope Embeddings

### 前端
- **框架**：Preact
- **构建工具**：Vite
- **语言**：TypeScript

## 与原项目的区别

### 原项目（deepagents）
- 包含完整的 deepagents 核心库源码
- 包含 CLI 工具源码
- 代码量：~100MB

### 精简项目（deepagents-webapp）
- 通过 pip 安装 deepagents 核心库
- 只保留 Web 应用相关的自定义代码
- 代码量：~10MB（减少 90%）

## 许可证

本项目基于 [langchain-ai/deepagents](https://github.com/langchain-ai/deepagents) 开发，遵循 MIT 许可证。
