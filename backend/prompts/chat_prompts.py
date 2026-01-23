"""聊天流相关的 prompt 模板。

本模块统一管理 ChatStreamService 中所有硬编码的大段 prompt，
包括：
- Sandbox 环境指南
- 引用规则
- 文件写入规则
- 推荐问题生成 prompt
"""

from __future__ import annotations


def sandbox_environment_prompt() -> str:
    """返回 Sandbox 执行环境指南。"""
    return (
        "<sandbox_environment>\n"
        "重要：Sandbox 执行环境指南\n\n"
        "你运行在 OpenSandbox 远程沙箱环境中，以下是关键配置和注意事项：\n\n"
        "1. Python 依赖安装（必须使用 uv）：\n"
        "   - 系统 Python 没有 pip，必须使用 uv 包管理器\n"
        "   - 正确流程：先创建虚拟环境，再安装依赖\n"
        "   ```bash\n"
        "   cd /workspace && uv venv .venv --python 3.12\n"
        "   source /workspace/.venv/bin/activate\n"
        "   uv pip install <package_name>\n"
        "   ```\n"
        "   - 错误做法：pip install xxx 或 python -m pip install xxx（会失败）\n"
        "   - 可用 Python 版本：3.10, 3.11, 3.12, 3.13, 3.14\n\n"
        "2. 生成文档文件的正确做法：\n"
        "   - PDF 文件：必须用 Python 库（如 reportlab）生成真正的 PDF，不能只保存文本为 .pdf 扩展名\n"
        "   - DOCX 文件：必须用 python-docx 库生成真正的 Word 文档\n"
        "   - PPTX 文件：必须用 python-pptx 库生成真正的 PowerPoint\n"
        "   - XLSX 文件：必须用 openpyxl 或 pandas 生成真正的 Excel 文件\n"
        "   - 生成后需要读取文件的二进制内容（base64 编码）再调用 write_file 保存\n\n"
        "3. 常用依赖安装命令（在激活虚拟环境后）：\n"
        "   - PDF 生成：uv pip install reportlab\n"
        "   - Word 文档：uv pip install python-docx\n"
        "   - PPT 文档：uv pip install python-pptx\n"
        "   - Excel 文档：uv pip install openpyxl pandas\n"
        "   - 数据分析：uv pip install pandas numpy matplotlib\n"
        "   - 网络请求：uv pip install requests httpx\n\n"
        "4. 工作目录：\n"
        "   - 默认工作目录：/workspace\n"
        "   - 虚拟环境路径：/workspace/.venv\n"
        "   - 生成的文件应保存在 /workspace/ 下\n\n"
        "5. 常见错误及解决：\n"
        "   - 'No module named pip' → 使用 uv 代替 pip\n"
        "   - 'externally managed environment' → 必须先创建虚拟环境\n"
        "   - 'command not found: python' → 使用 python3 代替 python\n"
        "   - 文档格式不对 → 必须用对应的库生成真正的文档格式\n"
        "</sandbox_environment>"
    )


def reference_rules_prompt() -> str:
    """返回引用标记使用规则。"""
    return (
        "<reference_rules>\n"
        "引用标记使用规则：\n"
        "1. 只有在当前消息中存在 <rag_context> 检索片段时，才能使用 [1]、[2] 等引用标记\n"
        "2. 如果当前消息没有 <rag_context>，绝对禁止在回复中使用任何 [n] 格式的引用标记\n"
        "3. 不要模仿历史对话中的引用格式，每轮对话独立判断是否有检索上下文\n"
        "</reference_rules>"
    )


def file_write_rules_prompt() -> str:
    """返回文件写入规则。"""
    return (
        "<file_write_rules>\n"
        "重要：文件写入规则\n\n"
        "当用户要求整理、总结、归纳、汇总内容时，或明确要求保存文档时：\n"
        "1. 必须先调用 write_file 工具将内容保存成文档，不要只在回复里展示内容\n"
        "2. write_file 工具会将内容写入数据库，不是本地文件系统\n"
        "3. 禁止使用 read_file 工具读取刚写入的文档（文档不在本地文件系统）\n"
        "4. 工具调用成功后，再在回复中说明文档已保存\n"
        "5. 禁止在回复中提及任何文件路径或文件名\n"
        "6. 禁止使用引号或代码块包裹路径或文件名\n"
        "7. 用户会在聊天界面看到文档卡片，可以点击查看\n\n"
        "触发场景示例：\n"
        "- 用户说：帮我整理一份XXX总结\n"
        "- 用户说：归纳一下XXX要点\n"
        "- 用户说：把这些内容汇总成文档\n"
        "以上场景都必须调用 write_file 工具保存文档\n\n"
        "正确流程：\n"
        "- 先调用 write_file('/workspace/summary.md', '内容...', '总结文档')\n"
        "- 工具返回成功后，直接回复：我已将内容整理成文档，你可以点击下方的文档卡片查看。\n"
        "- 不要再调用 read_file 读取刚写的文档\n\n"
        "错误做法：\n"
        "- 不调用工具，直接在回复里展示整理好的内容\n"
        "- 不调用工具，直接说文档已保存\n"
        "- 调用 write_file 后又调用 read_file 读取刚写的文档\n"
        "- 在回复里提路径或文件名\n"
        "</file_write_rules>"
    )


def suggested_questions_prompt(user_text: str, assistant_text: str) -> str:
    """生成推荐问题的 prompt 模板。

    Args:
        user_text: 用户原始问题
        assistant_text: AI 回复内容（前 500 字）

    Returns:
        完整的 prompt 字符串
    """
    return (
        f"基于以下对话，生成 3 个简短的延续问题（每个问题不超过 20 字），帮助用户深入了解相关内容。\n\n"
        f"用户问题：{user_text}\n\n"
        f"AI 回答：{assistant_text[:500]}\n\n"
        "要求：\n"
        "1. 问题要具体、可操作\n"
        "2. 与当前话题紧密相关\n"
        "3. 每个问题一行，不要编号\n"
        "4. 只输出 3 个问题，不要其他内容"
    )
