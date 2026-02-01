import { useState, useMemo, useEffect } from "preact/hooks";
import { getToolConfig } from "./registry";
import { registerAllRenderers } from "./renderers";
import { DefaultRenderer } from "./renderers/DefaultRenderer";
import { Icons } from "./Icons";
import type { ToolMessageProps, ToolStatus } from "./types";
import "./ToolMessage.css";

// 初始化渲染器注册表
let initialized = false;
function ensureInitialized() {
  if (!initialized) {
    registerAllRenderers();
    initialized = true;
  }
}

// 状态图标组件
function StatusIcon({ status }: { status: ToolStatus }) {
  if (status === "running") {
    return <span class="tool-status-icon tool-status-running" />;
  }
  if (status === "error") {
    return <span class="tool-status-icon tool-status-error" />;
  }
  return <span class="tool-status-icon tool-status-done" />;
}

// 工具卡片组件
function ToolCard({
  status,
  children,
  className = "",
}: {
  status: ToolStatus;
  children: preact.ComponentChildren;
  className?: string;
}) {
  const statusClass = {
    running: "tool-card--running",
    done: "tool-card--done",
    error: "tool-card--error",
  }[status];

  return (
    <div class={`tool-card ${statusClass} ${className}`}>
      {children}
    </div>
  );
}

// 工具头部组件
function ToolHeader({
  icon,
  title,
  status,
  duration,
  isOpen,
  onToggle,
}: {
  icon: preact.ComponentChild;
  title: string;
  status: ToolStatus;
  duration?: string | null;
  isOpen: boolean;
  onToggle: () => void;
}) {
  return (
    <div class="tool-header" onClick={onToggle}>
      <div class="tool-header__left">
        <StatusIcon status={status} />
        <span class="tool-header__icon">{icon}</span>
        <span class="tool-header__title">{title}</span>
      </div>
      <div class="tool-header__right">
        {duration && (
          <span class="tool-header__duration">{duration}s</span>
        )}
        <span class="tool-header__chevron">
          {isOpen ? <Icons.ChevronDown /> : <Icons.ChevronRight />}
        </span>
      </div>
    </div>
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

  return (
    <ToolCard status={status}>
      <ToolHeader
        icon={<Icon />}
        title={displayName}
        status={status}
        duration={duration}
        isOpen={isOpen}
        onToggle={() => setIsOpen(!isOpen)}
      />

      {isOpen && (
        <div class="tool-body">
          {runningHint ? (
            <div class="tool-running-hint">{runningHint}</div>
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
    </ToolCard>
  );
}

// 导出类型和工具函数
export * from "./types";
export { registerTool, getToolConfig } from "./registry";
export { Icons } from "./Icons";
