import type { ToolRendererProps } from "../types";
import { Icons } from "../Icons";

export function FetchUrlRenderer({ status, args, output }: ToolRendererProps) {
  const url = (args as any)?.url || "";
  
  if (status === "running") {
    return (
      <div class="tool-fetch">
        <div class="tool-fetch__header">
          <Icons.Link />
          <a class="tool-fetch__url" href={url} target="_blank" rel="noopener noreferrer">
            {url}
          </a>
        </div>
        <div class="tool-running-hint">正在抓取内容...</div>
      </div>
    );
  }

  // 解析内容
  let title = "";
  let content = "";
  
  if (typeof output === "string") {
    content = output;
  } else if (output) {
    const out = output as any;
    title = out.title || "";
    content = out.content || out.text || out.body || out.html || "";
  }

  // 截断过长内容
  const maxLength = 2000;
  const truncated = content.length > maxLength;
  const displayContent = truncated ? content.slice(0, maxLength) : content;

  return (
    <div class="tool-fetch">
      <div class="tool-fetch__header">
        <Icons.Link />
        <a class="tool-fetch__url" href={url} target="_blank" rel="noopener noreferrer">
          {url}
        </a>
      </div>
      
      {title && (
        <div class="tool-fetch__title">{title}</div>
      )}
      
      <div class="tool-fetch__content">
        {displayContent}
        {truncated && (
          <span class="tool-fetch__truncated">
            ...（内容已截断，共 {content.length} 字符）
          </span>
        )}
      </div>
    </div>
  );
}
