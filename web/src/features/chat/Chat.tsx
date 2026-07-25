import { FormEvent, KeyboardEvent, useEffect, useRef, useState } from "react";
import { api, ChatResponse, Conversation } from "../../lib/api";

type Message = { id: string; role: "user" | "assistant"; text: string; confirmation?: ChatResponse };

const prompts = ["开始睡眠", "结束睡眠", "记录喂奶", "记录尿布"];

function storageKey(ownerId: string) {
  return `baby-buddy-conversation:${ownerId}`;
}

function newId() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function newConversationId() {
  return newId();
}

function savedConversationId(ownerId: string) {
  return localStorage.getItem(storageKey(ownerId));
}

function rememberConversation(ownerId: string, sessionId: string) {
  localStorage.setItem(storageKey(ownerId), sessionId);
}

function formatUpdatedAt(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(date);
}

export function Chat({ ownerId, onLogout }: { ownerId: string; onLogout: () => Promise<void> }) {
  const [sessionId, setSessionId] = useState<string>(newConversationId);
  const activeSessionId = useRef(sessionId);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [messages, setMessages] = useState<Message[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [messagesLoading, setMessagesLoading] = useState(false);
  const [historyError, setHistoryError] = useState("");
  const [messageLoadError, setMessageLoadError] = useState("");

  function activateConversation(id: string) {
    activeSessionId.current = id;
    setSessionId(id);
    rememberConversation(ownerId, id);
  }

  async function loadMessages(id: string) {
    setMessagesLoading(true);
    setMessageLoadError("");
    setMessages([]);
    try {
      const response = await api.conversationMessages(id);
      if (activeSessionId.current !== id) return;
      setMessages(response.messages.map((message) => ({
        id: message.id,
        role: message.role,
        text: message.content,
      })));
    } catch (caught) {
      if (activeSessionId.current !== id) return;
      setMessageLoadError(caught instanceof Error ? caught.message : "无法加载对话记录。");
    } finally {
      if (activeSessionId.current === id) setMessagesLoading(false);
    }
  }

  async function refreshConversations() {
    try {
      const response = await api.conversations();
      setConversations(response.conversations);
    } catch {
      // A failed refresh must not interrupt an active conversation.
    }
  }

  useEffect(() => {
    let cancelled = false;

    async function hydrate() {
      try {
        const response = await api.conversations();
        if (cancelled) return;
        setConversations(response.conversations);
        const saved = savedConversationId(ownerId);
        const initial = response.conversations.some((conversation) => conversation.session_id === saved)
          ? saved!
          : response.conversations[0]?.session_id;

        if (initial) {
          activateConversation(initial);
          await loadMessages(initial);
        } else {
          const id = newConversationId();
          activateConversation(id);
          setMessages([]);
        }
      } catch (caught) {
        if (!cancelled) {
          setHistoryError(caught instanceof Error ? caught.message : "无法加载对话记录。");
          const id = newConversationId();
          activateConversation(id);
        }
      } finally {
        if (!cancelled) setHistoryLoading(false);
      }
    }

    void hydrate();
    return () => { cancelled = true; };
  }, [ownerId]);

  async function selectConversation(id: string) {
    if (id === activeSessionId.current || busy || historyLoading || messagesLoading) return;
    activateConversation(id);
    await loadMessages(id);
  }

  function createConversation() {
    if (busy || historyLoading || messagesLoading) return;
    activateConversation(newConversationId());
    setMessages([]);
    setText("");
    setMessageLoadError("");
  }

  async function send(value: string) {
    const content = value.trim();
    if (!content || busy || historyLoading || messagesLoading) return;
    setMessages((items) => [...items, { id: newId(), role: "user", text: content }]);
    setText("");
    setBusy(true);
    try {
      const response = await api.chat(sessionId, content);
      appendResponse(response);
      void refreshConversations();
    } catch (caught) {
      appendAssistant(caught instanceof Error ? caught.message : "暂时无法处理请求。");
    } finally {
      setBusy(false);
    }
  }

  function appendAssistant(messageText: string, confirmation?: ChatResponse) {
    setMessages((items) => [...items, { id: newId(), role: "assistant", text: messageText, confirmation }]);
  }

  function appendResponse(response: ChatResponse) {
    appendAssistant(response.message || "已完成。", response.status === "needs_confirmation" ? response : undefined);
  }

  async function decide(response: ChatResponse, approved: boolean) {
    if (!response.confirmation_id || busy) return;
    setBusy(true);
    try {
      const result = await api.confirm(response.confirmation_id, approved);
      setMessages((items) => items.map((item) => item.confirmation === response ? { ...item, confirmation: undefined } : item));
      appendResponse(result);
      void refreshConversations();
    } catch (caught) {
      appendAssistant(caught instanceof Error ? caught.message : "确认失败，请重试。");
    } finally {
      setBusy(false);
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    void send(text);
  }

  function sendOnEnter(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter" || event.shiftKey) return;
    event.preventDefault();
    void send(text);
  }

  const hasPending = messages.some((message) => message.confirmation);
  const inputDisabled = busy || hasPending || historyLoading || messagesLoading;

  return <main className="min-h-screen bg-stone-50 text-stone-800">
    <header className="sticky top-0 z-10 border-b border-stone-200 bg-white/95 px-4 py-3 backdrop-blur">
      <div className="mx-auto flex max-w-5xl items-center justify-between gap-3">
        <div><p className="text-xs font-bold tracking-widest text-emerald-700">家庭育儿助手</p><h1 className="text-lg font-bold">宝宝记录</h1></div>
        <div className="flex items-center gap-3"><button disabled={inputDisabled} onClick={createConversation} className="rounded-lg border border-emerald-700 px-3 py-2 text-sm font-semibold text-emerald-800">新建对话</button><button onClick={onLogout} className="text-sm font-semibold text-emerald-800">退出</button></div>
      </div>
    </header>
    <div className="mx-auto grid max-w-5xl md:min-h-[calc(100vh-68px)] md:grid-cols-[15rem_minmax(0,1fr)]">
      <aside className="border-b border-stone-200 bg-white px-4 py-4 md:border-r md:border-b-0">
        <h2 className="text-sm font-bold text-stone-700">对话记录</h2>
        {historyError && <p className="mt-2 text-xs leading-5 text-red-700">{historyError}</p>}
        <nav aria-label="对话记录" className="mt-3 flex gap-2 overflow-x-auto pb-1 md:flex-col md:overflow-y-auto">
          {historyLoading && <p className="text-sm text-stone-500">正在加载…</p>}
          {!historyLoading && conversations.length === 0 && <p className="text-sm text-stone-500">还没有历史对话</p>}
          {conversations.map((conversation) => <button key={conversation.session_id} type="button" onClick={() => { void selectConversation(conversation.session_id); }} disabled={busy || messagesLoading} className={`min-w-44 rounded-xl px-3 py-2 text-left text-sm md:min-w-0 ${conversation.session_id === sessionId ? "bg-emerald-100 text-emerald-950" : "hover:bg-stone-100"}`}>
            <span className="block truncate font-semibold">{conversation.title || "未命名对话"}</span>
            <span className="mt-1 block truncate text-xs text-stone-500">{conversation.preview || `${conversation.message_count} 条消息`}</span>
            <span className="mt-1 block text-xs text-stone-400">{formatUpdatedAt(conversation.updated_at)}</span>
          </button>)}
        </nav>
      </aside>
      <section className="flex min-h-[calc(100vh-68px)] min-w-0 flex-col px-4">
        <ol className="flex flex-1 flex-col gap-3 py-5">
          {messagesLoading && <li className="mx-auto mt-12 text-sm text-stone-500">正在加载对话…</li>}
          {!messagesLoading && messages.length === 0 && <li className="mx-auto mt-12 max-w-sm text-center text-sm leading-6 text-stone-500">告诉我发生了什么。信息不完整时，我会先追问，再请你确认写入。</li>}
          {messageLoadError && <li className="mx-auto text-sm text-red-700">{messageLoadError}</li>}
          {messages.map((message) => <li key={message.id} className={`max-w-[88%] rounded-2xl px-4 py-3 leading-6 ${message.role === "user" ? "ml-auto rounded-br-sm bg-emerald-700 text-white" : "rounded-bl-sm bg-white shadow-sm ring-1 ring-stone-200"}`}>
            <p className="whitespace-pre-wrap">{message.text}</p>
            {message.confirmation?.confirmation && <div className="mt-3 rounded-xl border border-amber-300 bg-amber-50 p-3 text-sm text-stone-800">
              <p className="font-bold">确认写入 Baby Buddy？</p>
              <p className="mt-1">{message.confirmation.confirmation.description}</p>
              <div className="mt-3 flex gap-2"><button disabled={busy} onClick={() => { void decide(message.confirmation!, false); }} className="rounded-lg border border-stone-300 bg-white px-3 py-2 font-semibold">取消</button><button disabled={busy} onClick={() => { void decide(message.confirmation!, true); }} className="rounded-lg bg-emerald-700 px-3 py-2 font-semibold text-white">确认写入</button></div>
            </div>}
          </li>)}
        </ol>
        <form onSubmit={submit} className="sticky bottom-0 border-t border-stone-200 bg-stone-50 py-3">
          <textarea value={text} onChange={(event) => setText(event.target.value)} onKeyDown={sendOnEnter} disabled={inputDisabled} placeholder="例如：宝宝刚尿湿了（Enter 发送，Shift + Enter 换行）" className="w-full resize-none rounded-2xl border border-stone-300 bg-white px-4 py-3 outline-none focus:border-emerald-600" rows={3} />
          <div className="mt-2 flex gap-2 overflow-x-auto pb-1">{prompts.map((prompt) => <button key={prompt} disabled={inputDisabled} onClick={() => { void send(prompt); }} type="button" className="whitespace-nowrap rounded-full bg-emerald-100 px-3 py-2 text-sm font-semibold text-emerald-900">{prompt}</button>)}<button disabled={inputDisabled} className="ml-auto rounded-xl bg-emerald-700 px-4 py-2 font-semibold text-white">{busy ? "处理中…" : "发送"}</button></div>
        </form>
      </section>
    </div>
  </main>;
}
