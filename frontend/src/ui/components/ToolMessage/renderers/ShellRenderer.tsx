import type { ToolRendererProps } from "../types";
import { CommandBlock, CodeBlock } from "../components/CodeBlock";
import { Icons } from "../Icons";

export function ShellRenderer({ status, args, output }: ToolRendererProps) {
  const command = (args as any)?.command || (args as any)?.cmd || "";
  const cwd = (args as any)?.cwd || (args as any)?.working_dir || "";
  
  if (status === "running") {
    return (
      <div className="tool-shell">
        <div className="tool-shell__command-wrapper">
           <details className="tool-shell__details">
              <summary className="tool-shell__summary">查看完整命令</summary>
              <CommandBlock command={command} />
           </details>
        </div>
        <div className="tool-running-hint">
          {cwd ? `在 ${cwd} 目录中执行命令...` : "正在执行命令..."}
        </div>
      </div>
    );
  }

  // 解析输出
  let stdout = "";
  let stderr = "";
  let exitCode: number | null = null;
  let exitMsg = "";
  
  if (typeof output === "string") {
    // 查找所有标签位置
    const tags: { type: 'stdout' | 'stderr', index: number, length: number }[] = [];
    
    // 辅助函数：查找所有出现位置
    const findAll = (sub: string, type: 'stdout' | 'stderr') => {
      let pos = -1;
      while ((pos = output.indexOf(sub, pos + 1)) !== -1) {
        tags.push({ type, index: pos, length: sub.length });
      }
    };
    
    findAll('[stdout]', 'stdout');
    findAll('[stderr]', 'stderr');
    
    // 查找退出状态行
    const statusMatch = output.match(/\[Command (succeeded|failed) with exit code (\d+)\]\s*$/);
    const endIndex = statusMatch ? statusMatch.index! : output.length;
    
    if (statusMatch) {
      exitCode = parseInt(statusMatch[2], 10);
      exitMsg = statusMatch[0];
    }
    
    if (tags.length === 0) {
      // 没有标签，全部作为 stdout
      stdout = output.substring(0, endIndex).trim();
    } else {
      // 按位置排序
      tags.sort((a, b) => a.index - b.index);
      
      // 过滤掉结束位置之后的标签（如果有的话）
      const validTags = tags.filter(t => t.index < endIndex);
      
      // 处理第一个标签之前的内容（如果有）
      if (validTags.length > 0 && validTags[0].index > 0) {
        const preContent = output.substring(0, validTags[0].index).trim();
        if (preContent) stdout = preContent;
      }
      
      // 提取每个标签的内容
      validTags.forEach((tag, i) => {
        const nextIndex = (i + 1 < validTags.length) ? validTags[i + 1].index : endIndex;
        let contentStart = tag.index + tag.length;
        // 如果标签后紧跟换行，跳过换行
        if (output[contentStart] === '\n') contentStart++;
        
        const content = output.substring(contentStart, nextIndex).trim();
        if (content) {
          if (tag.type === 'stderr') {
            stderr += (stderr ? "\n" : "") + content;
          } else {
            stdout += (stdout ? "\n" : "") + content;
          }
        }
      });
    }
  } else if (output) {
    const out = output as any;
    stdout = out.stdout || out.output || out.result || "";
    stderr = out.stderr || "";
    exitCode = out.exit_code ?? out.exitCode ?? out.code ?? null;
  }

  return (
    <div className="tool-shell">
      {/* 折叠/隐藏详细命令，点击可查看 */}
      <div className="tool-shell__command-wrapper">
         <details className="tool-shell__details">
            <summary className="tool-shell__summary">查看完整命令</summary>
            <CommandBlock command={command} />
         </details>
      </div>
      
      {stderr && (
        <div className="tool-shell__section">
          <div className={`tool-shell__label ${exitCode !== 0 && exitCode !== null ? "tool-shell__label--error" : ""}`}>STDERR</div>
          <CodeBlock code={stderr} showHeader={false} maxHeight={200} />
        </div>
      )}
      
      {stdout && (
        <div className="tool-shell__section">
          {stderr && <div className="tool-shell__label">STDOUT</div>}
          <CodeBlock code={stdout} showHeader={false} maxHeight={300} />
        </div>
      )}
      
      {(exitCode !== null || exitMsg) && (
        <div className={`tool-shell__status ${exitCode === 0 ? "tool-shell__status--success" : "tool-shell__status--error"}`}>
          {exitCode === 0 ? <Icons.Check /> : <div className="tool-status-icon-x">✕</div>}
          <span>{exitCode === 0 ? "Command succeeded" : "Command failed"} (Exit code: {exitCode})</span>
        </div>
      )}
    </div>
  );
}
