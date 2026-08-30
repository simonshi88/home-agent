import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type AnchorHTMLAttributes,
} from "react";
import {
  AssistantRuntimeProvider,
  ComposerPrimitive,
  MessagePartPrimitive,
  MessagePrimitive,
  ThreadPrimitive,
  useAuiState,
  useExternalStoreRuntime,
  type AppendMessage,
  type ThreadMessageLike,
  type ToolCallMessagePartProps,
} from "@assistant-ui/react";
import { MarkdownTextPrimitive } from "@assistant-ui/react-markdown";
import {
  Check,
  FileText,
  LogOut,
  Menu,
  Paperclip,
  Plus,
  Send,
  Trash2,
  Wrench,
  X,
} from "lucide-react";
import remarkGfm from "remark-gfm";
import {
  api,
  type ChatResponse,
  type Conversation,
  type StagedUpload,
  type StreamEvent,
} from "../../lib/api";

type ToolPart = {
  type: "tool-call";
  toolCallId: string;
  toolName: string;
  args: Record<string, never>;
  argsText?: string;
  artifact?: string;
  result?: unknown;
  isError?: boolean;
  waiting?: boolean;
};
type TextPart = { type: "text"; text: string; blockId?: string };
type ReasoningPart = { type: "reasoning"; text: string; blockId?: string };
type ImagePart = {
  type: "image";
  image: string;
  blockId?: string;
  mediaType?: string;
};
type MessageContent = (TextPart | ReasoningPart | ImagePart | ToolPart)[];
type ChatMessage =
  | { id: string; role: "user"; content: MessageContent }
  | {
      id: string;
      role: "assistant";
      content: MessageContent;
      status?: ThreadMessageLike["status"];
    };
const id = () => crypto.randomUUID();
const storageKey = (owner: string) => `agent-conversation:${owner}`;
const sessionPath = (sessionId: string) =>
  `/chat/${encodeURIComponent(sessionId)}`;
const sessionFromPath = () => {
  const match = window.location.pathname.match(/^\/chat\/([^/]+)\/?$/);
  if (!match) return null;
  try {
    const value = decodeURIComponent(match[1]);
    return /^[A-Za-z0-9._-]{1,128}$/.test(value) ? value : null;
  } catch {
    return null;
  }
};

function ToolProcess({
  toolName,
  result,
  argsText,
  artifact,
  isError,
}: ToolCallMessagePartProps) {
  const done = result !== undefined;
  const labels: Record<string, string> = {
    delegate_to_baby: "委派给 Baby 助手",
    delegate_to_exercise: "委派给动作助手",
    delegate_to_paperless: "委派给文档助手",
    query_exercises: "查询动作数据库",
    query_paperless: "查询 Paperless 文档",
    upload_paperless_document: "上传文档到 Paperless",
  };
  const delegation = toolName.startsWith("delegate_to_");
  return (
    <details className={`tool-process ${done ? "done" : "running"}`}>
      <summary>
        <span>
          {done && !isError ? <Check size={15} /> : <Wrench size={15} />}
        </span>
        <div>
          <strong>{labels[toolName] || toolName}</strong>
          <small>
            {isError
              ? "执行失败"
              : done
                ? "专项任务已完成"
                : delegation
                  ? "Home Jarvis 正在协调…"
                  : "正在执行工具…"}
          </small>
        </div>
      </summary>
      {argsText && <pre>{argsText}</pre>}
      {typeof artifact === "string" && artifact && <pre>{artifact}</pre>}
    </details>
  );
}
function MarkdownText() {
  return (
    <MarkdownTextPrimitive
      remarkPlugins={[remarkGfm]}
      components={{ a: MarkdownLink }}
      className="markdown"
    />
  );
}
function MarkdownLink({
  children,
  ...props
}: AnchorHTMLAttributes<HTMLAnchorElement>) {
  return (
    <a {...props} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  );
}
function MessageImage() {
  return (
    <figure className="message-image">
      <MessagePartPrimitive.Image alt="Baby Buddy 图片" loading="lazy" />
    </figure>
  );
}

const imageUrlPattern =
  /https?:\/\/[^\s<>()]+\/media\/[^\s<>()]+\.(?:avif|gif|jpe?g|png|webp)(?:\?[^\s<>()]*)?/gi;
