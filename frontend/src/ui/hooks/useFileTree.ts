import { useState, useCallback, useEffect } from "react";
import type { SourceItem, DragState, DragPosition } from "../types";

export type FileTreeState = {
  items: SourceItem[];
  expandedIds: Set<string>;
  selectedId: string | null;
  dragState: DragState;
  loading: boolean;
  error: string | null;
};

export type FileTreeActions = {
  fetchTree: () => Promise<void>;
  selectItem: (item: SourceItem) => void;
  toggleExpand: (id: string) => void;
  createFolder: (name: string, parentId?: string | null) => Promise<void>;
  renameItem: (id: string, newName: string) => Promise<void>;
  deleteItem: (id: string, isFolder?: boolean) => Promise<void>;
  duplicateItem: (id: string, targetParentId?: string | null) => Promise<void>;
  moveItem: (id: string, targetParentId: string | null) => Promise<void>;
  reorderItem: (itemId: string, targetId: string, position: DragPosition) => Promise<void>;
  // 拖拽相关
  handleDragStart: (id: string) => void;
  handleDragOver: (id: string, position: DragPosition) => void;
  handleDragEnd: () => void;
  handleDrop: () => void;
};

const initialDragState: DragState = {
  draggedId: null,
  targetId: null,
  position: null,
};

export function useFileTree(): [FileTreeState, FileTreeActions] {
  const [items, setItems] = useState<SourceItem[]>([]);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(() => new Set());
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [dragState, setDragState] = useState<DragState>(initialDragState);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 获取树形结构
  const fetchTree = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await fetch("/api/sources/tree");
      if (!resp.ok) throw new Error("Failed to fetch tree");
      const data = await resp.json();
      setItems(data.items || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }, []);

  // 选中项目
  const selectItem = useCallback((item: SourceItem) => {
    setSelectedId(item.id);
  }, []);

  // 展开/折叠
  const toggleExpand = useCallback((id: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }, []);

  // 创建文件夹
  const createFolder = useCallback(async (name: string, parentId?: string | null) => {
    try {
      const resp = await fetch("/api/sources/folder", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, parent_id: parentId }),
      });
      if (!resp.ok) throw new Error("Failed to create folder");
      await fetchTree();
      // 如果有父文件夹，展开它
      if (parentId) {
        setExpandedIds((prev) => new Set([...prev, parentId]));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
      throw err;
    }
  }, [fetchTree]);

  // 重命名
  const renameItem = useCallback(async (id: string, newName: string) => {
    try {
      const resp = await fetch(`/api/sources/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filename: newName }),
      });
      if (!resp.ok) throw new Error("Failed to rename");
      await fetchTree();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
      throw err;
    }
  }, [fetchTree]);

  // 删除
  const deleteItem = useCallback(async (id: string, isFolder = false) => {
    try {
      const url = isFolder ? `/api/sources/folder/${id}?recursive=true` : `/api/sources/${id}`;
      const resp = await fetch(url, { method: "DELETE" });
      if (!resp.ok) throw new Error("Failed to delete");
      await fetchTree();
      if (selectedId === id) {
        setSelectedId(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
      throw err;
    }
  }, [fetchTree, selectedId]);

  // 复制
  const duplicateItem = useCallback(async (id: string, targetParentId?: string | null) => {
    try {
      const resp = await fetch(`/api/sources/${id}/duplicate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ target_parent_id: targetParentId }),
      });
      if (!resp.ok) throw new Error("Failed to duplicate");
      await fetchTree();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
      throw err;
    }
  }, [fetchTree]);

  // 移动
  const moveItem = useCallback(async (id: string, targetParentId: string | null) => {
    try {
      const resp = await fetch(`/api/sources/${id}/move`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ target_parent_id: targetParentId }),
      });
      if (!resp.ok) throw new Error("Failed to move");
      await fetchTree();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
      throw err;
    }
  }, [fetchTree]);

  // 重排序
  const reorderItem = useCallback(async (itemId: string, targetId: string, position: DragPosition) => {
    try {
      const resp = await fetch("/api/sources/reorder", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ item_id: itemId, target_id: targetId, position }),
      });
      if (!resp.ok) throw new Error("Failed to reorder");
      await fetchTree();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
      throw err;
    }
  }, [fetchTree]);

  // 拖拽开始
  const handleDragStart = useCallback((id: string) => {
    setDragState({
      draggedId: id,
      targetId: null,
      position: null,
    });
  }, []);

  // 拖拽经过
  const handleDragOver = useCallback((id: string, position: DragPosition) => {
    setDragState((prev) => ({
      ...prev,
      targetId: id,
      position,
    }));
  }, []);

  // 拖拽结束
  const handleDragEnd = useCallback(() => {
    setDragState(initialDragState);
  }, []);

  // 放置
  const handleDrop = useCallback(async () => {
    const { draggedId, targetId, position } = dragState;
    if (!draggedId || !targetId || !position || draggedId === targetId) {
      setDragState(initialDragState);
      return;
    }

    try {
      await reorderItem(draggedId, targetId, position);
    } catch {
      // Error is already handled in reorderItem
    } finally {
      setDragState(initialDragState);
    }
  }, [dragState, reorderItem]);

  // 初始加载
  useEffect(() => {
    fetchTree();
  }, [fetchTree]);

  const state: FileTreeState = {
    items,
    expandedIds,
    selectedId,
    dragState,
    loading,
    error,
  };

  const actions: FileTreeActions = {
    fetchTree,
    selectItem,
    toggleExpand,
    createFolder,
    renameItem,
    deleteItem,
    duplicateItem,
    moveItem,
    reorderItem,
    handleDragStart,
    handleDragOver,
    handleDragEnd,
    handleDrop,
  };

  return [state, actions];
}

export default useFileTree;
