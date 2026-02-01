export interface BadgeProps {
  children: preact.ComponentChildren;
  variant?: "default" | "success" | "error" | "warning" | "info";
  icon?: preact.ComponentChild;
}

export function Badge({
  children,
  variant = "default",
  icon,
}: BadgeProps) {
  const variantClass = {
    default: "",
    success: "tool-badge--success",
    error: "tool-badge--error",
    warning: "tool-badge--warning",
    info: "tool-badge--info",
  }[variant];

  return (
    <span class={`tool-badge ${variantClass}`}>
      {icon && <span class="tool-badge__icon">{icon}</span>}
      {children}
    </span>
  );
}

// 状态徽章
export function StatusBadge({
  status,
}: {
  status: "success" | "error" | "pending" | "running";
}) {
  const config = {
    success: { variant: "success" as const, text: "成功" },
    error: { variant: "error" as const, text: "失败" },
    pending: { variant: "default" as const, text: "等待中" },
    running: { variant: "info" as const, text: "运行中" },
  }[status];

  return <Badge variant={config.variant}>{config.text}</Badge>;
}
