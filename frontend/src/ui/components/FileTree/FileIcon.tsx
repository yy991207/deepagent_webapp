type FileIconProps = {
  type: string;
  expanded?: boolean;
};

// 文件类型到颜色的映射
const FILE_TYPE_COLORS: Record<string, string> = {
  folder: "#f59e0b",
  pdf: "#ef4444",
  doc: "#3b82f6",
  docx: "#3b82f6",
  xls: "#22c55e",
  xlsx: "#22c55e",
  ppt: "#f97316",
  pptx: "#f97316",
  txt: "#6b7280",
  md: "#6b7280",
  json: "#eab308",
  xml: "#f97316",
  html: "#ef4444",
  css: "#3b82f6",
  js: "#eab308",
  ts: "#3b82f6",
  py: "#3b82f6",
  java: "#ef4444",
  jpg: "#8b5cf6",
  jpeg: "#8b5cf6",
  png: "#8b5cf6",
  gif: "#8b5cf6",
  svg: "#8b5cf6",
  mp3: "#ec4899",
  wav: "#ec4899",
  mp4: "#ef4444",
  zip: "#f59e0b",
  rar: "#f59e0b",
  file: "#6b7280",
};

export function FileIcon({ type, expanded }: FileIconProps) {
  const color = FILE_TYPE_COLORS[type] || FILE_TYPE_COLORS.file;

  if (type === "folder") {
    return (
      <span class="file-icon" style={{ color }}>
        {expanded ? (
          <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
            <path d="M1 3.5A1.5 1.5 0 0 1 2.5 2h3.172a1.5 1.5 0 0 1 1.06.44l.829.828a.5.5 0 0 0 .353.147H13.5A1.5 1.5 0 0 1 15 4.915V12.5a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 1 12.5v-9z" />
          </svg>
        ) : (
          <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
            <path d="M.54 3.87.5 3a2 2 0 0 1 2-2h3.672a2 2 0 0 1 1.414.586l.828.828A2 2 0 0 0 9.828 3h3.982a2 2 0 0 1 1.992 2.181l-.637 7A2 2 0 0 1 13.174 14H2.826a2 2 0 0 1-1.991-1.819l-.637-7a1.99 1.99 0 0 1 .342-1.31z" />
          </svg>
        )}
      </span>
    );
  }

  // 根据文件类型返回不同图标
  const iconPath = getIconPath(type);

  return (
    <span class="file-icon" style={{ color }}>
      <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
        <path d={iconPath} />
      </svg>
    </span>
  );
}

function getIconPath(type: string): string {
  switch (type) {
    case "pdf":
      return "M4 0a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V4.5L9.5 0H4zM9 4v1.5a1.5 1.5 0 0 0 1.5 1.5H12v7a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V2a1 1 0 0 1 1-1h4v3z";
    case "doc":
    case "docx":
      return "M4 0a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V4.5L9.5 0H4zM9 4v1.5a1.5 1.5 0 0 0 1.5 1.5H12v7a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V2a1 1 0 0 1 1-1h4v3zM5 8h6v1H5V8zm0 2h6v1H5v-1zm0 2h4v1H5v-1z";
    case "xls":
    case "xlsx":
      return "M4 0a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V4.5L9.5 0H4zM9 4v1.5a1.5 1.5 0 0 0 1.5 1.5H12v7a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V2a1 1 0 0 1 1-1h4v3zM5 7h2v2H5V7zm3 0h2v2H8V7zm0 3h2v2H8v-2zm-3 0h2v2H5v-2z";
    case "ppt":
    case "pptx":
      return "M4 0a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V4.5L9.5 0H4zM9 4v1.5a1.5 1.5 0 0 0 1.5 1.5H12v7a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V2a1 1 0 0 1 1-1h4v3z";
    case "jpg":
    case "jpeg":
    case "png":
    case "gif":
    case "svg":
      return "M6.002 5.5a1.5 1.5 0 1 1-3 0 1.5 1.5 0 0 1 3 0zM2.002 1a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V3a2 2 0 0 0-2-2h-12zm12 1a1 1 0 0 1 1 1v6.5l-3.777-1.947a.5.5 0 0 0-.577.093l-3.71 3.71-2.66-1.772a.5.5 0 0 0-.63.062L1.002 12V3a1 1 0 0 1 1-1h12z";
    case "mp3":
    case "wav":
      return "M6 13c0 1.105-1.12 2-2.5 2S1 14.105 1 13c0-1.104 1.12-2 2.5-2s2.5.896 2.5 2zm9-2c0 1.105-1.12 2-2.5 2s-2.5-.895-2.5-2 1.12-2 2.5-2 2.5.895 2.5 2z M14 11V2h1v9h-1zM6 3v10H5V3h1z M5 2.905a1 1 0 0 1 .9-.995l8-.8a1 1 0 0 1 1.1.995V3L5 4V2.905z";
    case "mp4":
      return "M0 1a1 1 0 0 1 1-1h14a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1H1a1 1 0 0 1-1-1V1zm4 0v6h8V1H4zm8 8H4v6h8V9zM1 1v2h2V1H1zm2 3H1v2h2V4zM1 7v2h2V7H1zm2 3H1v2h2v-2zm-2 3v2h2v-2H1zM15 1h-2v2h2V1zm-2 3v2h2V4h-2zm2 3h-2v2h2V7zm-2 3v2h2v-2h-2zm2 3h-2v2h2v-2z";
    case "zip":
    case "rar":
      return "M6.5 7.5a1 1 0 0 1 1-1h1a1 1 0 0 1 1 1v.938l.4 1.599a1 1 0 0 1-.416 1.074l-.93.62a1 1 0 0 1-1.109 0l-.93-.62a1 1 0 0 1-.415-1.074l.4-1.599V7.5zm2 0h-1v.938a1 1 0 0 1-.03.243l-.4 1.598.93.62.93-.62-.4-1.598a1 1 0 0 1-.03-.243V7.5z M4.406 0a2 2 0 0 0-1.94 1.515L.188 10.28A2 2 0 0 0 0 11.235V14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2.765a2 2 0 0 0-.188-.955L13.534 1.515A2 2 0 0 0 11.594 0H4.406z";
    case "json":
    case "xml":
      return "M14 4.5V14a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V2a2 2 0 0 1 2-2h5.5L14 4.5zm-3 0A1.5 1.5 0 0 1 9.5 3V1H4a1 1 0 0 0-1 1v12a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1V4.5h-2z";
    case "html":
    case "css":
    case "js":
    case "ts":
    case "py":
    case "java":
      return "M14 4.5V14a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V2a2 2 0 0 1 2-2h5.5L14 4.5zm-3 0A1.5 1.5 0 0 1 9.5 3V1H4a1 1 0 0 0-1 1v12a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1V4.5h-2zM4.5 12.5l.5-.5 1.5 1.5L8 12l.5.5-2 2-2-2zm3.5-6l.5-.5 2 2 2-2 .5.5-2.5 2.5L8 6.5z";
    case "txt":
    case "md":
    default:
      return "M14 4.5V14a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V2a2 2 0 0 1 2-2h5.5L14 4.5zm-3 0A1.5 1.5 0 0 1 9.5 3V1H4a1 1 0 0 0-1 1v12a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1V4.5h-2z";
  }
}

export default FileIcon;
