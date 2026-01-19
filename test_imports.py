#!/usr/bin/env python3
"""测试导入是否正常"""

print("测试导入...")

try:
    print("1. 测试 deepagents 核心库...")
    from deepagents import create_deep_agent
    print("   SUCCESS deepagents 核心库导入成功")
except ImportError as e:
    print(f"   FAIL deepagents 核心库导入失败: {e}")

try:
    print("2. 测试 deepagents-cli...")
    from deepagents_cli.agent import create_cli_agent
    from deepagents_cli.config import create_model, settings
    print("   SUCCESS deepagents-cli 导入成功")
except ImportError as e:
    print(f"   FAIL deepagents-cli 导入失败: {e}")

try:
    print("3. 测试本地 backend 模块...")
    from backend.database.mongo_manager import get_mongo_manager
    from backend.middleware.podcast_middleware import build_podcast_middleware
    from backend.middleware.rag_middleware import LlamaIndexRagMiddleware
    print("   SUCCESS backend 模块导入成功")
except ImportError as e:
    print(f"   FAIL backend 模块导入失败: {e}")

try:
    print("4. 测试 FastAPI...")
    from backend.main import app
    print("   SUCCESS main 导入成功")

    from backend.web_app import app as legacy_app
    _ = legacy_app
    print("   SUCCESS web_app 兼容层导入成功")
except ImportError as e:
    print(f"   FAIL web_app 导入失败: {e}")

print("\n所有导入测试完成！")
