# AgentScope 通用 Agent

这是一个使用 AgentScope 2.x 构建的通用对话 Agent。当前默认连接 BabyBuddy 的 MCP 服务，但核心包名和运行时设计保持通用，后续可以接入其他工作系统、模型供应商或 Web/API 入口。

## 架构

```text
CLI / Web 入口
    -> Conversation
    -> AgentScope Agent
    -> Toolkit
    -> MCPClient (Streamable HTTP)
    -> BabyBuddy MCP
```

应用层不直接调用 Anthropic、OpenAI 或 MCP SDK 的底层循环；模型、工具和消息循环都通过 AgentScope API 装配。

## 安装

代码按 AgentScope 2.0.5dev 文档中的 `Agent + Toolkit + MCPClient` 结构组织。当前配置源只提供 `agentscope==2.0.4.post1`，因此先锁定该可安装版本完成验证；升级到 2.0.5dev 时只需要替换依赖并重新运行检查。

目录中的 `.venv` 是 Linux 虚拟环境，Windows 下不能直接使用。推荐在项目目录创建 Windows 环境：

```bash
UV_PROJECT_ENVIRONMENT=.venv-win uv sync --extra dev
```

PowerShell：

```powershell
$env:UV_PROJECT_ENVIRONMENT = ".venv-win"
uv sync --extra dev
```

复制配置示例并填写模型凭据：

```bash
cp .env.example .env
```

CLI 会自动读取项目根目录的 `.env` 文件；也可以用 IDE、进程管理器或 shell 覆盖环境变量。Windows PowerShell 示例：

```powershell
$env:AGENTSCOPE_MODEL_PROVIDER = "anthropic"
$env:AGENTSCOPE_MODEL_NAME = "claude-opus-4-8"
$env:ANTHROPIC_API_KEY = "..."
$env:ANTHROPIC_BASE_URL = ""
$env:BABYBUDDY_MCP_URL = "http://192.168.5.13:2001/mcp"
```

## 配置

默认模型是 `claude-opus-4-8`，默认 provider 是 `anthropic`。可选 provider：

- `deepseek`：`DEEPSEEK_API_KEY`，可选 `DEEPSEEK_BASE_URL`，默认 `https://api.deepseek.com`
- `dashscope`：`DASHSCOPE_API_KEY` 和 `DASHSCOPE_BASE_URL`，默认百炼 OpenAI-compatible 地址
- `anthropic`：`ANTHROPIC_API_KEY`，可选 `ANTHROPIC_BASE_URL`
- `openai`：`OPENAI_API_KEY`，可选 `OPENAI_BASE_URL`
- `ollama`：`OLLAMA_HOST`，不需要 API key

MCP 默认配置：

```text
BABYBUDDY_MCP_URL=http://192.168.5.13:2001/mcp
BABYBUDDY_MCP_STATEFUL=true
BABYBUDDY_MCP_TIMEOUT=30
```

该 URL 使用 AgentScope 的 Streamable HTTP MCP transport。MCP host 有 allowlist 校验，修改地址时同步设置 `BABYBUDDY_MCP_ALLOWED_HOSTS`。

## 运行

检查配置，不连接 MCP：

```bash
uv run python -m agent --check-config
```

执行单轮请求：

```bash
uv run python -m agent --once "列出可用的 BabyBuddy 数据类型"
```

进入多轮会话：

```bash
uv run python -m agent
```

输入 `:help` 查看命令，输入 `:quit` 退出。

### 手机网页服务

Python 服务现在只提供 API；手机页面位于独立的 React + Tailwind 项目 `web/`。
先在 `.env` 中设置仅保留在服务端的密码和签名密钥：

```text
AGENT_WEB_PASSWORD=设置一个家庭密码
AGENT_WEB_SESSION_SECRET=1234  # 本地家庭环境可用；公网部署请使用长随机值
AGENT_WEB_HOST=0.0.0.0
AGENT_WEB_PORT=8000
```

启动服务：

```bash
uv run agent-web
```

另开一个终端启动 React 开发服务器：

```bash
npm --prefix web install
npm --prefix web run dev
```

Vite 会将 `/api` 代理到 `http://127.0.0.1:8000`。生产环境应由反向代理将 React
构建产物和 `/api` 路由到同一个来源，避免跨域 Cookie 配置。浏览器只接收页面、会话
Cookie、Agent 回复和待确认操作；不会收到 LLM key、Baby Buddy Token、MCP 地址或
审计日志。

### Docker 部署

Docker Compose 使用 Ubuntu 构建 API 和 Nginx 服务。Nginx 提供 React SPA，并将
`/api/`、`/chat`、`/api/ha/chat` 和 `/health` 反向代理到 API；其他路径回退到 SPA。
先复制并填写 `.env`，尤其是 `AGENT_WEB_PASSWORD`、`AGENT_WEB_SESSION_SECRET`、模型凭据
和 MCP 配置，然后运行：

