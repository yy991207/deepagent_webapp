import type { ReactNode } from "react";
import { useEffect, useRef } from "react";

export type MenuItem = {
  id: string;
  label: string;
  icon?: ReactNode;
  danger?: boolean;
};

export type KebabMenuProps = {
  items: MenuItem[];
  onAction: (action: string) => void;
  onClose: () => void;
};

export function KebabMenu({ items, onAction, onClose }: KebabMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        onClose();
      }
    };

    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
      }
    };

    // 延迟添加监听器，避免立即触发
    setTimeout(() => {
      document.addEventListener("click", handleClickOutside);
      document.addEventListener("keydown", handleEscape);
    }, 0);

    return () => {
      document.removeEventListener("click", handleClickOutside);
      document.removeEventListener("keydown", handleEscape);
    };
  }, [onClose]);

  return (
    <div ref={menuRef} className="kebab-menu">
      {items.map((item) => (
        <button
          key={item.id}
          className={`kebab-menu-item ${item.danger ? "danger" : ""}`}
          onClick={(e) => {
            e.stopPropagation();
            onAction(item.id);
          }}
        >
          {item.icon && <span className="menu-icon">{item.icon}</span>}
          <span className="menu-label">{item.label}</span>
        </button>
      ))}
    </div>
  );
}

export default KebabMenu;
