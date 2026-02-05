import { useMemo, useEffect, useState } from "react";
import { Card } from "@/ui/components/ui/card";
import { cn } from "@/lib/utils";
import { getToolConfig } from "./registry";
import { registerAllRenderers } from "./renderers";
import { DefaultRenderer } from "./renderers/DefaultRenderer";
import { Icons } from "./Icons";
import type { ToolMessageProps, ToolStatus } from "./types";

// 初始化渲染器注册表
let initialized = false;
function ensureInitialized() {
  if (!initialized) {
    registerAllRenderers();
    initialized = true;
  }
}

// 状态指示器组件
function StatusIndicator({ status }: { status: ToolStatus }) {
  const statusStyles = {
    running: "bg-blue-500 animate-pulse",
    done: "bg-green-500",
    error: "bg-red-500",
  };

  return (
    <span
      className={cn("w-2 h-2 rounded-full flex-shrink-0", statusStyles[status])}
    />
  );
}

// 主组件
export function ToolMessage({
  toolName,
  status = "done",
  args,
  output,
  startTime,
  endTime,
  metadata,
}: ToolMessageProps) {
  // 确保渲染器已注册
  useEffect(() => {
    ensureInitialized();
  }, []);

  ensureInitialized();

  // 获取工具配置
  const config = useMemo(() => getToolConfig(toolName), [toolName]);

  // 计算默认展开状态
  const getDefaultExpanded = (): boolean => {
    if (status === "running") return true;
    if (!config) return false;
    if (typeof config.defaultExpanded === "function") {
      return config.defaultExpanded(status);
    }
    return config.defaultExpanded ?? false;
  };

  const [isOpen, setIsOpen] = useState<boolean>(() => getDefaultExpanded());

  const Icon = config?.icon || Icons.Tool;
  const Renderer = config?.Renderer || DefaultRenderer;

  // 生成显示名称
  const displayName = config?.getDisplayName?.(args) || toolName;

  // 计算执行时间
  const duration =
    startTime && endTime
      ? ((endTime - startTime) / 1000).toFixed(2)
      : null;

  // 移除所有工具的边框
  const statusBorderStyles = "";

  const runningHint =
    status === "running" ? config?.getRunningHint?.(args) : null;

  return (
    <div
      className={cn(
        "overflow-hidden transition-all py-0 gap-0",
        "bg-transparent shadow-none border-0"
      )}
    >
      <div
        className={cn(
          "inline-flex items-center gap-2 px-3 py-1.5 rounded-full border transition-all cursor-pointer select-none mb-2",
           status === "running" 
             ? "bg-blue-50 border-blue-100 text-blue-700" 
             : "bg-zinc-50 border-zinc-200 text-zinc-700 hover:bg-zinc-100",
           // 错误状态
           status === "error" && "bg-red-50 border-red-100 text-red-700"
        )}
        onClick={() => setIsOpen((prev) => !prev)}
      >
        <div className="flex items-center gap-1.5">
          {status === "running" && <div className="w-1.5 h-1.5 rounded-full bg-current animate-pulse" />}
          {status === "error" && <div className="w-1.5 h-1.5 rounded-full bg-current" />}
          <span className="text-current opacity-70 scale-90">
            <Icon />
          </span>
          <span className="font-medium text-xs">{displayName}</span>
        </div>
        
        <div className="flex items-center gap-1.5 text-current/60 pl-1 border-l border-current/20 ml-1">
          {duration && (
            <span className="text-[10px] font-mono leading-none">
              {duration}s
            </span>
          )}
          <div className="transition-transform duration-200" style={{ transform: isOpen ? 'rotate(-180deg)' : 'rotate(0deg)' }}>
             <Icons.ChevronDown /> 
          </div>
        </div>
      </div>
      
      {isOpen && (
        <div className={cn("tool-body border-0 p-0 pl-1")}>
          {runningHint ? (
            <div className="tool-running-hint text-zinc-500 text-xs italic pl-2">{runningHint}</div>
          ) : (
            <Renderer
              status={status}
              args={args}
              output={output}
              startTime={startTime}
              endTime={endTime}
              metadata={metadata}
            />
          )}
        </div>
      )}
    </div>
  );
}

// 导出类型和工具函数
export * from "./types";
export { registerTool, getToolConfig } from "./registry";
export { Icons } from "./Icons";
