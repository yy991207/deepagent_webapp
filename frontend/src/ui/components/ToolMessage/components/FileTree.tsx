import { Icons } from "../Icons";

export interface FileTreeItem {
  name: string;
  type: "file" | "folder";
  path?: string;
  children?: FileTreeItem[];
}

export interface ToolFileTreeProps {
  items: FileTreeItem[] | string[];
  onItemClick?: (item: FileTreeItem | string) => void;
}

// 目录网格（平铺显示）
export function DirectoryGrid({
  items,
  onItemClick,
}: {
  items: string[];
  onItemClick?: (item: string) => void;
}) {
  const getItemType = (name: string): "file" | "folder" => {
    // 简单判断：无扩展名或以/结尾的视为文件夹
    if (name.endsWith("/")) return "folder";
    if (!name.includes(".")) return "folder";
    return "file";
  };

  return (
    <div class="tool-ls__grid">
      {items.map((item, idx) => {
        const type = getItemType(item);
        return (
          <div
            key={idx}
            class={`tool-ls__item ${type === "folder" ? "tool-ls__item--folder" : ""}`}
            onClick={() => onItemClick?.(item)}
          >
            {type === "folder" ? <Icons.Folder /> : <Icons.File />}
            <span>{item.replace(/\/$/, "")}</span>
          </div>
        );
      })}
    </div>
  );
}

// 文件树（层级显示）
export function ToolFileTree({
  items,
  onItemClick,
  level = 0,
}: ToolFileTreeProps & { level?: number }) {
  // 如果是字符串数组，转换为 DirectoryGrid
  if (items.length > 0 && typeof items[0] === "string") {
    return <DirectoryGrid items={items as string[]} onItemClick={onItemClick as (item: string) => void} />;
  }

  const treeItems = items as FileTreeItem[];

  return (
    <div class="tool-file-tree" style={{ paddingLeft: level > 0 ? "16px" : 0 }}>
      {treeItems.map((item, idx) => (
        <div key={idx}>
          <div
            class={`tool-file-tree__item ${item.type === "folder" ? "tool-file-tree__item--folder" : ""}`}
            onClick={() => onItemClick?.(item)}
          >
            <span class="tool-file-tree__icon">
              {item.type === "folder" ? <Icons.Folder /> : <Icons.File />}
            </span>
            <span class="tool-file-tree__name">{item.name}</span>
          </div>
          {item.children && item.children.length > 0 && (
            <ToolFileTree
              items={item.children}
              onItemClick={onItemClick}
              level={level + 1}
            />
          )}
        </div>
      ))}
    </div>
  );
}

// 文件路径显示
export function FilePath({
  path,
  icon = true,
}: {
  path: string;
  icon?: boolean;
}) {
  return (
    <span class="tool-file-read__path">
      {icon && <Icons.File />}
      {path}
    </span>
  );
}
