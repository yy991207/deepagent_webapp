export type TreeNode = {
  name: string;
  path: string;
  type: "dir" | "file";
  children?: TreeNode[];
};

export type UploadedSource = {
  id: string;
  filename: string;
  rel_path?: string;
  size?: number;
  created_at?: string;
};

// ========== File Tree Types ==========

export type SourceItemType = "file" | "folder";

export type SourceItem = {
  id: string;
  filename: string;
  rel_path?: string;
  size?: number;
  created_at?: string;
  updated_at?: string;
  parent_id: string | null;
  item_type: SourceItemType;
  file_type?: string;
  sort_order: number;
};

export type SourceTreeNode = SourceItem & {
  children: SourceTreeNode[];
  expanded?: boolean;
};

export type DragPosition = "before" | "after" | "inside";

export type DragState = {
  draggedId: string | null;
  targetId: string | null;
  position: DragPosition | null;
};

export type UploadedSourceDetail = UploadedSource & {
  sha256?: string;
  content_preview?: string | null;
};

export type PodcastSpeakerProfile = {
  id: string;
  name: string;
  description: string;
  tts_provider: string;
  tts_model: string;
  speakers: Array<{ name: string; voice_id: string; backstory: string; personality: string }>;
};

export type PodcastRunSummary = {
  run_id: string;
  status: string;
  episode_profile: string;
  speaker_profile: string;
  episode_name: string;
  created_at: string;
  updated_at: string;
  message?: string;
};

export type PodcastRunDetail = {
  run: PodcastRunSummary;
  result: null | {
    run_id: string;
    episode_profile: string;
    speaker_profile: string;
    episode_name: string;
    audio_file_path: string | null;
    transcript: unknown;
    outline: unknown;
    created_at: string;
    processing_time?: number;
  };
};

export type RagReference = {
  index: number;
  source?: string;
  mongo_id?: string;
  text?: string;
};

export type UrlReference = {
  index: number;
  url: string;
};

export type AttachmentMeta =
  | string
  | {
      mongo_id: string;
      filename?: string;
    };

export type ChatMessage =
  | {
      id: string;
      role: "user" | "assistant";
      content: string;
      attachments?: AttachmentMeta[];
      references?: RagReference[];
      suggestedQuestions?: string[];
      writes?: FilesystemWrite[];
      // 消息反馈：[copy, like, dislike]
      feedback?: [number, number, number];
      isPending?: boolean;
      timestamp?: string;
    }
  | {
      id: string;
      role: "tool";
      toolCallId: string;
      toolName: string;
      status: "running" | "done" | "error";
      args?: unknown;
      output?: unknown;
      startedAt?: string;
      endedAt?: string;
    };

export type AgentLog = {
  id: string;
  agentId: string;
  timestamp: string;
  message: string;
  type: "info" | "error" | "tool";
};

 export type ChatSession = {
   session_id: string;
   title: string;
   message_count: number;
   created_at: string;
   updated_at: string;
 };

export type FilesystemWrite = {
  write_id: string;
  session_id: string;
  file_path: string;
  title: string;
  type: string;
  size: number;
  created_at: string;
};

type SocketPayloadBase = {
  session_id?: string;
};

export type SocketPayload = SocketPayloadBase &
  (
    | { type: "chat.delta"; text: string }
    | { type: "delta"; text: string }
    | { type: "message.start"; message_id: string }
    | { type: "tool.start"; id: string; name: string; args: unknown }
    | { type: "tool.end"; id: string; name: string; status: string; output: unknown; message_id?: string }
    | { type: "rag.references"; references: RagReference[] }
    | { type: "suggested.questions"; questions: string[] }
    | { type: "session.status"; status: string }
    | { type: "error"; message: string }
  );

export type PodcastTranscriptEntry = {
  speaker?: string;
  dialogue?: string;
};

export type PodcastEpisodeProfile = {
  id: string;
  name: string;
  description: string;
  speaker_config: string;
  outline_provider: string;
  outline_model: string;
  transcript_provider: string;
  transcript_model: string;
  default_briefing: string;
  num_segments: number;
};

export type VoiceOption = {
  id: string;
  name: string;
  gender: string;
};

export const EDGE_TTS_VOICES: VoiceOption[] = [
  { id: "zh-CN-XiaoxiaoNeural", name: "晓晓", gender: "女" },
  { id: "zh-CN-XiaoyiNeural", name: "晓伊", gender: "女" },
  { id: "zh-CN-YunjianNeural", name: "云健", gender: "男" },
  { id: "zh-CN-YunxiNeural", name: "云希", gender: "男" },
  { id: "zh-CN-YunxiaNeural", name: "云夏", gender: "男" },
  { id: "zh-CN-YunyangNeural", name: "云扬", gender: "男" },
  { id: "zh-CN-liaoning-XiaobeiNeural", name: "晓北(辽宁)", gender: "女" },
  { id: "zh-CN-shaanxi-XiaoniNeural", name: "晓妮(陕西)", gender: "女" },
];

export const COSYVOICE_VOICES: VoiceOption[] = [
  { id: "longxiaochun_v2", name: "龙小淳", gender: "女" },
  { id: "longxiaoxia_v2", name: "龙小夏", gender: "女" },
  { id: "longlaotie_v2", name: "龙老铁", gender: "男" },
  { id: "longanyang_v2", name: "龙安阳", gender: "男" },
];

export const TTS_PROVIDERS = [
  { id: "edge", name: "Edge TTS (免费)" },
  { id: "dashscope", name: "CosyVoice v2 (阿里云)" },
];

export const LLM_MODELS = [
  { id: "qwen-plus", name: "Qwen Plus (推荐)" },
  { id: "qwen-turbo", name: "Qwen Turbo (快速)" },
  { id: "qwen-max", name: "Qwen Max (高质量)" },
];
