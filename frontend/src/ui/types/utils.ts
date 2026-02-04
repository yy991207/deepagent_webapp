import type { RagReference, UrlReference, PodcastTranscriptEntry } from "./index";

export const formatJson = (value: unknown) => {
  if (value === null || value === undefined) return "null";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
};

export const extractPodcastTranscript = (value: unknown): PodcastTranscriptEntry[] => {
  if (Array.isArray(value)) {
    return value
      .map((x) => {
        if (!x || typeof x !== "object") return null;
        const anyX = x as Record<string, unknown>;
        const speaker = typeof anyX.speaker === "string" ? anyX.speaker : "";
        const dialogue = typeof anyX.dialogue === "string" ? anyX.dialogue : "";
        if (!speaker || !dialogue) return null;
        return { speaker, dialogue };
      })
      .filter(Boolean) as PodcastTranscriptEntry[];
  }

  if (value && typeof value === "object" && "transcript" in value) {
    const anyV = value as Record<string, unknown>;
    return extractPodcastTranscript(anyV.transcript);
  }

  return [];
};

export const maxRefIndex = (refs: RagReference[] | undefined) => {
  if (!refs || refs.length === 0) return 0;
  let max = 0;
  for (const r of refs) {
    if (typeof r.index === "number" && r.index > max) {
      max = r.index;
    }
  }
  return max;
};

export const extractUrlReferences = (input: string, startIndex: number): { text: string; urlRefs: UrlReference[] } => {
  const reUrl = /(https?:\/\/[^\s)\]}>,"']+)/g;
  const found: string[] = [];

  let m: RegExpExecArray | null;
  while ((m = reUrl.exec(input)) !== null) {
    found.push(m[1]);
  }

  const unique: string[] = [];
  for (const u of found) {
    if (!unique.includes(u)) {
      unique.push(u);
    }
  }

  const urlRefs: UrlReference[] = unique.map((url, i) => ({ index: startIndex + i, url }));
  let text = input;
  for (const r of urlRefs) {
    text = text.split(r.url).join(`[${r.index}]`);
  }

  return { text, urlRefs };
};

const isLikelyHostname = (hostname: string) => {
  if (!hostname) return false;
  if (hostname === "localhost") return false;
  if (!hostname.includes(".")) return false;
  if (hostname.startsWith(".") || hostname.endsWith(".")) return false;
  if (hostname.includes("..")) return false;
  if (!/^[a-z0-9.-]+$/i.test(hostname)) return false;
  const parts = hostname.split(".");
  const tld = parts[parts.length - 1] || "";
  return tld.length >= 2 && tld.length <= 24;
};

export const getFaviconUrl = (url: string) => {
  try {
    const u = new URL(url);
    if (u.protocol !== "http:" && u.protocol !== "https:") {
      return "";
    }
    // 过滤明显无效的域名，避免 favicon 请求 404 造成控制台噪音
    if (!isLikelyHostname(u.hostname)) {
      return "";
    }
    return `https://www.google.com/s2/favicons?sz=64&domain=${encodeURIComponent(u.hostname)}`;
  } catch {
    return "";
  }
};

export const createId = () => Math.random().toString(36).slice(2, 10);

 export const getOrCreateSessionId = () => {
   const key = "deepagents_session_id";
   try {
     const stored = localStorage.getItem(key) || "";
     const sid = stored || `web-${createId()}`;
     localStorage.setItem(key, sid);
     try {
       sessionStorage.setItem(key, sid);
     } catch {
       // ignore
     }
     (window as any).__deepagents_session_id = sid;
     return sid;
   } catch {
     try {
       const stored = sessionStorage.getItem(key) || "";
       const sid = stored || `web-${createId()}`;
       sessionStorage.setItem(key, sid);
       (window as any).__deepagents_session_id = sid;
       return sid;
     } catch {
       const sid = `web-${createId()}`;
       (window as any).__deepagents_session_id = sid;
       return sid;
     }
   }
 };

export const getOrCreateThreadId = () => {
  const key = "deepagents_thread_id";
  try {
    const stored = localStorage.getItem(key) || "";
    const tid = stored || `web-${createId()}`;
    localStorage.setItem(key, tid);
    try {
      sessionStorage.setItem(key, tid);
    } catch {
      // ignore
    }
    (window as any).__deepagents_thread_id = tid;
    return tid;
  } catch {
    try {
      const stored = sessionStorage.getItem(key) || "";
      const tid = stored || `web-${createId()}`;
      sessionStorage.setItem(key, tid);
      (window as any).__deepagents_thread_id = tid;
      return tid;
    } catch {
      const tid = `web-${createId()}`;
      (window as any).__deepagents_thread_id = tid;
      return tid;
    }
  }
};
