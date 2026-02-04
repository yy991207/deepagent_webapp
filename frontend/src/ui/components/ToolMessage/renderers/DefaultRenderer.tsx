import type { ToolRendererProps } from "../types";

// JSON 格式化辅助函数
function formatJson(data: unknown): string {
  if (typeof data === "string") return data;
  try {
    return JSON.stringify(data, null, 2);
  } catch {
    return String(data);
  }
}

// 默认渲染器：用于未注册的工具
export function DefaultRenderer({ status, args, output }: ToolRendererProps) {
  const data = status === "running" ? args : output;
  
  if (!data) {
    return <div className="tool-empty">暂无可展示内容</div>;
  }

  // 字符串直接显示
  if (typeof data === "string") {
    return <pre className="tool-text-output">{data}</pre>;
  }

  // 对象/数组显示为 JSON
  return <pre className="tool-json-output">{formatJson(data)}</pre>;
}
