import type { ToolRendererProps } from "../types";
import { Badge } from "@/ui/components/ui/badge";
import { ScrollArea } from "@/ui/components/ui/scroll-area";
import { SearchResultList } from "../components/ResultList";
import { tryParseSearchResults } from "../utils";

function extractText(value: unknown): string {
  if (typeof value === "string") return value.trim();
  if (value == null) return "";
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return value.map((item) => extractText(item)).filter(Boolean).join("\n");
  if (typeof value === "object") {
    const obj = value as Record<string, unknown>;
    const candidateKeys = ["value", "content", "text", "result", "output", "summary", "answer"];
    for (const key of candidateKeys) {
      const text = extractText(obj[key]);
      if (text) return text;
    }
  }
  return "";
}

function extractKeyValues(value: unknown): Array<{ label: string; text: string }> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return [];
  const obj = value as Record<string, unknown>;
  return Object.keys(obj)
    .map((key) => ({
      label: key,
      text: extractText(obj[key]),
    }))
    .filter((item) => item.text);
}

export function TaskRenderer({ status, args, output }: ToolRendererProps) {
  const desc = (args as any)?.description || (args as any)?.task || "";
  const subagent = (args as any)?.subagent_type || "";
  
  // 尝试解析搜索结果 (直接结果或 history 中的结果)
  let searchResults: Array<{ title: string; url: string; snippet?: string }> = [];
  
  if (status === "done") {
    // 1. 尝试直接解析 output
    searchResults = tryParseSearchResults(output);
    
    // 2. 如果直接解析没有结果，尝试从 history 中提取
    if (searchResults.length === 0 && output) {
      try {
        let history = null;
        if (typeof output === "object") {
           // 检查 output 是否包含 history
           history = (output as any).history;
        }
        
        // 有时候 output 本身就是 history 数组
        if (!history && Array.isArray(output)) {
           // 检查元素是否像 history items
           if (output.some(item => item?.tool || item?.action)) {
             history = output;
           }
        }
        
        if (history && Array.isArray(history)) {
          // 遍历 history 寻找 web_search 的结果
          for (const item of history) {
            // 假设 item 结构类似 { tool: "web_search", output: ... }
            if (item?.tool === "web_search" || item?.action === "web_search") {
               const itemResults = tryParseSearchResults(item.output || item.result);
               if (itemResults.length > 0) {
                 searchResults = searchResults.concat(itemResults);
               }
            }
          }
        }
      } catch (e) {
        // ignore parsing errors
      }
    }
  }

  const resultText = extractText(output);
  const kvItems = resultText ? [] : extractKeyValues(output);
  const hasResult = resultText || kvItems.length > 0 || searchResults.length > 0;

  return (
    <div className="w-full font-sans text-sm">
      {(desc || subagent) && (
        <div className="flex flex-wrap gap-2 mb-2 items-center">
          {subagent && (
            <Badge variant="secondary" className="bg-zinc-100 text-zinc-600 hover:bg-zinc-200 border-zinc-200">
              {subagent}
            </Badge>
          )}
          {desc && <span className="text-zinc-600">{desc}</span>}
        </div>
      )}
      
      {status === "done" && (
        <div className="flex flex-col gap-2">
          {searchResults.length > 0 ? (
            <SearchResultList results={searchResults} />
          ) : hasResult ? (
            resultText ? (
              <ScrollArea className="tool-scroll">
                <div className="tool-plain text-zinc-600">
                  {resultText}
                </div>
              </ScrollArea>
            ) : (
              <div className="tool-kv">
                {kvItems.map((item, idx) => (
                  <div key={`${item.label}-${idx}`} className="tool-kv__row">
                    <div className="tool-kv__key">{item.label}</div>
                    <div className="tool-kv__value">{item.text}</div>
                  </div>
                ))}
              </div>
            )
          ) : (
             <div className="text-zinc-400 italic">暂无结果</div>
          )}
        </div>
      )}
      
      {status !== "done" && !desc && (
        <div className="text-zinc-400 italic">正在执行子任务...</div>
      )}
    </div>
  );
}
