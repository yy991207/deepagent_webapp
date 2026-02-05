import type { ToolRendererProps } from "../types";
import { Icons } from "../Icons";

function formatJson(data: unknown): string {
  if (typeof data === "string") return data;
  try {
    return JSON.stringify(data, null, 2);
  } catch {
    return String(data);
  }
}

export function TaskRenderer({ status, args, output }: ToolRendererProps) {
  const name = (args as any)?.name || "";
  const desc = (args as any)?.description || (args as any)?.task || (args as any)?.value || "";
  const subagent = (args as any)?.subagent_type || "";
  const result = status === "done" ? output : null;

  return (
    <div className="tool-task">
      <div className="tool-task__header">
        <Icons.Bolt />
        <span className="tool-task__title">{name || "子任务分派"}</span>
      </div>
      {desc && <div className="tool-task__desc">{desc}</div>}
      {subagent && (
        <div className="tool-task__meta">子智能体: {subagent}</div>
      )}
      {status === "done" && result && (
        <pre className="tool-task__result">{formatJson(result)}</pre>
      )}
      {status !== "done" && !desc && (
        <div className="tool-task__hint">正在执行子任务...</div>
      )}
    </div>
  );
}
