import type { ToolRendererProps } from "../types";
import { TodoList, type TodoItem } from "../components/TodoList";
import { Icons } from "../Icons";
import { cn } from "@/lib/utils";

export function TodosRenderer({ status, args, output }: ToolRendererProps) {
  // 从参数或输出中获取任务列表
  const data = status === "running" ? args : output;
  let items: TodoItem[] = [];
  let groups: TodoGroup[] = [];
  
  try {
    let todoData: any[] = [];
    
    if (typeof data === "string") {
      const parsed = JSON.parse(data);
      todoData = parsed.todoList || parsed.todos || parsed.items || parsed;
    } else if (Array.isArray(data)) {
      todoData = data;
    } else if ((data as any)?.todoList) {
      todoData = (data as any).todoList;
    } else if ((data as any)?.todos) {
      todoData = (data as any).todos;
    } else if ((data as any)?.items) {
      todoData = (data as any).items;
    }
    
    if (Array.isArray(todoData)) {
      // 兼容主任务+子任务结构：只要存在子任务数组，就走分组渲染
      const hasGroupedItems = todoData.some((item: any) =>
        Array.isArray(
          item?.items || item?.children || item?.tasks || item?.todos || item?.subtasks || item?.sub_tasks
        )
      );

      if (hasGroupedItems) {
        groups = todoData.map((group: any, idx: number) => {
          const rawItems =
            group?.items ||
            group?.children ||
            group?.tasks ||
            group?.todos ||
            group?.subtasks ||
            group?.sub_tasks ||
            [];
          const normalizedItems = Array.isArray(rawItems)
            ? rawItems.map((item: any, itemIdx: number) => normalizeSubTask(item, itemIdx))
            : [];

          return {
            id: group?.id || String(idx),
            title:
              group?.title ||
              group?.name ||
              group?.task ||
              group?.content ||
              group?.text ||
              `任务 ${idx + 1}`,
            subtitle: group?.subtitle || group?.desc || group?.description || group?.detail,
            items: normalizedItems.filter((item: SubTaskItem) => item.title),
          };
        });
      } else {
        items = todoData.map((item: any, idx: number) => ({
          id: item.id || String(idx),
          content: item.content || item.text || item.title || item.description || String(item),
          status: normalizeStatus(item.status || item.state),
        }));
      }
    }
  } catch {
    // 非 JSON 格式，尝试按行解析
    if (typeof data === "string") {
      const lines = data.split("\n").map((line) => line.trim()).filter(Boolean);
      // 兼容 "任务列表0/5" 这类摘要行
      const filtered = lines.filter((line, idx) =>
        !(idx === 0 && /^任务列表\s*\d+\s*\/\s*\d+/.test(line))
      );
      items = filtered
        .filter((line: string) => line.trim())
        .map((line: string, idx: number) => ({
          id: String(idx),
          content: line.replace(/^[-*\[\]x\s]+/i, "").trim(),
          status: line.toLowerCase().includes("[x]") ? "completed" as const : "pending" as const,
        }));
    }
  }

  const hasGroups = groups.length > 0;
  if (!hasGroups && items.length === 0) {
    return (
      <div className="tool-todos">
        <div className="tool-text">暂无任务</div>
      </div>
    );
  }

  if (hasGroups) {
    const totalCount = groups.reduce((sum, group) => sum + group.items.length, 0);
    const completedCount = groups.reduce(
      (sum, group) => sum + group.items.filter((item) => item.status === "completed").length,
      0
    );

    return (
      <div className="tool-todos">
        <div className="tool-todos__header">
          <Icons.Task />
          <span className="tool-todos__title">任务列表</span>
          <span className="tool-todos__count">
            {completedCount}/{totalCount}
          </span>
        </div>
        <div className="tool-todos__groups">
          {groups.map((group) => (
            <div key={group.id} className="tool-todos-group">
              <div className="tool-todos-group__header">
                <div className="tool-todos-group__title">{group.title}</div>
                {group.subtitle && (
                  <div className="tool-todos-group__subtitle">{group.subtitle}</div>
                )}
              </div>
              <div className="tool-todos-group__list">
                {group.items.map((item, idx) => (
                  <div
                    key={item.id || `${group.id}-${idx}`}
                    className={`tool-subtask tool-subtask--${item.status.replace("_", "-")}`}
                  >
                    <span
                      className={cn(
                        "tool-subtask__check",
                        item.status === "completed" ? "tool-subtask__check--done" : ""
                      )}
                    >
                      {item.status === "completed" ? <Icons.Check /> : <span className="tool-subtask__dot" />}
                    </span>
                    <div className="tool-subtask__content">
                      <div
                        className={cn(
                          "tool-subtask__title",
                          item.status === "completed" ? "tool-subtask__title--done" : ""
                        )}
                      >
                        {item.title}
                      </div>
                      {item.subtitle && (
                        <div className="tool-subtask__subtitle">{item.subtitle}</div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
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

function normalizeSubTask(item: any, idx: number): SubTaskItem {
  if (item == null) {
    return {
      id: String(idx),
      title: "",
      status: "pending",
    };
  }

  if (typeof item === "string") {
    return {
      id: String(idx),
      title: item,
      status: "pending",
    };
  }

  const doneFlag = item.done === true || item.completed === true || item.finished === true;
  const status = doneFlag ? "completed" : normalizeStatus(item.status || item.state);

  return {
    id: item.id || String(idx),
    title:
      item.title ||
      item.content ||
      item.text ||
      item.task ||
      item.name ||
      item.description ||
      String(item),
    subtitle: item.subtitle || item.desc || item.detail || item.note,
    status,
  };
}

interface SubTaskItem {
  id?: string;
  title: string;
  subtitle?: string;
  status: "pending" | "in_progress" | "completed";
}

interface TodoGroup {
  id?: string;
  title: string;
  subtitle?: string;
  items: SubTaskItem[];
}
