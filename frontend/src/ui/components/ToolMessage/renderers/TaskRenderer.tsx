import type { ToolRendererProps } from "../types";
import { Icons } from "../Icons";
import { Badge } from "@/ui/components/ui/badge";
import { ScrollArea } from "@/ui/components/ui/scroll-area";

function extractText(value: unknown): string {
  if (typeof value === "string") return value.trim();
  if (value == null) return "";
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return value.map((item) => extractText(item)).filter(Boolean).join("\n");
  if (typeof value === "object") {
    const obj = value as Record<string, unknown>;
    const candidateKeys = ["value", "content", "text", "result", "output", "summary", "answer"];
    for (const key of candidateKeys) {
      const text = extractText(obj[key]);
      if (text) return text;
    }
  }
  return "";
}

function extractKeyValues(value: unknown): Array<{ label: string; text: string }> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return [];
  const obj = value as Record<string, unknown>;
  return Object.keys(obj)
    .map((key) => ({
      label: key,
      text: extractText(obj[key]),
    }))
    .filter((item) => item.text);
}

export function TaskRenderer({ status, args, output }: ToolRendererProps) {
  const name = (args as any)?.name || "";
  const desc = (args as any)?.description || (args as any)?.task || "";
  const subagent = (args as any)?.subagent_type || "";
  const result = status === "done" ? output : null;

  const resultText = extractText(result);
  const kvItems = resultText ? [] : extractKeyValues(result);
  const hasResult = resultText || kvItems.length > 0;

  return (
    <div className="tool-task">
      <div className="tool-task__header">
        <Icons.Bolt />
        <span className="tool-task__title">{name || "子任务分派"}</span>
      </div>
      {(desc || subagent) && (
        <div className="tool-task__meta-row">
          {subagent && (
            <Badge variant="secondary" className="tool-task__badge">
              {subagent}
            </Badge>
          )}
        </div>
      )}
      {desc && (
        <div className="tool-section">
          <div className="tool-section__title">任务说明</div>
          <ScrollArea className="tool-scroll">
            <div className="tool-plain">{desc}</div>
          </ScrollArea>
        </div>
      )}
      {status === "done" && hasResult && (
        <div className="tool-section">
          <div className="tool-section__title">执行结果</div>
          {resultText ? (
            <ScrollArea className="tool-scroll">
              <div className="tool-plain">{resultText}</div>
            </ScrollArea>
          ) : (
            <div className="tool-kv">
              {kvItems.map((item, idx) => (
                <div key={`${item.label}-${idx}`} className="tool-kv__row">
                  <div className="tool-kv__key">{item.label}</div>
                  <div className="tool-kv__value">{item.text}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
      {status === "done" && !hasResult && (
        <div className="tool-task__hint">暂无结果</div>
      )}
      {status !== "done" && !desc && (
        <div className="tool-task__hint">正在执行子任务...</div>
      )}
    </div>
  );
}
