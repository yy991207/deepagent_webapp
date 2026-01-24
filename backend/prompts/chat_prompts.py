"""聊天流相关的 prompt 模板。

本模块统一管理 ChatStreamService 中所有硬编码的大段 prompt，
包括：
- Sandbox 环境指南
- 引用规则
- 文件写入规则
- 推荐问题生成 prompt
- 调研类任务的 task 子智能体使用规则提示词
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
        "3. PDF 中文支持（重要）：\n"
        "   - reportlab 默认字体不支持中文，必须使用 CID 字体或下载中文字体\n"
        "   - 方法一：使用 reportlab CID 字体（推荐）\n"
        "     ```python\n"
        "     from reportlab.pdfbase import pdfmetrics\n"
        "     from reportlab.pdfbase.cidfonts import UnicodeCIDFont\n"
        "     from reportlab.lib.fonts import addMapping\n"
        "     # 注册宋体字体\n"
        "     pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))\n"
        "     # 使用时\n"
        "     canvas.setFont('STSong-Light', 12)\n"
        "     ```\n"
        "   - 方法二：下载 Noto Sans CJK 字体\n"
        "     ```bash\n"
        "     wget -q -O /workspace/NotoSansSC-Regular.ttf 'https://github.com/googlefonts/noto-cjk/raw/main/Sans/OTF/SimplifiedChinese/NotoSansCJKsc-Regular.otf'\n"
        "     ```\n"
        "     ```python\n"
        "     from reportlab.pdfbase.ttfonts import TTFont\n"
        "     pdfmetrics.registerFont(TTFont('NotoSansSC', '/workspace/NotoSansSC-Regular.ttf'))\n"
        "     canvas.setFont('NotoSansSC', 12)\n"
        "     ```\n"
        "   - 生成包含中文的 PDF 时必须使用以上方法之一，否则中文会显示为方块\n\n"
        "4. 常用依赖安装命令（在激活虚拟环境后）：\n"
        "   - PDF 生成：uv pip install reportlab\n"
        "   - Word 文档：uv pip install python-docx\n"
        "   - PPT 文档：uv pip install python-pptx\n"
        "   - Excel 文档：uv pip install openpyxl pandas\n"
        "   - 数据分析：uv pip install pandas numpy matplotlib\n"
        "   - 网络请求：uv pip install requests httpx\n\n"
        "5. 工作目录：\n"
        "   - 默认工作目录：/workspace\n"
        "   - 虚拟环境路径：/workspace/.venv\n"
        "   - 生成的文件应保存在 /workspace/ 下\n\n"
        "6. 常见错误及解决：\n"
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
        "2. write_file 只负责写入文件系统（沙箱或工作区），不等于文档已入库\n"
        "3. write_file 成功后，必须再调用 save_filesystem_write 把内容存入 MongoDB，生成文档卡片\n"
        "4. 禁止使用 read_file 工具读取刚写入的文档来拼结果\n"
        "5. 工具调用成功后，再在回复中说明文档已保存\n"
        "6. 禁止在回复中提及任何文件路径或文件名\n"
        "7. 禁止使用引号或代码块包裹路径或文件名\n"
        "8. 用户会在聊天界面看到文档卡片，可以点击查看\n\n"
        "触发场景示例：\n"
        "- 用户说：帮我整理一份XXX总结\n"
        "- 用户说：归纳一下XXX要点\n"
        "- 用户说：把这些内容汇总成文档\n"
        "以上场景都必须调用 write_file 工具保存文档\n\n"
        "正确流程：\n"
        "- 先调用 write_file(...) 把内容写入文件\n"
        "- 再调用 save_filesystem_write(file_path, content, title) 把内容入库生成文档卡片\n"
        "- 工具返回成功后，直接回复：我已将内容整理成文档，你可以点击下方的文档卡片查看。\n"
        "- 不要再调用 read_file 读取刚写的文档\n\n"
        "错误做法：\n"
        "- 不调用工具，直接在回复里展示整理好的内容\n"
        "- 不调用工具，直接说文档已保存\n"
        "- 调用 write_file 后又调用 read_file 读取刚写的文档\n"
        "- 在回复里提路径或文件名\n"
        "</file_write_rules>"
    )


def research_output_format_prompt() -> str:
    """返回深度研究/调研类任务的输出格式规则。"""
    return (
        "<research_output_format>\n"
        "重要：深度研究/调研任务的输出格式规则\n\n"
        "当用户的需求属于以下类型时，默认使用 HTML 格式输出结果：\n"
        "- 调研类：市场调研、行业调研、竞品调研、用户调研等\n"
        "- 研究类：课题研究、专题研究、深度研究、研究报告等\n"
        "- 分析类：深度分析、综合分析、对比分析、趋势分析等\n"
        "- 报告类：研究报告、调研报告、分析报告、总结报告等\n\n"
        "识别关键词：调研、研究、深度、分析、报告、综述、探究、考察、调查等\n\n"
        "HTML 格式输出规则：\n"
        "1. 除非用户明确指定其他格式（如 PDF、DOCX、Markdown、Word、PPT 等），否则一律使用 HTML 格式\n"
        "2. HTML 文件应包含完整的结构：<!DOCTYPE html>、<html>、<head>、<body> 等\n"
        "3. 必须在 <head> 中包含内联 CSS 样式，确保文档美观、专业\n"
        "4. 推荐的 HTML 样式特点：\n"
        "   - 清晰的标题层级（h1、h2、h3）\n"
        "   - 适当的段落间距和行高\n"
        "   - 表格使用边框和斑马纹样式\n"
        "   - 重点内容使用高亮或加粗\n"
        "   - 整体配色专业、易读\n"
        "5. 文件扩展名使用 .html\n\n"
        "示例场景：\n"
        "- 用户说：帮我调研一下XX行业 → 输出 HTML 格式\n"
        "- 用户说：深度研究XX课题 → 输出 HTML 格式\n"
        "- 用户说：写一份XX分析报告 → 输出 HTML 格式\n"
        "- 用户说：帮我调研XX，输出 PDF → 输出 PDF 格式（用户明确指定）\n"
        "- 用户说：用 Markdown 写一份研究报告 → 输出 Markdown 格式（用户明确指定）\n"
        "</research_output_format>"
    )


def research_task_rules_prompt() -> str:
    """返回调研任务的 task 子智能体使用规则。"""
    return (
        "<research_task_rules>\n"
        "重要：调研类任务的执行规则\n\n"
        "当用户提出调研/研究/新闻整理/报告类需求时：\n"
        "1. 不要只描述流程，必须实际调用工具推进任务。\n"
        "2. 优先使用 task 工具把调研拆分成 2-5 个互不重叠的子问题，并行执行。\n"
        "3. task 的 subagent_type 固定使用 research-analyst。\n"
        "4. 子智能体返回后，你再综合所有子结果，输出最终结论/报告。\n\n"
        "示例：\n"
        "- 用户要‘最近 3 个月 AI Agent 新闻’，你可以拆成：OpenAI/Anthropic/Google、产品发布、融资并购、风险争议等。\n"
        "</research_task_rules>"
    )


def tool_whitelist_prompt(tool_names: list[str]) -> str:
    """返回工具白名单与严格拼写规则。

    说明：
    - 真实线上经常出现工具名拼写错误（例如把两个工具名拼在一起：write_todosls）。
    - 这里把运行时可用的工具名显式列出来，并要求模型只能从白名单中选择。
    - 该提示词只约束“工具调用名字”，不约束自然语言回答。

    Args:
        tool_names: 运行时可用工具名列表（已去重、已排序）

    Returns:
        工具白名单提示词
    """

    names = [str(x).strip() for x in (tool_names or []) if str(x).strip()]
    uniq_sorted = sorted(set(names))
    rendered = ", ".join(uniq_sorted)

    return (
        "<tool_whitelist>\n"
        "重要：工具调用白名单（强制）\n\n"
        "你只能调用下面列出的工具名，工具名必须完全一致（区分下划线/大小写），否则会报错：\n"
        f"{rendered}\n\n"
        "严格规则：\n"
        "1. 工具名必须从白名单中逐字选择，禁止自己编新名字。\n"
        "2. 禁止把两个工具名拼在一起（例如：write_todosls、read_filegrep）。\n"
        "3. 禁止在工具名上添加前缀/后缀/复数/大小写变体（例如：Write_File、writeFiles）。\n"
        "4. 当你不确定工具名时：不要尝试调用，先用自然语言确认或在脑中对照白名单。\n"
        "5. 只要收到 'not a valid tool' 的报错：立刻停止继续试错，重新从白名单里选正确工具。\n"
        "</tool_whitelist>"
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
