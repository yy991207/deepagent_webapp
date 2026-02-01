import { useState } from "preact/hooks";

export interface CodeBlockProps {
  code: string;
  language?: string;
  showLineNumbers?: boolean;
  maxHeight?: number;
  showCopy?: boolean;
  showHeader?: boolean;
}

export function CodeBlock({
  code,
  language,
  showLineNumbers = false,
  maxHeight = 300,
  showCopy = true,
  showHeader = true,
}: CodeBlockProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // 静默失败
    }
  };

  const lines = code.split("\n");

  return (
    <div class="tool-code-block-wrapper">
      {showHeader && (language || showCopy) && (
        <div class="tool-code-header">
          {language && (
            <span class="tool-code-header__language">{language}</span>
          )}
          {showCopy && (
            <button class="tool-code-header__copy" onClick={handleCopy}>
              {copied ? "已复制" : "复制"}
            </button>
          )}
        </div>
      )}
      <pre
        class={`tool-code-block ${showHeader && language ? "tool-code-block--with-header" : ""} ${showLineNumbers ? "tool-code-block--line-numbers" : ""}`}
        style={{ maxHeight: `${maxHeight}px` }}
      >
        {showLineNumbers ? (
          lines.map((line, idx) => (
            <div key={idx} class="tool-code-line">
              <span class="tool-code-line__number">{idx + 1}</span>
              <span class="tool-code-line__content">{line}</span>
            </div>
          ))
        ) : (
          <code>{code}</code>
        )}
      </pre>
    </div>
  );
}

// 简化版代码块（用于命令行）
export function CommandBlock({
  command,
  prompt = "$",
}: {
  command: string;
  prompt?: string;
}) {
  return (
    <div class="tool-shell__command">
      <span class="tool-shell__prompt">{prompt}</span>
      <span class="tool-shell__cmd">{command}</span>
    </div>
  );
}
