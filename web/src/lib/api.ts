export type Confirmation = {
  confirmation_id: string;
  confirmation: { description: string; expires_at: string };
};

export type ChatResponse = {
  status: "completed" | "needs_confirmation" | "failed";
  message: string;
} & Partial<Confirmation>;

export type SessionResponse = {
  status: "authenticated";
  owner_id: string;
};

export type Conversation = {
  session_id: string;
  title?: string;
  preview?: string;
  updated_at: string;
  message_count?: number;
};

export type StreamEvent =
  | {
      type:
        | "text_start"
        | "text_end"
        | "thinking_start"
        | "thinking_end"
        | "data_end";
      reply_id: string;
      block_id: string;
    }
  | {
      type: "text_delta" | "thinking_delta";
      reply_id: string;
      block_id: string;
      delta: string;
    }
  | {
      type: "data_start";
      reply_id: string;
      block_id: string;
      media_type: string;
    }
  | {
      type: "data_delta";
      reply_id: string;
      block_id: string;
      media_type: string;
      data: string;
    }
  | { type: "tool_start"; tool_call_id: string; tool_name: string }
  | {
      type: "tool_args_delta" | "tool_result_delta";
      tool_call_id: string;
      delta: string;
    }
  | { type: "tool_result_start"; tool_call_id: string }
  | { type: "tool_result_end"; tool_call_id: string; state: string }
  | {
      type: "human_required";
      kind: "confirmation" | "external_execution";
      tool_call_ids: string[];
    }
  | {
      type: "hint";
      reply_id: string;
      block_id: string;
      source: string | null;
      hint: string;
    }
  | ({ type: "outcome" } & ChatResponse)
  | { type: "error"; message: string }
  | { type: "done" };

export type ConversationMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  status: string | null;
  created_at: string;
};

const timezone = () => Intl.DateTimeFormat().resolvedOptions().timeZone;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...init?.headers },
    ...init,
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || "请求失败，请重试。");
  return body as T;
}

export const api = {
  babyBuddyMediaUrl: (source: string) => {
    try {
      const marker = "/media/";
      const pathname = source.startsWith(marker)
        ? source
        : new URL(source).pathname;
      const offset = pathname.indexOf(marker);
      if (offset < 0) return source;
      const path = pathname.slice(offset + marker.length);
      return `/api/babybuddy-media/${path
        .split("/")
        .map(encodeURIComponent)
        .join("/")}`;
    } catch {
      return source;
    }
  },
  login: (password: string) =>
    request<{ status: string }>("/api/login", {
      method: "POST",
      body: JSON.stringify({ password }),
    }),
  session: () => request<SessionResponse>("/api/session"),
  logout: () =>
    request<{ status: string }>("/api/logout", { method: "POST", body: "{}" }),
  conversations: () =>
    request<{ conversations: Conversation[] }>("/api/conversations"),
  conversationMessages: (sessionId: string) =>
    request<{ messages: ConversationMessage[] }>(
      `/api/conversations/${encodeURIComponent(sessionId)}/messages`,
    ),
  deleteConversation: (sessionId: string) =>
    request<{ status: "deleted" }>(
      `/api/conversations/${encodeURIComponent(sessionId)}`,
      { method: "DELETE" },
    ),
  chat: (session_id: string, text: string) =>
    request<ChatResponse>("/api/chat", {
      method: "POST",
      body: JSON.stringify({ session_id, text, timezone: timezone() }),
    }),
  streamChat: async (
    session_id: string,
    text: string,
    onEvent: (event: StreamEvent) => void,
  ) => {
    const response = await fetch("/api/chat/stream", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id, text, timezone: timezone() }),
    });
    if (!response.ok || !response.body) throw new Error("无法启动流式响应。");
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";
      for (const line of lines)
        if (line.trim()) onEvent(JSON.parse(line) as StreamEvent);
      if (done) break;
    }
  },
  confirm: (confirmation_id: string, approved: boolean) =>
    request<ChatResponse>("/api/confirm", {
      method: "POST",
      body: JSON.stringify({ confirmation_id, approved, timezone: timezone() }),
    }),
};
