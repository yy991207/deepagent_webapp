"""记忆总结相关的 prompt 模板。

本模块统一管理 MemorySummaryService 中硬编码的总结 prompt。
"""

from __future__ import annotations


def memory_summary_prompt(memory_text: str) -> str:
    """生成记忆总结的 prompt。

    Args:
        memory_text: 需要总结的历史记忆文本

    Returns:
        完整的 prompt 字符串
    """
    return (
        "你是一名对话记录整理员。下面是一段用户与助手的历史记忆文本。\n"
        "请把它压缩成一段不超过 500 字的总结，要求：\n"
        "1) 只保留对后续对话最有用的信息\n"
        "2) 提炼出用户的核心需求/偏好、发生过的主要事件、已确定的结论或约束\n"
        "3) 不要出现无意义的客套话，不要逐条复述原文\n"
        "4) 输出必须是纯文本，不要加标题，不要加编号\n"
        "5) 总结完成后，请另起一行，输出：\"以上是过往的总结记忆，以下是新的记忆：\"\n\n"
        f"需要总结的内容如下：\n"
        f"{memory_text.strip()}"
    )
