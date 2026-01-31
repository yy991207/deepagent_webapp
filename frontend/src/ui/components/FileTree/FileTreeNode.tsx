import { useCallback, useRef } from "preact/hooks";
import type { SourceItem, SourceTreeNode, DragState, DragPosition } from "../../types";
import { KebabMenu } from "./KebabMenu";
import { FileIcon } from "./FileIcon";

export type FileTreeNodeProps = {
  node: SourceTreeNode;
  depth: number;
  selectedId: string | null;
  checkedIds: Set<string>;
  dragState: DragState;
  openMenuId: string | null;
  onSelect: (item: SourceItem) => void;
  onToggleExpand: (id: string) => void;
  onToggleCheck: (id: string) => void;
  onDragStart: (id: string) => void;
  onDragOver: (id: string, position: DragPosition) => void;
  onDragEnd: () => void;
  onMenuAction: (action: string, item: SourceItem) => void;
  onMenuToggle: (id: string) => void;
  onMenuClose: () => void;
};

export function FileTreeNode({
  node,
  depth,
  selectedId,
  checkedIds,
  dragState,
  openMenuId,
  onSelect,
  onToggleExpand,
  onToggleCheck,
  onDragStart,
  onDragOver,
  onDragEnd,
  onMenuAction,
  onMenuToggle,
  onMenuClose,
}: FileTreeNodeProps) {
  const nodeRef = useRef<HTMLDivElement>(null);
  const menuOpen = openMenuId === node.id;

  const isFolder = node.item_type === "folder";
  const isSelected = selectedId === node.id;
  const isChecked = checkedIds.has(node.id);
  const isDragging = dragState.draggedId === node.id;
  const isDropTarget = dragState.targetId === node.id;

  // 计算拖拽位置样式
  const getDropIndicatorClass = () => {
    if (!isDropTarget || !dragState.position) return "";
    return `drop-${dragState.position}`;
  };

  const handleClick = useCallback(
    (e: MouseEvent) => {
      e.stopPropagation();
      if (isFolder) {
        onToggleExpand(node.id);
      } else {
        onSelect(node);
      }
    },
    [isFolder, node, onSelect, onToggleExpand]
  );

  const handleCheckboxClick = useCallback(
    (e: MouseEvent) => {
      e.stopPropagation();
      onToggleCheck(node.id);
    },
    [node.id, onToggleCheck]
  );

  const handleDragStart = useCallback(
    (e: DragEvent) => {
      e.stopPropagation();
      if (e.dataTransfer) {
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("text/plain", node.id);
      }
      onDragStart(node.id);
    },
    [node.id, onDragStart]
  );

  const handleDragOver = useCallback(
    (e: DragEvent) => {
      e.preventDefault();
      e.stopPropagation();

      if (dragState.draggedId === node.id) return;

      const rect = nodeRef.current?.getBoundingClientRect();
      if (!rect) return;

      const y = e.clientY - rect.top;
      const height = rect.height;

      let position: DragPosition;
      if (isFolder) {
        // 文件夹：上 1/4 = before，中 1/2 = inside，下 1/4 = after
        if (y < height * 0.25) {
          position = "before";
        } else if (y > height * 0.75) {
          position = "after";
        } else {
          position = "inside";
        }
      } else {
        // 文件：上半 = before，下半 = after
        position = y < height / 2 ? "before" : "after";
      }

      onDragOver(node.id, position);
    },
    [dragState.draggedId, isFolder, node.id, onDragOver]
  );

  const handleDragEnd = useCallback(
    (e: DragEvent) => {
      e.stopPropagation();
      onDragEnd();
    },
    [onDragEnd]
  );

  const handleMenuClick = useCallback((e: MouseEvent) => {
    e.stopPropagation();
    onMenuToggle(node.id);
  }, [node.id, onMenuToggle]);

  const handleMenuAction = useCallback(
    (action: string) => {
      onMenuClose();
      onMenuAction(action, node);
    },
    [node, onMenuAction, onMenuClose]
  );

  // SVG 图标
  const iconRename = (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
      <path d="M12.146.146a.5.5 0 0 1 .708 0l3 3a.5.5 0 0 1 0 .708l-10 10a.5.5 0 0 1-.168.11l-5 2a.5.5 0 0 1-.65-.65l2-5a.5.5 0 0 1 .11-.168l10-10zM11.207 2.5 13.5 4.793 14.793 3.5 12.5 1.207 11.207 2.5zm1.586 3L10.5 3.207 4 9.707V10h.5a.5.5 0 0 1 .5.5v.5h.5a.5.5 0 0 1 .5.5v.5h.293l6.5-6.5zm-9.761 5.175-.106.106-1.528 3.821 3.821-1.528.106-.106A.5.5 0 0 1 5 12.5V12h-.5a.5.5 0 0 1-.5-.5V11h-.5a.5.5 0 0 1-.468-.325z"/>
    </svg>
  );
  const iconImport = (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
      <path d="M.5 9.9a.5.5 0 0 1 .5.5v2.5a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-2.5a.5.5 0 0 1 1 0v2.5a2 2 0 0 1-2 2H2a2 2 0 0 1-2-2v-2.5a.5.5 0 0 1 .5-.5z"/>
      <path d="M7.646 1.146a.5.5 0 0 1 .708 0l3 3a.5.5 0 0 1-.708.708L8.5 2.707V11.5a.5.5 0 0 1-1 0V2.707L5.354 4.854a.5.5 0 1 1-.708-.708l3-3z"/>
    </svg>
  );
  const iconNewFolder = (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
      <path d="M.54 3.87.5 3a2 2 0 0 1 2-2h3.672a2 2 0 0 1 1.414.586l.828.828A2 2 0 0 0 9.828 3h3.982a2 2 0 0 1 1.992 2.181L15.546 8H14.54l.265-2.91A1 1 0 0 0 13.81 4H9.828a3 3 0 0 1-2.12-.879l-.83-.828A1 1 0 0 0 6.173 2H2.5a1 1 0 0 0-1 .981L1.546 4h-1L.54 3.87z"/>
      <path d="M7.5 9.5a.5.5 0 0 1 1 0V11h1.5a.5.5 0 0 1 0 1H8.5v1.5a.5.5 0 0 1-1 0V12H6a.5.5 0 0 1 0-1h1.5V9.5z"/>
    </svg>
  );
  const iconDuplicate = (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
      <path d="M4 2a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V2zm2-1a1 1 0 0 0-1 1v8a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1V2a1 1 0 0 0-1-1H6zM2 5a1 1 0 0 0-1 1v8a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1v-1h1v1a2 2 0 0 1-2 2H2a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h1v1H2z"/>
    </svg>
  );
  const iconMove = (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
      <path d="M.54 3.87.5 3a2 2 0 0 1 2-2h3.672a2 2 0 0 1 1.414.586l.828.828A2 2 0 0 0 9.828 3h3.982a2 2 0 0 1 1.992 2.181l-.637 7A2 2 0 0 1 13.174 14H2.826a2 2 0 0 1-1.991-1.819l-.637-7a1.99 1.99 0 0 1 .342-1.31z"/>
    </svg>
  );
  const iconDelete = (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
      <path d="M5.5 5.5A.5.5 0 0 1 6 6v6a.5.5 0 0 1-1 0V6a.5.5 0 0 1 .5-.5zm2.5 0a.5.5 0 0 1 .5.5v6a.5.5 0 0 1-1 0V6a.5.5 0 0 1 .5-.5zm3 .5a.5.5 0 0 0-1 0v6a.5.5 0 0 0 1 0V6z"/>
      <path fill-rule="evenodd" d="M14.5 3a1 1 0 0 1-1 1H13v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V4h-.5a1 1 0 0 1-1-1V2a1 1 0 0 1 1-1H6a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1h3.5a1 1 0 0 1 1 1v1zM4.118 4 4 4.059V13a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1V4.059L11.882 4H4.118zM2.5 3V2h11v1h-11z"/>
    </svg>
  );

  const menuItems = isFolder
    ? [
        { id: "rename", label: "重命名", icon: iconRename },
        { id: "import", label: "导入文件", icon: iconImport },
        { id: "new-folder", label: "新建子文件夹", icon: iconNewFolder },
        { id: "duplicate", label: "复制", icon: iconDuplicate },
        { id: "delete", label: "删除", icon: iconDelete, danger: true },
      ]
    : [
        { id: "rename", label: "重命名", icon: iconRename },
        { id: "duplicate", label: "复制", icon: iconDuplicate },
        { id: "move", label: "移动到...", icon: iconMove },
        { id: "delete", label: "删除", icon: iconDelete, danger: true },
      ];

  return (
    <div class="file-tree-node-wrapper">
      <div
        ref={nodeRef}
        class={[
          "file-tree-node",
          isSelected && "selected",
          isDragging && "dragging",
          isDropTarget && getDropIndicatorClass(),
        ]
          .filter(Boolean)
          .join(" ")}
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
        draggable
        onClick={handleClick}
        onDragStart={handleDragStart}
        onDragOver={handleDragOver}
        onDragEnd={handleDragEnd}
      >
        {/* 展开/折叠按钮（仅文件夹） */}
        {isFolder && (
          <span
            class={`expand-icon ${node.expanded ? "expanded" : ""}`}
            onClick={(e) => {
              e.stopPropagation();
              onToggleExpand(node.id);
            }}
          >
            <svg width="12" height="12" viewBox="0 0 12 12">
              <path
                d="M4 2 L8 6 L4 10"
                fill="none"
                stroke="currentColor"
                stroke-width="1.5"
              />
            </svg>
          </span>
        )}
        {!isFolder && <span class="expand-icon-placeholder" />}

        {/* 复选框（仅文件） */}
        {!isFolder && (
          <span
            class={`file-checkbox ${isChecked ? "checked" : ""}`}
            onClick={handleCheckboxClick}
            title={isChecked ? "取消选中" : "选中此文件"}
          >
            {isChecked ? (
              <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor">
                <path d="M14 1a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H2a1 1 0 0 1-1-1V2a1 1 0 0 1 1-1h12zM2 0a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V2a2 2 0 0 0-2-2H2z"/>
                <path d="M10.97 4.97a.75.75 0 0 1 1.071 1.05l-3.992 4.99a.75.75 0 0 1-1.08.02L4.324 8.384a.75.75 0 1 1 1.06-1.06l2.094 2.093 3.473-4.425a.236.236 0 0 1 .02-.022z"/>
              </svg>
            ) : (
              <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor">
                <path d="M14 1a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H2a1 1 0 0 1-1-1V2a1 1 0 0 1 1-1h12zM2 0a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V2a2 2 0 0 0-2-2H2z"/>
              </svg>
            )}
          </span>
        )}

        {/* 文件图标 */}
        <FileIcon type={isFolder ? "folder" : (node.file_type || "file")} expanded={node.expanded} />

        {/* 文件名 */}
        <span class="file-name" title={node.filename}>
          {node.filename}
        </span>

        {/* 三点菜单 */}
        <button
          class="kebab-menu-trigger"
          onClick={handleMenuClick}
          title="更多操作"
        >
          <svg width="16" height="16" viewBox="0 0 16 16">
            <circle cx="8" cy="3" r="1.5" fill="currentColor" />
            <circle cx="8" cy="8" r="1.5" fill="currentColor" />
            <circle cx="8" cy="13" r="1.5" fill="currentColor" />
          </svg>
        </button>

        {menuOpen && (
          <KebabMenu
            items={menuItems}
            onAction={handleMenuAction}
            onClose={onMenuClose}
          />
        )}
      </div>

      {/* 子节点 */}
      {isFolder && node.expanded && node.children.length > 0 && (
        <div class="file-tree-children">
          {node.children.map((child) => (
            <FileTreeNode
              key={child.id}
              node={child}
              depth={depth + 1}
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
              onMenuToggle={onMenuToggle}
              onMenuClose={onMenuClose}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export default FileTreeNode;
