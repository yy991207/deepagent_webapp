import { Icons } from "../Icons";

export interface TodoItem {
  id?: string;
  content: string;
  status: "pending" | "in_progress" | "completed";
}

export interface TodoListProps {
  items: TodoItem[];
  title?: string;
  showHeader?: boolean;
}

function TodoCheckbox({ status }: { status: TodoItem["status"] }) {
  if (status === "completed") {
    return (
      <span class="tool-todo__checkbox">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
          <path d="M8 0a8 8 0 1 1 0 16A8 8 0 0 1 8 0zM6.5 11.5L3 8l1-1 2.5 2.5 5-5 1 1-6 6z" />
        </svg>
      </span>
    );
  }

  if (status === "in_progress") {
    return (
      <span class="tool-todo__checkbox">
        <span class="tool-todo__spinner" />
      </span>
    );
  }

  return (
    <span class="tool-todo__checkbox">
      <span class="tool-todo__circle" />
    </span>
  );
}

export function TodoList({
  items,
  title = "任务列表",
  showHeader = true,
}: TodoListProps) {
  const completedCount = items.filter(
    (item) => item.status === "completed"
  ).length;

  return (
    <div class="tool-todos">
      {showHeader && (
        <div class="tool-todos__header">
          <Icons.Task />
          <span class="tool-todos__title">{title}</span>
          <span class="tool-todos__count">
            {completedCount}/{items.length}
          </span>
        </div>
      )}
      <div class="tool-todos__list">
        {items.map((item, idx) => (
          <div
            key={item.id || idx}
            class={`tool-todo tool-todo--${item.status.replace("_", "-")}`}
          >
            <TodoCheckbox status={item.status} />
            <span class="tool-todo__content">{item.content}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
