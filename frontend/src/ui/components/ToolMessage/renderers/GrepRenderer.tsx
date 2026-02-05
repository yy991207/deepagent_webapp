import type { ToolRendererProps } from "../types";

function formatOutput(output: unknown): string {
  if (typeof output === "string") return output;
  try {
    return JSON.stringify(output, null, 2);
  } catch {
    return String(output);
  }
}

export function GrepRenderer({ status, args, output }: ToolRendererProps) {
  const query =
    (args as any)?.Query ||
    (args as any)?.Pattern ||
    (args as any)?.pattern ||
    "";
  const path =
    (args as any)?.SearchPath ||
    (args as any)?.SearchDirectory ||
    (args as any)?.path ||
    "";

  if (status === "running") {
    return (
      <div className="tool-grep">
        <div className="tool-grep__meta">
          {query ? `搜索: ${query}` : "搜索中..."}
          {path ? ` · 目录: ${path}` : ""}
        </div>
        <div className="tool-running-hint">正在检索文件...</div>
      </div>
    );
  }

  const content = formatOutput(output);

  return (
    <div className="tool-grep">
      <div className="tool-grep__meta">
        {query ? `搜索: ${query}` : "搜索结果"}
        {path ? ` · 目录: ${path}` : ""}
      </div>
      {content ? (
        <pre className="tool-code">{content}</pre>
      ) : (
        <div className="tool-text">暂无匹配结果</div>
      )}
    </div>
  );
}