```bash
docker compose up --build -d
```

默认对外暴露 `http://<host>/`。持久数据使用 Compose 管理的 `agent_data` 卷，并在 API
容器中挂载为 `/data`；SQLite 数据库和审计日志分别保存为
`/data/agent-web.sqlite3` 和 `/data/audit/events.jsonl`。本地开发仍使用 `.env` 中的
`var/` 路径，不受 Compose 覆盖影响。可用 `GET /health` 检查 API 进程状态；该检查不需要
认证，也不会连接模型或 MCP 服务。

HTTP 接口：

- `POST /api/chat`：提交 `{ "text", "session_id", "timezone" }`，其中
  `timezone` 是浏览器提供的 IANA 时区（如 `Asia/Shanghai`）；返回完成回复或
  `needs_confirmation` 和 `confirmation_id`。
- `POST /api/confirm`：提交 `{ "confirmation_id", "approved", "timezone" }`。
  只有 `approved: true` 才会让挂起的 AgentScope 工具调用继续执行。
- `GET /api/today`：只读获取今日摘要、最近喂奶、睡眠状态、尿布次数和最近记录。
- `POST /api/audio`：当前固定返回 `501 audio_not_configured`；语音转文字留待后续版本。
- `POST /chat`（`/api/ha/chat` 也是等价别名）：供 Home Assistant 调用。需配置
  `AGENT_HA_TOKEN`，并使用 `Authorization: Bearer <token>` 或 `X-Agent-HA-Token`。
  请求为 `{ "text", "conversation_id?", "timezone?", "user_id?", "device_id?", "satellite_id?" }`，
  返回 `{ "reply", "conversation_id", "status", ... }`。`conversation_id` 由 HA 在后续请求原样
  传回，以保持语音多轮上下文；未提供 `timezone` 时使用 `AGENT_HA_TIMEZONE`（默认
  `Asia/Shanghai`）。

Home Assistant 使用短语音提示完成写入确认：助手会先复述将要写入的内容并询问“确认吗？”，
只有下一轮的明确肯定才会调用写入工具。HA 无需处理网页确认卡片或 `confirmation_id`；网页端
仍使用确认卡片保护写入操作。

网页会保留当前会话的消息气泡；同一浏览器的 `session_id` 会在服务运行期间复用同一
AgentScope 对话上下文。因此当 Agent 追问“只有小便还是也有大便？”时，直接在输入框
补充即可，字段齐全后才会显示写入确认卡。

服务使用 SQLite 只保存会话归属、待确认操作的脱敏元数据和回复哈希，不复制 Baby
Buddy 育儿记录。AgentScope 上下文与可恢复工具调用仅存在于运行内存中：服务重启时，
所有待确认操作都会标记为过期，必须重新提交，绝不会在重启后自动写入。

## 写入安全

AgentScope 默认权限模式会在工具执行前产生 `RequireUserConfirmEvent`。本项目对待确认调用显示工具名和参数摘要，只有输入 `y` 才会继续执行。拒绝、超时、MCP 失败和不确定结果不会被报告为成功。

当前首版对 MCP 工具使用保守确认策略。完成第一次工具发现后，应根据 BabyBuddy MCP 实际工具 schema 配置只读 allowlist；不要仅凭工具名称中的 `create`、`update` 或 `delete` 猜测权限。

审计日志默认写入 `var/audit/events.jsonl`，只保存工具名、调用 ID、参数哈希和参数 key，不保存完整参数值或凭据。

## 测试与检查

```bash
uv run pytest
uv run python -m compileall src
uv run ruff check src tests
```

真实 MCP smoke test 需要显式配置凭据和内网可达性。默认自动测试不修改 BabyBuddy 数据；建议先执行工具发现和只读请求，再手动确认写入。

## 目录

- `src/agent/config.py`：环境变量和边界校验
- `src/agent/model_factory.py`：AgentScope 模型 provider 工厂
- `src/agent/mcp_client.py`：MCPClient 生命周期和 Toolkit 装配
- `src/agent/agent.py`：通用 AgentScope Agent
- `src/agent/chat.py`：多轮上下文和确认事件循环
- `src/agent/audit.py`：脱敏 JSONL 审计
- `src/agent/cli.py`：交互式 CLI
- `src/agent/runtime/`：SQLite 元数据与 HTTP 服务运行时状态
- `src/agent/web/`：FastAPI API 入口与认证边界
- `web/`：独立的 Vite、React 与 Tailwind 手机前端
- `tests/runtime/`：运行时和持久化测试
- `tests/web/`：HTTP 页面和 API 契约测试
- `tests/`：其余单元测试；真实 MCP 测试需显式开启
