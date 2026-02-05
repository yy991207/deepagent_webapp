import { useState, useMemo } from "react";
import { Icons } from "../Icons";
import { cn } from "@/lib/utils";

export interface TodoItem {
  id?: string;
  content: string;
  status: "pending" | "in_progress" | "completed";
}

export interface TodoListProps {
  items: TodoItem[];
  title?: string;
  showHeader?: boolean;
  status?: "running" | "done" | "error";
  duration?: string;
}

function StatusIcon({ status, index, isLast }: { status: TodoItem["status"]; index: number; isLast: boolean }) {
  return (
    <div className="flex flex-col items-center mr-3 relative self-stretch">
      {/* Vertical Line */}
      {!isLast && (
        <div className="absolute top-8 bottom-0 w-px bg-border/40" />
      )}
      
      <div className={cn(
        "relative z-10 w-5 h-5 rounded-full flex items-center justify-center border transition-all mt-3.5",
        status === "completed" && "bg-green-500 border-green-500 text-white",
        status === "in_progress" && "border-blue-500 text-blue-500 bg-white",
        status === "pending" && "border-zinc-300 text-transparent bg-white"
      )}>
        {status === "completed" && (
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="20 6 9 17 4 12" />
          </svg>
        )}
        {status === "in_progress" && (
           <div className="w-2.5 h-2.5 bg-current rounded-full animate-pulse" />
        )}
        {status === "pending" && (
          <div className="w-2.5 h-2.5 rounded-full" />
        )}
      </div>
    </div>
  );
}

export function TodoList({
  items,
  title = "Planning tasks", // Default title if none provided
  showHeader = true,
  status = "done",
  duration,
}: TodoListProps) {
  const [isCollapsed, setIsCollapsed] = useState(false);
  
  const completedCount = items.filter(
    (item) => item.status === "completed"
  ).length;

  const isAllCompleted = completedCount === items.length && items.length > 0;
  
  // Determine header text based on state
  const headerTitle = useMemo(() => {
    if (status === "running") return "Thinking...";
    if (isAllCompleted) return "Finished";
    return title;
  }, [status, isAllCompleted, title]);

  return (
    <div className="w-full font-sans text-sm">
      {/* 移除内置头部，使用外部统一头部 */}
      
      {!isCollapsed && (
        <div className="mt-2 flex flex-col gap-2">
          {items.map((item, idx) => (
            <div
              key={item.id || idx}
              className="flex items-start group"
            >
              <StatusIcon status={item.status} index={idx} isLast={idx === items.length - 1} />
              
              <div className={cn(
                "flex-1 px-4 py-3 rounded-2xl transition-all border",
                item.status === "in_progress" 
                  ? "bg-blue-50/50 border-blue-100/50 shadow-sm" 
                  : "bg-zinc-50/50 border-zinc-100 hover:bg-zinc-100 hover:border-zinc-200",
                item.status === "completed" && "opacity-75"
              )}>
                <div className={cn(
                  "leading-relaxed",
                  item.status === "completed" ? "text-muted-foreground" : "text-foreground",
                  item.status === "in_progress" ? "font-medium text-blue-700" : ""
                )}>
                  {item.content}
                </div>
              </div>
            </div>
          ))}
          
          {items.length === 0 && (
            <div className="px-4 py-8 text-center text-muted-foreground bg-zinc-50 rounded-2xl border border-zinc-100">
              No tasks
            </div>
          )}
        </div>
      )}
    </div>
  );
}
