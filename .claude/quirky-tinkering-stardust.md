# Context

当前工作区 `d:\code\agentscope` 只有虚拟环境和 `uv.toml`，没有业务源码、入口、依赖声明或测试。虚拟环境中已有 AgentScope 2.0.4.post1、MCP 1.28.1 和 Anthropic 等依赖，但用户要求按 AgentScope 2.0.5dev 的架构搭建一个可扩展的 BabyBuddy 对话 Agent。Agent 需要通过远程 MCP 服务 `http://192.168.5.13:2001/mcp` 查询和写入 BabyBuddy 内容，并在写入类操作前保留 AgentScope 的用户确认机制。

目标是先建立标准 Python 项目骨架和最小可运行的交互式消息循环：模型、MCP 客户端、Agent、配置和 CLI 分层，后续可以替换模型供应商、增加工具/技能或接入 Web 服务，而不重写 Agent 核心。

# 推荐实现

## 1. 建立可复现的 Python 项目骨架

新增：

- `pyproject.toml`：使用 `src/` 布局，固定 Python >=3.11；声明 AgentScope 2.0.5dev 对应版本/预发布依赖、`mcp<2`、Anthropic SDK，以及测试依赖。安装时优先使用现有 `uv.toml` 镜像；若 2.0.5dev 尚未在镜像发布，明确保留可切换到官方源或 Git 版本的依赖说明，不把 2.0.4.post1 当作目标版本。
- `.env.example`：只记录变量名和示例值，不包含密钥。
- `README.md`：记录安装、模型配置、MCP 地址、运行命令、确认行为和排错方法。
- `src/agent/__init__.py`：公开应用层工厂。
- `tests/`：放配置、模型工厂、MCP 装配和消息循环的单元测试。

## 2. 配置层

新增 `src/agent/config.py`：

- 定义类型化设置对象，从环境变量读取 `AGENTSCOPE_MODEL_PROVIDER`、模型名、对应 API key/base URL、`BABYBUDDY_MCP_URL`、MCP timeout、stateful 开关、Agent 最大迭代次数和用户标识。
- 默认 MCP URL 使用用户提供的内网地址，但允许环境变量覆盖，便于测试/部署。
- 默认使用 Anthropic 的 AgentScope 模型适配器和 `claude-opus-4-8`；模型供应商作为配置项保留扩展点。若实现时发现目标 AgentScope 版本的某供应商适配器签名不同，以已安装版本/2.0.5dev 文档为准修正，不在业务层直接调用 Messages API。
- 对密钥只做边界校验，绝不写入日志、提示词、会话文件或 README。

## 3. 模型工厂

新增 `src/agent/model_factory.py`：

- 提供 `build_chat_model(settings)`，把 `AnthropicCredential`/`AnthropicChatModel` 等具体 provider 细节集中在一个模块。
- 保持 AgentScope 的 `ChatModelBase` 接口，未来可通过 provider registry 增加 DashScope、OpenAI-compatible 或 Ollama，而不修改 Agent 构造和消息循环。
- 默认启用流式模型配置；为 AgentScope 的 `Agent.reply_stream` 提供事件流。
- 模型失败/重试策略使用 AgentScope 的 `ModelConfig`，不要在业务层复制模型调用循环。

## 4. MCP 适配层

新增 `src/agent/mcp_client.py`：

- 使用 `agentscope.mcp.MCPClient` 和 `HttpMCPConfig`，配置 `url=settings.babybuddy_mcp_url`、headers（如后续需要）和 timeout。
- 交互式会话默认使用 `is_stateful=True`，在启动时 `await connect()`，在 `finally` 中 `await close()`；通过环境变量保留切换为 stateless 的能力。该 URL 不是 `/sse`，按 AgentScope 的 streamable HTTP transport 处理。
- 将 MCP 工具通过 `Toolkit(mcps=[client])` 注入 Agent；不要手写 MCP tool schema 或绕过 AgentScope 调用底层 `mcp.ClientSession`。
- 暴露 MCP 工具发现/健康检查函数，启动阶段列出工具名，便于确认 BabyBuddy 服务已连接；输出中不得暴露凭据。
- 保留 `enable_tools`/`disable_tools` 配置入口，后续可以按实际 BabyBuddy 工具名做最小权限 allowlist。

## 5. Agent 装配层

新增 `src/agent/agent.py`：