const relativeImagePattern =
  /\/media\/[^\s<>()]+\.(?:avif|gif|jpe?g|png|webp)(?:\?[^\s<>()]*)?/gi;
const noteImageFilenamePattern =
  /(?:^|[\s：:（(])([\w.-]+\.(?:avif|gif|jpe?g|png|webp))(?=$|[\s，,。；;）)])/gi;

function normalizeBabyBuddyLinks(text: string) {
  return text.replace(
    /https?:\/\/babybuddy(?::\d+)?(?=\/media\/)/gi,
    "http://baby.home",
  );
}

function imagesFromText(text: string): ImagePart[] {
  const absolute = text.match(imageUrlPattern) || [];
  const relative = (text.match(relativeImagePattern) || []).filter(
    (path) => !absolute.some((url) => url.includes(path)),
  );
  const filenames = [...text.matchAll(noteImageFilenamePattern)].map(
    (match) => `/media/notes/images/${match[1]}`,
  );
  return [...new Set([...absolute, ...relative, ...filenames])].map(
    (source) => ({
      type: "image",
      image: api.babyBuddyMediaUrl(source),
    }),
  );
}

function textWithImages(text: string): MessageContent {
  return [{ type: "text", text }, ...imagesFromText(text)];
}
function Reasoning({ text }: { text: string }) {
  return (
    <details className="reasoning">
      <summary>思考过程</summary>
      <div>{text}</div>
    </details>
  );
}
function ChatBubble() {
  const role = useAuiState((state) => state.message.role);
  return (
    <MessagePrimitive.Root className={`message ${role}`}>
      <div className="message-body">
        <MessagePrimitive.Parts
          components={{
            Text: MarkdownText,
            Reasoning,
            Image: MessageImage,
            tools: { Fallback: ToolProcess },
          }}
        />
      </div>
    </MessagePrimitive.Root>
  );
}
function Thread({
  upload,
  uploading,
  onDocument,
  onRemoveUpload,
}: {
  upload: StagedUpload | null;
  uploading: boolean;
  onDocument: (file: File) => void;
  onRemoveUpload: () => void;
}) {
  return (
    <ThreadPrimitive.Root className="thread-root">
      <ThreadPrimitive.Viewport className="thread-viewport">
        <ThreadPrimitive.Empty>
          <div className="empty">
            <span>HOME JARVIS</span>
            <h2>家里的事，交给 Jarvis</h2>
            <p>主助手会理解你的目标，并协调合适的专项助手完成。</p>
            <div className="capabilities">
              <div>
                <strong>Baby 助手</strong>
                <small>喂奶、睡眠、尿布与育儿记录</small>
              </div>
              <div>
                <strong>动作助手</strong>
                <small>动作步骤、器械与目标肌群</small>
              </div>
              <div>
                <strong>文档助手</strong>
                <small>搜索、查看和上传家庭文档</small>
              </div>
            </div>
          </div>
        </ThreadPrimitive.Empty>
        <ThreadPrimitive.Messages components={{ Message: ChatBubble }} />
        <div className="composer-wrap">
          {upload && (
            <div className="upload-chip">
              <FileText size={16} />
              <span>{upload.filename}</span>
              <button onClick={onRemoveUpload} aria-label="移除待上传文档">
                <X size={16} />
              </button>
            </div>
          )}
          <ComposerPrimitive.Root className="composer">
            <label className={`attach ${uploading ? "uploading" : ""}`}>
              <Paperclip size={19} />
              <span className="sr-only">选择要上传到 Paperless 的文档</span>
              <input
                type="file"
                disabled={uploading}
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) onDocument(file);
                  event.target.value = "";
                }}
              />
            </label>
            <ComposerPrimitive.Input
              autoFocus
              placeholder="告诉 Home Jarvis 你想做什么…"
              rows={1}
            />
            <ComposerPrimitive.Send className="send" aria-label="发送">
              <Send size={18} />
            </ComposerPrimitive.Send>
          </ComposerPrimitive.Root>
          <p>Home Jarvis 会协调专项助手；请核对重要信息。</p>
        </div>
      </ThreadPrimitive.Viewport>
    </ThreadPrimitive.Root>
  );
}

