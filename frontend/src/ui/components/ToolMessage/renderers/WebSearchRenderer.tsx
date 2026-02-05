import type { ToolRendererProps } from "../types";
import { SearchResultList } from "../components/ResultList";
import { ScrollArea } from "@/ui/components/ui/scroll-area";

export function WebSearchRenderer({ status, args, output }: ToolRendererProps) {
  const query = (args as any)?.query || (args as any)?.q || "";
  
  if (status === "running") {
    return (
      <div className="tool-search">
        <div className="tool-search__query">
          <span className="tool-search__query-icon">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
              <path d="M15.5 14h-.79l-.28-.27C15.41 12.59 16 11.11 16 9.5 16 5.91 13.09 3 9.5 3S3 5.91 3 9.5 5.91 16 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z"/>
            </svg>
          </span>
          <span className="tool-search__query-text">{query}</span>
        </div>
        <div className="tool-running-hint">正在搜索中...</div>
      </div>
    );
  }

  // 解析搜索结果
  let results: Array<{ title: string; url: string; snippet?: string }> = [];
  
  try {
    if (typeof output === "string") {
      const parsed = JSON.parse(output);
      if (Array.isArray(parsed)) {
        results = parsed;
      } else if (parsed.results && Array.isArray(parsed.results)) {
        results = parsed.results;
      }
    } else if (Array.isArray(output)) {
      results = output;
    } else if ((output as any)?.results) {
      results = (output as any).results;
    }
  } catch {
    // 非 JSON 格式
  }

  if (results.length === 0 && typeof output === "string") {
    results = parsePlainTextResults(output);
  }

  return (
    <div className="tool-search">
      <div className="tool-search__query">
        <span className="tool-search__query-icon">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
            <path d="M15.5 14h-.79l-.28-.27C15.41 12.59 16 11.11 16 9.5 16 5.91 13.09 3 9.5 3S3 5.91 3 9.5 5.91 16 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z"/>
          </svg>
        </span>
        <span className="tool-search__query-text">{query}</span>
      </div>
      
      {results.length > 0 ? (
        <SearchResultList results={results} />
      ) : (
        <ScrollArea className="tool-scroll">
          <div className="tool-plain">
            {typeof output === "string" ? output : JSON.stringify(output, null, 2)}
          </div>
        </ScrollArea>
      )}
    </div>
  );
}

function parsePlainTextResults(text: string): Array<{ title: string; url: string }> {
  const lines = text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);

  const results: Array<{ title: string; url: string }> = [];
  let pendingTitle: string | null = null;

  for (const line of lines) {
    const urlMatch = line.match(/https?:\/\/\S+/i);
    if (urlMatch) {
      const url = urlMatch[0];
      const title = line.replace(url, "").trim() || pendingTitle || url;
      results.push({ title, url });
      pendingTitle = null;
      continue;
    }

    // 形如 "标题 - https://..."
    const splitMatch = line.match(/(.+?)\s+(https?:\/\/\S+)/i);
    if (splitMatch) {
      results.push({ title: splitMatch[1].trim(), url: splitMatch[2] });
      pendingTitle = null;
      continue;
    }

    pendingTitle = line;
  }

  return results;
}
