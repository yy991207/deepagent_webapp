import type { ToolRendererProps } from "../types";
import { CommandBlock, CodeBlock } from "../components/CodeBlock";

export function ShellRenderer({ status, args, output }: ToolRendererProps) {
  const command = (args as any)?.command || (args as any)?.cmd || "";
  const cwd = (args as any)?.cwd || (args as any)?.working_dir || "";
  
  if (status === "running") {
    return (
      <div className="tool-shell">
        <CommandBlock command={command} />
        <div className="tool-running-hint">
          {cwd ? `在 ${cwd} 目录中执行命令...` : "正在执行命令..."}
        </div>
      </div>
    );
  }

  // 解析输出
  let outputText = "";
  let exitCode: number | null = null;
  
  if (typeof output === "string") {
    outputText = output;
  } else if (output) {
    const out = output as any;
    outputText = out.stdout || out.output || out.result || "";
    if (out.stderr) {
      outputText += (outputText ? "\n" : "") + out.stderr;
    }
    exitCode = out.exit_code ?? out.exitCode ?? out.code ?? null;
  }

  return (
    <div className="tool-shell">
      <CommandBlock command={command} />
      
      {outputText && (
        <div className="tool-shell__output">
          {outputText}
        </div>
      )}
      
      {exitCode !== null && exitCode !== 0 && (
        <div className="tool-shell__exit-code">
          退出码: {exitCode}
        </div>
      )}
    </div>
  );
}
