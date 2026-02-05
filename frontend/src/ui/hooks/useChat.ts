import { useState, useRef } from "react";
import type { ChatMessage, SocketPayload, RagReference, AttachmentMeta } from "../types";
import { createId } from "../types/utils";

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
    const copy = [...prev];
    copy[existingIndex] = merged;
    return copy;
  }
  return [...prev, merged];
};

export function useChat(sessionId: string, selectedList: string[], selectedAttachmentNames: AttachmentMeta[]) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [status, setStatus] = useState("就绪");

  const abortControllerRef = useRef<AbortController | null>(null);
  const assistantBufferRef = useRef({ id: "", text: "" });
  const pendingAssistantIdRef = useRef<string | null>(null);
  const pendingRefsRef = useRef<RagReference[] | null>(null);

  const resetStreamState = () => {
    assistantBufferRef.current = { id: "", text: "" };
    pendingAssistantIdRef.current = null;
    pendingRefsRef.current = null;
  };

  const cancelActiveStream = async () => {
    // 没有正在进行的流式请求就不触发取消，避免误伤
    if (!abortControllerRef.current) return;
    // 先终止前端 SSE 请求，再通知后端中断对应会话的流式生成
    abortControllerRef.current?.abort();
    abortControllerRef.current = null;
    resetStreamState();
    setStatus("就绪");
    const sid = String(sessionId || "").trim();
    if (!sid) return;
    try {
      await fetch(`/api/chat/session/${encodeURIComponent(sid)}/cancel`, { method: "POST" });
    } catch {
      // ignore
    }
  };

  const handleSocketPayload = (payload: SocketPayload) => {
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
    if (payload.type === "chat.delta") {
      const timestamp = new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
      if (!assistantBufferRef.current.id) {
        const id = pendingAssistantIdRef.current || createId();
        assistantBufferRef.current = { id, text: "" };
        setMessages((prev: ChatMessage[]) => {
          const exists = prev.some((m) => m.id === id);
          if (exists) {
            return prev.map((m) =>
              m.id === id && m.role === "assistant"
                ? { ...m, timestamp, isPending: false, references: pendingRefsRef.current || m.references }
                : m
            );
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
    if (payload.type === "tool.start") {
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
      return;
    }
    if (payload.type === "session.status") {
      if (payload.status === "thinking") {
        setStatus("思考中...");
      }
      if (payload.status === "done") {
        setStatus("就绪");
        resetStreamState();
      }
      return;
    }
    if (payload.type === "error") {
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
    await cancelActiveStream();
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
      }
    } finally {
      abortControllerRef.current = null;
    }
  };

  const abort = () => {
    void cancelActiveStream();
  };

  return {
    messages,
    setMessages,
    input,
    setInput,
    status,
    setStatus,
    sendMessage,
    abort,
  };
}
