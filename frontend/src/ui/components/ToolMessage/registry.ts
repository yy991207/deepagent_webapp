import type { ToolRendererConfig } from "./types";

// 工具注册表
const registry: Map<string, ToolRendererConfig> = new Map();

// 注册工具
export function registerTool(config: ToolRendererConfig): void {
  for (const name of config.names) {
    registry.set(name.toLowerCase(), config);
  }
}

// 获取工具配置
export function getToolConfig(toolName: string): ToolRendererConfig | undefined {
  return registry.get(toolName.toLowerCase());
}

// 获取所有已注册的工具名称
export function getRegisteredTools(): string[] {
  return Array.from(registry.keys());
}

// 检查工具是否已注册
export function isToolRegistered(toolName: string): boolean {
  return registry.has(toolName.toLowerCase());
}

// 清空注册表（用于测试）
export function clearRegistry(): void {
  registry.clear();
}

// 注册表是否已初始化
let initialized = false;

// 初始化注册表（延迟导入渲染器以避免循环依赖）
export async function initializeRegistry(): Promise<void> {
  if (initialized) return;
  
  // 动态导入渲染器
  const { registerAllRenderers } = await import("./renderers");
  registerAllRenderers();
  
  initialized = true;
}

// 同步初始化（在模块加载时调用）
export function initializeRegistrySync(): void {
  if (initialized) return;
  
  // 同步导入渲染器（需要在编译时确定）
  // 这里使用 require 风格的导入
  import("./renderers").then(({ registerAllRenderers }) => {
    registerAllRenderers();
  });
  
  initialized = true;
}
