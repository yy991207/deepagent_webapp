import type { ReactNode } from "react";
import type { RagReference } from "../../types";
import { maxRefIndex, extractUrlReferences, getFaviconUrl } from "../../types/utils";

export function AssistantContent({
  text,
  isPending,
  references,
  onOpenRef,
}: {
  text: string;
  isPending: boolean;
  references?: RagReference[];
  onOpenRef: (idx: number) => void;
}) {
  if (isPending && !text) {
    return (
      <div className="assistant-thinking">
        <span className="dot" />
        <span className="dot" />
        <span className="dot" />
      </div>
    );
  }

  const urlStartIndex = maxRefIndex(references) + 1;
  const extracted = extractUrlReferences(text, urlStartIndex);
  const urlRefs = extracted.urlRefs;
  const processedText = extracted.text;

  const renderInline = (value: string) => {
    const nodes: Array<ReactNode> = [];
    const re = /(\[(\d+)\])|(\*\*(.*?)\*\*)|(\*(.*?)\*)/g;
    let lastIdx = 0;
    let mm: RegExpExecArray | null;

    while ((mm = re.exec(value)) !== null) {
      const start = mm.index;
      const end = start + mm[0].length;

      if (start > lastIdx) {
        nodes.push(value.slice(lastIdx, start));
      }

      if (mm[1]) {
        const idx = Number(mm[2]);
        const ragExists = (references || []).some((r) => r.index === idx);
        const urlRef = urlRefs.find((r) => r.index === idx);
        if (ragExists) {
          nodes.push(
            <button
              key={`ref-${start}-${idx}`}
              type="button"
              className="ref-chip"
              onClick={() => onOpenRef(idx)}
              title="查看引用"
            >
              [{idx}]
            </button>,
          );
        } else if (urlRef) {
          const iconUrl = getFaviconUrl(urlRef.url);
          nodes.push(
            <a
              key={`url-${start}-${idx}`}
              className="ref-chip ref-link"
              href={urlRef.url}
              target="_blank"
              rel="noreferrer"
              title={urlRef.url}
            >
              {iconUrl ? <img className="ref-favicon" src={iconUrl} alt="" loading="lazy" /> : null}
              [{idx}]
            </a>,
          );
        } else {
          // 无对应 references 数据时，渲染为纯文本而非按钮
          nodes.push(<span key={`txt-${start}-${idx}`} className="ref-text-only">[{idx}]</span>);
        }
      } else if (mm[3]) {
        nodes.push(<strong key={`bold-${start}`} className="md-bold">{mm[4]}</strong>);
      } else if (mm[5]) {
        nodes.push(<em key={`em-${start}`} className="md-italic">{mm[6]}</em>);
      }

      lastIdx = end;
    }

    if (lastIdx < value.length) {
      nodes.push(value.slice(lastIdx));
    }
    return nodes;
  };

  const renderMarkdownBlocks = (src: string) => {
    const lines = src.replace(/\r\n/g, "\n").split("\n");
    const blocks: ReactNode[] = [];
    let i = 0;
    let blockIdx = 0;

    while (i < lines.length) {
      const line = lines[i];

      if (line.trim().startsWith("```")) {
        const lang = line.trim().slice(3).trim();
        i += 1;
        const codeLines: string[] = [];
        while (i < lines.length && !lines[i].trim().startsWith("```")) {
          codeLines.push(lines[i]);
          i += 1;
        }
        i += 1;
        blocks.push(
          <div key={`code-${blockIdx++}`} className="md-code-block">
            {lang && <div className="md-code-lang">{lang}</div>}
            <pre className="md-code" data-lang={lang || undefined}>
              <code>{codeLines.join("\n")}</code>
            </pre>
          </div>
        );
        continue;
      }

      const heading = /^\s{0,3}(#{1,6})\s+(.*)$/.exec(line);
      if (heading) {
        const level = heading[1].length;
        const content = heading[2] || "";
        const Tag = (`h${Math.min(level, 6)}` as unknown) as any;
        blocks.push(<Tag key={`h-${blockIdx++}`} className={`md-heading h${level}`}>{renderInline(content)}</Tag>);
        i += 1;
        continue;
      }

      if (line.trim().startsWith("|") && i + 1 < lines.length && lines[i+1].trim().includes("|---")) {
        const rows: string[][] = [];
        rows.push(line.split("|").filter(s => s.trim()).map(s => s.trim()));
        i += 2;
        while (i < lines.length && lines[i].trim().startsWith("|")) {
          rows.push(lines[i].split("|").filter(s => s.trim()).map(s => s.trim()));
          i += 1;
        }
        blocks.push(
          <div key={`table-${blockIdx++}`} className="md-table-wrapper">
            <table className="md-table">
              <thead>
                <tr>{rows[0].map((cell, ci) => <th key={ci}>{renderInline(cell)}</th>)}</tr>
              </thead>
              <tbody>
                {rows.slice(1).map((row, ri) => (
                  <tr key={ri}>{row.map((cell, ci) => <td key={ci}>{renderInline(cell)}</td>)}</tr>
                ))}
              </tbody>
            </table>
          </div>
        );
        continue;
      }

      const bullet = /^\s*[-*]\s+(.*)$/.exec(line);
      if (bullet) {
        const items: ReactNode[] = [];
        let itemIdx = 0;
        while (i < lines.length) {
          const m = /^\s*[-*]\s+(.*)$/.exec(lines[i]);
          if (!m) break;
          items.push(<li key={itemIdx++}>{renderInline(m[1] || "")}</li>);
          i += 1;
        }
        blocks.push(<ul key={`ul-${blockIdx++}`} className="md-ul">{items}</ul>);
        continue;
      }

      const numbered = /^\s*(\d+)\.\s+(.*)$/.exec(line);
      if (numbered) {
        const items: ReactNode[] = [];
        let itemIdx = 0;
        while (i < lines.length) {
          const m = /^\s*(\d+)\.\s+(.*)$/.exec(lines[i]);
          if (!m) break;
          items.push(<li key={itemIdx++}>{renderInline(m[2] || "")}</li>);
          i += 1;
        }
        blocks.push(<ol key={`ol-${blockIdx++}`} className="md-ol">{items}</ol>);
        continue;
      }

      if (!line.trim()) {
        i += 1;
        continue;
      }

      const paraLines: string[] = [line];
      i += 1;
      while (i < lines.length && lines[i].trim() &&
             !lines[i].trim().startsWith("```") &&
             !/^\s{0,3}#{1,6}\s+/.test(lines[i]) &&
             !/^\s*[-*]\s+/.test(lines[i]) &&
             !/^\s*\d+\.\s+/.test(lines[i]) &&
             !lines[i].trim().startsWith("|")) {
        paraLines.push(lines[i]);
        i += 1;
      }
      blocks.push(<p key={`p-${blockIdx++}`} className="md-p">{renderInline(paraLines.join("\n"))}</p>);
    }

    return blocks;
  };

  return <div className="md-root">{renderMarkdownBlocks(processedText)}</div>;
}
