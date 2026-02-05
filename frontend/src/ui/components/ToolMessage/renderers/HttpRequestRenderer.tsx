import type { ToolRendererProps } from "../types";

function formatJson(data: unknown): string {
  if (typeof data === "string") return data;
  try {
    return JSON.stringify(data, null, 2);
  } catch {
    return String(data);
  }
}

export function HttpRequestRenderer({ status, args, output }: ToolRendererProps) {
  const method = (args as any)?.method || "GET";
  const url = (args as any)?.url || "";
  const headers = (args as any)?.headers;
  const params = (args as any)?.params;
  const body = (args as any)?.data;

  const result = typeof output === "string" ? safeParse(output) : output;
  const statusCode = (result as any)?.status_code || (result as any)?.status || (result as any)?.code;
  const content = (result as any)?.content ?? output;

  return (
    <div className="tool-http">
      <div className="tool-http__request">
        <span className="tool-http__method">{method}</span>
        <span className="tool-http__url">{url || "未知地址"}</span>
      </div>

      {status === "running" && (
        <div className="tool-running-hint">正在请求中...</div>
      )}

      {status !== "running" && (
        <>
          {statusCode !== undefined && (
            <div className="tool-http__status">状态码: {String(statusCode)}</div>
          )}
          {(headers || params || body) && (
            <div className="tool-http__section">
              <div className="tool-http__section-title">请求参数</div>
              <pre className="tool-code">
                {formatJson({ headers, params, body })}
              </pre>
            </div>
          )}
          {content !== undefined && content !== null && (
            <div className="tool-http__section">
              <div className="tool-http__section-title">响应内容</div>
              <pre className="tool-code">{formatJson(content)}</pre>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function safeParse(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}
