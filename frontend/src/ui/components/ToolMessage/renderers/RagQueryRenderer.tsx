import type { ToolRendererProps } from "../types";
import { RagResultList } from "../components/ResultList";
import { ScrollArea } from "@/ui/components/ui/scroll-area";

export function RagQueryRenderer({ status, args, output }: ToolRendererProps) {
  const query = (args as any)?.query || (args as any)?.q || "";
  
  if (status === "running") {
    return (
      <div className="tool-rag">
        <div className="tool-search__query">
          <span className="tool-search__query-icon">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
              <path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z"/>
              <polyline points="14,2 14,8 20,8"/>
            </svg>
          </span>
          <span className="tool-search__query-text">{query}</span>
        </div>
        <div className="tool-running-hint">正在检索知识库...</div>
      </div>
    );
  }

  // 解析 RAG 结果
  let results: Array<{ source: string; content: string; score?: number }> = [];
  
  try {
    if (typeof output === "string") {
      const parsed = JSON.parse(output);
      if (Array.isArray(parsed)) {
        results = parsed.map((r: any) => ({
          source: r.source || r.filename || r.doc_id || "未知来源",
          content: r.content || r.text || r.chunk || "",
          score: r.score || r.similarity,
        }));
      } else if (parsed.results && Array.isArray(parsed.results)) {
        results = parsed.results.map((r: any) => ({
          source: r.source || r.filename || r.doc_id || "未知来源",
          content: r.content || r.text || r.chunk || "",
          score: r.score || r.similarity,
        }));
      }
    } else if (Array.isArray(output)) {
      results = output.map((r: any) => ({
        source: r.source || r.filename || r.doc_id || "未知来源",
        content: r.content || r.text || r.chunk || "",
        score: r.score || r.similarity,
      }));
    }
  } catch {
    // 非 JSON 格式
  }

  return (
    <div className="tool-rag">
      <div className="tool-search__query">
        <span className="tool-search__query-icon">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
            <path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z"/>
            <polyline points="14,2 14,8 20,8"/>
          </svg>
        </span>
        <span className="tool-search__query-text">{query}</span>
      </div>
      
      {results.length > 0 ? (
        <RagResultList results={results} />
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
