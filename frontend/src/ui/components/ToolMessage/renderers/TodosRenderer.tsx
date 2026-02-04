import type { ToolRendererProps } from "../types";
import { TodoList, type TodoItem } from "../components/TodoList";

export function TodosRenderer({ status, args, output }: ToolRendererProps) {
  // 从参数或输出中获取任务列表
  const data = status === "running" ? args : output;
  let items: TodoItem[] = [];
  
  try {
    let todoData: any[] = [];
    
    if (typeof data === "string") {
      const parsed = JSON.parse(data);
      todoData = parsed.todos || parsed.items || parsed;
    } else if (Array.isArray(data)) {
      todoData = data;
    } else if ((data as any)?.todos) {
      todoData = (data as any).todos;
    } else if ((data as any)?.items) {
      todoData = (data as any).items;
    }
    
    if (Array.isArray(todoData)) {
      items = todoData.map((item: any, idx: number) => ({
        id: item.id || String(idx),
        content: item.content || item.text || item.title || item.description || String(item),
        status: normalizeStatus(item.status || item.state),
      }));
    }
  } catch {
    // 非 JSON 格式，尝试按行解析
    if (typeof data === "string") {
      items = data.split("\n")
        .filter((line: string) => line.trim())
        .map((line: string, idx: number) => ({
          id: String(idx),
          content: line.replace(/^[-*\[\]x\s]+/i, "").trim(),
          status: line.toLowerCase().includes("[x]") ? "completed" as const : "pending" as const,
        }));
    }
  }

  if (items.length === 0) {
    return (
      <div className="tool-todos">
        <div className="tool-text">暂无任务</div>
      </div>
    );
  }

  return <TodoList items={items} />;
}

function normalizeStatus(status: string | undefined): TodoItem["status"] {
  if (!status) return "pending";
  
  const s = status.toLowerCase();
  if (s === "completed" || s === "done" || s === "finished") {
    return "completed";
  }
  if (s === "in_progress" || s === "running" || s === "active") {
    return "in_progress";
  }
  return "pending";
}
