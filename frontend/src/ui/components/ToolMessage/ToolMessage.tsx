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

  // 状态对应的边框样式
  const statusBorderStyles = {
    running: "ring-1 ring-blue-200/70",
    done: "ring-1 ring-black/5",
    error: "ring-1 ring-red-200/70",
  };

  const runningHint =
    status === "running" ? config?.getRunningHint?.(args) : null;

  return (
    <Card
      className={cn(
        "overflow-hidden transition-all py-0 gap-0 rounded-xl",
        "bg-background/95",
        "shadow-[0_1px_2px_rgba(0,0,0,0.04)]",
        "hover:shadow-[0_2px_8px_rgba(0,0,0,0.06)]",
        "hover:ring-1 hover:ring-black/10",
        statusBorderStyles[status]
      )}
    >
      <div
        className={cn(
          "flex items-center justify-between px-4 py-3 cursor-pointer",
          "hover:bg-muted/50 transition-colors"
        )}
        onClick={() => setIsOpen((prev) => !prev)}
      >
        <div className="flex items-center gap-2.5">
          <StatusIndicator status={status} />
          <span className="text-muted-foreground">
            <Icon />
          </span>
          <span className="font-medium text-sm">{displayName}</span>
        </div>
        <div className="flex items-center gap-2 text-muted-foreground">
          {duration && (
            <span className="text-xs font-mono">
              {duration}s
            </span>
          )}
          <span>{isOpen ? <Icons.ChevronDown /> : <Icons.ChevronRight />}</span>
        </div>
      </div>
      {isOpen && (
        <div className="tool-body">
          {runningHint ? (
            <div className="tool-running-hint">{runningHint}</div>
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
    </Card>
  );
}

// 导出类型和工具函数
export * from "./types";
export { registerTool, getToolConfig } from "./registry";
export { Icons } from "./Icons";
