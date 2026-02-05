import { type ReactNode, useState } from "react";

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

function Favicon({ url }: { url: string }) {
  const [error, setError] = useState(false);

  const getFaviconUrl = (u: string) => {
    try {
      const domain = new URL(u).hostname;
      return `https://www.google.com/s2/favicons?domain=${domain}&sz=128`;
    } catch {
      return "";
    }
  };

  if (error) {
    return (
      <svg 
        width="10" 
        height="10" 
        viewBox="0 0 24 24" 
        fill="none" 
        stroke="currentColor" 
        strokeWidth="2"
        className="text-muted-foreground"
      >
        <circle cx="11" cy="11" r="8"></circle>
        <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
      </svg>
    );
  }

  return (
    <img
      src={getFaviconUrl(url)}
      alt=""
      className="w-full h-full object-cover"
      onError={() => setError(true)}
    />
  );
}

export function SearchResultList({
  results,
  onResultClick,
}: {
  results: SearchResult[];
  onResultClick?: (result: SearchResult) => void;
}) {
  const getDomain = (url: string) => {
    try {
      return new URL(url).hostname;
    } catch {
      return "";
    }
  };

  return (
    <div className="flex flex-col gap-2 p-1">
      {results.map((result, idx) => {
        const domain = getDomain(result.url);
        
        return (
          <a
            key={idx}
            href={result.url}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => {
              if (onResultClick) {
                e.preventDefault();
                onResultClick(result);
              }
            }}
            className="group flex items-start gap-3 px-4 py-3 rounded-2xl transition-all border bg-zinc-50/50 border-zinc-100 hover:bg-zinc-100 hover:border-zinc-200 text-left no-underline"
          >
            <div className="flex-shrink-0 mt-0.5">
              <div className="w-5 h-5 rounded-full bg-white border border-zinc-200 flex items-center justify-center overflow-hidden">
                <Favicon url={result.url} />
              </div>
            </div>
            
            <div className="flex-1 min-w-0">
              <div className="font-medium text-sm text-foreground leading-snug mb-1 group-hover:text-blue-600 transition-colors">
                {result.title}
              </div>
              
              <div className="text-xs text-muted-foreground mb-1.5 truncate">
                {domain}
              </div>
              
              {result.snippet && (
                <div className="text-xs text-muted-foreground leading-relaxed line-clamp-2">
                  {result.snippet}
                </div>
              )}
            </div>
          </a>
        );
      })}
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
