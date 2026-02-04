export interface ProgressProps {
  value: number; // 0-100
  text?: string;
  showPercentage?: boolean;
  color?: "primary" | "success" | "error" | "warning";
}

export function Progress({
  value,
  text,
  showPercentage = true,
  color = "primary",
}: ProgressProps) {
  const clampedValue = Math.max(0, Math.min(100, value));

  const colorClass = {
    primary: "",
    success: "tool-progress__fill--success",
    error: "tool-progress__fill--error",
    warning: "tool-progress__fill--warning",
  }[color];

  return (
    <div className="tool-progress">
      <div className="tool-progress__bar">
        <div
          className={`tool-progress__fill ${colorClass}`}
          style={{ width: `${clampedValue}%` }}
        />
      </div>
      {(text || showPercentage) && (
        <div className="tool-progress__text">
          {text || `${clampedValue.toFixed(0)}%`}
        </div>
      )}
    </div>
  );
}

// 不确定进度条（加载中）
export function IndeterminateProgress({ text }: { text?: string }) {
  return (
    <div className="tool-progress">
      <div className="tool-progress__bar tool-progress__bar--indeterminate">
        <div className="tool-progress__fill tool-progress__fill--indeterminate" />
      </div>
      {text && <div className="tool-progress__text">{text}</div>}
    </div>
  );
}
