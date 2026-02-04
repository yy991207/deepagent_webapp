import type { ReactNode } from "react";

export interface ResultListItem {
  id?: string;
  title?: string;
  subtitle?: string;
  content?: ReactNode;
  url?: string;
  score?: number;
  metadata?: Record<string, unknown>;
}

export interface ResultListProps {
  items: ResultListItem[];
  emptyMessage?: string;
  onItemClick?: (item: ResultListItem, index: number) => void;
  renderItem?: (item: ResultListItem, index: number) => ReactNode;
}

// 默认项目渲染器
function DefaultResultItem({
  item,
  onClick,
}: {
  item: ResultListItem;
  onClick?: () => void;
}) {
  return (
    <div
      className={`tool-result-item ${onClick ? "tool-result-item--clickable" : ""}`}
      onClick={onClick}
    >
      {item.title && (
        <div className="tool-result-item__title">{item.title}</div>
      )}
      {item.subtitle && (
        <div className="tool-result-item__subtitle">{item.subtitle}</div>
      )}
      {item.content && (
        <div className="tool-result-item__content">{item.content}</div>
      )}
      {item.score !== undefined && (
        <span className="tool-result-item__score">
          相关度: {(item.score * 100).toFixed(0)}%
        </span>
      )}
    </div>
  );
}

export function ResultList({
  items,
  emptyMessage = "暂无结果",
  onItemClick,
  renderItem,
}: ResultListProps) {
  if (items.length === 0) {
    return (
      <div className="tool-result-list tool-result-list--empty">
        <span className="tool-result-list__empty-message">{emptyMessage}</span>
      </div>
    );
  }

  return (
    <div className="tool-result-list">
      {items.map((item, index) =>
        renderItem ? (
          <div key={item.id || index} className="tool-result-list__item">
            {renderItem(item, index)}
          </div>
        ) : (
          <DefaultResultItem
            key={item.id || index}
            item={item}
            onClick={onItemClick ? () => onItemClick(item, index) : undefined}
          />
        )
      )}
    </div>
  );
}

// 搜索结果专用组件
export interface SearchResult {
  title: string;
  url: string;
  snippet?: string;
}

export function SearchResultList({
  results,
  onResultClick,
}: {
  results: SearchResult[];
  onResultClick?: (result: SearchResult) => void;
}) {
  return (
    <div className="tool-search__results">
      {results.map((result, idx) => (
        <div key={idx} className="tool-search__result">
          <a
            className="tool-search__result-title"
            href={result.url}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => {
              if (onResultClick) {
                e.preventDefault();
                onResultClick(result);
              }
            }}
          >
            {result.title}
          </a>
          <div className="tool-search__result-url">{result.url}</div>
          {result.snippet && (
            <div className="tool-search__result-snippet">{result.snippet}</div>
          )}
        </div>
      ))}
    </div>
  );
}

// RAG 结果专用组件
export interface RagResult {
  source: string;
  content: string;
  score?: number;
}

export function RagResultList({ results }: { results: RagResult[] }) {
  return (
    <div className="tool-rag__results">
      {results.map((result, idx) => (
        <div key={idx} className="tool-rag__result">
          <div className="tool-rag__result-header">
            <span className="tool-rag__result-source">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z" />
                <polyline points="14,2 14,8 20,8" />
              </svg>
              {result.source}
            </span>
            {result.score !== undefined && (
              <span className="tool-rag__result-score">
                {(result.score * 100).toFixed(0)}%
              </span>
            )}
          </div>
          <div className="tool-rag__result-content">{result.content}</div>
        </div>
      ))}
    </div>
  );
}
