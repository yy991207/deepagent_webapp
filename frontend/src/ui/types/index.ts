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
    | { type: "tool.start"; id: string; name: string; args: unknown }
    | { type: "tool.end"; id: string; name: string; status: string; output: unknown }
    | { type: "rag.references"; references: RagReference[] }
    | { type: "suggested.questions"; questions: string[] }
    | { type: "session.status"; status: string }
    | { type: "error"; message: string }
  );

export type PodcastTranscriptEntry = {
  speaker?: string;
  dialogue?: string;
};