export function Chat({
  ownerId,
  onLogout,
}: {
  ownerId: string;
  onLogout: () => Promise<void>;
}) {
  const initialSessionRef = useRef(
    sessionFromPath() || localStorage.getItem(storageKey(ownerId)) || id(),
  );
  const [sessionId, setSessionId] = useState(
    initialSessionRef.current,
  );
  const sessionRef = useRef(sessionId);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [running, setRunning] = useState(false);
  const [pending, setPending] = useState<ChatResponse | null>(null);
  const [stagedUpload, setStagedUpload] = useState<StagedUpload | null>(null);
  const [uploading, setUploading] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const refresh = useCallback(
    async () => setConversations((await api.conversations()).conversations),
    [],
  );
  const load = useCallback(
    async (
      target: string,
      options: { history?: "push" | "replace" | "none" } = {},
    ) => {
      sessionRef.current = target;
      setSessionId(target);
      setPending(null);
      setStagedUpload(null);
      setSidebarOpen(false);
      localStorage.setItem(storageKey(ownerId), target);
      if (options.history === "push")
        window.history.pushState({ sessionId: target }, "", sessionPath(target));
      if (options.history === "replace")
        window.history.replaceState(
          { sessionId: target },
          "",
          sessionPath(target),
        );
      let response;
      try {
        response = await api.conversationMessages(target);
      } catch {
        // A newly generated route has no server-side messages until its first
        // user turn. It is still a valid, isolated conversation session.
        setMessages([]);
        return;
      }
      setMessages(
        response.messages.map((message): ChatMessage =>
          message.role === "assistant"
            ? {
                id: message.id,
                role: "assistant",
                content: textWithImages(message.content),
                status: { type: "complete", reason: "stop" },
              }
            : {
                id: message.id,
                role: "user",
                content: [{ type: "text", text: message.content }],
              },
        ),
      );
    },
    [ownerId],
  );
  useEffect(() => {
    void (async () => {
      const list = (await api.conversations()).conversations;
      setConversations(list);
      const target = initialSessionRef.current;
      const routeSession = sessionFromPath();
      await load(target, {
        history: routeSession === target ? "none" : "replace",
      });
    })();
  }, [load]);
  useEffect(() => {
    const onPopState = () => {
      const target = sessionFromPath();
      if (!target || running) {
        window.history.replaceState(
          { sessionId: sessionRef.current },
          "",
          sessionPath(sessionRef.current),
        );
        return;
      }
      void load(target, { history: "none" });
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, [load, running]);
  const updateAssistant = (
    messageId: string,
    update: (message: ChatMessage) => ChatMessage,
  ) =>
    setMessages((items) =>
      items.map((item) => (item.id === messageId ? update(item) : item)),
    );

  const sendMessage = useCallback(
    async (message: AppendMessage) => {
      const text = message.content
        .filter((part) => part.type === "text")
        .map((part) => part.text)
        .join("\n")
        .trim();
      if (!text || running) return;
      setRunning(true);
      let userMessageAdded = false;
      if (pending?.confirmation_id) {
        const normalized = text.replace(/[\s，。！？!?,.]/g, "").toLowerCase();
        const approved = /^(确认|确定|是|好的|好|可以|同意|执行|yes|y)$/.test(
          normalized,
        );
        const denied = /^(取消|否|不|不要|不同意|停止|no|n)$/.test(normalized);
        try {
          const confirmation = await api.confirm(
            pending.confirmation_id,
            approved,
          );
          setPending(null);
          setMessages((items) => {
            const updated = items.map((item): ChatMessage =>
              item.role === "assistant"
                ? {
                    ...item,
                    content: item.content.map((part) =>
                      part.type === "tool-call" && part.waiting
                        ? {
                            ...part,
                            waiting: false,
                            result: { completed: approved },
                            isError:
                              !approved || confirmation.status === "failed",
                          }
                        : part,
                    ),
                  }
                : item,
            );
            const user: ChatMessage = {
              id: id(),
              role: "user",
              content: [{ type: "text", text }],
            };
            const assistant: ChatMessage = {
              id: id(),
              role: "assistant",
              content: [{ type: "text", text: confirmation.message }],
              status: { type: "complete", reason: "stop" },
            };
            return [...updated, user, assistant];
          });
          userMessageAdded = true;
          if (approved || denied) {
            setRunning(false);
            void refresh();
            return;
          }
        } catch (error) {
          setMessages((items) => [
            ...items,
            {
              id: id(),
              role: "assistant",
              content: [
                {
                  type: "text",
                  text:
                    error instanceof Error
                      ? error.message
                      : "确认失败，请重试。",
                },
              ],
              status: { type: "incomplete", reason: "error" },
            },
          ]);
          setRunning(false);
          return;
        }
      }
      const assistantId = id();
      setPending(null);
      setMessages((items) => [
        ...items,
        ...(userMessageAdded
          ? []
          : [
              {
                id: id(),
                role: "user" as const,
                content: [{ type: "text" as const, text }],
              },
            ]),
        {
          id: assistantId,
          role: "assistant",
          content: [{ type: "text", text: "" }],
          status: { type: "running" },
        },
      ]);
      try {
        await api.streamChat(
          sessionRef.current,
          text,
          (event: StreamEvent) => {
            if (event.type === "text_start")
              updateAssistant(assistantId, (item) => ({
                ...item,
                content:
                  item.content.length === 1 &&
                  item.content[0]?.type === "text" &&
                  !item.content[0].text
                    ? [{ type: "text", text: "", blockId: event.block_id }]
                    : [
                        ...item.content,
                        { type: "text", text: "", blockId: event.block_id },
                      ],
              }));
            if (event.type === "text_delta")
              updateAssistant(assistantId, (item) => ({
                ...item,
                content: item.content.map((part) =>
                  part.type === "text" &&
                  (!part.blockId || part.blockId === event.block_id)
                    ? {
                        ...part,
                        blockId: event.block_id,
                        text: part.text + event.delta,
                      }
                    : part,
                ),
              }));
            if (event.type === "thinking_start")
              updateAssistant(assistantId, (item) => ({
                ...item,
                content: [
                  ...item.content,
                  { type: "reasoning", text: "", blockId: event.block_id },
                ],
              }));
            if (event.type === "thinking_delta")
              updateAssistant(assistantId, (item) => ({
                ...item,
                content: item.content.map((part) =>
                  part.type === "reasoning" && part.blockId === event.block_id
                    ? { ...part, text: part.text + event.delta }
                    : part,
                ),
              }));
            if (
              event.type === "data_start" &&
              event.media_type.startsWith("image/")
            )
              updateAssistant(assistantId, (item) => ({
                ...item,
                content: [
                  ...item.content,
                  {
                    type: "image",
                    image: `data:${event.media_type};base64,`,
                    mediaType: event.media_type,
                    blockId: event.block_id,
                  },
                ],
              }));
            if (
              event.type === "data_delta" &&
              event.media_type.startsWith("image/")
            )
              updateAssistant(assistantId, (item) => ({
                ...item,
                content: item.content.map((part) =>
                  part.type === "image" && part.blockId === event.block_id
                    ? { ...part, image: part.image + event.data }
                    : part,
                ),
              }));
            if (event.type === "tool_start")
              updateAssistant(assistantId, (item) => ({
                ...item,
                content: [
                  ...item.content,
                  {
                    type: "tool-call",
                    toolCallId: event.tool_call_id || id(),
                    toolName: event.tool_name,
                    args: {},
                  },
                ],
              }));
            if (event.type === "tool_args_delta")
              updateAssistant(assistantId, (item) => ({
                ...item,
                content: item.content.map((part) =>
                  part.type === "tool-call" &&
                  part.toolCallId === event.tool_call_id
                    ? { ...part, argsText: (part.argsText || "") + event.delta }
                    : part,
                ),
              }));
            if (event.type === "tool_result_delta")
              updateAssistant(assistantId, (item) => ({
                ...item,
                content: item.content.map((part) =>
                  part.type === "tool-call" &&
                  part.toolCallId === event.tool_call_id
                    ? {
                        ...part,
                        artifact: `${part.artifact || ""}${event.delta}`,
                      }
                    : part,
                ),
              }));
            if (event.type === "tool_result_end")
              updateAssistant(assistantId, (item) => ({
                ...item,
                content: (() => {
                  const content = item.content.map((part) =>
                    part.type === "tool-call" &&
                    part.toolCallId === event.tool_call_id
                      ? {
                          ...part,
                          result: part.result ?? { completed: true },
                          isError:
                            event.state === "error" || event.state === "denied",
                        }
                      : part,
                  );
                  const toolResult = content.find(
                    (part): part is ToolPart =>
                      part.type === "tool-call" &&
                      part.toolCallId === event.tool_call_id,
                  )?.artifact;
                  const existing = new Set(
                    content
                      .filter(
                        (part): part is ImagePart => part.type === "image",
                      )
                      .map((part) => part.image),
                  );
                  return [
                    ...content,
                    ...imagesFromText(toolResult || "").filter(
                      (part) => !existing.has(part.image),
                    ),
                  ];
                })(),
              }));
            if (event.type === "human_required")
              updateAssistant(assistantId, (item) => ({
                ...item,
                content: item.content.map((part) =>
                  part.type === "tool-call" &&
                  event.tool_call_ids.includes(part.toolCallId)
                    ? { ...part, waiting: true }
                    : part,
                ),
              }));
            if (event.type === "hint")
              updateAssistant(assistantId, (item) => ({
                ...item,
                content: [
                  ...item.content,
                  {
                    type: "text",
                    text: `> ${event.source ? `**${event.source}**：` : ""}${event.hint}`,
                    blockId: event.block_id,
                  },
                ],
              }));
            if (event.type === "outcome") {
              setPending(event.status === "needs_confirmation" ? event : null);
              updateAssistant(assistantId, (item) => ({
                ...item,
                status: { type: "complete", reason: "stop" },
                content: (() => {
                  const content = item.content.some(
                    (part) => part.type === "text" && part.text,
                  )
                    ? item.content
                    : [{ type: "text" as const, text: event.message }];
                  const normalized = content.map((part) =>
                    part.type === "text"
                      ? { ...part, text: normalizeBabyBuddyLinks(part.text) }
                      : part,
                  );
                  const text = normalized
                    .filter((part): part is TextPart => part.type === "text")
                    .map((part) => part.text)
                    .join("\n");
                  const existing = new Set(
                    content
                      .filter(
                        (part): part is ImagePart => part.type === "image",
                      )
                      .map((part) => part.image),
                  );
                  return [
                    ...normalized,
                    ...imagesFromText(text).filter(
                      (part) => !existing.has(part.image),
                    ),
                  ];
                })(),
              }));
            }
          },
          stagedUpload ? [stagedUpload.upload_id] : [],
        );
        setStagedUpload(null);
      } catch (error) {
        updateAssistant(assistantId, (item) => ({
          ...item,
          status: { type: "incomplete", reason: "error" },
          content: [
            {
              type: "text",
              text: error instanceof Error ? error.message : "请求失败",
            },
          ],
        }));
      } finally {
        setRunning(false);
        void refresh();
      }
    },
    [pending, refresh, running, stagedUpload],
  );

  const runtime = useExternalStoreRuntime({
    messages,
    isRunning: running,
    onNew: sendMessage,
    convertMessage: (message: ChatMessage): ThreadMessageLike => message,
  });
  const create = (history: "push" | "replace" = "push") => {
    if (running) return;
    const next = id();
    void load(next, { history });
  };
  const removeConversation = async (conversation: Conversation) => {
    if (
      running ||
      !window.confirm(
        `删除对话“${conversation.title || "新对话"}”？此操作无法撤销。`,
      )
    )
      return;
    await api.deleteConversation(conversation.session_id);
    if (conversation.session_id === sessionRef.current) create("replace");
    await refresh();
  };
  const decide = async (approved: boolean) => {
    if (!pending?.confirmation_id) return;
    setRunning(true);
    try {
      const result = await api.confirm(pending.confirmation_id, approved);
      setPending(null);
      setMessages((items) => [
        ...items.map((message): ChatMessage =>
          message.role === "assistant"
            ? {
                ...message,
                content: message.content.map((part) =>
                  part.type === "tool-call" && part.waiting
                    ? {
                        ...part,
                        waiting: false,
                        result: { completed: approved },
                        isError: !approved || result.status === "failed",
                      }
                    : part,
                ),
              }
            : message,
        ),
        {
          id: id(),
          role: "assistant",
          content: [{ type: "text", text: result.message }],
          status: { type: "complete", reason: "stop" },
        },
      ]);
      void refresh();
    } catch (error) {
      setMessages((items) => [
        ...items,
        {
          id: id(),
          role: "assistant",
          content: [
            {
              type: "text",
              text:
                error instanceof Error ? error.message : "确认失败，请重试。",
            },
          ],
          status: { type: "incomplete", reason: "error" },
        },
      ]);
    } finally {
      setRunning(false);
    }
  };
  const stageDocument = async (file: File) => {
    setUploading(true);
    try {
      setStagedUpload(await api.stageDocument(file));
    } catch (error) {
      window.alert(error instanceof Error ? error.message : "文档暂存失败。");
    } finally {
      setUploading(false);
    }
  };
  return (
    <div className="app-shell">
      <aside className={`sidebar ${sidebarOpen ? "open" : ""}`}>
        <div className="brand">
          <div className="brand-mark">J</div>
          <div>
            <strong>Home Jarvis</strong>
            <small>家庭智能中枢</small>
          </div>
          <button
            className="sidebar-close"
            onClick={() => setSidebarOpen(false)}
            aria-label="关闭历史记录"
          >
            <X size={20} />
          </button>
        </div>
        <button className="new-chat" onClick={() => create()}>
          <Plus size={17} /> 新建对话
        </button>
        <nav>
          <p>历史记录</p>
          {conversations.map((conversation) => (
            <div
              className={`history-item ${conversation.session_id === sessionId ? "active" : ""}`}
              key={conversation.session_id}
            >
              <button
                className="history-select"
                onClick={() =>
                  !running &&
                  void load(conversation.session_id, { history: "push" })
                }
                title={conversation.title || "新对话"}
              >
                {conversation.title || "新对话"}
              </button>
              <button
                className="history-delete"
                aria-label={`删除 ${conversation.title || "新对话"}`}
                title="删除对话"
                onClick={() => void removeConversation(conversation)}
              >
                <Trash2 size={15} />
              </button>
            </div>
          ))}
        </nav>
        <button className="logout" onClick={() => void onLogout()}>
          <LogOut size={16} /> 退出
        </button>
      </aside>
      <button
        className={`sidebar-backdrop ${sidebarOpen ? "visible" : ""}`}
        onClick={() => setSidebarOpen(false)}
        aria-label="关闭历史记录"
        tabIndex={sidebarOpen ? 0 : -1}
      />
      <main className="chat-panel">
        <header>
          <div>
            <div className="header-title">
              <button
                className="sidebar-toggle"
                onClick={() => setSidebarOpen(true)}
                aria-label="打开历史记录"
                aria-expanded={sidebarOpen}
              >
                <Menu size={21} />
              </button>
              <strong>Home Jarvis</strong>
            </div>
            <span>
              <i /> 在线
            </span>
          </div>
        </header>
        <AssistantRuntimeProvider runtime={runtime}>
          <Thread
            upload={stagedUpload}
            uploading={uploading}
            onDocument={(file) => void stageDocument(file)}
            onRemoveUpload={() => setStagedUpload(null)}
          />
        </AssistantRuntimeProvider>
        {pending?.confirmation && (
          <div
            className={`confirm-card ${pending.confirmation.severity}`}
            role="dialog"
            aria-labelledby="confirmation-title"
          >
            <strong id="confirmation-title">
              {pending.confirmation.title}
            </strong>
            <p>{pending.confirmation.description}</p>
            <small>
              可以点击按钮，也可以在输入框回复“确认”或“取消”。输入其他内容将取消本次操作并继续对话。
            </small>
            <div>
              <button onClick={() => void decide(false)}>
                {pending.confirmation.cancel_label}
              </button>
              <button onClick={() => void decide(true)}>
                {pending.confirmation.confirm_label}
              </button>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
