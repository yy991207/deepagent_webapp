import type { ReactNode } from "react";
import { useEffect, useMemo, useRef, useState } from "react";

import type {
  TreeNode,
  UploadedSource,
  UploadedSourceDetail,
  PodcastSpeakerProfile,
  PodcastRunSummary,
  PodcastRunDetail,
  RagReference,
  UrlReference,
  AttachmentMeta,
  ChatMessage,
  AgentLog,
  SocketPayload,
  ChatSession,
  FilesystemWrite,
  PodcastEpisodeProfile,
  VoiceOption,
  SourceItem,
} from "./types";

import {
  formatJson,
  extractPodcastTranscript,
  maxRefIndex,
  extractUrlReferences,
  getFaviconUrl,
  createId,
  getOrCreateSessionId,
} from "./types/utils";

import {
  EDGE_TTS_VOICES,
  COSYVOICE_VOICES,
  TTS_PROVIDERS,
  LLM_MODELS,
} from "./types";

import { useChat } from "./hooks/useChat";
import { useFileTree } from "./hooks/useFileTree";
import { FileTree } from "./components/FileTree";
import { ToolMessage } from "./components/ToolMessage";
import { AssistantContent } from "./components/Chat/AssistantContent";


function MemoryProgressRing({ ratio, chars, title }: { ratio: number; chars: number; title: string }) {
  const size = 16;
  const stroke = 2;
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const safeRatio = Number.isFinite(ratio) ? Math.max(0, Math.min(1, ratio)) : 0;
  const dashOffset = c * (1 - safeRatio);
  const progressColor = chars < 4000 ? "#34a853" : "#f9ab00";

  return (
    <div className="memory-ring" title={title} aria-label={title}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          stroke="rgba(60, 64, 67, 0.45)"
          strokeWidth={stroke}
          fill="none"
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          stroke={progressColor}
          strokeWidth={stroke}
          fill="none"
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={dashOffset}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
        />
      </svg>
    </div>
  );
}


const upsertToolMessage = (
  prev: ChatMessage[],
  nextTool: Omit<Extract<ChatMessage, { role: "tool" }>, "role" | "id">,
): ChatMessage[] => {
  const id = nextTool.toolCallId;
  const existingIndex = prev.findIndex(
    (m) => m.role === "tool" && (m as Extract<ChatMessage, { role: "tool" }>).toolCallId === id,
  );

  const merged: Extract<ChatMessage, { role: "tool" }> =
    existingIndex >= 0
      ? ({
          ...(prev[existingIndex] as Extract<ChatMessage, { role: "tool" }>),
          ...nextTool,
          role: "tool",
        } as Extract<ChatMessage, { role: "tool" }>)
      : ({
          id,
          role: "tool",
          ...nextTool,
        } as Extract<ChatMessage, { role: "tool" }>);

  if (existingIndex >= 0) {
    return prev.map((m, i) => (i === existingIndex ? merged : m));
  }
  
  // 新的 tool 消息应该插入到最后一个 assistant 消息之前
  // 这样可以保持 tool 调用在 assistant 回复之前的正确顺序
  // 从后往前找，找到最后一个 assistant 消息的位置
  let insertIndex = prev.length;
  for (let i = prev.length - 1; i >= 0; i--) {
    if (prev[i].role === "assistant") {
      insertIndex = i;
      break;
    }
    // 如果遇到 user 消息，说明还没有 assistant 回复，直接添加到末尾
    if (prev[i].role === "user") {
      break;
    }
  }
  
  // 插入到指定位置
  const result = [...prev];
  result.splice(insertIndex, 0, merged);
  return result;
};

