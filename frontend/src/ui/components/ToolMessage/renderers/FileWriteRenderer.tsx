import type { ToolRendererProps } from "../types";
import { Icons } from "../Icons";
import { FilePath } from "../components/FileTree";

export function FileWriteRenderer({ status, args, output }: ToolRendererProps) {
  const path = (args as any)?.TargetFile || (args as any)?.file_path || (args as any)?.path || "";
  const content = (args as any)?.CodeContent || (args as any)?.content || "";
  
  // 预先声明 success 变量
  let success = true;
  let message = "";

  if (status === "running") {
    return (
      <div className="tool-file-write">
        <div className="tool-file-write__header">
          <FilePath path={path} />
          <span className="tool-file-write__status tool-file-write__status--running">
            <span className="tool-todo__spinner" style={{ width: "12px", height: "12px" }} />
            正在写入...
          </span>
        </div>
      </div>
    );
  }

  // 检查是否为结构化文档生成结果 (如 PDF 报告)
  // 格式: {"status": "success", "title": "...", "type": "pdf", ...}
  let artifactTitle = "";
  let artifactType = "";
  
  if (output && typeof output === "string" && output.trim().startsWith("{")) {
    try {
      const json = JSON.parse(output);
      if (json.title && json.type) {
        artifactTitle = json.title;
        artifactType = json.type;
        success = json.status === "success";
      }
    } catch {}
  } else if (output && typeof output === "object") {
     const out = output as any;
     if (out.title && out.type) {
        artifactTitle = out.title;
        artifactType = out.type;
        success = out.status === "success";
     }
  }

  // 如果是文档生成结果，渲染专门的卡片
  if (artifactTitle) {
    return (
      <div className="tool-file-write">
         <div className="tool-artifact-card">
            <div className="tool-artifact-icon">
               {artifactType.toLowerCase() === 'pdf' ? <Icons.Pdf /> : <Icons.File />}
            </div>
            <div className="tool-artifact-info">
               <div className="tool-artifact-title">{artifactTitle}</div>
               <div className="tool-artifact-meta">
                  {artifactType.toUpperCase()} 文档 · {success ? "已生成" : "生成失败"}
               </div>
            </div>
            {success && (
               <div className="tool-artifact-action">
                  <Icons.Check />
               </div>
            )}
         </div>
      </div>
    );
  }

  // 普通文件写入检查
  if (typeof output === "string") {
    success = !output.toLowerCase().includes("error") && !output.toLowerCase().includes("failed");
    message = output;
  } else if (output) {
    const out = output as any;
    success = out.success !== false;
    message = out.message || out.error || "";
  }

  // 计算内容统计
  const lines = content ? content.split("\n").length : 0;
  const bytes = content ? new Blob([content]).size : 0;

  return (
    <div className="tool-file-write">
      <div className="tool-file-write__header">
        <FilePath path={path} />
        <span className={`tool-file-write__status ${success ? "" : "tool-file-write__status--error"}`}>
          {success ? (
            <>
              <Icons.Check />
              已写入
            </>
          ) : (
            <>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/>
              </svg>
              失败
            </>
          )}
        </span>
      </div>
      
      {lines > 0 && (
        <div className="tool-file-write__stats">
          {lines} 行 · {formatBytes(bytes)}
        </div>
      )}
      
      {message && !success && (
        <div className="tool-file-write__error">
          {message}
        </div>
      )}
    </div>
  );
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
}
