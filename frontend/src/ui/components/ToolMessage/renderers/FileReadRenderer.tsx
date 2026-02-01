import type { ToolRendererProps } from "../types";
import { FilePath } from "../components/FileTree";

export function FileReadRenderer({ status, args, output }: ToolRendererProps) {
  const path = (args as any)?.file_path || (args as any)?.path || "";
  const startLine = (args as any)?.start_line || (args as any)?.offset || 1;
  const endLine = (args as any)?.end_line || (args as any)?.limit;
  
  if (status === "running") {
    return (
      <div class="tool-file-read">
        <div class="tool-file-read__header">
          <FilePath path={path} />
        </div>
        <div class="tool-running-hint">正在读取文件...</div>
      </div>
    );
  }

  // 获取文件内容
  let content = "";
  
  if (typeof output === "string") {
    content = output;
  } else if ((output as any)?.content) {
    content = (output as any).content;
  } else if ((output as any)?.data) {
    content = (output as any).data;
  }

  const lines = content.split("\n");
  const displayLines = lines.slice(0, 100); // 最多显示100行

  return (
    <div class="tool-file-read">
      <div class="tool-file-read__header">
        <FilePath path={path} />
        <span class="tool-file-read__lines">
          {endLine
            ? `第 ${startLine}-${endLine} 行`
            : lines.length > 100
              ? `共 ${lines.length} 行（显示前 100 行）`
              : `共 ${lines.length} 行`}
        </span>
      </div>
      
      <pre class="tool-file-read__content">
        {displayLines.map((line, idx) => (
          <div key={idx} class="tool-file-read__line">
            <span class="tool-file-read__line-number">{startLine + idx}</span>
            <span class="tool-file-read__line-content">{line}</span>
          </div>
        ))}
        {lines.length > 100 && (
          <div class="tool-file-read__line tool-file-read__line--truncated">
            <span class="tool-file-read__line-number">...</span>
            <span class="tool-file-read__line-content">（还有 {lines.length - 100} 行未显示）</span>
          </div>
        )}
      </pre>
    </div>
  );
}