// --- Icons ---
const Icons = {
  Logo: () => <svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/></svg>, // Simplified logo
  NotebookLogo: () => (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
       <circle cx="12" cy="12" r="10" stroke="black" strokeWidth="2" fill="none" />
       <path d="M8 12a4 4 0 0 1 8 0" stroke="black" strokeWidth="2" strokeLinecap="round" />
       <path d="M12 8v8" stroke="black" strokeWidth="2" strokeLinecap="round" />
    </svg>
  ), // Mock abstract logo
  Plus: () => <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"/></svg>,
  Bolt: () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
      <path d="M11 21h-1l1-7H7.5c-.67 0-1.04-.78-.62-1.3L14 3h1l-1 7h3.5c.67 0 1.04.78.62 1.3L11 21z" />
    </svg>
  ),
  Globe: () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
      <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm7.93 9h-3.17a15.53 15.53 0 0 0-1.05-4.3A8.02 8.02 0 0 1 19.93 11zM12 4c.92 1.23 1.67 3.04 2.07 5H9.93C10.33 7.04 11.08 5.23 12 4zM4.07 13h3.17c.21 1.52.62 2.98 1.05 4.3A8.02 8.02 0 0 1 4.07 13zm3.17-2H4.07a8.02 8.02 0 0 1 4.22-4.3c-.43 1.32-.84 2.78-1.05 4.3zM12 20c-.92-1.23-1.67-3.04-2.07-5h4.14c-.4 1.96-1.15 3.77-2.07 5zm2.78-2.7c.43-1.32.84-2.78 1.05-4.3h3.17a8.02 8.02 0 0 1-4.22 4.3zM16.76 11H7.24c.13-1.74.52-3.42 1.06-5h7.4c.54 1.58.93 3.26 1.06 5zm-9.52 2h9.52c-.13 1.74-.52 3.42-1.06 5h-7.4c-.54-1.58-.93-3.26-1.06-5z" />
    </svg>
  ),
  ArrowRight: () => (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
      <path d="M12 4l-1.41 1.41L15.17 10H4v2h11.17l-4.58 4.59L12 18l8-6z" />
    </svg>
  ),
  Search: () => <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M15.5 14h-.79l-.28-.27C15.41 12.59 16 11.11 16 9.5 16 5.91 13.09 3 9.5 3S3 5.91 3 9.5 5.91 16 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z"/></svg>,
  Send: () => <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>,
  Stop: () => <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M6 6h12v12H6z"/></svg>,
  Share: () => <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M18 16.08c-.76 0-1.44.3-1.96.77L8.91 12.7c.05-.23.09-.46.09-.7s-.04-.47-.09-.7l7.05-4.11c.54.5 1.25.81 2.04.81 1.66 0 3-1.34 3-3s-1.34-3-3-3-3 1.34-3 3c0 .24.04.47.09.7L8.04 9.81C7.5 9.31 6.79 9 6 9c-1.66 0-3 1.34-3 3s1.34 3 3 3c.79 0 1.5-.31 2.04-.81l7.12 4.16c-.05.21-.08.43-.08.65 0 1.61 1.31 2.92 2.92 2.92 1.61 0 2.92-1.31 2.92-2.92s-1.31-2.92-2.92-2.92zm-9.52 2h9.52c-.13 1.74-.52 3.42-1.06 5h-7.4c-.54-1.58-.93-3.26-1.06-5z"/></svg>,
  Settings: () => <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M19.14 12.94c.04-.3.06-.61.06-.94 0-.32-.02-.64-.07-.94l2.03-1.58a.49.49 0 0 0 .12-.61l-1.92-3.32a.488.488 0 0 0-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94l-.36-2.54a.484.484 0 0 0-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96c-.22-.08-.47 0-.59.22L2.74 8.87c-.12.21-.08.47.12.61l2.03 1.58c-.05.3-.09.63-.09.94s.02.64.07.94l-2.03 1.58a.49.49 0 0 0-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.58 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32c.12-.22.07-.47-.12-.61l-2.01-1.58zM12 15.6c-1.98 0-3.6-1.62-3.6-3.6s1.62-3.6 3.6-3.6 3.6 1.62 3.6 3.6-1.62 3.6-3.6 3.6z"/></svg>,
  Apps: () => <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M4 8h4V4H4v4zm6 12h4v-4h-4v4zm-6 0h4v-4H4v4zm0-6h4v-4H4v4zm6 0h4v-4h-4v4zm6-10v4h4V4h-4zm-6 4h4V4h-4v4zm6 6h4v-4h-4v4zm0 6h4v-4h-4v4z"/></svg>,
  Sparkles: () => <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M9 21c0 .55.45 1 1 1h4c.55 0 1-.45 1-1v-1H9v1zm3-19C8.14 2 5 5.14 5 9c0 2.38 1.19 4.47 3 5.74V17c0 .55.45 1 1 1h6c.55 0 1-.45 1-1v-2.26c1.81-1.27 3-3.36 3-5.74 0-3.86-3.14-7-7-7zm2.85 11.1l-.85.6V16h-4v-2.3l-.85-.6C7.8 12.16 7 10.63 7 9c0-2.76 2.24-5 5-5s5 2.24 5 5c0 1.63-.8 3.16-2.15 4.1z"/></svg>,
  Tool: () => <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M22.7 19l-9.1-9.1c.9-2.3.4-5-1.5-6.9-2-2-5-2.4-7.4-1.3L9 6 6 9 1.6 4.7C.4 7.1.9 10.1 2.9 12.1c1.9 1.9 4.6 2.4 6.9 1.5l9.1 9.1c.4.4 1 .4 1.4 0l2.3-2.3c.5-.4.5-1.1.1-1.4z"/></svg>,
  ChevronRight: () => <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M10 6L8.59 7.41 13.17 12l-4.58 4.59L10 18l6-6z"/></svg>,
  ChevronLeft: () => <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M14 6l-1.41 1.41L8 12l4.59 4.59L14 18l-6-6z"/></svg>,
  PanelCollapseLeft: () => (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="12" r="10" />
      <path d="M14 8l-4 4 4 4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ),
  PanelExpandLeft: () => (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="12" r="10" />
      <path d="M10 8l4 4-4 4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ),
  PanelCollapseRight: () => (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="12" r="10" />
      <path d="M10 8l4 4-4 4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ),
  PanelExpandRight: () => (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="12" r="10" />
      <path d="M14 8l-4 4 4 4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ),
  ChevronDown: () => <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M16.59 8.59L12 13.17 7.41 8.59 6 10l6 6 6-6z"/></svg>,
  Folder: () => <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M10 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2h-8l-2-2z"/></svg>,
  Upload: () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
      <path d="M5 20h14v-2H5v2z" />
      <path d="M19 12h-4V3H9v9H5l7 7 7-7z" />
    </svg>
  ),
  Link: () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
      <path d="M3.9 12c0-1.71 1.39-3.1 3.1-3.1h4v-2H7c-2.82 0-5.1 2.28-5.1 5.1S4.18 17.1 7 17.1h4v-2H7c-1.71 0-3.1-1.39-3.1-3.1zm5.1 1h6v-2H9v2zm8-6.1h-4v2h4c1.71 0 3.1 1.39 3.1 3.1s-1.39 3.1-3.1 3.1h-4v2h4c2.82 0 5.1-2.28 5.1-5.1s-2.28-5.1-5.1-5.1z" />
    </svg>
  ),
  Copy: () => <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/></svg>,
  ThumbUp: () => <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M1 21h4V9H1v12zm22-11c0-1.1-.9-2-2-2h-6.31l.95-4.57.03-.32c0-.41-.17-.79-.44-1.06L14.17 1 7.59 7.59C7.22 7.95 7 8.45 7 9v10c0 1.1.9 2 2 2h9c.83 0 1.54-.5 1.84-1.22l3.02-7.05c.09-.23.14-.47.14-.73v-1.91l-.01-.01L23 10z"/></svg>,
  ThumbDown: () => <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M15 3H6c-.83 0-1.54.5-1.84 1.22l-3.02 7.05c-.09.23-.14.47-.14.73v1.91l.01.01L1 14c0 1.1.9 2 2 2h6.31l.95 4.57-.03.32c0 .41.17.79.44 1.06L9.83 23l6.59-6.59c.36-.36.58-.86.58-1.41V5c0-1.1-.9-2-2-2zm4 0v12h4V3h-4z"/></svg>,
  MoreVert: () => <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M12 8c1.1 0 2-.9 2-2s-.9-2-2-2-2 .9-2 2 .9 2 2 2zm0 2c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2zm0 6c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2z"/></svg>,
  Drive: () => <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M2 12l6 10.39h13L15 12H2zm21-1l-6-10.39H4L10 11h13zm-1 1l-6 10.39H2l6-10.39h15z" opacity="0.3"/><path d="M10.23 11.27l-6.12 10.6h12.76l6.12-10.6H10.23zM7.34 9.61l6.12-10.6H.7L6.81 9.61h.53zM15.49 11.27l6.12-10.6H8.89l-6.12 10.6h12.72z"/></svg>,
  Sound: () => <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"/></svg>,
  MindMap: () => <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/></svg>,
  Video: () => <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M17 10.5V7c0-.55-.45-1-1-1H4c-.55 0-1 .45-1 1v10c0 .55.45 1 1 1h12c.55 0 1-.45 1-1v-3.5l4 4v-11l-4 4z"/></svg>,
  Quiz: () => <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M4 6h16v2H4zm0 5h16v2H4zm0 5h16v2H4z"/></svg>,
  Pdf: () => <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M20 2H8c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm-8.5 7.5c0 .83-.67 1.5-1.5 1.5H9v2H7.5V7H10c.83 0 1.5.67 1.5 1.5v1zm5 2c0 .83-.67 1.5-1.5 1.5h-2.5V7H15c.83 0 1.5.67 1.5 1.5v3zm4-3H19v1h1.5V11H19v2h-1.5V7h3v1.5zM9 9.5h1v-1H9v1zM4 6H2v14c0 1.1.9 2 2 2h14v-2H4V6zm10 5.5h1v-3h-1v3z"/></svg>,
  User: () => <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"/></svg>,
  Mic: () => <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M12 14c1.66 0 2.99-1.34 2.99-3L15 5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3zm5.3-3c0 3-2.54 5.1-5.3 5.1S6.7 14 6.7 11H5c0 3.41 2.72 6.23 6 6.72V21h2v-3.28c3.28-.48 6-3.3 6-6.72h-1.7z"/></svg>,
  Close: () => <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg>,
};

const AGENTS = [
  { id: "audio", name: "音频概览", Icon: Icons.Sound, color: "#e1f5fe" },
  { id: "mindmap", name: "思维导图", Icon: Icons.MindMap, color: "#f3e5f5" },
  { id: "video", name: "视频概览", Icon: Icons.Video, color: "#e8f5e9" },
  { id: "quiz", name: "测验", Icon: Icons.Quiz, color: "#e0f2f1" },
];

function SpeakerProfileEditor({
  profile,
  onChange,
  onSave,
  onCancel,
}: {
  profile: PodcastSpeakerProfile;
  onChange: (p: PodcastSpeakerProfile) => void;
  onSave: () => void;
  onCancel: () => void;
}) {
  const voices = profile.tts_provider === "edge" ? EDGE_TTS_VOICES : COSYVOICE_VOICES;

  const updateSpeaker = (index: number, field: string, value: string) => {
    const newSpeakers = [...(profile.speakers || [])];
    newSpeakers[index] = { ...newSpeakers[index], [field]: value };
    onChange({ ...profile, speakers: newSpeakers });
  };

  const addSpeaker = () => {
    if ((profile.speakers?.length || 0) >= 4) return;
    onChange({
      ...profile,
      speakers: [
        ...(profile.speakers || []),
        { name: `说话人${(profile.speakers?.length || 0) + 1}`, voice_id: voices[0]?.id || "", backstory: "", personality: "" },
      ],
    });
  };

  const removeSpeaker = (index: number) => {
    if ((profile.speakers?.length || 0) <= 1) return;
    onChange({
      ...profile,
      speakers: (profile.speakers || []).filter((_, i) => i !== index),
    });
  };

  return (
    <div className="podcast-edit-form">
      <div className="podcast-form-row">
        <label className="podcast-form-label">配置名称 *</label>
        <input
          className="podcast-form-input"
          value={profile.name}
          onInput={(e) => onChange({ ...profile, name: (e.target as HTMLInputElement).value })}
          placeholder="例如：双人对话"
        />
      </div>

      <div className="podcast-form-row">
        <label className="podcast-form-label">TTS 提供商</label>
        <select
          className="podcast-form-select"
          value={profile.tts_provider}
          onChange={(e) => {
            const newProvider = e.currentTarget.value;
            const newVoices = newProvider === "edge" ? EDGE_TTS_VOICES : COSYVOICE_VOICES;
            onChange({
              ...profile,
              tts_provider: newProvider,
              tts_model: newProvider === "edge" ? "" : "cosyvoice-v2",
              speakers: (profile.speakers || []).map((s) => ({ ...s, voice_id: newVoices[0]?.id || "" })),
            });
          }}
        >
          {TTS_PROVIDERS.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>
      </div>

      <div className="podcast-form-row">
        <label className="podcast-form-label">说话人列表 ({profile.speakers?.length || 0}/4)</label>
        <div className="podcast-speakers-list">
          {(profile.speakers || []).map((speaker, idx) => (
            <div key={idx} className="podcast-speaker-card">
              <div className="podcast-speaker-header">
                <span className="podcast-speaker-title">说话人 {idx + 1}</span>
                {(profile.speakers?.length || 0) > 1 && (
                  <button className="podcast-speaker-remove" onClick={() => removeSpeaker(idx)}>
                    移除
                  </button>
                )}
              </div>
              <div className="podcast-speaker-fields">
                <div className="podcast-speaker-field">
                  <label>名称</label>
                  <input
                    value={speaker.name || ""}
                    onInput={(e) => updateSpeaker(idx, "name", (e.target as HTMLInputElement).value)}
                    placeholder="主持人"
                  />
                </div>
                <div className="podcast-speaker-field">
                  <label>音色</label>
                  <select
                    value={speaker.voice_id || ""}
                    onChange={(e) => updateSpeaker(idx, "voice_id", e.currentTarget.value)}
                  >
                    {voices.map((v) => (
                      <option key={v.id} value={v.id}>{v.name} ({v.gender})</option>
                    ))}
                  </select>
                </div>
                <div className="podcast-speaker-field full">
                  <label>人设背景</label>
                  <input
                    value={speaker.backstory || ""}
                    onInput={(e) => updateSpeaker(idx, "backstory", (e.target as HTMLInputElement).value)}
                    placeholder="可选"
                  />
                </div>
                <div className="podcast-speaker-field full">
                  <label>性格特征</label>
                  <input
                    value={speaker.personality || ""}
                    onInput={(e) => updateSpeaker(idx, "personality", (e.target as HTMLInputElement).value)}
                    placeholder="可选"
                  />
                </div>
              </div>
            </div>
          ))}
          {(profile.speakers?.length || 0) < 4 && (
            <button className="podcast-add-speaker-btn" onClick={addSpeaker}>
              + 添加说话人
            </button>
          )}
        </div>
      </div>

      <div className="podcast-form-actions">
        <button className="add-source-action" onClick={onCancel}>取消</button>
        <button className="add-source-action primary" onClick={onSave}>保存</button>
      </div>
    </div>
  );
}

function EpisodeProfileEditor({
  profile,
  speakerProfiles,
  onChange,
  onSave,
  onCancel,
}: {
  profile: PodcastEpisodeProfile;
  speakerProfiles: PodcastSpeakerProfile[];
  onChange: (p: PodcastEpisodeProfile) => void;
  onSave: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="podcast-edit-form">
      <div className="podcast-form-row">
        <label className="podcast-form-label">配置名称 *</label>
        <input
          className="podcast-form-input"
          value={profile.name}
          onInput={(e) => onChange({ ...profile, name: (e.target as HTMLInputElement).value })}
          placeholder="例如：科技讨论"
        />
      </div>

      <div className="podcast-form-row">
        <label className="podcast-form-label">关联说话人配置</label>
        <select
          className="podcast-form-select"
          value={profile.speaker_config}
          onChange={(e) => onChange({ ...profile, speaker_config: e.currentTarget.value })}
        >
          <option value="">请选择</option>
          {speakerProfiles.map((p) => (
            <option key={p.id} value={p.name}>{p.name}</option>
          ))}
        </select>
      </div>

      <div className="podcast-form-row">
        <label className="podcast-form-label">大纲生成模型</label>
        <select
          className="podcast-form-select"
          value={profile.outline_model}
          onChange={(e) => onChange({ ...profile, outline_model: e.currentTarget.value })}
        >
          {LLM_MODELS.map((m) => (
            <option key={m.id} value={m.id}>{m.name}</option>
          ))}
        </select>
      </div>

      <div className="podcast-form-row">
        <label className="podcast-form-label">对话生成模型</label>
        <select
          className="podcast-form-select"
          value={profile.transcript_model}
          onChange={(e) => onChange({ ...profile, transcript_model: e.currentTarget.value })}
        >
          {LLM_MODELS.map((m) => (
            <option key={m.id} value={m.id}>{m.name}</option>
          ))}
        </select>
      </div>

      <div className="podcast-form-row">
        <label className="podcast-form-label">段落数量</label>
        <input
          className="podcast-form-input"
          type="number"
          min="1"
          max="10"
          value={profile.num_segments}
          onInput={(e) => onChange({ ...profile, num_segments: parseInt((e.target as HTMLInputElement).value) || 4 })}
        />
      </div>

      <div className="podcast-form-actions">
        <button className="add-source-action" onClick={onCancel}>取消</button>
        <button className="add-source-action primary" onClick={onSave}>保存</button>
      </div>
    </div>
  );
}

function App() {
  const [tree, setTree] = useState<TreeNode | null>(null);
  const [selectedFiles, setSelectedFiles] = useState<Set<string>>(new Set());
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [searchValue, setSearchValue] = useState("");
  const [status, setStatus] = useState("就绪");
  const [isLeftCollapsed, setIsLeftCollapsed] = useState(false);
  const [isRightCollapsed, setIsRightCollapsed] = useState(false);

  const [addSourceOpen, setAddSourceOpen] = useState(false);
  const [pendingUploadFiles, setPendingUploadFiles] = useState<File[]>([]);
  const [urlDraft, setUrlDraft] = useState("");
  const [urlMode, setUrlMode] = useState<"crawl" | "llm_summary">("crawl");
  const [urlParseState, setUrlParseState] = useState<
    | { status: "idle" }
    | { status: "parsing" }
    | { status: "ready"; filename: string; content: string }
    | { status: "error"; message: string }
  >({ status: "idle" });
  const [uploadState, setUploadState] = useState<
    | { status: "idle" }
    | { status: "ready"; count: number }
    | { status: "uploading"; count: number }
    | { status: "done"; count: number }
    | { status: "error"; count: number; message: string }
  >({ status: "idle" });
  const directoryInputRef = useRef<HTMLInputElement>(null);

  const [sources, setSources] = useState<UploadedSource[]>([]);
  const [sourceDetailOpen, setSourceDetailOpen] = useState(false);
  const [sourceDetail, setSourceDetail] = useState<UploadedSourceDetail | null>(null);
  const [sourceDetailLoading, setSourceDetailLoading] = useState(false);

  const [sourceActionMenuId, setSourceActionMenuId] = useState<string | null>(null);
  const [renameSourceOpen, setRenameSourceOpen] = useState(false);
  const [renameSourceTarget, setRenameSourceTarget] = useState<UploadedSource | null>(null);
  const [renameSourceDraft, setRenameSourceDraft] = useState<string>("");
  const [deleteSourceId, setDeleteSourceId] = useState<string | null>(null);
  
  // FileTree hook for hierarchical source management
  const [fileTreeState, fileTreeActions] = useFileTree();
  const [newFolderName, setNewFolderName] = useState("");
  const [newFolderParentId, setNewFolderParentId] = useState<string | null>(null);
  const [createFolderOpen, setCreateFolderOpen] = useState(false);
  
  const [selectedAgentId, setSelectedAgentId] = useState<string>("");
  const [logs, setLogs] = useState<AgentLog[]>([]);

  const [podcastConfigOpen, setPodcastConfigOpen] = useState(false);
  const [podcastSpeakerProfiles, setPodcastSpeakerProfiles] = useState<PodcastSpeakerProfile[]>([]);
  const [podcastSelectedSpeaker, setPodcastSelectedSpeaker] = useState<string>("");
  const [podcastEpisodeName, setPodcastEpisodeName] = useState<string>("");
  const [podcastBriefingSuffix, setPodcastBriefingSuffix] = useState<string>("");
  const [podcastSelectedSourceIds, setPodcastSelectedSourceIds] = useState<Set<string>>(new Set());
  const [podcastSources, setPodcastSources] = useState<UploadedSource[]>([]);
  const [podcastSourcesLoading, setPodcastSourcesLoading] = useState(false);
  const [podcastRuns, setPodcastRuns] = useState<PodcastRunSummary[]>([]);
  const [podcastRunDetailOpen, setPodcastRunDetailOpen] = useState(false);
  const [deletePodcastRunId, setDeletePodcastRunId] = useState<string | null>(null);
  const [podcastRunDetail, setPodcastRunDetail] = useState<PodcastRunDetail | null>(null);
  const [podcastRunDetailLoading, setPodcastRunDetailLoading] = useState(false);

  // 配置管理状态
  const [podcastSettingsOpen, setPodcastSettingsOpen] = useState(false);
  const [podcastSettingsTab, setPodcastSettingsTab] = useState<"speaker" | "episode">("speaker");
  const [podcastEpisodeProfiles, setPodcastEpisodeProfiles] = useState<PodcastEpisodeProfile[]>([]);
  const [editingSpeakerProfile, setEditingSpeakerProfile] = useState<PodcastSpeakerProfile | null>(null);
  const [editingEpisodeProfile, setEditingEpisodeProfile] = useState<PodcastEpisodeProfile | null>(null);
  const [isCreatingProfile, setIsCreatingProfile] = useState(false);
  const [podcastSelectedEpisode, setPodcastSelectedEpisode] = useState<string>("");
  const [podcastSourceSelectOpen, setPodcastSourceSelectOpen] = useState(false);
  const [deletingProfileId, setDeletingProfileId] = useState<string | null>(null);
  const [deletingProfileType, setDeletingProfileType] = useState<"speaker" | "episode" | null>(null);

  const [memoryStats, setMemoryStats] = useState<{ chars: number; limit: number; ratio: number }>({
    chars: 0,
    limit: 5000,
    ratio: 0,
  });
  const memorySummaryRunningRef = useRef(false);

  const abortControllerRef = useRef<AbortController | null>(null);
  const assistantBufferRef = useRef<{ id: string; text: string }>({ id: "", text: "" });
  const pendingAssistantIdRef = useRef<string | null>(null);
  const pendingRefsRef = useRef<any[] | null>(null);
  const currentMessageIdRef = useRef<string | null>(null);
  const pendingWritesRef = useRef<Map<string, FilesystemWrite[]>>(new Map());
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const currentSessionIdRef = useRef<string>("");

  const [sessionId, setSessionId] = useState<string>(() => {
    const sid = getOrCreateSessionId();
    currentSessionIdRef.current = sid;
    return sid;
  });

  const [leftPanelMode, setLeftPanelMode] = useState<"sources" | "sessions">("sources");
  const [chatSessions, setChatSessions] = useState<ChatSession[]>([]);
  const [deleteSessionId, setDeleteSessionId] = useState<string | null>(null);
  const [filesystemWrites, setFilesystemWrites] = useState<FilesystemWrite[]>([]);
  const [writeDetailOpen, setWriteDetailOpen] = useState(false);
  const [writeDetailFullscreen, setWriteDetailFullscreen] = useState(false);
  const [writeDetail, setWriteDetail] = useState<{write_id: string; content: string; binary_content?: string; title: string; file_type?: string; file_path?: string} | null>(null);

  const [refModalOpen, setRefModalOpen] = useState(false);
  const [refModalIndex, setRefModalIndex] = useState<number | null>(null);
  const [refModalRefs, setRefModalRefs] = useState<RagReference[] | null>(null);
  const [refModalFileContent, setRefModalFileContent] = useState<string>("");
  const [refModalFileLoading, setRefModalFileLoading] = useState(false);

  const selectedList = useMemo(() => Array.from(selectedFiles), [selectedFiles]);
  const isStreaming = status === "思考中...";

  const resetStreamState = () => {
    assistantBufferRef.current = { id: "", text: "" };
    pendingAssistantIdRef.current = null;
    pendingRefsRef.current = null;
  };

  const cancelActiveStream = async (sid: string) => {
    // 没有正在进行的流式请求就不触发取消，避免误伤
    if (!abortControllerRef.current) return;
    // 先终止前端 SSE 请求，再通知后端中断对应会话的流式生成
    abortControllerRef.current?.abort();
    abortControllerRef.current = null;
    resetStreamState();
    const session = String(sid || "").trim();
    if (!session) return;
    try {
      await fetch(`/api/chat/session/${encodeURIComponent(session)}/cancel`, { method: "POST" });
    } catch {
      // ignore
    }
  };

  const selectedAttachmentNames = useMemo(() => {
    const map = new Map(sources.map((s) => [s.id, s.filename] as const));
    return selectedList.map((id) => map.get(id) || id);
  }, [selectedList, sources]);

  const allFilePaths = useMemo(() => sources.map((s) => s.id), [sources]);

  // 发送单条消息的反馈信息：index 含义为 [copy, like, dislike]
  const sendMessageFeedback = async (messageId: string, index: number) => {
    const mid = String(messageId || "").trim();
    const sid = String(sessionId || "").trim();
    if (!mid || !sid) return;
    if (![0, 1, 2].includes(index)) return;

    const action = index === 0 ? "copy" : index === 1 ? "like" : "dislike";
    try {
      await fetch("/api/chat/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sid, message_id: mid, action }),
      });
    } catch {
      // 静默失败：反馈不上报不影响主流程
    }
  };

  const handleCopyMessage = async (message: ChatMessage) => {
    if (message.role !== "assistant") return;
    const text = message.content || "";
    try {
      if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
        await navigator.clipboard.writeText(text);
        addLog("已复制回复内容", "info");
      } else {
        // 兼容降级：直接选中内容交给用户手动复制
        addLog("当前环境不支持一键复制，请手动选中文本复制", "error");
      }
    } catch {
      addLog("复制失败，请手动复制", "error");
    }

    await sendMessageFeedback(message.id, 0);
  };

  const handleLikeMessage = async (message: ChatMessage) => {
    if (message.role !== "assistant") return;
    await sendMessageFeedback(message.id, 1);
  };

  const handleDislikeMessage = async (message: ChatMessage) => {
    if (message.role !== "assistant") return;
    await sendMessageFeedback(message.id, 2);
  };

  const setAllSelected = (checked: boolean) => {
    if (!checked) {
      setSelectedFiles(new Set());
      return;
    }
    setSelectedFiles(new Set(allFilePaths));
  };

  useEffect(() => {
    fetchTree();
    void fetchSources();
    void fetchChatHistory(sessionId);
    void fetchChatSessions();
    void refreshMemoryStats(sessionId);
    void fetchPodcastSpeakerProfiles();
    void fetchPodcastEpisodeProfiles();
    void fetchPodcastRuns();
    return () => {
      abortControllerRef.current?.abort();
    };
  }, []);

  useEffect(() => {
    if (!sourceActionMenuId) return;

    const onDocClick = (ev: MouseEvent) => {
      const target = ev.target as HTMLElement | null;
      if (!target) {
        setSourceActionMenuId(null);
        return;
      }
      if (typeof (target as any).closest === "function") {
        const inside = (target as any).closest(".source-more-wrap");
        if (inside) return;
      }
      setSourceActionMenuId(null);
    };

    const onKeyDown = (ev: KeyboardEvent) => {
      if (ev.key === "Escape") {
        setSourceActionMenuId(null);
      }
    };

    document.addEventListener("click", onDocClick);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("click", onDocClick);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [sourceActionMenuId]);

  const refreshMemoryStats = async (sid: string) => {
    const threadId = String(sid || "").trim();
    if (!threadId) return;
    try {
      const resp = await fetch(`/api/chat/memory/stats?thread_id=${encodeURIComponent(threadId)}&assistant_id=agent`);
      if (!resp.ok) return;
      const data = (await resp.json()) as any;
      const chars = Number(data.memory_text_chars || 0);
      const limit = Number(data.memory_limit || 5000);
      const ratio = Number(data.ratio || 0);
      setMemoryStats({ chars, limit, ratio });
    } catch {
      // ignore
    }
  };

  const runMemorySummaryIfNeeded = async (sid: string) => {
    const threadId = String(sid || "").trim();
    if (!threadId) return;
    if (memorySummaryRunningRef.current) return;
    // 达到阈值才触发 summary
    if (!(memoryStats.limit > 0 && memoryStats.chars >= memoryStats.limit)) return;

    memorySummaryRunningRef.current = true;
    try {
      const resp = await fetch("/api/chat/memory/summary", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ thread_id: threadId, assistant_id: "agent" }),
      });
      if (!resp.ok) return;
      const data = (await resp.json()) as any;
      // 总结完成后，用接口返回的字数占比立刻刷新圆环
      const chars = Number(data.memory_text_chars || 0);
      const limit = Number(data.memory_limit || memoryStats.limit || 5000);
      const ratio = Number(data.ratio || 0);
      setMemoryStats({ chars, limit, ratio });
    } catch {
      // ignore
    } finally {
      memorySummaryRunningRef.current = false;
    }
  };

  const fetchChatSessions = async () => {
    const resp = await fetch(`/api/chat/sessions?assistant_id=agent&limit=50`);
    if (!resp.ok) {
      setChatSessions([]);
      return;
    }
    const data = (await resp.json()) as { sessions?: ChatSession[] };
    setChatSessions(Array.isArray(data.sessions) ? data.sessions : []);
  };

  const createNewSession = async () => {
    const resp = await fetch("/api/chat/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ assistant_id: "agent" }),
    });
    if (!resp.ok) {
      return null;
    }
    const data = (await resp.json()) as { session_id?: string };
    const sid = String(data.session_id || "").trim();
    return sid || null;
  };

  const switchSession = async (sid: string) => {
    const next = String(sid || "").trim();
    if (!next) return;
    // 切换会话时终止当前 SSE 请求
    await cancelActiveStream(sessionId);
    currentSessionIdRef.current = next;
    setSessionId(next);
    setStatus("就绪");
    try {
      localStorage.setItem("deepagents_session_id", next);
    } catch {
      // ignore
    }
    await fetchChatHistory(next);
    await refreshMemoryStats(next);
  };

  const requestDeleteSession = (sid: string) => {
    setDeleteSessionId(sid);
  };

  const confirmDeleteSession = async () => {
    const sid = deleteSessionId;
    if (!sid) return;

    // 删除当前会话时终止正在进行的 SSE 请求
    if (sid === sessionId) {
      await cancelActiveStream(sessionId);
      setStatus("就绪");
    }

    const resp = await fetch(`/api/chat/session/${encodeURIComponent(sid)}?assistant_id=agent`, {
      method: "DELETE",
    });
    setDeleteSessionId(null);
    if (!resp.ok) {
      return;
    }

    await fetchChatSessions();
    if (sid === sessionId) {
      const newSid = await createNewSession();
      if (newSid) {
        await switchSession(newSid);
      } else {
        setMessages([]);
      }
    }
  };

  const fetchPodcastSpeakerProfiles = async () => {
    const resp = await fetch("/api/podcast/speaker-profiles");
    if (!resp.ok) {
      return;
    }
    const data = (await resp.json()) as { results?: PodcastSpeakerProfile[] };
    setPodcastSpeakerProfiles(Array.isArray(data.results) ? data.results : []);
  };

  const fetchPodcastEpisodeProfiles = async () => {
    try {
      const resp = await fetch("/api/podcast/episode-profiles");
      if (!resp.ok) return;
      const data = await resp.json();
      setPodcastEpisodeProfiles(Array.isArray(data.results) ? data.results : []);
    } catch {
      // ignore
    }
  };

  const saveSpeakerProfile = async (profile: Partial<PodcastSpeakerProfile>) => {
    const isNew = !profile.id || isCreatingProfile;
    const url = isNew
      ? "/api/podcast/speaker-profiles"
      : `/api/podcast/speaker-profiles/${profile.id}`;
    const method = isNew ? "POST" : "PUT";

    try {
      const resp = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(profile),
      });
      if (!resp.ok) {
        const err = await resp.json();
        alert(err.detail || "保存失败");
        return false;
      }
      await fetchPodcastSpeakerProfiles();
      return true;
    } catch {
      alert("网络错误");
      return false;
    }
  };

  const deleteSpeakerProfile = async (id: string) => {
    if (!confirm("确定删除此配置？")) return;
    try {
      const resp = await fetch(`/api/podcast/speaker-profiles/${id}`, { method: "DELETE" });
      if (!resp.ok) {
        alert("删除失败");
        return;
      }
      await fetchPodcastSpeakerProfiles();
    } catch {
      alert("网络错误");
    }
  };

  const saveEpisodeProfile = async (profile: Partial<PodcastEpisodeProfile>) => {
    const isNew = !profile.id || isCreatingProfile;
    const url = isNew
      ? "/api/podcast/episode-profiles"
      : `/api/podcast/episode-profiles/${profile.id}`;
    const method = isNew ? "POST" : "PUT";

    try {
      const resp = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(profile),
      });
      if (!resp.ok) {
        const err = await resp.json();
        alert(err.detail || "保存失败");
        return false;
      }
      await fetchPodcastEpisodeProfiles();
      return true;
    } catch {
      alert("网络错误");
      return false;
    }
  };

  const deleteEpisodeProfile = async (id: string) => {
    if (!confirm("确定删除此配置？")) return;
    try {
      const resp = await fetch(`/api/podcast/episode-profiles/${id}`, { method: "DELETE" });
      if (!resp.ok) {
        alert("删除失败");
        return;
      }
      await fetchPodcastEpisodeProfiles();
    } catch {
      alert("网络错误");
    }
  };

  const fetchPodcastRuns = async () => {
    const resp = await fetch("/api/podcast/runs?limit=50");
    if (!resp.ok) {
      return;
    }
    const data = (await resp.json()) as { results?: PodcastRunSummary[] };
    setPodcastRuns(Array.isArray(data.results) ? data.results : []);
  };

  const requestDeletePodcastRun = (runId: string) => {
    setDeletePodcastRunId(runId);
  };

  const confirmDeletePodcastRun = async () => {
    const runId = deletePodcastRunId;
    if (!runId) return;

    setDeletePodcastRunId(null);

    const resp = await fetch(`/api/podcast/runs/${encodeURIComponent(runId)}`, {
      method: "DELETE",
    });
    if (!resp.ok) {
      return;
    }

    await fetchPodcastRuns();

    if (podcastRunDetailOpen && podcastRunDetail?.run?.run_id === runId) {
      setPodcastRunDetailOpen(false);
      setPodcastRunDetail(null);
    }
  };

  const fetchPodcastSources = async (q: string) => {
    setPodcastSourcesLoading(true);
    try {
      const response = await fetch(
        `/api/sources/list?q=${encodeURIComponent(q || "")}&limit=500&skip=0`,
      );
      if (!response.ok) {
        setPodcastSources([]);
        return;
      }
      const data = (await response.json()) as { results?: UploadedSource[] };
      setPodcastSources(Array.isArray(data.results) ? data.results : []);
    } finally {
      setPodcastSourcesLoading(false);
    }
  };

  const openPodcastRunDetail = async (runId: string) => {
    setPodcastRunDetailOpen(true);
    setPodcastRunDetailLoading(true);
    setPodcastRunDetail(null);
    try {
      const resp = await fetch(`/api/podcast/runs/${encodeURIComponent(runId)}`);
      if (!resp.ok) {
        return;
      }
      const data = (await resp.json()) as PodcastRunDetail;
      setPodcastRunDetail(data);
    } finally {
      setPodcastRunDetailLoading(false);
    }
  };

  const togglePodcastSource = (id: string) => {
    setPodcastSelectedSourceIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const setAllPodcastSources = (checked: boolean) => {
    if (!checked) {
      setPodcastSelectedSourceIds(new Set());
      return;
    }
    setPodcastSelectedSourceIds(new Set(podcastSources.map((s) => s.id)));
  };

  const startPodcastGeneration = async () => {
    if (!podcastSelectedSpeaker) {
      setPodcastConfigOpen(true);
      return;
    }
    if (!podcastEpisodeName.trim()) {
      setPodcastConfigOpen(true);
      return;
    }
    const selectedSourceIds = Array.from(podcastSelectedSourceIds);
    if (selectedSourceIds.length === 0) {
      setPodcastConfigOpen(true);
      return;
    }

    // 使用新的 Agent API 格式：agent_id, config, meta_info
    const agentPayload = {
      agent_id: "podcast",
      config: {
        episode_profile: podcastSelectedEpisode || "tech_discussion",
        speaker_profile: podcastSelectedSpeaker,
        episode_name: podcastEpisodeName.trim(),
        source_ids: selectedSourceIds,
        briefing_suffix: podcastBriefingSuffix.trim() || undefined,
      },
      meta_info: {
        session_id: sessionId,
        user_id: "web_user",
      },
    };

    try {
      // 1. 提交任务到 Agent API
      const resp = await fetch("/api/agent/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(agentPayload),
      });
      
      if (!resp.ok) {
        const text = await resp.text();
        addLog(text || "播客生成触发失败", "error");
        return;
      }
      
      const result = await resp.json();
      const taskId = result.task_id;
      
      if (!taskId) {
        addLog("未获取到 task_id", "error");
        return;
      }
      
      addLog(`播客生成任务已提交 (task_id: ${taskId})`, "info");
      
      // 2. 开始轮询任务状态
      pollTaskStatus(taskId);
      
      // 3. 刷新运行历史
      await fetchPodcastRuns();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "播客生成请求失败";
      addLog(msg, "error");
    }
  };

  // 轮询任务状态
  const pollTaskStatus = async (taskId: string) => {
    const pollInterval = 3000; // 3秒轮询一次
    const maxPolls = 200; // 最多轮询200次（约10分钟）
    let pollCount = 0;
    
    const poll = async () => {
      pollCount++;
      
      try {
        const resp = await fetch(`/api/agent/task/${encodeURIComponent(taskId)}/poll`);
        
        if (!resp.ok) {
          if (pollCount < 3) {
            // 前几次失败可能是任务还没创建完成，继续轮询
            setTimeout(poll, pollInterval);
            return;
          }
          addLog(`查询任务状态失败: HTTP ${resp.status}`, "error");
          return;
        }
        
        const status = await resp.json();
        const taskStatus = status.status;
        const message = status.message || "";
        const progress = status.progress || 0;
        
        // 更新日志
        if (taskStatus === "PENDING") {
          // 排队中，继续轮询
        } else if (taskStatus === "STARTED") {
          addLog(`播客生成中... (${progress}%)`, "info");
        } else if (taskStatus === "DELIVERED") {
          addLog(`任务已投递到 Agent (${progress}%)`, "info");
        } else if (taskStatus === "SUCCESS") {
          addLog("播客生成完成！", "info");
          // 刷新运行历史以显示结果
          await fetchPodcastRuns();
          return; // 停止轮询
        } else if (taskStatus === "FAILURE") {
          addLog(`播客生成失败: ${status.error || "未知错误"}`, "error");
          return; // 停止轮询
        } else if (taskStatus === "CANCELLED") {
          addLog("播客生成已取消", "info");
          return; // 停止轮询
        }
        
        // 检查是否达到最大轮询次数
        if (pollCount >= maxPolls) {
          addLog("轮询超时，请手动刷新查看结果", "error");
          return;
        }
        
        // 继续轮询
        setTimeout(poll, pollInterval);
      } catch (err) {
        const msg = err instanceof Error ? err.message : "轮询失败";
        addLog(`轮询错误: ${msg}`, "error");
      }
    };
    
    // 开始第一次轮询
    setTimeout(poll, 1000); // 1秒后开始第一次轮询
  };

  const fetchChatHistory = async (sid: string) => {
    const resp = await fetch(`/api/chat/history?session_id=${encodeURIComponent(sid)}&limit=200`);
    if (!resp.ok) {
      return;
    }
    const data = (await resp.json()) as {
      writes?: FilesystemWrite[];
      messages?: Array<{
        id: string;
        role: string;
        content: string;
        attachments?: AttachmentMeta[];
        references?: RagReference[];
        suggested_questions?: string[];
        created_at?: string;
        tool_call_id?: string | null;
        tool_name?: string | null;
        tool_args?: unknown;
        tool_status?: string | null;
        tool_output?: unknown;
        started_at?: string | null;
        ended_at?: string | null;
      }>;
    };
    const items = Array.isArray(data.messages) ? data.messages : [];
    const writes = Array.isArray(data.writes) ? data.writes : [];
    setFilesystemWrites(writes);

    // 构建 write_id 到文档的映射
    const writeMap = new Map<string, FilesystemWrite>();
    writes.forEach((w) => writeMap.set(w.write_id, w));

    // 构建 tool_call_id 到 write_id 的映射
    // 说明：
    // - 新逻辑：优先使用 save_filesystem_write 工具的 output（其中包含 write_id/title/type）
    // - 兼容旧逻辑：如果 write_file 的 output 里带有 write_id，也一并支持
    const toolToWriteMap = new Map<string, string>();
    items.forEach((m) => {
      if (m.role === "tool" && m.tool_output) {
        try {
          const output = typeof m.tool_output === "string" ? JSON.parse(m.tool_output) : m.tool_output;
          const writeId = (output as any)?.write_id;
          if (
            writeId &&
            (m.tool_name === "save_filesystem_write" || m.tool_name === "write_file")
          ) {
            toolToWriteMap.set(String(m.tool_call_id || m.id), String(writeId));
          }
        } catch (e) {
          // 忽略解析错误
        }
      }
    });

    // 构建 assistant 消息 ID 到文档列表的映射
    const assistantWritesMap = new Map<string, FilesystemWrite[]>();
    
    // 遍历消息，找到每个文档写入工具调用对应的 assistant 消息
    let currentAssistantId: string | null = null;
    for (let i = items.length - 1; i >= 0; i--) {
      const m = items[i];
      if (m.role === "assistant") {
        currentAssistantId = m.id;
      } else if (
        m.role === "tool" &&
        (m.tool_name === "save_filesystem_write" || m.tool_name === "write_file") &&
        currentAssistantId
      ) {
        const writeId = toolToWriteMap.get(String(m.tool_call_id || m.id));
        if (writeId && writeMap.has(writeId)) {
          const write = writeMap.get(writeId)!;
          if (!assistantWritesMap.has(currentAssistantId)) {
            assistantWritesMap.set(currentAssistantId, []);
          }
          assistantWritesMap.get(currentAssistantId)!.push(write);
        }
      }
    }

    const mapped: ChatMessage[] = items
      .filter((m) => m.role === "user" || m.role === "assistant" || m.role === "tool")
      .map((m) => {
        const timestamp = m.created_at
          ? new Date(m.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
          : undefined;

        if (m.role === "tool") {
          const toolCallId = String(m.tool_call_id || m.id);
          return {
            id: toolCallId,
            role: "tool",
            toolCallId,
            toolName: String(m.tool_name || "tool"),
            status:
              (m.tool_status || "done") === "running"
                ? "running"
                : (m.tool_status || "done") === "error"
                  ? "error"
                  : "done",
            args: m.tool_args,
            output: m.tool_output,
            startedAt: m.started_at || undefined,
            endedAt: m.ended_at || undefined,
          };
        }

        const baseMessage = {
          id: m.id,
          role: m.role as "user" | "assistant",
          content: m.content || "",
          attachments: m.attachments || [],
          references: m.references || [],
          suggestedQuestions: m.suggested_questions || [],
          feedback: (m as any).feedback as [number, number, number] | undefined,
          timestamp,
        };

        // 如果是 assistant 消息，绑定对应的文档
        if (m.role === "assistant" && assistantWritesMap.has(m.id)) {
          return {
            ...baseMessage,
            writes: assistantWritesMap.get(m.id),
          };
        }

        return baseMessage;
      });
    setMessages(mapped);
    if (import.meta.env.DEV) {
      console.log(
        "历史会话加载完成，文档绑定情况:",
        Array.from(assistantWritesMap.entries()).map(([id, writes]) => ({ assistantId: id, writeCount: writes.length }))
      );
    }
  };

  useEffect(() => {
    const el = directoryInputRef.current;
    if (!el) {
      return;
    }
    el.value = "";
  }, [directoryInputRef]);

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  const addLog = (message: string, type: "info" | "error" | "tool" = "info") => {
    setLogs(prev => [
      {
        id: createId(),
        agentId: "main",
        timestamp: new Date().toLocaleTimeString(),
        message,
        type
      },
      ...prev
    ]);
  };

  const fetchTree = async () => {
    const response = await fetch("/api/fs/tree");
    if (!response.ok) {
      setTree(null);
      return;
    }
    const data = (await response.json()) as TreeNode;
    setTree(data);
  };

  const fetchSources = async () => {
    const response = await fetch(`/api/sources/list?q=${encodeURIComponent(searchValue || "")}&limit=200&skip=0`);
    if (!response.ok) {
      setSources([]);
      return;
    }
    const data = (await response.json()) as { results?: UploadedSource[] };
    setSources(Array.isArray(data.results) ? data.results : []);
  };

  const requestRenameSource = (src: UploadedSource) => {
    setSourceActionMenuId(null);
    setRenameSourceTarget(src);
    setRenameSourceDraft(src.filename || "");
    setRenameSourceOpen(true);
  };

  const confirmRenameSource = async () => {
    const target = renameSourceTarget;
    const nextName = renameSourceDraft.trim();
    if (!target || !nextName) return;

    try {
      const resp = await fetch(`/api/sources/${encodeURIComponent(target.id)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filename: nextName }),
      });
      if (!resp.ok) {
        return;
      }
    } catch {
      return;
    } finally {
      setRenameSourceOpen(false);
      setRenameSourceTarget(null);
      setRenameSourceDraft("");
    }

    // 刷新文件树和数据源列表
    await fileTreeActions.fetchTree();
    await fetchSources();

    if (sourceDetailOpen && sourceDetail?.id === target.id) {
      setSourceDetail({ ...sourceDetail, filename: nextName });
    }
  };

  const requestDeleteSource = (src: UploadedSource) => {
    setSourceActionMenuId(null);
    setDeleteSourceId(src.id);
  };

  const confirmDeleteSource = async () => {
    const id = deleteSourceId;
    if (!id) return;
    setDeleteSourceId(null);

    try {
      const resp = await fetch(`/api/sources/${encodeURIComponent(id)}`, { method: "DELETE" });
      if (!resp.ok) {
        return;
      }
    } catch {
      return;
    }

    setSelectedFiles((prev) => {
      const next = new Set(prev);
      next.delete(id);
      return next;
    });

    if (sourceDetailOpen && sourceDetail?.id === id) {
      setSourceDetailOpen(false);
      setSourceDetail(null);
    }

    // 刷新文件树和数据源列表
    await fileTreeActions.fetchTree();
    await fetchSources();
  };

  useEffect(() => {
    if (!podcastConfigOpen) {
      return;
    }
    void fetchPodcastSources("");
  }, [podcastConfigOpen]);

  const openSourceDetail = async (src: UploadedSource) => {
    setSourceDetailOpen(true);
    setSourceDetailLoading(true);
    setSourceDetail(null);
    try {
      const resp = await fetch(`/api/sources/detail?id=${encodeURIComponent(src.id)}&max_bytes=200000`);
      if (!resp.ok) {
        setSourceDetail({ ...src, content_preview: null });
        return;
      }
      const detail = (await resp.json()) as UploadedSourceDetail;
      setSourceDetail(detail);
    } finally {
      setSourceDetailLoading(false);
    }
  };

  const parseUrlToPreview = async () => {
    const url = urlDraft.trim();
    if (!url) {
      setUrlParseState({ status: "error", message: "请先输入 URL" });
      return;
    }
    setUrlParseState({ status: "parsing" });
    try {
      const resp = await fetch("/api/sources/url/parse", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url, mode: urlMode }),
      });
      if (!resp.ok) {
        const text = await resp.text();
        setUrlParseState({ status: "error", message: text || "解析失败" });
        return;
      }
      const data = (await resp.json()) as { filename?: string; content?: string };
      const filename = String(data.filename || "url.md");
      const content = String(data.content || "");
      setUrlParseState({ status: "ready", filename, content });
    } catch (err) {
      const msg = err instanceof Error ? err.message : "解析失败";
      setUrlParseState({ status: "error", message: msg });
    }
  };

  const uploadParsedUrl = async () => {
    if (urlParseState.status !== "ready") return;
    const blob = new Blob([urlParseState.content], { type: "text/markdown;charset=utf-8" });
    const f = new File([blob], urlParseState.filename, { type: "text/markdown" });
    await startUpload([f]);
  };

  const chooseUploadFiles = () => {
    directoryInputRef.current?.click();
  };

  const uploadPendingFiles = async () => {
    if (!pendingUploadFiles.length) return;
    await startUpload(pendingUploadFiles);
    setPendingUploadFiles([]);
  };

  const onDirectoryChosen = (e: React.ChangeEvent<HTMLInputElement>) => {
    const input = e.target;
    const list = Array.from(input.files || []);
    setPendingUploadFiles(list);
    if (list.length > 0) {
      setUploadState({ status: "ready", count: list.length });
    } else {
      setUploadState({ status: "idle" });
    }
  };

  const startUpload = async (files: File[]) => {
    if (!files.length) {
      return;
    }
    setUploadState({ status: "uploading", count: files.length });
    try {
      const form = new FormData();
      for (const f of files) {
        const anyFile = f as unknown as { webkitRelativePath?: string };
        const name = anyFile.webkitRelativePath || f.name;
        form.append("files", f, name);
      }
      const resp = await fetch("/api/sources/upload", {
        method: "POST",
        body: form,
      });
      if (!resp.ok) {
        const text = await resp.text();
        setUploadState({ status: "error", count: files.length, message: text || "上传失败" });
        return;
      }
      setUploadState({ status: "done", count: files.length });
      await fetchSources();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "上传失败";
      setUploadState({ status: "error", count: files.length, message: msg });
    }
  };

  const closeAddSource = () => {
    setAddSourceOpen(false);
    setUrlDraft("");
    setUrlParseState({ status: "idle" });
    setPendingUploadFiles([]);
  };

  const searchFiles = async (query: string) => {
    setSearchValue(query);
    const response = await fetch(`/api/sources/list?q=${encodeURIComponent(query || "")}`);
    if (!response.ok) {
      setSources([]);
      return;
    }
    const data = (await response.json()) as { results?: UploadedSource[] };
    setSources(Array.isArray(data.results) ? data.results : []);
  };

  const toggleSelected = (path: string) => {
    setSelectedFiles((prev: Set<string>) => {
      const next = new Set(prev);
      if (next.has(path)) {
        next.delete(path);
      } else {
        next.add(path);
      }
      return next;
    });
  };


  const handleSocketPayload = (payload: SocketPayload) => {
    // 过滤非当前会话的 SSE 事件，避免旧会话的数据渲染到新会话
    if (payload.session_id && payload.session_id !== currentSessionIdRef.current) {
      return;
    }
    if (payload.type === "rag.references") {
      pendingRefsRef.current = payload.references || [];
      if (assistantBufferRef.current.id) {
        setMessages((prev: ChatMessage[]) =>
          prev.map((m: ChatMessage) =>
            m.id === assistantBufferRef.current.id && m.role === "assistant"
              ? { ...m, references: pendingRefsRef.current || [] }
              : m
          )
        );
      }
      return;
    }
    if (payload.type === "suggested.questions") {
      if (assistantBufferRef.current.id) {
        setMessages((prev: ChatMessage[]) =>
          prev.map((m: ChatMessage) =>
            m.id === assistantBufferRef.current.id && m.role === "assistant"
              ? { ...m, suggestedQuestions: payload.questions || [] }
              : m
          )
        );
      }
      return;
    }
    if (payload.type === "chat.delta" || payload.type === "delta") {
      const timestamp = new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
      if (!assistantBufferRef.current.id) {
        const id = pendingAssistantIdRef.current || createId();
        console.log("chat.delta 创建新消息，使用 ID:", id, "来源:", pendingAssistantIdRef.current ? "后端 message_id" : "前端 createId()");
        assistantBufferRef.current = { id, text: "" };
        setMessages((prev: ChatMessage[]) => {
          const exists = prev.some((m) => m.id === id);
          if (exists) {
            console.log("消息已存在，更新内容:", id);
            return prev.map((m) =>
              m.id === id && m.role === "assistant"
                ? { ...m, timestamp, isPending: false, references: pendingRefsRef.current || m.references }
                : m
            );
          }
          console.log("创建新 assistant 消息:", id);
          
          // 检查是否有待绑定的文档
          const pendingWrites = pendingWritesRef.current.get(id);
          if (pendingWrites && pendingWrites.length > 0) {
            console.log(`发现待绑定文档 ${pendingWrites.length} 个，立即绑定到消息 ${id}`);
            pendingWritesRef.current.delete(id);
            return [...prev, { id, role: "assistant", content: "", timestamp, isPending: false, references: pendingRefsRef.current || [], writes: pendingWrites }];
          }
          
          return [...prev, { id, role: "assistant", content: "", timestamp, isPending: false, references: pendingRefsRef.current || [] }];
        });
      }
      assistantBufferRef.current.text += payload.text;
      setMessages((prev: ChatMessage[]) =>
        prev.map((msg: ChatMessage) =>
          msg.id === assistantBufferRef.current.id
            ? { ...msg, content: assistantBufferRef.current.text }
            : msg
        )
      );
      return;
    }
    if (payload.type === "message.start") {
      currentMessageIdRef.current = payload.message_id || null;
      pendingAssistantIdRef.current = payload.message_id || null;
      console.log("message.start 收到 message_id:", currentMessageIdRef.current);
      return;
    }
    if (payload.type === "tool.start") {
      addLog(`Tool Start: ${payload.name}`, "tool");
      const startedAt = new Date().toISOString();
      setMessages((prev: ChatMessage[]) =>
        upsertToolMessage(prev, {
          toolCallId: payload.id,
          toolName: payload.name,
          status: "running",
          args: payload.args,
          startedAt,
        }),
      );
      return;
    }
    if (payload.type === "tool.end") {
      console.log("tool.end 事件收到:", {
        name: payload.name,
        status: payload.status,
        output: payload.output,
        message_id: (payload as any).message_id,
      });
      addLog(`Tool End: ${payload.name}`, "tool");
      const endedAt = new Date().toISOString();
      setMessages((prev: ChatMessage[]) =>
        upsertToolMessage(prev, {
          toolCallId: payload.id,
          toolName: payload.name,
          status: payload.status === "error" ? "error" : "done",
          output: payload.output,
          endedAt,
        }),
      );

      // 关键逻辑：文档写入相关工具结束后，直接把文档结果写入前端状态，避免必须刷新页面才能看到卡片
      const isWriteTool = payload.name === "save_filesystem_write" || payload.name === "write_file";
      console.log("检查是否为文档写入工具:", {
        name: payload.name,
        isWriteTool,
        notError: payload.status !== "error",
      });

      if (isWriteTool && payload.status !== "error") {
        let out = payload.output as any;

        // 如果 output 是字符串，尝试解析为 JSON
        if (typeof out === "string") {
          try {
            out = JSON.parse(out);
          } catch (e) {
            console.warn("文档写入工具 output 不是有效的 JSON:", out);
          }
        }

        console.log("文档写入工具 tool.end 收到:", { name: payload.name, output: out, type: typeof out });

        const writeId = out && typeof out === "object" ? String((out as any).write_id || "") : "";
        if (writeId) {
          const title = String((out as any).title || "文档");
          const type = String((out as any).type || "txt");
          const size = Number((out as any).size || 0);
          const filePath = String((out as any).file_path || "");

          const nextWrite: FilesystemWrite = {
            write_id: writeId,
            session_id: currentSessionIdRef.current,
            file_path: filePath,
            title,
            type,
            size,
            created_at: new Date().toISOString(),
          };

          console.log("即将更新 filesystemWrites，新文档:", nextWrite);

          setFilesystemWrites((prev) => {
            // 去重：同一个 write_id 只保留最新一条
            const updated = [nextWrite, ...(prev || []).filter((w) => w.write_id !== writeId)];
            console.log("filesystemWrites 已更新:", updated);
            return updated;
          });

          // 绑定到当前 message_id 对应的 assistant 消息
          const targetMessageId = (payload as any).message_id || currentMessageIdRef.current;
          console.log("文档写入工具绑定到 message_id:", targetMessageId);

          setMessages((prev) => {
            console.log(
              "绑定文档时的消息列表:",
              prev.map((m) => ({ id: m.id, role: m.role })),
            );

            if (!targetMessageId) {
              console.warn("没有 targetMessageId，使用回退逻辑");
              // 如果没有 message_id，回退到旧逻辑：绑定到最后一条 assistant 消息
              const lastAssistantIndex = [...prev]
                .map((m, i) => ({ m, i }))
                .reverse()
                .find((x) => x.m.role === "assistant")?.i;

              if (lastAssistantIndex === undefined) {
                console.warn("没有找到 assistant 消息");
                return prev;
              }

              return prev.map((m, i) => {
                if (i !== lastAssistantIndex || m.role !== "assistant") {
                  return m;
                }
                const existing = Array.isArray((m as any).writes)
                  ? ((m as any).writes as FilesystemWrite[])
                  : [];
                const merged = [nextWrite, ...existing.filter((w) => w.write_id !== writeId)];
                return { ...(m as any), writes: merged };
              });
            }

            // 找到 id 匹配的 assistant 消息
            const matchedMessage = prev.find(
              (m) => m.id === targetMessageId && m.role === "assistant",
            );
            if (!matchedMessage) {
              console.warn(
                `未找到匹配的 assistant 消息: ${targetMessageId}，缓存文档等待消息创建`,
              );
              // 缓存文档，等消息创建后再绑定
              const existing = pendingWritesRef.current.get(targetMessageId) || [];
              pendingWritesRef.current.set(targetMessageId, [nextWrite, ...existing]);
              console.log(
                `已缓存文档到 pendingWritesRef，message_id: ${targetMessageId}，当前缓存:`,
                Array.from(pendingWritesRef.current.entries()),
              );
              return prev;
            }

            return prev.map((m) => {
              if (m.id !== targetMessageId || m.role !== "assistant") {
                return m;
              }
              const existing = Array.isArray((m as any).writes)
                ? ((m as any).writes as FilesystemWrite[])
                : [];
              const merged = [nextWrite, ...existing.filter((w) => w.write_id !== writeId)];
              console.log(`文档已绑定到消息 ${targetMessageId}:`, merged);
              return { ...(m as any), writes: merged };
            });
          });
        }
      }
      return;
    }
    if (payload.type === "session.status") {
      if (payload.status === "thinking") {
        setStatus("思考中...");
      }
      if (payload.status === "done") {
        setStatus("就绪");
        assistantBufferRef.current = { id: "", text: "" };
        pendingAssistantIdRef.current = null;
        pendingRefsRef.current = null;
        void fetchChatSessions();

        // 每轮对话结束后刷新字数圆环；达到阈值则触发一次总结并同步更新圆环
        void (async () => {
          await refreshMemoryStats(currentSessionIdRef.current);
          await runMemorySummaryIfNeeded(currentSessionIdRef.current);
        })();
      }
      return;
    }
    if (payload.type === "error") {
      addLog(`Error: ${payload.message}`, "error");
      const toolCallId = createId();
      setMessages((prev: ChatMessage[]) =>
        upsertToolMessage(prev, {
          toolCallId,
          toolName: "Error",
          status: "error",
          output: payload.message || "Unknown error",
          endedAt: new Date().toISOString(),
        }),
      );
    }
  };

  const sendMessage = async () => {
    const trimmed = input.trim();
    if (!trimmed) {
      return;
    }
    await cancelActiveStream(sessionId);
    // 确保 currentSessionIdRef 和当前 sessionId 同步，避免 SSE 事件被过滤
    currentSessionIdRef.current = sessionId;
    
    const attachments = selectedAttachmentNames;
    const pendingAssistantId = createId();
    pendingAssistantIdRef.current = pendingAssistantId;
    pendingRefsRef.current = null;

    const userTimestamp = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

    setMessages((prev: ChatMessage[]) => [
      ...prev,
      { id: createId(), role: "user", content: trimmed, attachments, timestamp: userTimestamp },
    ]);
    setStatus("思考中...");
    setInput("");
    setSelectedFiles(new Set());

    const abortController = new AbortController();
    abortControllerRef.current = abortController;

    try {
      const response = await fetch("/api/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text: trimmed,
          files: selectedList,
          session_id: sessionId,
          assistant_id: "agent",
        }),
        signal: abortController.signal,
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const reader = response.body?.getReader();
      if (!reader) {
        throw new Error("No response body");
      }

      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (line.startsWith("data: ")) {
            const json = line.slice(6);
            try {
              const payload = JSON.parse(json) as SocketPayload;
              handleSocketPayload(payload);
            } catch (e) {
              console.error("Failed to parse SSE event:", e);
            }
          }
        }
      }
    } catch (error: any) {
      if (error.name !== "AbortError") {
        setStatus("连接失败");
        addLog(`Error: ${error.message}`, "error");
      }
    } finally {
      abortControllerRef.current = null;
    }
  };

  const openRefModal = async (refs: RagReference[] | undefined, idx: number) => {
    if (!refs || !refs.length) {
      return;
    }
    setRefModalRefs(refs);
    setRefModalIndex(idx);
    setRefModalFileContent("");
    setRefModalOpen(true);

    const match = refs.find((r) => r.index === idx);
    const source = match?.source;
    const mongoId = match?.mongo_id;
    if (!source && !mongoId) {
      return;
    }
    setRefModalFileLoading(true);
    try {
      if (mongoId) {
        const resp = await fetch(`/api/sources/detail?id=${encodeURIComponent(mongoId)}&max_bytes=200000`);
        if (resp.ok) {
          const data = (await resp.json()) as { content_preview?: string | null };
          setRefModalFileContent(data.content_preview || "");
        }
      } else if (source) {
        const resp = await fetch(`/api/fs/read?path=${encodeURIComponent(source)}&limit=400`);
        if (resp.ok) {
          const data = (await resp.json()) as { content?: string };
          setRefModalFileContent(data.content || "");
        }
      }
    } finally {
      setRefModalFileLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // Command/Ctrl + Enter 发送消息
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      sendMessage();
    }
  };

  return (
    <div className="app-root">
      {/* Main Body (Three Columns) */}
      <div
        className={`app-body ${isLeftCollapsed ? "left-collapsed" : ""} ${
          isRightCollapsed ? "right-collapsed" : ""
        } ${isLeftCollapsed && isRightCollapsed ? "both-collapsed" : ""}`}
      >
        {/* Left Sidebar: Sources */}
        <aside className="sidebar left-sidebar">
          {isLeftCollapsed ? (
            <div className="sidebar-rail">
              <button
                className="sidebar-collapse-icon-btn"
                onClick={() => setIsLeftCollapsed(false)}
                aria-label="展开来源"
                type="button"
              >
                <Icons.PanelExpandLeft />
              </button>
              <button
                className="sidebar-collapse-icon-btn"
                onClick={() => {
                  setIsLeftCollapsed(false);
                  setLeftPanelMode("sources");
                }}
                aria-label="数据来源"
                type="button"
                title="数据来源"
              >
                <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M10 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2h-8l-2-2z"/>
                </svg>
              </button>
            </div>
          ) : (
            <div className="sidebar-card">
              <div className="sidebar-header">
                <h2>{leftPanelMode === "sources" ? "数据来源" : "聊天历史"}</h2>
                <div className="sidebar-header-actions">
                  <button
                    className="sidebar-collapse-icon-btn"
                    onClick={() => setIsLeftCollapsed(true)}
                    aria-label="折叠来源"
                    type="button"
                  >
                    <Icons.PanelCollapseLeft />
                  </button>
                </div>
              </div>

              <div style={{ display: "flex", gap: 8, padding: "0 12px 12px" }}>
                <button
                  type="button"
                  className="source-search-chip"
                  style={{ flex: 1, justifyContent: "center", opacity: leftPanelMode === "sources" ? 1 : 0.7 }}
                  onClick={() => setLeftPanelMode("sources")}
                >
                  数据来源
                </button>
                <button
                  type="button"
                  className="source-search-chip"
                  style={{ flex: 1, justifyContent: "center", opacity: leftPanelMode === "sessions" ? 1 : 0.7 }}
                  onClick={() => {
                    setLeftPanelMode("sessions");
                    void fetchChatSessions();
                  }}
                >
                  聊天历史
                </button>
              </div>

              {leftPanelMode === "sessions" ? (
                <>
                <button
                  className="add-source-btn"
                  type="button"
                  onClick={async () => {
                    const newSid = await createNewSession();
                    if (newSid) {
                      await switchSession(newSid);
                      await fetchChatSessions();
                    }
                  }}
                >
                  <Icons.Plus />
                  新增会话
                </button>
                <div 
                  className="source-list" 
                  style={{ paddingTop: 0 }}
                  onClick={() => setDeleteSessionId(null)}
                >
                  <div className="file-list">
                    {chatSessions.length ? (
                      chatSessions.map((s) => {
                        const active = s.session_id === sessionId;
                        const isDeleting = deleteSessionId === s.session_id;
                        const timeText = s.updated_at
                          ? new Date(s.updated_at).toLocaleString([], { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })
                          : "";
                        
                        return (
                          <div
                            key={s.session_id}
                            className={`file-item ${active ? "selected" : ""}`}
                            onClick={(e) => {
                              e.stopPropagation();
                              void switchSession(s.session_id);
                            }}
                            style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}
                          >
                            <div style={{ minWidth: 0 }}>
                              <div style={{ fontWeight: 600, fontSize: 13, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                                {s.title || "新对话"}
                              </div>
                              <div style={{ fontSize: 12, opacity: 0.7 }}>
                                {timeText}{s.message_count ? ` · ${s.message_count} 条` : ""}
                              </div>
                            </div>
                            <button
                              type="button"
                              style={{ 
                                background: "none",
                                border: "none",
                                color: isDeleting ? "#1f2937" : "#9ca3af",
                                fontSize: 18,
                                cursor: "pointer",
                                padding: 4,
                                lineHeight: 1,
                                transition: "color 0.2s",
                                animation: isDeleting ? "shake 0.5s ease-in-out infinite" : "none"
                              }}
                              onMouseEnter={(e) => !isDeleting && (e.currentTarget.style.color = "#ef4444")}
                              onMouseLeave={(e) => !isDeleting && (e.currentTarget.style.color = "#9ca3af")}
                              onClick={(e) => {
                                e.stopPropagation();
                                if (isDeleting) {
                                  confirmDeleteSession();
                                } else {
                                  requestDeleteSession(s.session_id);
                                }
                              }}
                              aria-label="删除会话"
                            >
                              ×
                            </button>
                          </div>
                        );
                      })
                    ) : (
                      <div className="ref-muted" style={{ padding: 12 }}>暂无历史对话</div>
                    )}
                  </div>
                </div>
                </>
              ) : (
                <>
              <div className="source-actions-row">
                <button
                  className="add-source-btn"
                  type="button"
                  onClick={() => {
                    setPendingUploadFiles([]);
                    setUploadState({ status: "idle" });
                    setAddSourceOpen(true);
                  }}
                >
                  <Icons.Plus />
                  添加来源
                </button>
                <button
                  className="add-folder-btn"
                  type="button"
                  onClick={() => {
                    setNewFolderName("");
                    setNewFolderParentId(null);
                    setCreateFolderOpen(true);
                  }}
                  title="创建文件夹"
                >
                  <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
                    <path d="M.54 3.87.5 3a2 2 0 0 1 2-2h3.672a2 2 0 0 1 1.414.586l.828.828A2 2 0 0 0 9.828 3h3.982a2 2 0 0 1 1.992 2.181l-.637 7A2 2 0 0 1 13.174 14H2.826a2 2 0 0 1-1.991-1.819l-.637-7a1.99 1.99 0 0 1 .342-1.31z" />
                  </svg>
                </button>
              </div>

              <div className="source-list">
                <FileTree
                  items={fileTreeState.items}
                  expandedIds={fileTreeState.expandedIds}
                  selectedId={fileTreeState.selectedId}
                  checkedIds={selectedFiles}
                  dragState={fileTreeState.dragState}
                  onSelect={(item) => {
                    if (item.item_type === "file") {
                      openSourceDetail({ id: item.id, filename: item.filename, rel_path: item.rel_path, size: item.size, created_at: item.created_at });
                    }
                    fileTreeActions.selectItem(item);
                  }}
                  onToggleExpand={fileTreeActions.toggleExpand}
                  onToggleCheck={toggleSelected}
                  onDragStart={fileTreeActions.handleDragStart}
                  onDragOver={fileTreeActions.handleDragOver}
                  onDragEnd={fileTreeActions.handleDragEnd}
                  onDrop={fileTreeActions.handleDrop}
                  onMenuAction={async (action, item) => {
                    switch (action) {
                      case "rename":
                        setRenameSourceTarget({ id: item.id, filename: item.filename });
                        setRenameSourceDraft(item.filename);
                        setRenameSourceOpen(true);
                        break;
                      case "delete":
                        if (item.item_type === "folder") {
                          if (confirm(`确定要删除文件夹 "${item.filename}" 及其所有内容吗？`)) {
                            await fileTreeActions.deleteItem(item.id, true);
                          }
                        } else {
                          setDeleteSourceId(item.id);
                        }
                        break;
                      case "duplicate":
                        await fileTreeActions.duplicateItem(item.id);
                        break;
                      case "import":
                        setPendingUploadFiles([]);
                        setUploadState({ status: "idle" });
                        setNewFolderParentId(item.id);
                        setAddSourceOpen(true);
                        break;
                      case "new-folder":
                        setNewFolderName("");
                        setNewFolderParentId(item.id);
                        setCreateFolderOpen(true);
                        break;
                      case "move":
                        // TODO: implement folder selection modal
                        break;
                    }
                  }}
                />
              </div>
              </>
              )}

              {uploadState.status !== "idle" && (
                <div className="upload-status">
                  {uploadState.status === "uploading" && (
                    <div className="upload-status-row">
                      <span className="upload-spinner" />
                      <span className="upload-status-text">正在上传 {uploadState.count} 个文件...</span>
                    </div>
                  )}
                  {uploadState.status === "done" && (
                    <div className="upload-status-row">
                      <span className="upload-status-text">上传完成（{uploadState.count} 个文件）</span>
                    </div>
                  )}
                  {uploadState.status === "error" && (
                    <div className="upload-status-row">
                      <span className="upload-status-text">上传失败：{uploadState.message}</span>
                    </div>
                  )}
                </div>
              )}

              <div className="corner-actions">
                <div className="header-actions">
                  <button className="icon-btn-header" title="设置"><Icons.Settings /></button>
                  <div className="user-avatar" title="用户">Y</div>
                </div>
              </div>
            </div>
          )}
        </aside>

        {/* Main Content: Chat */}
        <main className="main-content">
          <header className="chat-header">
            <div className="chat-title">对话</div>
          </header>

          <div className="chat-messages">
            {messages.length === 0 && (
               <div className="empty-state">
                  <div className="empty-icon"><Icons.Sparkles /></div>
                  <p>开始与您的文档对话</p>
               </div>
            )}
            {messages.map((message, index) => {
              const lastAssistantIndex = (() => {
                for (let i = messages.length - 1; i >= 0; i -= 1) {
                  if (messages[i].role === "assistant") return i;
                }
                return -1;
              })();

              // 判断是否是连续工具调用中的第一个（前一个消息不是 tool）
              const prevMessage = index > 0 ? messages[index - 1] : null;
              const isFirstToolInSequence = message.role === "tool" && (!prevMessage || prevMessage.role !== "tool");
              // 判断 assistant 消息是否紧跟在 tool 消息后面（此时不显示头像，因为 tool 已显示）
              const isAssistantAfterTool = message.role === "assistant" && prevMessage && prevMessage.role === "tool";
              
              return (
              <div key={message.id} className={`message-row ${message.role}`}>
                {message.role === "tool" ? (
                  <div className="assistant-row">
                    <div className={`assistant-avatar-col ${!isFirstToolInSequence ? 'avatar-hidden' : ''}`}>
                      {isFirstToolInSequence && (
                        <div className="assistant-avatar">
                          <Icons.NotebookLogo />
                        </div>
                      )}
                    </div>
                    <div className="tool-wrapper">
                      <ToolMessage
                        toolName={message.toolName}
                        status={message.status}
                        args={message.args}
                        output={message.output}
                      />
                    </div>
                  </div>
                ) : message.role === "assistant" ? (
                  <div className="assistant-row">
                    <div className={`assistant-avatar-col ${isAssistantAfterTool ? 'avatar-hidden' : ''}`}>
                      {!isAssistantAfterTool && (
                        <div className="assistant-avatar">
                          <Icons.NotebookLogo />
                        </div>
                      )}
                    </div>
                    <div className="message-container assistant">
                      <div className={`message-bubble ${message.role}`}>
                        <div className="message-content">
                          <AssistantContent
                            text={message.content}
                            isPending={!!message.isPending}
                            references={message.references}
                            onOpenRef={(idx) => openRefModal(message.references, idx)}
                          />
                        </div>
                      </div>
                      {(() => {
                        const boundWrites = Array.isArray((message as any).writes)
                          ? ((message as any).writes as FilesystemWrite[])
                          : [];

                        if (!boundWrites.length) {
                          return null;
                        }

                        return (
                          <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 8 }}>
                            {boundWrites.map((w: FilesystemWrite) => (
                              <div
                                key={w.write_id}
                                style={{
                                  background: "#f8f9fa",
                                  border: "1px solid #e9ecef",
                                  borderRadius: 8,
                                  padding: "10px 12px",
                                  display: "flex",
                                  alignItems: "center",
                                  gap: 10,
                                  transition: "all 0.2s",
                                }}
                                onMouseEnter={(e) => (e.currentTarget.style.background = "#e9ecef")}
                                onMouseLeave={(e) => (e.currentTarget.style.background = "#f8f9fa")}
                              >
                                <div style={{ display: "flex", alignItems: "center" }}>
                                  <Icons.Pdf />
                                </div>
                                <div
                                  style={{ flex: 1, minWidth: 0, cursor: "pointer" }}
                                  onClick={async () => {
                                    const resp = await fetch(
                                      `/api/filesystem/write/${encodeURIComponent(w.write_id)}?session_id=${encodeURIComponent(sessionId)}`,
                                    );
                                    if (resp.ok) {
                                      const data = await resp.json();
                                      setWriteDetail({
                                        write_id: w.write_id,
                                        content: data.content || "",
                                        binary_content: data.binary_content || "",
                                        title: w.title,
                                        file_type: data.metadata?.type || "",
                                        file_path: data.file_path || "",
                                      });
                                      setWriteDetailOpen(true);
                                    }
                                  }}
                                >
                                  <div
                                    style={{
                                      fontSize: 13,
                                      fontWeight: 600,
                                      color: "#1a1a1a",
                                      overflow: "hidden",
                                      textOverflow: "ellipsis",
                                      whiteSpace: "nowrap",
                                    }}
                                  >
                                    {w.title}
                                  </div>
                                  <div style={{ fontSize: 12, color: "#6c757d" }}>
                                    {w.type} · {(w.size / 1024).toFixed(1)}KB
                                  </div>
                                </div>
                                <button
                                  style={{
                                    background: "transparent",
                                    border: "none",
                                    padding: "6px",
                                    color: "#6c757d",
                                    cursor: "pointer",
                                    display: "flex",
                                    alignItems: "center",
                                    justifyContent: "center",
                                    borderRadius: 4,
                                    transition: "all 0.2s",
                                  }}
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    const downloadUrl = `/api/filesystem/write/${encodeURIComponent(w.write_id)}/download?session_id=${encodeURIComponent(sessionId)}`;
                                    const link = document.createElement("a");
                                    link.href = downloadUrl;
                                    link.download = w.title.endsWith(".md") ? w.title : `${w.title}.md`;
                                    document.body.appendChild(link);
                                    link.click();
                                    document.body.removeChild(link);
                                  }}
                                  onMouseEnter={(e) => {
                                    e.currentTarget.style.background = "#e9ecef";
                                    e.currentTarget.style.color = "#495057";
                                  }}
                                  onMouseLeave={(e) => {
                                    e.currentTarget.style.background = "transparent";
                                    e.currentTarget.style.color = "#6c757d";
                                  }}
                                >
                                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                                    <polyline points="7 10 12 15 17 10" />
                                    <line x1="12" y1="15" x2="12" y2="3" />
                                  </svg>
                                </button>
                              </div>
                            ))}
                          </div>
                        );
                      })()}
                      <div className="message-actions">
                        <button
                          className="action-btn"
                          type="button"
                          onClick={() => handleCopyMessage(message)}
                        >
                          <Icons.Copy />
                        </button>
                        <button
                          className="action-btn"
                          type="button"
                          onClick={() => handleLikeMessage(message)}
                        >
                          <Icons.ThumbUp />
                        </button>
                        <button
                          className="action-btn"
                          type="button"
                          onClick={() => handleDislikeMessage(message)}
                        >
                          <Icons.ThumbDown />
                        </button>
                      </div>
                      {message.suggestedQuestions && message.suggestedQuestions.length > 0 && (
                        <div className="suggested-questions">
                          {message.suggestedQuestions.map((q, idx) => (
                            <button
                              key={idx}
                              className="suggested-question-btn"
                              type="button"
                              onClick={() => {
                                setInput(q);
                                setTimeout(() => sendMessage(), 100);
                              }}
                            >
                              {q}
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                ) : (
                  <div className={`message-container ${message.role}`}>
                     {message.role === "user" && message.timestamp && (
                        <div className="message-meta-row">
                          <div className="message-meta">今天 • {message.timestamp}</div>
                        </div>
                     )}
                     <div className={`message-bubble ${message.role}`}>
                        <div className="message-content">
                          {message.content}
                          {!!message.attachments?.length && (
                            <div className="message-attachments">
                              <div className="message-attachments-header">已附带来源</div>
                              <div className="message-attachments-chips">
                                {(message.attachments.filter(Boolean) as AttachmentMeta[]).slice(0, 8).map((p) => {
                                  const mongoId = typeof p === "string" ? p : (p.mongo_id || "");
                                  const filename = typeof p === "string" ? "" : (p.filename || "");
                                  const title = filename || mongoId;
                                  const label = (filename || mongoId).split("/").pop();
                                  return (
                                    <span
                                      key={mongoId || filename || JSON.stringify(p)}
                                      className="attachment-chip"
                                      title={title}
                                    >
                                      {label}
                                    </span>
                                  );
                                })}
                                {message.attachments.length > 8 && (
                                  <span className="attachment-chip">+{message.attachments.length - 8}</span>
                                )}
                              </div>
                            </div>
                          )}
                        </div>
                     </div>
                  </div>
                )}
              </div>
            );
            })}
            {(() => {
              const hasRunningTool = messages.some(
                (m) => m.role === "tool" && m.status === "running",
              );
              const shouldShowThinking = status === "思考中..." && !hasRunningTool;
              if (!shouldShowThinking) return null;
              return (
                <div className="message-row assistant">
                  <div className="assistant-row">
                    <div className="assistant-avatar-col">
                      <div className="assistant-avatar">
                        <Icons.NotebookLogo />
                      </div>
                    </div>
                    <div className="message-container assistant">
                      <div className="message-bubble assistant">
                        <div className="message-content">
                          <div className="assistant-thinking">
                            <span className="dot" />
                            <span className="dot" />
                            <span className="dot" />
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              );
            })()}
            <div ref={messagesEndRef} />
          </div>

          <div className="input-area">
            <div className="input-wrapper">
              <textarea
                rows={1}
                placeholder="用 DeepAgents 创造无限可能"
                value={input}
                onInput={(e) => {
                  const target = e.target as HTMLTextAreaElement;
                  target.style.height = 'auto';
                  target.style.height = `${Math.min(target.scrollHeight, 200)}px`;
                  setInput(target.value);
                }}
                onKeyDown={handleKeyDown}
              />
              <div className="input-footer">
                <div className="input-actions-left">
                  <button type="button" className="input-action-btn" title="添加">
                    <Icons.Plus />
                  </button>
                  <button type="button" className="input-action-btn" title="提及">
                    <Icons.User />
                  </button>
                  <MemoryProgressRing
                    ratio={memoryStats.ratio}
                    chars={memoryStats.chars}
                    title={`记忆字数 ${memoryStats.chars}/${memoryStats.limit}`}
                  />
                </div>
                <div className="input-actions-right">
                  <button type="button" className="input-action-btn" title="语音">
                    <Icons.Mic />
                  </button>
                  {isStreaming ? (
                    <button
                      className="send-btn"
                      title="停止生成"
                      onClick={() => {
                        void cancelActiveStream(sessionId);
                        setStatus("就绪");
                      }}
                    >
                      <Icons.Stop />
                    </button>
                  ) : null}
                  <button className="send-btn" onClick={sendMessage} disabled={!input.trim()}>
                    <Icons.Send />
                  </button>
                </div>
              </div>
            </div>
            <div className="disclaimer">AI生成的内容可能不准确，请仔细核对重要信息</div>
          </div>
        </main>

        {/* Right Sidebar: Agents/Studio */}
        <aside className="sidebar right-sidebar">
          {isRightCollapsed ? (
            <div className="sidebar-rail sidebar-rail-right">
              <button
                className="sidebar-collapse-icon-btn"
                onClick={() => setIsRightCollapsed(false)}
                aria-label="展开 Studio"
                type="button"
              >
                <Icons.PanelExpandRight />
              </button>
            </div>
          ) : (
            <div className="sidebar-card studio-card">
              <div className="sidebar-header">
                <h2>Studio</h2>
                <div className="sidebar-header-actions">
                  <button
                    className="sidebar-collapse-icon-btn"
                    onClick={() => setIsRightCollapsed(true)}
                    aria-label="折叠 Studio"
                    type="button"
                  >
                    <Icons.PanelCollapseRight />
                  </button>
                </div>
              </div>
              
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, padding: "0 12px 12px" }}>
                <div
                  style={{
                    background: "#d1e7dd",
                    borderRadius: 12,
                    padding: "12px",
                    cursor: "pointer",
                    display: "flex",
                    flexDirection: "column",
                    gap: 8,
                    position: "relative",
                    border: selectedAgentId === "podcast" ? "2px solid #0d6efd" : "none"
                  }}
                  onClick={() => {
                    setSelectedAgentId("podcast");
                    void startPodcastGeneration();
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    <div style={{ color: "#198754", display: "flex" }}><Icons.Sound /></div>
                    <div style={{ fontSize: 13, fontWeight: 600, color: "#1a1a1a" }}>生成播客</div>
                  </div>
                  <button
                    type="button"
                    style={{
                      position: "absolute",
                      top: 8,
                      right: 8,
                      background: "rgba(255,255,255,0.8)",
                      border: "none",
                      borderRadius: 6,
                      width: 24,
                      height: 24,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      cursor: "pointer",
                      color: "#666"
                    }}
                    onClick={(e) => {
                      e.stopPropagation();
                      setPodcastConfigOpen(true);
                    }}
                    aria-label="播客配置"
                  >
                    <Icons.Settings />
                  </button>
                </div>

                {AGENTS.map(agent => (
                  <div 
                    key={agent.id}
                    style={{
                      background: agent.color,
                      borderRadius: 12,
                      padding: "12px",
                      cursor: "pointer",
                      display: "flex",
                      flexDirection: "column",
                      gap: 8,
                      position: "relative",
                      border: selectedAgentId === agent.id ? "2px solid #0d6efd" : "none"
                    }}
                    onClick={() => setSelectedAgentId(agent.id)}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                      <div style={{ color: "#666", display: "flex" }}><agent.Icon /></div>
                      <div style={{ fontSize: 13, fontWeight: 600, color: "#1a1a1a" }}>{agent.name}</div>
                    </div>
                    <button
                      type="button"
                      style={{
                        position: "absolute",
                        top: 8,
                        right: 8,
                        background: "rgba(255,255,255,0.8)",
                        border: "none",
                        borderRadius: 6,
                        width: 24,
                        height: 24,
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        cursor: "pointer",
                        color: "#666"
                      }}
                      onClick={(e) => e.stopPropagation()}
                    >
                      <Icons.Settings />
                    </button>
                  </div>
                ))}
              </div>

              <div className="saved-notes-section">
                <div className="section-title">运行历史</div>
                <div className="note-list">
                  {podcastRuns.map((r) => (
                    <div
                      key={r.run_id}
                      className="note-item"
                      onClick={() => void openPodcastRunDetail(r.run_id)}
                      style={{
                        cursor: "pointer",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between",
                        gap: 8,
                      }}
                    >
                      {(() => {
                        const isDeleting = deletePodcastRunId === r.run_id;
                        return (
                          <>
                            <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
                              <div className="note-icon"><Icons.Sound /></div>
                              <div className="note-content">
                                <div className="note-title" style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                                  {r.episode_name}
                                </div>
                                <div className="note-meta">{r.created_at} • {r.status}</div>
                              </div>
                            </div>
                            <button
                              type="button"
                              style={{
                                background: "none",
                                border: "none",
                                color: isDeleting ? "#1f2937" : "#9ca3af",
                                fontSize: 18,
                                cursor: "pointer",
                                padding: 4,
                                lineHeight: 1,
                                transition: "color 0.2s",
                                animation: isDeleting ? "shake 0.5s ease-in-out infinite" : "none",
                              }}
                              onMouseEnter={(e) => !isDeleting && (e.currentTarget.style.color = "#ef4444")}
                              onMouseLeave={(e) => !isDeleting && (e.currentTarget.style.color = "#9ca3af")}
                              onClick={(e) => {
                                e.stopPropagation();
                                if (isDeleting) {
                                  void confirmDeletePodcastRun();
                                } else {
                                  requestDeletePodcastRun(r.run_id);
                                }
                              }}
                              aria-label="删除运行记录"
                            >
                              ×
                            </button>
                          </>
                        );
                      })()}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </aside>
      </div>

      {podcastConfigOpen && (
        <div className="add-source-backdrop" onClick={() => setPodcastConfigOpen(false)}>
          <div className="podcast-config-modal" onClick={(e) => e.stopPropagation()}>
            <div className="add-source-top">
              <div className="add-source-title">
                播客配置
              </div>
              <div className="podcast-config-top-actions">
                <button
                  className="podcast-config-icon-btn"
                  type="button"
                  title="配置管理"
                  onClick={() => setPodcastSettingsOpen(true)}
                >
                  <Icons.Settings />
                </button>
                <button
                  className="podcast-config-icon-btn"
                  type="button"
                  title="关闭"
                  onClick={() => setPodcastConfigOpen(false)}
                >
                  <Icons.Close />
                </button>
              </div>
            </div>

            <div className="podcast-config-body">
              <div className="podcast-config-row">
                <div className="ref-section-title">发言人</div>
                <select
                  className="podcast-config-select"
                  value={podcastSelectedSpeaker}
                  onChange={(e) => setPodcastSelectedSpeaker(e.currentTarget.value)}
                >
                  <option value="">请选择</option>
                  {podcastSpeakerProfiles.map((p) => (
                    <option key={p.id} value={p.name}>{p.name}</option>
                  ))}
                </select>
              </div>

              <div className="podcast-config-row">
                <div className="ref-section-title">节目配置</div>
                <select
                  className="podcast-config-select"
                  value={podcastSelectedEpisode}
                  onChange={(e) => setPodcastSelectedEpisode(e.currentTarget.value)}
                >
                  <option value="">请选择（可选）</option>
                  {podcastEpisodeProfiles.map((p) => (
                    <option key={p.id} value={p.name}>{p.name}</option>
                  ))}
                </select>
              </div>

              <div className="podcast-config-row">
                <div className="ref-section-title">播客标题</div>
                <input
                  className="podcast-config-input"
                  value={podcastEpisodeName}
                  onInput={(e) => setPodcastEpisodeName((e.target as HTMLInputElement).value)}
                  placeholder="请输入播客标题"
                />
              </div>

              <div className="podcast-config-row">
                <div className="ref-section-title">补充指令</div>
                <textarea
                  className="podcast-config-textarea"
                  value={podcastBriefingSuffix}
                  onInput={(e) => setPodcastBriefingSuffix((e.target as HTMLTextAreaElement).value)}
                  placeholder="可选：补充生成要求"
                />
              </div>

              <div className="podcast-config-row">
                <div className="ref-section-title">数据源</div>
                <button
                  className="podcast-source-select-btn"
                  type="button"
                  onClick={() => setPodcastSourceSelectOpen(true)}
                >
                  <span>选择数据源</span>
                  <span className="podcast-source-count">已选 {podcastSelectedSourceIds.size}/{podcastSources.length}</span>
                </button>
              </div>

              <div className="podcast-config-actions">
                <button className="add-source-action" type="button" onClick={() => setPodcastConfigOpen(false)}>
                  取消
                </button>
                <button
                  className="add-source-action primary"
                  type="button"
                  onClick={() => {
                    setPodcastConfigOpen(false);
                    void startPodcastGeneration();
                  }}
                >
                  生成播客
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {podcastSourceSelectOpen && (
        <div className="add-source-backdrop" onClick={() => setPodcastSourceSelectOpen(false)}>
          <div className="podcast-source-modal" onClick={(e) => e.stopPropagation()}>
            <div className="add-source-top">
              <div className="add-source-title">
                选择数据源
                <div className="add-source-subtitle">选择用于生成播客的素材</div>
              </div>
              <button className="add-source-close" type="button" onClick={() => setPodcastSourceSelectOpen(false)}>
                ×
              </button>
            </div>
            <div className="podcast-source-modal-body">
              <label className="podcast-source-all">
                <input
                  type="checkbox"
                  checked={podcastSources.length > 0 && podcastSelectedSourceIds.size === podcastSources.length}
                  onChange={(e) => setAllPodcastSources((e.target as HTMLInputElement).checked)}
                />
                <span className="podcast-source-all-text">选择所有来源</span>
                <span className="podcast-source-all-meta">
                  已选 {podcastSelectedSourceIds.size}/{podcastSources.length}
                </span>
              </label>

              <div className="podcast-source-list">
                {podcastSourcesLoading ? (
                  <div className="ref-muted" style={{ padding: "8px 2px" }}>加载中...</div>
                ) : (
                  <div className="podcast-source-items">
                    {podcastSources.map((s) => {
                      const checked = podcastSelectedSourceIds.has(s.id);
                      return (
                        <div
                          key={s.id}
                          className={`podcast-source-row ${checked ? "selected" : ""}`}
                          onClick={() => togglePodcastSource(s.id)}
                          role="button"
                          tabIndex={0}
                        >
                          <div className="podcast-source-left">
                            <div className="podcast-source-icon"><Icons.Pdf /></div>
                            <div className="podcast-source-name" title={s.filename}>{s.filename}</div>
                          </div>
                          <div className="podcast-source-right" onClick={(e) => e.stopPropagation()}>
                            <input
                              type="checkbox"
                              checked={checked}
                              onChange={() => togglePodcastSource(s.id)}
                            />
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>
            <div className="podcast-source-modal-actions">
              <button className="add-source-action primary" type="button" onClick={() => setPodcastSourceSelectOpen(false)}>
                确定
              </button>
            </div>
          </div>
        </div>
      )}

      {podcastRunDetailOpen && (
        <div className="ref-modal-backdrop" onClick={() => setPodcastRunDetailOpen(false)}>
          <div className="ref-modal" onClick={(e) => e.stopPropagation()}>
            <div className="ref-modal-header">
              <div className="ref-modal-title">运行历史详情</div>
              <button className="ref-modal-close" onClick={() => setPodcastRunDetailOpen(false)} type="button">
                ×
              </button>
            </div>
            <div className="ref-modal-body">
              {podcastRunDetailLoading ? (
                <div className="ref-muted">加载中...</div>
              ) : podcastRunDetail ? (
                <div>
                  <div className="ref-source">{podcastRunDetail.run.episode_name}</div>
                  <div className="ref-muted" style={{ marginTop: 8 }}>
                    {podcastRunDetail.run.status} • {podcastRunDetail.run.created_at}
                  </div>
                  {podcastRunDetail.run.message && (
                    <div className="ref-muted" style={{ marginTop: 8 }}>{podcastRunDetail.run.message}</div>
                  )}
                  <div className="ref-divider" />
                  <div className="ref-section-title">音频</div>
                  {podcastRunDetail.result?.audio_file_path ? (
                    <div style={{ marginTop: 8 }}>
                      <audio
                        controls
                        preload="none"
                        src={`/api/podcast/runs/${encodeURIComponent(podcastRunDetail.run.run_id)}/audio`}
                        style={{ width: "100%" }}
                      />
                      <div className="ref-muted" style={{ marginTop: 8 }}>
                        <a
                          href={`/api/podcast/runs/${encodeURIComponent(podcastRunDetail.run.run_id)}/audio`}
                          target="_blank"
                          rel="noreferrer"
                        >
                          下载音频
                        </a>
                      </div>
                    </div>
                  ) : (
                    <div className="ref-muted">暂无音频（可能仍在生成中）</div>
                  )}
                  <div className="ref-divider" />
                  <div className="ref-section-title">对话内容</div>
                  {podcastRunDetail.result ? (
                    (() => {
                      const items = extractPodcastTranscript(podcastRunDetail.result.transcript);
                      if (!items.length) {
                        return <div className="ref-muted">暂无对话内容</div>;
                      }
                      return (
                        <div className="podcast-transcript">
                          {items.map((it, idx) => (
                            <div key={`${idx}-${it.speaker}`} className="podcast-transcript-item">
                              <div className="podcast-transcript-speaker" title={it.speaker || ""}>
                                {it.speaker}
                              </div>
                              <div className="podcast-transcript-bubble">
                                {it.dialogue}
                              </div>
                            </div>
                          ))}
                        </div>
                      );
                    })()
                  ) : (
                    <div className="ref-muted">暂无结果（可能仍在生成中）</div>
                  )}

                  {podcastRunDetail.result && (
                    <div style={{ marginTop: 12 }}>
                      <details>
                        <summary style={{ cursor: "pointer" }}>原始 JSON</summary>
                        <pre style={{ fontSize: 12, marginTop: 8 }}>{formatJson(podcastRunDetail.result)}</pre>
                      </details>
                    </div>
                  )}
                </div>
              ) : (
                <div className="ref-muted">暂无数据</div>
              )}
            </div>
          </div>
        </div>
      )}

      {podcastSettingsOpen && (
        <div className="add-source-backdrop" onClick={() => {
          setPodcastSettingsOpen(false);
          setEditingSpeakerProfile(null);
          setEditingEpisodeProfile(null);
          setIsCreatingProfile(false);
        }}>
          <div className="podcast-settings-modal" onClick={(e) => e.stopPropagation()}>
            <div className="add-source-top">
              <div className="add-source-title">
                配置管理
              </div>
              <button className="add-source-close" type="button" onClick={() => {
                setPodcastSettingsOpen(false);
                setEditingSpeakerProfile(null);
                setEditingEpisodeProfile(null);
                setIsCreatingProfile(false);
              }}>
                ×
              </button>
            </div>

            <div className="podcast-settings-tabs">
              <button
                className={`podcast-settings-tab ${podcastSettingsTab === "speaker" ? "active" : ""}`}
                onClick={() => {
                  setPodcastSettingsTab("speaker");
                  setEditingSpeakerProfile(null);
                  setEditingEpisodeProfile(null);
                  setIsCreatingProfile(false);
                }}
              >
                说话人配置
              </button>
              <button
                className={`podcast-settings-tab ${podcastSettingsTab === "episode" ? "active" : ""}`}
                onClick={() => {
                  setPodcastSettingsTab("episode");
                  setEditingSpeakerProfile(null);
                  setEditingEpisodeProfile(null);
                  setIsCreatingProfile(false);
                }}
              >
                节目配置
              </button>
            </div>

            <div className="podcast-settings-body">
              {podcastSettingsTab === "speaker" && !editingSpeakerProfile && (
                <div className="podcast-profile-list">
                  {podcastSpeakerProfiles.map((p) => (
                    <div key={p.id} className={`podcast-profile-item ${deletingProfileId === p.id ? "deleting" : ""}`}>
                      <div className="podcast-profile-info">
                        <div className="podcast-profile-name">{p.name}</div>
                        <div className="podcast-profile-meta">
                          {p.tts_provider} • {p.speakers?.length || 0} 位说话人
                        </div>
                      </div>
                      <div className="podcast-profile-actions">
                        <button
                          className="podcast-profile-icon-btn"
                          title="编辑"
                          onClick={() => {
                            setEditingSpeakerProfile(p);
                            setIsCreatingProfile(false);
                          }}
                        >
                          <Icons.Settings />
                        </button>
                        <button
                          className="podcast-profile-icon-btn"
                          title="删除"
                          onClick={() => {
                            setDeletingProfileId(p.id);
                            setDeletingProfileType("speaker");
                          }}
                        >
                          <Icons.Close />
                        </button>
                      </div>
                    </div>
                  ))}
                  <button
                    className="podcast-add-btn"
                    onClick={() => {
                      setEditingSpeakerProfile({
                        id: "",
                        name: "",
                        description: "",
                        tts_provider: "dashscope",
                        tts_model: "cosyvoice-v2",
                        speakers: [{ name: "主持人", voice_id: "longxiaochun_v2", backstory: "", personality: "" }],
                      });
                      setIsCreatingProfile(true);
                    }}
                  >
                    + 新建说话人配置
                  </button>
                </div>
              )}

              {podcastSettingsTab === "speaker" && editingSpeakerProfile && (
                <SpeakerProfileEditor
                  profile={editingSpeakerProfile}
                  onChange={setEditingSpeakerProfile}
                  onSave={async () => {
                    const success = await saveSpeakerProfile(editingSpeakerProfile);
                    if (success) {
                      setEditingSpeakerProfile(null);
                      setIsCreatingProfile(false);
                    }
                  }}
                  onCancel={() => {
                    setEditingSpeakerProfile(null);
                    setIsCreatingProfile(false);
                  }}
                />
              )}

              {podcastSettingsTab === "episode" && !editingEpisodeProfile && (
                <div className="podcast-profile-list">
                  {podcastEpisodeProfiles.map((p) => (
                    <div key={p.id} className={`podcast-profile-item ${deletingProfileId === p.id ? "deleting" : ""}`}>
                      <div className="podcast-profile-info">
                        <div className="podcast-profile-name">{p.name}</div>
                        <div className="podcast-profile-meta">
                          {p.outline_model} • {p.num_segments} 段落
                        </div>
                      </div>
                      <div className="podcast-profile-actions">
                        <button
                          className="podcast-profile-icon-btn"
                          title="编辑"
                          onClick={() => {
                            setEditingEpisodeProfile(p);
                            setIsCreatingProfile(false);
                          }}
                        >
                          <Icons.Settings />
                        </button>
                        <button
                          className="podcast-profile-icon-btn"
                          title="删除"
                          onClick={() => {
                            setDeletingProfileId(p.id);
                            setDeletingProfileType("episode");
                          }}
                        >
                          <Icons.Close />
                        </button>
                      </div>
                    </div>
                  ))}
                  <button
                    className="podcast-add-btn"
                    onClick={() => {
                      setEditingEpisodeProfile({
                        id: "",
                        name: "",
                        description: "",
                        speaker_config: podcastSpeakerProfiles[0]?.name || "",
                        outline_provider: "openai-compatible",
                        outline_model: "qwen-plus",
                        transcript_provider: "openai-compatible",
                        transcript_model: "qwen-turbo",
                        default_briefing: "",
                        num_segments: 4,
                      });
                      setIsCreatingProfile(true);
                    }}
                  >
                    + 新建节目配置
                  </button>
                </div>
              )}

              {podcastSettingsTab === "episode" && editingEpisodeProfile && (
                <EpisodeProfileEditor
                  profile={editingEpisodeProfile}
                  speakerProfiles={podcastSpeakerProfiles}
                  onChange={setEditingEpisodeProfile}
                  onSave={async () => {
                    const success = await saveEpisodeProfile(editingEpisodeProfile);
                    if (success) {
                      setEditingEpisodeProfile(null);
                      setIsCreatingProfile(false);
                    }
                  }}
                  onCancel={() => {
                    setEditingEpisodeProfile(null);
                    setIsCreatingProfile(false);
                  }}
                />
              )}
            </div>
          </div>
        </div>
      )}

      {deletingProfileId && (
        <div className="add-source-backdrop" onClick={() => {
          setDeletingProfileId(null);
          setDeletingProfileType(null);
        }}>
          <div className="source-action-modal" onClick={(e) => e.stopPropagation()}>
            <div className="source-action-title">删除配置</div>
            <div className="source-action-desc">确认删除该配置吗？删除后不可恢复。</div>
            <div className="source-action-actions">
              <button className="source-action-btn" type="button" onClick={() => {
                setDeletingProfileId(null);
                setDeletingProfileType(null);
              }}>
                取消
              </button>
              <button className="source-action-btn danger" type="button" onClick={async () => {
                if (deletingProfileType === "speaker") {
                  await deleteSpeakerProfile(deletingProfileId);
                } else if (deletingProfileType === "episode") {
                  await deleteEpisodeProfile(deletingProfileId);
                }
                setDeletingProfileId(null);
                setDeletingProfileType(null);
              }}>
                删除
              </button>
            </div>
          </div>
        </div>
      )}

      {refModalOpen && (
        <div className="ref-modal-backdrop" onClick={() => setRefModalOpen(false)}>
          <div className="ref-modal" onClick={(e) => e.stopPropagation()}>
            <div className="ref-modal-header">
              <div className="ref-modal-title">
                引用 [{refModalIndex}]
              </div>
              <button className="ref-modal-close" onClick={() => setRefModalOpen(false)} type="button">
                ×
              </button>
            </div>
            <div className="ref-modal-body">
              {(() => {
                const r = (refModalRefs || []).find((x) => x.index === refModalIndex);
                if (!r) {
                  return <div className="ref-muted">没有找到引用内容</div>;
                }
                return (
                  <div>
                    <div className="ref-source">{r.source ? r.source.split("/").pop() : "unknown"}</div>
                    {r.text && <pre className="ref-snippet">{r.text}</pre>}
                    <div className="ref-divider" />
                    <div className="ref-section-title">原文片段</div>
                    {refModalFileLoading ? (
                      <div className="ref-muted">加载中...</div>
                    ) : (
                      <pre className="ref-file">{refModalFileContent || ""}</pre>
                    )}
                  </div>
                );
              })()}
            </div>
          </div>
        </div>
      )}

      {writeDetailOpen && (
        <div className="ref-modal-backdrop" onClick={() => { setWriteDetailOpen(false); setWriteDetailFullscreen(false); }}>
          <div
            className={writeDetailFullscreen ? "ref-modal ref-modal-fullscreen" : "ref-modal"}
            onClick={(e) => e.stopPropagation()}
            style={writeDetailFullscreen ? {
              width: "100vw",
              height: "100vh",
              borderRadius: 0,
              margin: 0
            } : undefined}
          >
            <div className="ref-modal-header">
              <div className="ref-modal-title">
                {writeDetail?.title || "文档详情"}
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <button
                  className="ref-modal-close"
                  onClick={() => setWriteDetailFullscreen(!writeDetailFullscreen)}
                  type="button"
                  title={writeDetailFullscreen ? "退出全屏" : "全屏查看"}
                >
                  {writeDetailFullscreen ? (
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M8 3v3a2 2 0 0 1-2 2H3m18 0h-3a2 2 0 0 1-2-2V3m0 18v-3a2 2 0 0 1 2-2h3M3 16h3a2 2 0 0 1 2 2v3" />
                    </svg>
                  ) : (
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3" />
                    </svg>
                  )}
                </button>
                <button className="ref-modal-close" onClick={() => { setWriteDetailOpen(false); setWriteDetailFullscreen(false); }} type="button">
                  ×
                </button>
              </div>
            </div>
            <div className="ref-modal-body" style={writeDetailFullscreen ? { height: "calc(100vh - 56px)" } : undefined}>
              {writeDetail ? (
                <div>
                  <div className="ref-section-title">文档内容</div>
                  <div style={{ maxHeight: "calc(100vh - 150px)", overflow: "auto" }}>
                    {(() => {
                      const fileType = writeDetail.file_type?.toLowerCase() || "";
                      // 获取二进制内容（优先使用 binary_content，兼容旧数据用 content）
                      const binaryData = writeDetail.binary_content || writeDetail.content;
                      // PDF 文件：使用 embed 标签渲染
                      if (fileType === "pdf") {
                        if (!binaryData) {
                          return <div className="ref-muted">PDF 内容为空</div>;
                        }
                        const pdfDataUrl = `data:application/pdf;base64,${binaryData}`;
                        return (
                          <embed
                            src={pdfDataUrl}
                            type="application/pdf"
                            style={{ width: "100%", height: "calc(100vh - 200px)", minHeight: "500px" }}
                          />
                        );
                      }
                      // 图片文件：使用 img 标签渲染
                      if (["png", "jpg", "jpeg", "gif", "webp"].includes(fileType)) {
                        if (!binaryData) {
                          return <div className="ref-muted">图片内容为空</div>;
                        }
                        const mimeType = fileType === "jpg" ? "jpeg" : fileType;
                        const imgDataUrl = `data:image/${mimeType};base64,${binaryData}`;
                        return (
                          <img
                            src={imgDataUrl}
                            alt={writeDetail.title}
                            style={{ maxWidth: "100%", height: "auto" }}
                          />
                        );
                      }
                      // HTML 文件：使用 iframe 渲染
                      if (["html", "htm"].includes(fileType)) {
                        return (
                          <iframe
                            srcDoc={writeDetail.content}
                            title={writeDetail.title}
                            style={{
                              width: "100%",
                              height: "calc(100vh - 200px)",
                              minHeight: "500px",
                              border: "1px solid #e0e0e0",
                              borderRadius: "4px",
                              background: "#fff"
                            }}
                            sandbox="allow-same-origin"
                          />
                        );
                      }
                      // 其他文件：使用 AssistantContent 渲染（文本/Markdown）
                      return (
                        <AssistantContent
                          text={writeDetail.content}
                          isPending={false}
                          references={[]}
                          onOpenRef={() => {}}
                        />
                      );
                    })()}
                  </div>
                </div>
              ) : (
                <div className="ref-muted">加载中...</div>
              )}
            </div>
          </div>
        </div>
      )}


      <input
        ref={directoryInputRef}
        type="file"
        style={{ display: "none" }}
        multiple
        accept=".txt,.md,.markdown,.pdf,.doc,.docx,.ppt,.pptx,.xls,.xlsx,.csv,.json,.yaml,.yml"
        onChange={onDirectoryChosen}
      />

      {addSourceOpen && (
        <div className="add-source-backdrop" onClick={closeAddSource}>
          <div className="add-source-modal" onClick={(e) => e.stopPropagation()}>
            <div className="add-source-top">
              <div className="add-source-title">
                根据以下内容生成音频概览和视频概览
                <div className="add-source-subtitle">您的笔记</div>
              </div>
              <button className="add-source-close" type="button" onClick={closeAddSource}>
                ×
              </button>
            </div>

            <div className="add-source-search">
              <div className="add-source-search-box">
                <div className="add-source-search-row">
                  <div className="add-source-search-icon">
                    <Icons.Search />
                  </div>
                  <input
                    className="add-source-search-input"
                    placeholder="在网络中搜索新来源"
                    value={urlDraft}
                    onInput={(e) => {
                      setUrlDraft((e.target as HTMLInputElement).value);
                      if (urlParseState.status !== "idle") {
                        setUrlParseState({ status: "idle" });
                      }
                    }}
                  />
                </div>

                <div className="add-source-search-controls">
                  <button
                    className={`add-source-chip ${urlMode === "crawl" ? "active" : ""}`}
                    type="button"
                    aria-pressed={urlMode === "crawl"}
                    onClick={() => setUrlMode("crawl")}
                  >
                    <span className="chip-icon"><Icons.Globe /></span>
                    <span className="chip-text">Web</span>
                    <span className="chip-caret"><Icons.ChevronDown /></span>
                  </button>
                  <button
                    className={`add-source-chip ${urlMode === "llm_summary" ? "active" : ""}`}
                    type="button"
                    aria-pressed={urlMode === "llm_summary"}
                    onClick={() => setUrlMode("llm_summary")}
                  >
                    <span className="chip-icon"><Icons.Bolt /></span>
                    <span className="chip-text">Fast Research</span>
                    <span className="chip-caret"><Icons.ChevronDown /></span>
                  </button>
                </div>

                <button className="add-source-go" type="button" onClick={parseUrlToPreview}>
                  <Icons.ArrowRight />
                </button>
              </div>

              {urlParseState.status === "parsing" && (
                <div className="add-source-selected">正在解析...</div>
              )}
              {urlParseState.status === "error" && (
                <div className="add-source-selected">解析失败：{urlParseState.message}</div>
              )}
              {urlParseState.status === "ready" && (
                <div style={{ marginTop: 12 }}>
                  <div className="ref-section-title">解析预览</div>
                  <pre className="ref-file" style={{ maxHeight: 240, overflow: "auto" }}>{urlParseState.content}</pre>
                  <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 10 }}>
                    <button className="add-source-action primary" type="button" onClick={uploadParsedUrl}>
                      上传
                    </button>
                  </div>
                </div>
              )}
            </div>

            <div className="add-source-drop">
              <div className="add-source-drop-title">或将文件拖至此处</div>
              <div className="add-source-actions">
                <button className="add-source-action" type="button" onClick={chooseUploadFiles}>
                  <span className="chip-icon"><Icons.Upload /></span>
                  上传文件
                </button>
                <button className="add-source-action" type="button">
                  <span className="chip-icon"><Icons.Link /></span>
                  网站
                </button>
                <button className="add-source-action" type="button">
                  <span className="chip-icon"><Icons.Drive /></span>
                  云端硬盘
                </button>
                <button className="add-source-action" type="button">
                  <span className="chip-icon"><Icons.Copy /></span>
                  复制的文字
                </button>
              </div>

              {pendingUploadFiles.length > 0 ? (
                <div className="add-source-selected">
                  已选择 {pendingUploadFiles.length} 个文件。
                  <span style={{ marginLeft: 8 }}>
                    <button
                      className="add-source-action primary"
                      type="button"
                      onClick={uploadPendingFiles}
                      disabled={uploadState.status === "uploading"}
                    >
                      上传
                    </button>
                  </span>
                </div>
              ) : (
                <div className="add-source-selected muted">未选择文件</div>
              )}
            </div>
          </div>
        </div>
      )}

      {sourceDetailOpen && (
        <div className="ref-modal-backdrop" onClick={() => setSourceDetailOpen(false)}>
          <div className="ref-modal" onClick={(e) => e.stopPropagation()}>
            <div className="ref-modal-header">
              <div className="ref-modal-title">来源详情</div>
              <button className="ref-modal-close" onClick={() => setSourceDetailOpen(false)} type="button">
                ×
              </button>
            </div>
            <div className="ref-modal-body">
              {sourceDetailLoading ? (
                <div className="ref-muted">加载中...</div>
              ) : sourceDetail ? (
                <div>
                  <div className="ref-source">{sourceDetail.filename}</div>
                  <div className="ref-muted" style={{ marginTop: 8 }}>
                    {sourceDetail.rel_path || sourceDetail.filename}
                  </div>
                  <div className="ref-divider" />
                  <div className="ref-section-title">内容预览</div>
                  <pre className="ref-file">{sourceDetail.content_preview || "(二进制文件或暂无可预览文本)"}</pre>
                </div>
              ) : (
                <div className="ref-muted">暂无详情</div>
              )}
            </div>
          </div>
        </div>
      )}

      {renameSourceOpen && (
        <div className="add-source-backdrop" onClick={() => setRenameSourceOpen(false)}>
          <div className="source-action-modal" onClick={(e) => e.stopPropagation()}>
            <div className="source-action-title">重命名</div>
            <input
              className="source-action-input"
              value={renameSourceDraft}
              onInput={(e) => setRenameSourceDraft((e.target as HTMLInputElement).value)}
              placeholder="请输入新的名称"
            />
            <div className="source-action-actions">
              <button className="source-action-btn" type="button" onClick={() => setRenameSourceOpen(false)}>
                取消
              </button>
              <button className="source-action-btn primary" type="button" onClick={() => void confirmRenameSource()}>
                确定
              </button>
            </div>
          </div>
        </div>
      )}

      {deleteSourceId && (
        <div className="add-source-backdrop" onClick={() => setDeleteSourceId(null)}>
          <div className="source-action-modal" onClick={(e) => e.stopPropagation()}>
            <div className="source-action-title">删除来源</div>
            <div className="source-action-desc">确认删除该来源吗？删除后不可恢复。</div>
            <div className="source-action-actions">
              <button className="source-action-btn" type="button" onClick={() => setDeleteSourceId(null)}>
                取消
              </button>
              <button className="source-action-btn danger" type="button" onClick={() => void confirmDeleteSource()}>
                删除
              </button>
            </div>
          </div>
        </div>
      )}

      {createFolderOpen && (
        <div className="add-source-backdrop" onClick={() => setCreateFolderOpen(false)}>
          <div className="source-action-modal" onClick={(e) => e.stopPropagation()}>
            <div className="source-action-title">创建文件夹</div>
            <input
              className="source-action-input"
              value={newFolderName}
              onInput={(e) => setNewFolderName((e.target as HTMLInputElement).value)}
              placeholder="请输入文件夹名称"
              autoFocus
            />
            <div className="source-action-actions">
              <button className="source-action-btn" type="button" onClick={() => setCreateFolderOpen(false)}>
                取消
              </button>
              <button
                className="source-action-btn primary"
                type="button"
                onClick={async () => {
                  const name = newFolderName.trim();
                  if (!name) return;
                  try {
                    await fileTreeActions.createFolder(name, newFolderParentId);
                    setCreateFolderOpen(false);
                    setNewFolderName("");
                    setNewFolderParentId(null);
                  } catch {
                    // Error handled in hook
                  }
                }}
              >
                创建
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// Collapsible Tool Message Component (Legacy - 保留旧实现作为备份)
function ToolMessageLegacy({
  toolName,
  status,
  args,
  output,
}: {
  toolName: string;
  status?: string;
  args?: unknown;
  output?: unknown;
}) {
  const [isOpen, setIsOpen] = useState(() => {
    // 说明：history 回放时，很多工具消息默认是 done 状态；如果默认折叠，用户会觉得“没渲染结果”。
    // 这里对常见“需要看结果”的工具默认展开。
    if (status === "running") return true;
    return ["web_search", "rag_query", "fetch_url", "read_url_content", "write_file", "write_to_file"].includes(toolName);
  });

  // Debug: 输出完整的 props 信息
  console.log('ToolMessage props:', { toolName, status, args, output });

  const title =
    status === "running"
      ? `正在执行: ${toolName}`
      : status === "error"
        ? `执行失败: ${toolName}`
        : `已完成: ${toolName}`;

  const renderContent = () => {
    let data = status === "running" ? args : output;
    if (!data) return null;

    // 查询类工具在执行中不要展示 JSON 入参，避免出现 {"value":""} 这种原始结构
    if (status === "running") {
      if (toolName === "web_search") {
        const query = (args as any)?.query || (args as any)?.q || (args as any)?.value || "";
        return <div className="ref-muted">正在搜索{query ? `：${query}` : "..."}</div>;
      }
      if (toolName === "rag_query") {
        const query = (args as any)?.query || (args as any)?.q || (args as any)?.value || "";
        return <div className="ref-muted">正在检索{query ? `：${query}` : "..."}</div>;
      }
      if (toolName === "http_request") {
        const url = (args as any)?.url || (args as any)?.uri || (args as any)?.value || "";
        return <div className="ref-muted">正在请求{url ? `：${url}` : "..."}</div>;
      }
      if (toolName === "fetch_url") {
        const url = (args as any)?.url || (args as any)?.uri || (args as any)?.value || "";
        return <div className="ref-muted">正在抓取{url ? `：${url}` : "..."}</div>;
      }
    }

    // 尝试解析 JSON 字符串
    if (typeof data === 'string') {
      try {
        data = JSON.parse(data);
      } catch (e) {
        // 如果不是 JSON，保持原样
      }
    }

    console.log('ToolMessage renderContent:', { toolName, status, hasArgs: !!args, hasOutput: !!output, dataType: typeof data, parsedData: data });

    // Web Search Results Rendering
    if (toolName === "web_search" && typeof data === "object") {
      const results = (data as any).results || [];
      if (results.length > 0) {
        return (
          <div className="tool-results-list">
            {results.map((r: any, idx: number) => {
              // 提取域名
              let domain = '';
              try {
                const urlObj = new URL(r.url);
                domain = urlObj.hostname.replace('www.', '');
              } catch (e) {
                domain = r.url;
              }
              
              // 评分可视化（0-1 转换为百分比）
              const scorePercent = Math.round((r.score || 0) * 100);
              const scoreColor = scorePercent >= 80 ? '#4caf50' : scorePercent >= 60 ? '#ff9800' : '#9e9e9e';
              
              return (
                <div key={idx} className="tool-result-item">
                  <div className="result-header">
                    <div className="result-title-row">
                      <Icons.Globe />
                      <span className="result-title-text">{r.title}</span>
                    </div>
                    {r.score !== undefined && (
                      <div className="result-score">
                        <span className="score-value">{scorePercent}%</span>
                      </div>
                    )}
                  </div>
                  <div className="result-content">{r.content}</div>
                  <div className="result-meta">
                    <a href={r.url} target="_blank" rel="noreferrer" className="result-link">
                      <Icons.Link />
                      <span>{domain}</span>
                    </a>
                  </div>
                </div>
              );
            })}
          </div>
        );
      }
      return <div className="ref-muted">暂无搜索结果</div>;
    }

    // RAG Query Results Rendering
    if (toolName === "rag_query" && Array.isArray(data)) {
      if (!data.length) {
        return <div className="ref-muted">暂无检索结果</div>;
      }
      return (
        <div className="tool-results-list">
          {data.map((r: any, idx: number) => {
            // 评分可视化（0-1 转换为百分比）
            const score = r.score || 0;
            const scorePercent = Math.round(score * 100);
            const scoreColor = scorePercent >= 80 ? '#4caf50' : scorePercent >= 60 ? '#ff9800' : '#f44336';
            const relevanceLabel = scorePercent >= 80 ? '高相关' : scorePercent >= 60 ? '中相关' : '低相关';
            
            return (
              <div key={idx} className="tool-result-item rag-result-item">
                <div className="result-header">
                  <div className="rag-index">
                    <Icons.Search />
                    <span>片段 {r.index || idx + 1}</span>
                  </div>
                  <div className="rag-relevance" style={{ color: scoreColor }}>
                    <span className="relevance-label">{relevanceLabel}</span>
                    <span className="score-value">{scorePercent}%</span>
                  </div>
                </div>
                <div className="rag-score-bar">
                  <div className="score-bar-fill" style={{ width: `${scorePercent}%`, backgroundColor: scoreColor }}></div>
                </div>
                <div className="result-content rag-content">{r.text}</div>
                <div className="result-meta rag-source">
                  <Icons.Pdf />
                  <span>{r.source || '未知来源'}</span>
                  {r.mongo_id && <span className="mongo-id">ID: {r.mongo_id.substring(0, 8)}...</span>}
                </div>
              </div>
            );
          })}
        </div>
      );
    }

    // Shell Command Rendering
    if (toolName === "shell" || toolName === "bash") {
      const cmd = (args as any)?.command || (args as any)?.cmd || "";
      const out = typeof data === "string" ? data : formatJson(data);
      return (
        <div className="tool-shell-box">
          <div className="tool-shell-cmd">
            <span className="shell-prompt">$</span> {cmd}
          </div>
          {status === "done" && out && (
            <pre className="tool-shell-out">{out}</pre>
          )}
        </div>
      );
    }

    // File Operation Rendering - 特别美化 write_file（参考 AnyGen）
    if (["read_file", "write_file", "edit_file", "write_to_file", "edit", "replace_file_content"].includes(toolName)) {
      const path = (args as any)?.file_path || (args as any)?.path || (args as any)?.TargetFile || "";
      const isReadOp = toolName.includes("read");
      const isWriteOp = toolName.includes("write") || toolName === "write_to_file";
      const isEditOp = toolName.includes("edit") || toolName.includes("replace");
      
      // write_file 专用美化 UI（参考 AnyGen 样式）
      if (isWriteOp && status === "done") {
        let parsedOutput = data;
        if (typeof parsedOutput === "string") {
          try {
            parsedOutput = JSON.parse(parsedOutput);
          } catch (e) {
            // 保持原样
          }
        }
        
        const title = (parsedOutput as any)?.title || path.split("/").pop() || "未知文件";
        const fileType = (parsedOutput as any)?.type || "txt";
        const fileSize = (parsedOutput as any)?.size || 0;
        
        return (
          <div className="tool-file-box write-file-box">
            <div className="write-file-header">
              <div className="write-file-icon">
                <Icons.Pdf />
              </div>
              <div className="write-file-info">
                <div className="write-file-title">{title}</div>
                <div className="write-file-meta">
                  <span className="file-type">{fileType}</span>
                  <span className="file-separator">·</span>
                  <span className="file-size">{(fileSize / 1024).toFixed(1)}KB</span>
                </div>
              </div>
            </div>
            
            <div className="write-file-steps">
              <div className="step-item completed">
                <div className="step-icon success">✓</div>
                <div className="step-text">未知文件</div>
              </div>
              <div className="step-item completed">
                <div className="step-icon success">✓</div>
                <div className="step-text">操作成功</div>
              </div>
            </div>
          </div>
        );
      }
      
      // 从 output 字符串中提取文件路径（如果 path 为空）
      let displayPath = path;
      if (!displayPath && typeof output === 'string') {
        const pathMatch = output.match(/\/[\w\/\-\.]+\.(md|py|js|ts|tsx|json|txt|css)/i);
        if (pathMatch) {
          displayPath = pathMatch[0];
        }
      }
      
      return (
        <div className="tool-file-box">
          <div className="tool-file-header">
            <Icons.Pdf /> 
            <span className="tool-file-path">{displayPath || '未知文件'}</span>
            {isReadOp && <span className="file-op-badge read-badge">读取</span>}
            {isWriteOp && <span className="file-op-badge write-badge">写入</span>}
            {isEditOp && <span className="file-op-badge edit-badge">编辑</span>}
          </div>
          
          {/* read_file: 显示带行号的内容 */}
          {isReadOp && typeof data === "string" && (
            <div className="file-read-container">
              <div className="file-stats">
                <span>行数: {data.split('\n').length}</span>
                <span>字符: {data.length}</span>
              </div>
              <pre className="tool-file-content with-line-numbers">
                {data.split('\n').slice(0, 100).map((line, idx) => (
                  <div key={idx} className="code-line">
                    <span className="line-number">{idx + 1}</span>
                    <span className="line-content">{line}</span>
                  </div>
                ))}
                {data.split('\n').length > 100 && (
                  <div className="code-line-more">… 还有 {data.split('\n').length - 100} 行</div>
                )}
              </pre>
            </div>
          )}
          
          {/* write_file/edit_file: 显示修改摘要 */}
          {!isReadOp && (
            <div className="file-write-summary">
              <div className="summary-item success">
                <Icons.Logo />
                <span>操作成功</span>
              </div>
              {(args as any)?.CodeContent && (
                <div className="summary-item">
                  <span>新增内容: {((args as any).CodeContent as string).split('\n').length} 行</span>
                </div>
              )}
              {(args as any)?.Instruction && (
                <div className="summary-item instruction">
                  <Icons.Tool />
                  <span>{(args as any).Instruction}</span>
                </div>
              )}
              {(args as any)?.ReplacementChunks && (
                <div className="summary-item">
                  <span>修改块数: {((args as any).ReplacementChunks as any[]).length}</span>
                </div>
              )}
              {typeof output === 'string' && output.includes('Updated') && (
                <div className="summary-item">
                  <span>{output}</span>
                </div>
              )}
            </div>
          )}
        </div>
      );
    }

    // Directory Listing Rendering
    if (toolName === "ls" || toolName === "list_dir") {
      const path = (args as any)?.DirectoryPath || (args as any)?.path || "";
      let items: string[] = [];
      if (typeof data === "string") {
        items = data.split("\n").filter(Boolean);
      } else if (Array.isArray(data)) {
        items = data.map(i => typeof i === "string" ? i : (i.name || formatJson(i)));
      }
      return (
        <div className="tool-file-box">
          <div className="tool-file-header">
            <Icons.Folder /> <span className="tool-file-path">{path || "当前目录"}</span>
          </div>
          {status === "done" && (
            <div className="tool-ls-grid">
              {items.map((item, idx) => (
                <div key={idx} className="tool-ls-item">
                  {item.includes("/") || !item.includes(".") ? <Icons.Folder /> : <Icons.Pdf />}
                  <span>{item}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      );
    }

    // Search/Grep Rendering
    if (toolName === "grep" || toolName === "grep_search" || toolName === "glob") {
      const query = (args as any)?.Query || (args as any)?.Pattern || "";
      const path = (args as any)?.SearchPath || (args as any)?.SearchDirectory || "";
      return (
        <div className="tool-file-box">
          <div className="tool-file-header">
            <Icons.Search /> <span className="tool-file-path">{path || "搜索结果"}: {query}</span>
          </div>
          {status === "done" && (
            <pre className="tool-file-content">{typeof data === "string" ? data : formatJson(data)}</pre>
          )}
        </div>
      );
    }

    // Subagent Task Rendering
    if (toolName === "task") {
      const desc = (args as any)?.description || "";
      const name = (args as any)?.name || "";
      return (
        <div className="tool-file-box">
          <div className="tool-file-header">
            <Icons.Bolt /> <span className="tool-file-path">分派子任务: {name || desc}</span>
          </div>
          <div className="tool-fetch-body">
            <div className="tool-fetch-title">任务描述</div>
            <div className="tool-fetch-content">{desc}</div>
            {status === "done" && (
              <>
                <div className="tool-fetch-title" style={{marginTop: '8px'}}>执行结果</div>
                <div className="tool-fetch-content">{typeof data === "string" ? data : formatJson(data)}</div>
              </>
            )}
          </div>
        </div>
      );
    }

    // HTTP Request Rendering
    if (toolName === "http_request") {
      const url = (args as any)?.url || "";
      const method = (args as any)?.method || "GET";
      return (
        <div className="tool-file-box">
          <div className="tool-file-header">
            <Icons.Globe /> <span className="tool-file-path">[{method}] {url}</span>
          </div>
          {status === "done" && (
            <div className="tool-fetch-body">
              <div className="tool-fetch-title">响应状态</div>
              <div className="tool-fetch-content">{formatJson(data)}</div>
            </div>
          )}
        </div>
      );
    }

    // Fetch URL Rendering
    if (toolName === "fetch_url") {
      const url = (args as any)?.url || "";
      const title = (data as any)?.title || "";
      const content = (data as any)?.markdown_content || (data as any)?.markdown || (data as any)?.content || "";
      return (
        <div className="tool-file-box">
          <div className="tool-file-header">
            <Icons.Link /> <span className="tool-file-path">{url}</span>
          </div>
          {status === "done" && (
            <div className="tool-fetch-body">
              {title && <div className="tool-fetch-title">{title}</div>}
              <div className="tool-fetch-content">{content}</div>
            </div>
          )}
        </div>
      );
    }

    // Write Todos Rendering (AnyGen style)
    if (toolName === "write_todos") {
      // 尝试从多个可能的位置提取 todos 数据
      let todos = [];
      
      // 优先从 args 中获取（工具调用时）
      if (args && (args as any).todos) {
        todos = (args as any).todos;
      }
      // 其次从 output 中获取（工具执行完成后）
      else if (output && typeof output === 'string') {
        try {
          // 处理 "Updated todo list to [...]" 格式
          let jsonStr = output;
          
          // 提取方括号内的内容
          const match = output.match(/\[.*\]/);
          if (match) {
            jsonStr = match[0];
          }
          
          // 将 Python 风格的单引号替换为双引号
          jsonStr = jsonStr.replace(/'/g, '"');
          
          const parsed = JSON.parse(jsonStr);
          if (Array.isArray(parsed)) {
            todos = parsed;
          } else if (parsed.todos) {
            todos = parsed.todos;
          }
        } catch (e) {
          console.error('Failed to parse write_todos output:', e, output);
        }
      }
      else if (output && (output as any).todos) {
        todos = (output as any).todos;
      }
      else if (data && (data as any).todos) {
        todos = (data as any).todos;
      }
      
      console.log('write_todos debug:', { toolName, status, args, output, data, todos });
      
      if (Array.isArray(todos) && todos.length > 0) {
        return (
          <div className="tool-todos-container">
            <div className="tool-todos-header">
              <Icons.Apps />
              <span className="tool-todos-title">任务列表</span>
              <span className="tool-todos-count">{todos.length} 项</span>
            </div>
            <div className="tool-todos-list">
              {todos.map((todo: any, idx: number) => {
                const todoStatus = todo.status || "pending";
                const todoPriority = todo.priority || "medium";
                const todoContent = todo.content || todo.task || "";
                
                return (
                  <div key={idx} className={`tool-todo-item tool-todo-${todoStatus}`}>
                    <div className="tool-todo-checkbox">
                      {todoStatus === "completed" && (
                        <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
                          <path d="M13.854 3.646a.5.5 0 0 1 0 .708l-7 7a.5.5 0 0 1-.708 0l-3.5-3.5a.5.5 0 1 1 .708-.708L6.5 10.293l6.646-6.647a.5.5 0 0 1 .708 0z"/>
                        </svg>
                      )}
                      {todoStatus === "in_progress" && (
                        <div className="tool-todo-spinner"></div>
                      )}
                      {todoStatus === "pending" && (
                        <div className="tool-todo-circle"></div>
                      )}
                    </div>
                    <div className="tool-todo-content">
                      <span className={todoStatus === "completed" ? "tool-todo-text-completed" : ""}>
                        {todoContent}
                      </span>
                      {todoPriority === "high" && (
                        <span className="tool-todo-priority-high">高优先级</span>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        );
      }
    }

    // Default rendering: 避免直接展示 JSON
    if (typeof data === "string") {
      return <pre className="tool-text-output">{data}</pre>;
    }
    return <div className="ref-muted">暂无可展示内容</div>;
  };

  // 生成工具描述文本
  const getToolDescription = () => {
    if (toolName === 'write_todos') return '任务列表';
    if (toolName === 'web_search') {
      const query = (args as any)?.query || '';
      return query ? `搜索: ${query}` : '网络搜索';
    }
    if (toolName === 'rag_query') {
      const query = (args as any)?.query || '';
      return query ? `检索: ${query}` : '知识检索';
    }
    if (toolName === 'read_file') {
      const path = (args as any)?.file_path || '';
      const filename = path.split('/').pop() || '文件';
      return `读取: ${filename}`;
    }
    if (toolName === 'write_file' || toolName === 'write_to_file') {
      const path = (args as any)?.TargetFile || (args as any)?.file_path || '';
      const filename = path.split('/').pop() || '文件';
      return `写入: ${filename}`;
    }
    if (toolName === 'edit_file' || toolName === 'replace_file_content') {
      const path = (args as any)?.TargetFile || (args as any)?.file_path || '';
      const filename = path.split('/').pop() || '文件';
      return `编辑: ${filename}`;
    }
    return toolName;
  };

  const containerClass = `tool-container ${status === "running" ? "tool-running" : status === "error" ? "tool-error" : "tool-done"}`;

  return (
    <div className={containerClass}>
      <div className="tool-header" onClick={() => setIsOpen(!isOpen)}>
        <div className="tool-info">
          <span className="tool-dot" />
          <span className="tool-name">{getToolDescription()}</span>
        </div>
        <span className="chevron">{isOpen ? <Icons.ChevronDown /> : <Icons.ChevronRight />}</span>
      </div>
      {isOpen && <div className="tool-body">{renderContent()}</div>}
    </div>
  );
}

// Flat File List Component (Recursively flattens tree)
function FileTreeFlat({ node, onSelect, selected }: { node: TreeNode; onSelect: (path: string) => void; selected: Set<string> }) {
  const flatten = (n: TreeNode): TreeNode[] => {
     if (n.type === "file") return [n];
     if (n.type === "dir" && n.children) {
        return n.children.flatMap(flatten);
     }
     return [];
  };

  const files = useMemo(() => flatten(node), [node]);

  return (
    <div className="file-list">
      {files.map(file => (
        <div key={file.path} className="file-item" onClick={() => onSelect(file.path)}>
           <div className="file-icon"><Icons.Pdf /></div> 
           <div className="file-name">{file.name}</div>
           <div className="checkbox-wrapper">
              <input type="checkbox" checked={selected.has(file.path)} readOnly />
           </div>
        </div>
      ))}
    </div>
  );
}

export { App };

export default App;
