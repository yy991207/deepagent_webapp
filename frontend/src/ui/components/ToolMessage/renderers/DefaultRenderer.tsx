import type { ToolRendererProps } from "../types";
import { ScrollArea } from "@/ui/components/ui/scroll-area";

// JSON 格式化辅助函数
function formatJson(data: unknown): string {
  if (typeof data === "string") return data;
  try {
    return JSON.stringify(data, null, 2);
  } catch {
    return String(data);
  }
}

function isPrimitive(value: unknown): boolean {
  return value == null || ["string", "number", "boolean"].includes(typeof value);
}

function renderValue(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return formatJson(value);
}

// 默认渲染器：用于未注册的工具
export function DefaultRenderer({ status, args, output }: ToolRendererProps) {
  const data = status === "running" ? args : output;

  if (!data) {
    return <div className="tool-empty">暂无可展示内容</div>;
  }

  if (typeof data === "string") {
    return (
      <div className="tool-default">
        <div className="tool-plain">{data}</div>
      </div>
    );
  }

  if (Array.isArray(data)) {
    const allPrimitive = data.every((item) => isPrimitive(item));
    return (
      <div className="tool-default">
        {allPrimitive ? (
          <ul className="tool-list">
            {data.map((item, idx) => (
              <li key={idx}>{renderValue(item)}</li>
            ))}
          </ul>
        ) : (
          <ScrollArea className="tool-scroll">
            <pre className="tool-code">{formatJson(data)}</pre>
          </ScrollArea>
        )}
      </div>
    );
  }

  if (typeof data === "object") {
    const entries = Object.entries(data as Record<string, unknown>);
    return (
      <div className="tool-default">
        <div className="tool-kv">
          {entries.map(([key, value]) => (
            <div key={key} className="tool-kv__row">
              <div className="tool-kv__key">{key}</div>
              <div className="tool-kv__value">{renderValue(value)}</div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="tool-default">
      <div className="tool-plain">{String(data)}</div>
    </div>
  );
}
