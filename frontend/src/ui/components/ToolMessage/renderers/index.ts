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
import { HttpRequestRenderer } from "./HttpRequestRenderer";
import { GrepRenderer } from "./GrepRenderer";

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
export { HttpRequestRenderer };
export { GrepRenderer };

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
    defaultExpanded: false,
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
    defaultExpanded: false,
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
    defaultExpanded: false,
  });

  // Shell / Bash 执行
  registerTool({
    names: ["shell", "bash", "execute", "execute_command", "run_command", "run_shell_command"],
    Renderer: ShellRenderer,
    icon: Icons.Terminal,
    getDisplayName: (args) => {
      const cmd = (args as any)?.command || (args as any)?.cmd || "";
      
      // 智能语义化标题生成
      if (!cmd) return "命令执行";

      const lowerCmd = cmd.toLowerCase().trim();

      // 1. 包管理
      if (lowerCmd.includes("pip install") || lowerCmd.includes("npm install") || lowerCmd.includes("yarn add")) {
        // 尝试提取包名
        const pkgMatch = cmd.match(/(?:install|add)\s+([a-zA-Z0-9_\-\s\.]+)/i);
        const pkg = pkgMatch ? pkgMatch[1].trim().split(/\s+/)[0] : "";
        return pkg ? `安装依赖: ${pkg}...` : "安装依赖";
      }
      
      // 2. Python 执行
      if (lowerCmd.startsWith("python") || lowerCmd.includes(" python ")) {
        const pyMatch = cmd.match(/python\s+(?:-m\s+)?([^\s;]+)/);
        const script = pyMatch ? pyMatch[1].split('/').pop() : "";
        return script ? `运行脚本: ${script}` : "运行 Python";
      }

      // 3. 环境配置
      if (lowerCmd.includes("source ") || lowerCmd.includes("/activate") || lowerCmd.includes("conda activate")) {
        return "激活虚拟环境";
      }
      
      // 4. 文件操作
      if (lowerCmd.startsWith("cd ")) {
        const target = cmd.split(/\s+/)[1] || "";
        return `切换目录${target ? `: ${target}` : ""}`;
      }
      if (lowerCmd.startsWith("ls") || lowerCmd.startsWith("dir")) {
        return "查看目录内容";
      }
      if (lowerCmd.startsWith("cat ") || lowerCmd.startsWith("head ") || lowerCmd.startsWith("tail ")) {
        const file = cmd.split(/\s+/)[1] || "";
        return `查看文件: ${file.split('/').pop()}`;
      }
      if (lowerCmd.startsWith("mkdir ")) {
        return "创建目录";
      }
      if (lowerCmd.startsWith("rm ")) {
        return "删除文件";
      }
      if (lowerCmd.startsWith("cp ") || lowerCmd.startsWith("mv ")) {
        return "移动/复制文件";
      }

      // 5. Git 操作
      if (lowerCmd.startsWith("git ")) {
        if (lowerCmd.includes("clone")) return "克隆代码库";
        if (lowerCmd.includes("commit")) return "提交代码";
        if (lowerCmd.includes("push")) return "推送代码";
        if (lowerCmd.includes("pull")) return "拉取代码";
        if (lowerCmd.includes("status")) return "查看 Git 状态";
        if (lowerCmd.includes("diff")) return "查看 Git 差异";
        return "Git 操作";
      }

      // 6. 其它常见工具
      if (lowerCmd.startsWith("grep ")) return "搜索文本";
      if (lowerCmd.startsWith("curl ") || lowerCmd.startsWith("wget ")) return "下载/请求";
      if (lowerCmd.startsWith("ping ")) return "网络测试";

      // 兜底：如果命令不太长，显示命令前部；否则显示通用标题
      if (cmd.length < 20) return `执行: ${cmd}`;
      return `执行命令 (${cmd.slice(0, 15)}...)`;
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
    defaultExpanded: false,
  });

  // 文件写入
  registerTool({
    names: ["write_file", "write_to_file", "create_file", "save_filesystem_write"],
    Renderer: FileWriteRenderer,
    icon: Icons.File,
    getDisplayName: (args) => {
      // 检查是否是 artifact 生成
      const title = (args as any)?.title;
      if (title) return `生成文档: ${title}`;

      const path = (args as any)?.TargetFile || (args as any)?.file_path || (args as any)?.path || "";
      const filename = path.split("/").pop() || "文件";
      return `写入: ${filename}`;
    },
    defaultExpanded: false,
  });

  // 文件编辑
  registerTool({
    names: ["edit_file", "replace_file_content", "modify_file"],
    Renderer: FileWriteRenderer,
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
    Renderer: HttpRequestRenderer,
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
    defaultExpanded: false,
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
    Renderer: GrepRenderer,
    icon: Icons.Search,
    getDisplayName: (args) => {
      const query = (args as any)?.Query || (args as any)?.Pattern || (args as any)?.pattern || "";
      return query ? `搜索: ${query}` : "文件搜索";
    },
  });

  // 子任务分派
  registerTool({
    names: ["task", "subtask", "delegate"],
    Renderer: TaskRenderer,
    icon: Icons.Bolt,
    getDisplayName: (args) => {
      const name = (args as any)?.name || (args as any)?.description || "";
      const shortName = name.length > 30 ? name.slice(0, 30) + "..." : name;
      return shortName ? `子任务: ${shortName}` : "子任务分派";
    },
    defaultExpanded: false,
    getRunningHint: (args) => {
      const name = (args as any)?.name || (args as any)?.description || "";
      return name ? `正在执行：${name}` : "正在执行子任务...";
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
    defaultExpanded: false,
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
