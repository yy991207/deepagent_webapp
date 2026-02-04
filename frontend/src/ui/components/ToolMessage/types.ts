import type { ComponentType, ReactNode } from "react";

// 工具状态
export type ToolStatus = "running" | "done" | "error";

// 工具消息 Props
export interface ToolMessageProps {
  toolName: string;
  toolCallId?: string;
  status: ToolStatus;
  args?: unknown;
  output?: unknown;
  startTime?: number;    // 开始时间戳
  endTime?: number;      // 结束时间戳
  metadata?: Record<string, unknown>;  // 扩展元数据
}

// 工具渲染器 Props
export interface ToolRendererProps {
  status: ToolStatus;
  args: unknown;
  output: unknown;
  startTime?: number;
  endTime?: number;
  metadata?: Record<string, unknown>;
}

// 工具渲染器配置
export interface ToolRendererConfig {
  // 工具名称（支持多个别名）
  names: string[];
  // 渲染器组件
  Renderer: ComponentType<ToolRendererProps>;
  // 工具图标
  icon: ComponentType;
  // 显示名称生成器
  getDisplayName: (args: unknown) => string;
  // 默认是否展开
  defaultExpanded?: boolean | ((status: ToolStatus) => boolean);
  // 执行中时的提示信息生成器
  getRunningHint?: (args: unknown) => string;
}

// 工具卡片 Props
export interface ToolCardProps {
  status: ToolStatus;
  children: ReactNode;
  className?: string;
}

// 工具头部 Props
export interface ToolHeaderProps {
  icon: ReactNode;
  title: string;
  status: ToolStatus;
  duration?: string | null;
  isOpen: boolean;
  onToggle: () => void;
}

// 代码块 Props
export interface CodeBlockProps {
  code: string;
  language?: string;
  showLineNumbers?: boolean;
  maxLines?: number;
  onCopy?: () => void;
}

// 结果项
export interface ResultItem {
  id: string | number;
  title?: string;
  content: string;
  url?: string;
  score?: number;
  source?: string;
  icon?: ComponentChild;
}

// 结果列表 Props
export interface ResultListProps {
  items: ResultItem[];
  emptyText?: string;
  maxItems?: number;
  showScore?: boolean;
  onItemClick?: (item: ResultItem) => void;
}

// 评分徽章 Props
export interface ScoreBadgeProps {
  score: number;  // 0-1 或 0-100
  showLabel?: boolean;
}

// 复制按钮 Props
export interface CopyButtonProps {
  text?: string;
  onClick?: () => void;
}

// 状态图标 Props
export interface StatusIconProps {
  status: ToolStatus;
  size?: number;
}

// Todo 项
export interface TodoItem {
  content: string;
  status: "pending" | "in_progress" | "completed";
  priority?: "low" | "medium" | "high";
}
