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
  title: string;
  preview: string;
  updated_at: string;
  message_count: number;
};

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
  login: (password: string) => request<{ status: string }>("/api/login", { method: "POST", body: JSON.stringify({ password }) }),
  session: () => request<SessionResponse>("/api/session"),
  logout: () => request<{ status: string }>("/api/logout", { method: "POST", body: "{}" }),
  conversations: () => request<{ conversations: Conversation[] }>("/api/conversations"),
  conversationMessages: (sessionId: string) => request<{ messages: ConversationMessage[] }>(`/api/conversations/${encodeURIComponent(sessionId)}/messages`),
  chat: (session_id: string, text: string) =>
    request<ChatResponse>("/api/chat", {
      method: "POST",
      body: JSON.stringify({ session_id, text, timezone: timezone() }),
    }),
  confirm: (confirmation_id: string, approved: boolean) =>
    request<ChatResponse>("/api/confirm", {
      method: "POST",
      body: JSON.stringify({ confirmation_id, approved, timezone: timezone() }),
    }),
};