- 用 `agentscope.agent.Agent` 创建唯一的 Agent 实例，注入模型和 MCP Toolkit；不创建自定义 ReActAgent，也不直接实现 LLM tool loop。
- 配置稳定的中文 system prompt：Agent 是 BabyBuddy 助手；只能依据 MCP 返回结果确认数据；涉及创建、修改、删除、记录写入时必须先说明将要写入的字段并等待 AgentScope 用户确认；工具返回失败时如实说明；不能把计划/推测说成已写入；不要泄露密钥或内部配置。
- 使用 `ReActConfig(max_iters=...)` 限制单轮工具循环，避免 MCP 异常时无限运行。
- 预留 `ModelConfig` fallback/retry 和 `ContextConfig` 的注入位置，但不在首版引入未经需求验证的复杂压缩/持久化。
- Agent 生命周期由上层管理，避免每轮对话重复创建 MCP 连接和 Agent。

## 6. 对话消息循环

新增 `src/agent/chat.py`：

- 用 `UserMsg(name="user", content=...)` 向同一个 Agent 实例发送每轮输入，从而保留 AgentScope state/context。
- 采用 `agent.reply_stream(...)`，消费 AgentScope `AgentEvent`；将文本增量写到终端，同时显示必要的工具调用/结果状态。
- 正确处理 `RequireUserConfirmEvent`：展示待执行的工具名和参数摘要，读取用户 `y/n`，构造 `ConfirmResult` 与 `UserConfirmResultEvent`，再把事件传回 `agent.reply_stream`；拒绝写操作必须让 Agent 继续解释或等待用户重新描述，而不是伪造成功。
- 处理 `ReplyEndEvent`、MCP/tool error、最大迭代和 Ctrl-C；退出时关闭 MCP 客户端。
- 将“所有 MCP 工具都要求确认”的安全默认交给 AgentScope 默认权限机制；后续拿到 BabyBuddy 实际工具元数据后，再将只读工具加入 allow rule，仅对写工具确认。
- CLI 只负责 I/O，AgentScope 工具和模型都由装配层提供，后续可替换为 WebSocket/HTTP UI。

## 7. 启动入口与运行方式

新增 `src/agent/__main__.py`：

- 读取设置、构建 MCP client、连接并做工具健康检查、创建 Agent，然后进入异步 stdin 对话。
- 支持 `--once` 或单轮参数用于 smoke test，默认进入多轮模式。
- 通过 `uv run python -m agent` 启动；不把真实 API key 写入命令行参数或代码。

## 8. 测试策略

新增测试覆盖：

- 配置默认值、环境变量覆盖和缺失密钥的清晰错误。
- 模型工厂只选择 AgentScope model adapter，不直接调用 Anthropic/OpenAI client。
- MCP client 使用假的/注入的 `MCPClient` 或 monkeypatch 验证 `HttpMCPConfig`、stateful 生命周期和 Toolkit 装配，不让普通单元测试依赖内网 BabyBuddy。
- 消息循环能处理普通文本、`RequireUserConfirmEvent` 的允许/拒绝、MCP 错误和 Ctrl-C。
- 可选集成 smoke test 通过显式环境变量启用，连接实际 `BABYBUDDY_MCP_URL` 并只执行只读工具发现；写入测试必须由用户手动确认，不在自动测试中修改 BabyBuddy 数据。

# 验证

1. 安装目标依赖：`uv sync`，确认导入路径和实际 AgentScope 版本为 2.0.5dev 目标版本；若镜像无该版本，按 README 的官方源/Git 安装说明处理。
2. 运行静态/单元检查：`uv run pytest`，并执行 `uv run python -m compileall src`。
3. 配置有效模型凭据和 `BABYBUDDY_MCP_URL` 后运行 `uv run python -m agent --once "列出 BabyBuddy 中可用的记录类型"`，确认 MCP 工具发现、AgentScope 消息循环和文本输出完整。
4. 运行多轮对话：先查询 BabyBuddy 数据，再提交一个明确的写入请求；确认 AgentScope 发出用户确认事件，拒绝时无写入，允许后仅以 MCP 实际返回为准报告结果。
5. 连接失败、模型失败、工具失败和服务端返回错误时，确认 CLI 给出可诊断错误且不输出密钥；最后再考虑把同一装配层接入 Web/API 页面。
