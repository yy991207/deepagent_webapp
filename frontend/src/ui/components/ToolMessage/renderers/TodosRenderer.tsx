import type { ToolRendererProps } from "../types";
import { TodoList, type TodoItem } from "../components/TodoList";
import { Icons } from "../Icons";
import { cn } from "@/lib/utils";

export function TodosRenderer({ status, args, output, startTime, endTime }: ToolRendererProps) {
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
    
    // 如果不是数组且是字符串，尝试从字符串中提取 JSON 数组
    if (!Array.isArray(todoData) && typeof data === "string") {
      // 策略：找到可能的列表起始位置，尝试解析
      // 优先找 "todo_list" 关键词后面的 [
      const kwIndex = data.indexOf("todo_list");
      let start = -1;
      
      if (kwIndex !== -1) {
        start = data.indexOf('[', kwIndex);
      }
      
      // 如果没找到或没有关键词，找第一个 [
      if (start === -1) {
        start = data.indexOf('[');
      }
      
      if (start !== -1) {
        // 尝试从最右边的 ] 开始匹配，以处理嵌套列表
        let end = data.lastIndexOf(']');
        
        // 如果最宽的匹配失败，且存在多个 ]，可以尝试逐步向左收缩（简单的回退策略）
        // 这里暂时只尝试最宽匹配，因为它能处理最常见的嵌套情况
        if (end > start) {
           const potentialJson = data.substring(start, end + 1);
           try {
             const fixedJson = potentialJson
               .replace(/False/g, 'false')
               .replace(/True/g, 'true')
               .replace(/None/g, 'null')
               .replace(/'/g, '"'); 
             const parsed = JSON.parse(fixedJson);
             if (Array.isArray(parsed)) todoData = parsed;
           } catch {
             // 如果最宽匹配失败，可能是因为包含了多个不相关的列表
             // 比如: ... todo_list: [...], other: [...] ...
             // 这种情况下，lastIndexOf(']') 会包括 other: [...]，导致 parse 失败
             // 简单的处理：尝试找到与 start 对应层级的结束 ] (需要堆栈计数)
             try {
                let balance = 0;
                let foundEnd = -1;
                for (let i = start; i < data.length; i++) {
                    if (data[i] === '[') balance++;
                    else if (data[i] === ']') {
                        balance--;
                        if (balance === 0) {
                            foundEnd = i;
                            break;
                        }
                    }
                }
                
                if (foundEnd !== -1) {
                    const exactJson = data.substring(start, foundEnd + 1);
                     const fixedJson = exactJson
                       .replace(/False/g, 'false')
                       .replace(/True/g, 'true')
                       .replace(/None/g, 'null')
                       .replace(/'/g, '"');
                    const parsed = JSON.parse(fixedJson);
                    if (Array.isArray(parsed)) todoData = parsed;
                }
             } catch {}
           }
        }
      }
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
  
  // Calculate duration string
  const durationString =
    startTime && endTime
      ? ((endTime - startTime) / 1000).toFixed(1) + "s"
      : undefined;

  if (!hasGroups && items.length === 0) {
    return (
      <div className="tool-todos">
        <div className="tool-text">暂无任务</div>
      </div>
    );
  }

  if (hasGroups) {
    // For now, render groups using the legacy style but wrapped in similar container if needed
    // Or we could try to adapt the new style to groups later. 
    // Given the request specifically showed a flat list, we'll keep the groups as is for safety,
    // but maybe update the header to be consistent if requested.
    // However, let's inject the StatusIcon style into the groups if possible or just leave them.
    // The user request was "todolist reference this design", implying the TodoList component.
    const totalCount = groups.reduce((sum, group) => sum + group.items.length, 0);
    const completedCount = groups.reduce(
      (sum, group) => sum + group.items.filter((item) => item.status === "completed").length,
      0
    );

    return (
      <div className="tool-todos">
        <div className="tool-todos__header">
          <Icons.Task />
          <span className="tool-todos__title">Task Lists</span>
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

  return <TodoList items={items} status={status} duration={durationString} />;
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
