import { registerTool } from "../registry";
import { Icons } from "../Icons";
import { DefaultRenderer } from "./DefaultRenderer";
import { WebSearchRenderer } from "./WebSearchRenderer";
import { RagQueryRenderer } from "./RagQueryRenderer";
import { TodosRenderer } from "./TodosRenderer";
import { ShellRenderer } from "./ShellRenderer";
import { FileReadRenderer } from "./FileReadRenderer";
import { FileWriteRenderer } from "./FileWriteRenderer";
import { DirectoryRenderer } from "./DirectoryRenderer";
import { FetchUrlRenderer } from "./FetchUrlRenderer";
import { TaskRenderer } from "./TaskRenderer";

// 导出所有渲染器
export { DefaultRenderer };
export { WebSearchRenderer };
export { RagQueryRenderer };
export { TodosRenderer };
export { ShellRenderer };
export { FileReadRenderer };
export { FileWriteRenderer };
export { DirectoryRenderer };
export { FetchUrlRenderer };
export { TaskRenderer };

// 注册所有工具渲染器
export function registerAllRenderers(): void {
  // 网络搜索
  registerTool({
    names: ["web_search", "search_web", "google_search"],
    Renderer: WebSearchRenderer,
    icon: Icons.Globe,
    getDisplayName: (args) => {
      const query = (args as any)?.query || (args as any)?.q || "";
      return query ? `搜索: ${query}` : "网络搜索";
    },
    defaultExpanded: true,
    getRunningHint: (args) => {
      const query = (args as any)?.query || (args as any)?.q || "";
      return `正在搜索${query ? `：${query}` : "..."}`;
    },
  });

  // RAG 检索
  registerTool({
    names: ["rag_query", "rag_search", "knowledge_search"],
    Renderer: RagQueryRenderer,
    icon: Icons.Search,
    getDisplayName: (args) => {
      const query = (args as any)?.query || (args as any)?.q || "";
      return query ? `检索: ${query}` : "知识检索";
    },
    defaultExpanded: true,
    getRunningHint: (args) => {
      const query = (args as any)?.query || (args as any)?.q || "";
      return `正在检索${query ? `：${query}` : "..."}`;
    },
  });

  // 任务列表
  registerTool({
    names: ["write_todos", "update_todos", "set_todos"],
    Renderer: TodosRenderer,
    icon: Icons.Task,
    getDisplayName: () => "任务列表",
    defaultExpanded: true,
  });

  // 子任务分派
  registerTool({
    names: ["task"],
    Renderer: TaskRenderer,
    icon: Icons.Bolt,
    getDisplayName: () => "子任务分派",
    defaultExpanded: true,
    getRunningHint: (args) => {
      const name = (args as any)?.name || "";
      return name ? `正在执行：${name}` : "正在执行子任务...";
    },
  });

  // Shell / Bash 执行
  registerTool({
    names: ["shell", "bash", "execute_command", "run_command"],
    Renderer: ShellRenderer,
    icon: Icons.Terminal,
    getDisplayName: (args) => {
      const cmd = (args as any)?.command || (args as any)?.cmd || "";
      const shortCmd = cmd.length > 30 ? cmd.slice(0, 30) + "..." : cmd;
      return shortCmd ? `执行: ${shortCmd}` : "命令执行";
    },
    defaultExpanded: (status) => status === "running",
  });

  // 文件读取
  registerTool({
    names: ["read_file", "cat_file", "view_file"],
    Renderer: FileReadRenderer,
    icon: Icons.File,
    getDisplayName: (args) => {
      const path = (args as any)?.file_path || (args as any)?.path || "";
      const filename = path.split("/").pop() || "文件";
      return `读取: ${filename}`;
    },
    defaultExpanded: true,
  });

  // 文件写入
  registerTool({
    names: ["write_file", "write_to_file", "create_file"],
    Renderer: FileWriteRenderer,
    icon: Icons.File,
    getDisplayName: (args) => {
      const path = (args as any)?.TargetFile || (args as any)?.file_path || (args as any)?.path || "";
      const filename = path.split("/").pop() || "文件";
      return `写入: ${filename}`;
    },
    defaultExpanded: true,
  });

  // 文件编辑
  registerTool({
    names: ["edit_file", "replace_file_content", "modify_file"],
    Renderer: DefaultRenderer, // 后续替换为 FileEditRenderer
    icon: Icons.Edit,
    getDisplayName: (args) => {
      const path = (args as any)?.TargetFile || (args as any)?.file_path || (args as any)?.path || "";
      const filename = path.split("/").pop() || "文件";
      return `编辑: ${filename}`;
    },
    defaultExpanded: (status) => status === "running",
  });

  // HTTP 请求
  registerTool({
    names: ["http_request", "fetch", "curl"],
    Renderer: DefaultRenderer, // 后续替换为 HttpRequestRenderer
    icon: Icons.Http,
    getDisplayName: (args) => {
      const url = (args as any)?.url || "";
      const method = (args as any)?.method || "GET";
      return url ? `[${method}] ${url}` : "HTTP 请求";
    },
    getRunningHint: (args) => {
      const url = (args as any)?.url || "";
      return `正在请求${url ? `：${url}` : "..."}`;
    },
  });

  // URL 抓取
  registerTool({
    names: ["fetch_url", "read_url", "read_url_content"],
    Renderer: FetchUrlRenderer,
    icon: Icons.Link,
    getDisplayName: (args) => {
      const url = (args as any)?.url || "";
      try {
        const hostname = new URL(url).hostname;
        return `抓取: ${hostname}`;
      } catch {
        return url ? `抓取: ${url}` : "URL 抓取";
      }
    },
    defaultExpanded: true,
    getRunningHint: (args) => {
      const url = (args as any)?.url || "";
      return `正在抓取${url ? `：${url}` : "..."}`;
    },
  });

  // 目录列表
  registerTool({
    names: ["ls", "list_dir", "list_directory"],
    Renderer: DirectoryRenderer,
    icon: Icons.Folder,
    getDisplayName: (args) => {
      const path = (args as any)?.DirectoryPath || (args as any)?.path || "";
      return path ? `目录: ${path}` : "目录列表";
    },
  });

  // 搜索/Grep
  registerTool({
    names: ["grep", "grep_search", "glob", "find_files"],
    Renderer: DefaultRenderer, // 后续替换为 GrepRenderer
    icon: Icons.Search,
    getDisplayName: (args) => {
      const query = (args as any)?.Query || (args as any)?.Pattern || (args as any)?.pattern || "";
      return query ? `搜索: ${query}` : "文件搜索";
    },
  });

  // 子任务分派
  registerTool({
    names: ["task", "subtask", "delegate"],
    Renderer: DefaultRenderer, // 后续替换为 TaskRenderer
    icon: Icons.Bolt,
    getDisplayName: (args) => {
      const name = (args as any)?.name || (args as any)?.description || "";
      const shortName = name.length > 30 ? name.slice(0, 30) + "..." : name;
      return shortName ? `子任务: ${shortName}` : "子任务分派";
    },
  });

  // 图片生成
  registerTool({
    names: ["generate_image", "create_image", "draw"],
    Renderer: DefaultRenderer, // 后续替换为 ImageGenRenderer
    icon: Icons.Image,
    getDisplayName: (args) => {
      const prompt = (args as any)?.prompt || "";
      const shortPrompt = prompt.length > 30 ? prompt.slice(0, 30) + "..." : prompt;
      return shortPrompt ? `生成图片: ${shortPrompt}` : "图片生成";
    },
    defaultExpanded: true,
  });

  // 数据库查询
  registerTool({
    names: ["query_db", "sql_query", "database_query"],
    Renderer: DefaultRenderer, // 后续替换为 DatabaseRenderer
    icon: Icons.Database,
    getDisplayName: (args) => {
      const query = (args as any)?.query || (args as any)?.sql || "";
      const shortQuery = query.length > 30 ? query.slice(0, 30) + "..." : query;
      return shortQuery ? `查询: ${shortQuery}` : "数据库查询";
    },
  });
}
