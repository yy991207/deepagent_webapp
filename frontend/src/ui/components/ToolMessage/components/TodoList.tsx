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
    <div className="flex flex-col items-center mr-3 relative">
      {/* Vertical Line */}
      {!isLast && (
        <div className="absolute top-6 bottom-[-16px] w-px bg-border/60" />
      )}
      
      <div className={cn(
        "relative z-10 w-5 h-5 rounded-full flex items-center justify-center border transition-colors bg-card",
        status === "completed" && "bg-green-500 border-green-500 text-white",
        status === "in_progress" && "border-blue-500 text-blue-500",
        status === "pending" && "border-muted-foreground/30 text-transparent"
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
      {showHeader && (
        <div 
          className="flex items-center justify-between py-2 px-1 cursor-pointer select-none group"
          onClick={() => setIsCollapsed(!isCollapsed)}
        >
          <div className="flex items-center gap-2">
             <span className={cn(
               "font-medium",
               status === "running" ? "text-blue-600 animate-pulse" : "text-foreground"
             )}>
               {headerTitle}
             </span>
             {duration && (
               <span className="text-muted-foreground text-xs">for {duration}</span>
             )}
          </div>
          
          <div className="flex items-center gap-3 text-muted-foreground">
            <span className="text-xs">
              {completedCount} / {items.length} tasks done
            </span>
            <div className="transition-transform duration-200" style={{ transform: isCollapsed ? 'rotate(-90deg)' : 'rotate(0deg)' }}>
              <Icons.ChevronDown />
            </div>
          </div>
        </div>
      )}

      {!isCollapsed && (
        <div className="mt-1 flex flex-col gap-0 border rounded-lg bg-card/50 overflow-hidden shadow-sm">
          {items.map((item, idx) => (
            <div
              key={item.id || idx}
              className={cn(
                "flex items-start px-4 py-3 border-b last:border-0 transition-colors",
                item.status === "in_progress" ? "bg-accent/30" : "bg-transparent"
              )}
            >
              <StatusIcon status={item.status} index={idx} isLast={idx === items.length - 1} />
              
              <div className={cn(
                "flex-1 leading-5 pt-0.5",
                item.status === "completed" ? "text-muted-foreground" : "text-foreground",
                 item.status === "in_progress" ? "font-medium text-blue-700" : ""
              )}>
                {item.content}
              </div>
            </div>
          ))}
          
          {items.length === 0 && (
            <div className="px-4 py-8 text-center text-muted-foreground">
              No tasks
            </div>
          )}
        </div>
      )}
    </div>
  );
}
