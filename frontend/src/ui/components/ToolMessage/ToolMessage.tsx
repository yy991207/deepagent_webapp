import { useState, useMemo, useEffect } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { Card, CardContent } from "@/ui/components/ui/card";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/ui/components/ui/collapsible";
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
  toolCallId,
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

  const [isOpen, setIsOpen] = useState(getDefaultExpanded);

  // 使用配置中的渲染器或默认渲染器
  const Renderer = config?.Renderer || DefaultRenderer;
  const Icon = config?.icon || Icons.Tool;

  // 生成显示名称
  const displayName = config?.getDisplayName?.(args) || toolName;

  // 执行中提示
  const runningHint =
    status === "running" && config?.getRunningHint
      ? config.getRunningHint(args)
      : null;

  // 计算执行时间
  const duration =
    startTime && endTime
      ? ((endTime - startTime) / 1000).toFixed(2)
      : null;

  // 状态对应的边框样式
  const statusBorderStyles = {
    running: "border-blue-400 shadow-sm shadow-blue-100",
    done: "border-border",
    error: "border-red-400",
  };

  return (
    <Card
      className={cn(
        "overflow-hidden transition-all py-0 gap-0",
        statusBorderStyles[status]
      )}
    >
      <Collapsible open={isOpen} onOpenChange={setIsOpen}>
        <CollapsibleTrigger className="w-full">
          <div
            className={cn(
              "flex items-center justify-between px-4 py-3 cursor-pointer",
              "hover:bg-muted/50 transition-colors"
            )}
          >
            <div className="flex items-center gap-2.5">
              <StatusIndicator status={status} />
              <span className="text-muted-foreground">
                <Icon />
              </span>
              <span className="font-medium text-sm">{displayName}</span>
            </div>
            <div className="flex items-center gap-2">
              {duration && (
                <span className="text-xs text-muted-foreground font-mono">
                  {duration}s
                </span>
              )}
              {isOpen ? (
                <ChevronDown className="h-4 w-4 text-muted-foreground" />
              ) : (
                <ChevronRight className="h-4 w-4 text-muted-foreground" />
              )}
            </div>
          </div>
        </CollapsibleTrigger>

        <CollapsibleContent>
          <CardContent className="pt-0 pb-4 border-t">
            {runningHint ? (
              <div className="py-3 text-sm text-muted-foreground italic">
                {runningHint}
              </div>
            ) : (
              <div className="pt-3">
                <Renderer
                  status={status}
                  args={args}
                  output={output}
                  startTime={startTime}
                  endTime={endTime}
                  metadata={metadata}
                />
              </div>
            )}
          </CardContent>
        </CollapsibleContent>
      </Collapsible>
    </Card>
  );
}

// 导出类型和工具函数
export * from "./types";
export { registerTool, getToolConfig } from "./registry";
export { Icons } from "./Icons";
