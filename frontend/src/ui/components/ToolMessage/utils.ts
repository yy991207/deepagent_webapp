
export function parsePlainTextResults(text: string): Array<{ title: string; url: string }> {
  const lines = text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);

  const results: Array<{ title: string; url: string }> = [];
  let pendingLines: string[] = [];

  for (const line of lines) {
    const urlMatch = line.match(/https?:\/\/\S+/i);
    
    // 如果这一行包含 URL
    if (urlMatch) {
      const url = urlMatch[0];
      
      // 检查是否是 "Title - URL" 这种格式
      const textWithoutUrl = line.replace(url, "").trim();
      
      let title = "";
      
      if (textWithoutUrl.length > 0) {
        // 如果同一行还有其他文本，优先作为标题
        title = textWithoutUrl;
        // 之前的 pendingLines 可能是上一条的孤儿文本，或者这一条的描述
        pendingLines = []; 
      } else if (pendingLines.length > 0) {
        // 使用之前的行作为标题
        title = pendingLines.join(" ");
        pendingLines = [];
      } else {
        // 没有标题，使用 URL
        title = url;
      }
      
      // 清理标题中的特殊字符
      title = title.replace(/^-\s*/, "").replace(/^-/, "").trim();
      
      results.push({ title, url });
      continue;
    }

    // 不包含 URL，存入 pendingLines
    pendingLines.push(line);
  }

  return results;
}

export function tryParseSearchResults(output: unknown): Array<{ title: string; url: string; snippet?: string }> {
  let results: Array<{ title: string; url: string; snippet?: string }> = [];
  try {
    if (typeof output === "string") {
      // 尝试解析 JSON
      if (output.trim().startsWith("{") || output.trim().startsWith("[")) {
        const parsed = JSON.parse(output);
        if (Array.isArray(parsed)) {
          results = parsed;
        } else if (parsed.results && Array.isArray(parsed.results)) {
          results = parsed.results;
        }
      }
    } else if (Array.isArray(output)) {
      results = output;
    } else if ((output as any)?.results) {
      results = (output as any).results;
    }
  } catch {
    // 非 JSON 格式或解析失败
  }
  
  if (results.length === 0 && typeof output === "string") {
    results = parsePlainTextResults(output);
  }
  
  // 简单的验证，确保至少有 title 或 url
  return results.filter(r => (r.title || r.url) && typeof r.url === 'string');
}
