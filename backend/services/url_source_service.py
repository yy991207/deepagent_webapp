from __future__ import annotations

import logging
import re
from typing import Any

import requests
from markdownify import markdownify

from deepagents_cli.config import create_model
from langchain_core.messages import HumanMessage

logger = logging.getLogger(__name__)


class UrlSourceService:
    """URL 来源服务：负责抓取网页、转 Markdown、可选 LLM 摘要，以及生成保存用的文件名"""

    def is_valid_http_url(self, url: str) -> bool:
        try:
            from urllib.parse import urlparse

            u = urlparse(url)
            return u.scheme in ("http", "https") and bool(u.netloc)
        except Exception:
            return False

    def safe_filename(self, name: str) -> str:
        base = (name or "").strip() or "source"
        base = re.sub(r"\s+", " ", base).strip()
        base = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff _\-\.]+", "", base).strip()
        base = base.strip(".")
        if not base:
            base = "source"
        return base[:120]

    def fetch_url_to_markdown(self, url: str, *, timeout: int = 30) -> tuple[str, str, str]:
        resp = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0 (compatible; DeepAgents/1.0)"},
        )
        resp.raise_for_status()
        final_url = str(resp.url)
        html = resp.text or ""
        md = markdownify(html)
        title = ""
        try:
            m = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
            if m:
                title = re.sub(r"\s+", " ", m.group(1)).strip()
        except Exception:
            title = ""
        return final_url, title, md

    async def parse_url_source(self, payload: dict[str, Any]) -> dict[str, Any]:
        # 关键逻辑：这里只做解析与预览，不做入库
        url = str(payload.get("url") or "").strip()
        mode = str(payload.get("mode") or "crawl").strip().lower()

        if not url or not self.is_valid_http_url(url):
            raise ValueError("invalid url")
        if mode not in ("crawl", "llm_summary"):
            raise ValueError("invalid mode")

        final_url, title, md = self.fetch_url_to_markdown(url)

        content = md
        if mode == "llm_summary":
            llm = create_model()
            raw = md
            if len(raw) > 50_000:
                raw = raw[:50_000] + "\n\n[内容过长已截断]"
            prompt = (
                "请把下面网页内容整理成干净、结构化的 Markdown，并在开头给出 2-3 句中文总结。\n\n"
                f"网页标题：{title or 'unknown'}\n"
                f"URL：{final_url}\n\n"
                "网页原始内容：\n"
                f"{raw}\n\n"
                "要求：\n"
                "- 去掉广告、导航、无关内容\n"
                "- 保留关键事实、数据、时间、人物\n"
                "- 输出只要 Markdown，不要额外解释"
            )
            msg = await llm.ainvoke([HumanMessage(content=prompt)])
            content = getattr(msg, "content", "") or ""

        filename_base = self.safe_filename(title) if title else "url"
        filename = f"{filename_base}.md"
        rel_path = f"url/{filename}"

        return {
            "url": final_url,
            "title": title,
            "mode": mode,
            "filename": filename,
            "rel_path": rel_path,
            "content": content,
        }
