import { useCallback, useRef, useState } from "preact/hooks";
import type { SourceItem, SourceTreeNode, DragState, DragPosition } from "../../types";
import { FileTreeNode } from "./FileTreeNode";
import "./FileTree.css";

export type FileTreeProps = {
  items: SourceItem[];
  expandedIds: Set<string>;
  selectedId: string | null;
  checkedIds: Set<string>;
  dragState: DragState;
  onSelect: (item: SourceItem) => void;
  onToggleExpand: (id: string) => void;
  onToggleCheck: (id: string) => void;
  onDragStart: (id: string) => void;
  onDragOver: (id: string, position: DragPosition) => void;
  onDragEnd: () => void;
  onDrop: () => void;
  onMenuAction: (action: string, item: SourceItem) => void;
};

// 构建树形结构
function buildTree(items: SourceItem[], expandedIds: Set<string>): SourceTreeNode[] {
  const map = new Map<string, SourceTreeNode>();
  const roots: SourceTreeNode[] = [];

  // 先创建所有节点
  for (const item of items) {
    map.set(item.id, {
      ...item,
      children: [],
      expanded: expandedIds.has(item.id),
    });
  }

  // 再建立父子关系
  for (const item of items) {
    const node = map.get(item.id)!;
    if (item.parent_id && map.has(item.parent_id)) {
      map.get(item.parent_id)!.children.push(node);
    } else {
      roots.push(node);
    }
  }

  // 排序：文件夹在前，然后按 sort_order
  const sortNodes = (nodes: SourceTreeNode[]) => {
    nodes.sort((a, b) => {
      if (a.item_type !== b.item_type) {
        return a.item_type === "folder" ? -1 : 1;
      }
      return a.sort_order - b.sort_order;
    });
    for (const node of nodes) {
      if (node.children.length > 0) {
        sortNodes(node.children);
      }
    }
  };

  sortNodes(roots);
  return roots;
}

export function FileTree({
  items,
  expandedIds,
  selectedId,
  checkedIds,
  dragState,
  onSelect,
  onToggleExpand,
  onToggleCheck,
  onDragStart,
  onDragOver,
  onDragEnd,
  onDrop,
  onMenuAction,
}: FileTreeProps) {
  const tree = buildTree(items, expandedIds);
  const containerRef = useRef<HTMLDivElement>(null);
  // 当前打开菜单的节点 ID，确保同时只有一个菜单打开
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);

  const handleDragOver = useCallback(
    (e: DragEvent) => {
      e.preventDefault();
    },
    []
  );

  const handleDrop = useCallback(
    (e: DragEvent) => {
      e.preventDefault();
      onDrop();
    },
    [onDrop]
  );

  const handleMenuToggle = useCallback((id: string) => {
    setOpenMenuId((prev) => (prev === id ? null : id));
  }, []);

  const handleMenuClose = useCallback(() => {
    setOpenMenuId(null);
  }, []);

  return (
    <div
      ref={containerRef}
      class="file-tree"
      onDragOver={handleDragOver}
      onDrop={handleDrop}
    >
      {tree.length === 0 ? (
        <div class="file-tree-empty">暂无数据源</div>
      ) : (
        tree.map((node) => (
          <FileTreeNode
            key={node.id}
            node={node}
            depth={0}
            selectedId={selectedId}
            checkedIds={checkedIds}
            dragState={dragState}
            openMenuId={openMenuId}
            onSelect={onSelect}
            onToggleExpand={onToggleExpand}
            onToggleCheck={onToggleCheck}
            onDragStart={onDragStart}
            onDragOver={onDragOver}
            onDragEnd={onDragEnd}
            onMenuAction={onMenuAction}
            onMenuToggle={handleMenuToggle}
            onMenuClose={handleMenuClose}
          />
        ))
      )}
    </div>
  );
}

export default FileTree;
