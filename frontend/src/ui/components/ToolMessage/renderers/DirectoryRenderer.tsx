import type { ToolRendererProps } from "../types";
import { DirectoryGrid } from "../components/FileTree";

export function DirectoryRenderer({ status, args, output }: ToolRendererProps) {
  const path = (args as any)?.DirectoryPath || (args as any)?.path || ".";
  
  if (status === "running") {
    return (
      <div class="tool-ls">
        <div class="tool-running-hint">正在列出 {path} 目录...</div>
      </div>
    );
  }

  // 解析目录列表
  let items: string[] = [];
  
  if (typeof output === "string") {
    // 尝试 JSON 解析
    try {
      const parsed = JSON.parse(output);
      if (Array.isArray(parsed)) {
        items = parsed.map((item: any) => 
          typeof item === "string" ? item : item.name || item.path || String(item)
        );
      } else if (parsed.files) {
        items = parsed.files;
      } else if (parsed.entries) {
        items = parsed.entries;
      }
    } catch {
      // 按行分割
      items = output.split("\n").filter((line: string) => line.trim());
    }
  } else if (Array.isArray(output)) {
    items = output.map((item: any) =>
      typeof item === "string" ? item : item.name || item.path || String(item)
    );
  } else if ((output as any)?.files) {
    items = (output as any).files;
  } else if ((output as any)?.entries) {
    items = (output as any).entries;
  }

  if (items.length === 0) {
    return (
      <div class="tool-ls">
        <div class="tool-text">目录为空</div>
      </div>
    );
  }

  return (
    <div class="tool-ls">
      <DirectoryGrid items={items} />
    </div>
  );
}
