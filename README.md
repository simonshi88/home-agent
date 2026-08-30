# Home Jarvis

这是一个使用 AgentScope 2.x 构建的家庭多 Agent 系统。用户只与 Home Jarvis 主 Agent 对话；主 Agent 按领域委派给能力隔离的专项 Agent。Web 端基于 assistant-ui，支持流式输出、委派/工具过程、HITL 和历史记录。

## 架构

```text
CLI / Web / Home Assistant
    -> Home Jarvis（leader，仅持有委派工具和主会话上下文）
       ├─ delegate_to_baby -> Baby Specialist
       │                       └─ BabyBuddy MCP
       ├─ delegate_to_exercise -> Exercise Specialist
       │                           └─ query_exercises -> PostgreSQL exercise_catalog
       └─ delegate_to_paperless -> Paperless Specialist
                                    ├─ query_paperless -> Paperless-ngx REST API
                                    └─ upload_paperless_document -> HITL -> Paperless
```

每个 Toolkit 只属于一个 Agent：Home Jarvis 不持有领域工具；Baby Specialist 独占
BabyBuddy MCP；Exercise Specialist 独占只读 `query_exercises`；Paperless Specialist
独占文档查询和上传工具。子 Agent 的事件、工具过程和 HITL 会透传到 leader 的页面流。

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

动作数据库配置：

```text
DATABASE_URL=postgresql://<用户名>:<密码>@<数据库主机>:5432/<数据库名>
```

请只在未纳入 Git 的 `.env` 中填写真实连接信息。`query_exercises` 支持搜索、
按四位 ID 取详情和读取筛选项；数据库凭据不会发送到浏览器或模型，工具也不接受任意 SQL。

Paperless-ngx 配置：

```text
PAPERLESS_URL=http://paperless.home
PAPERLESS_API_TOKEN=在 Paperless 用户设置中创建的 API Token
PAPERLESS_TIMEOUT=30
PAPERLESS_UPLOAD_DIR=var/paperless-uploads
PAPERLESS_UPLOAD_MAX_MB=32
```

`query_paperless` 支持全文搜索、文档详情、标签、通讯者、文档类型、存储路径、
自定义字段和上传任务查询。网页输入框左侧的附件按钮会先把文件暂存在当前登录用户的
隔离目录中；`upload_paperless_document` 只能使用该上传 ID，不能读取任意服务器路径。
真正上传前会显示 HITL 确认卡。Paperless 接收上传后返回异步任务 ID，可继续查询处理状态。

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

Docker 镜像使用独立的 Node 和 Python 3.14 构建阶段，最终运行镜像只包含 Python 运行时、
Home Jarvis 后端和编译后的 React 页面。FastAPI 在同一个来源提供页面与 API，不需要
额外的 Nginx 容器。先复制并填写 `.env`，尤其是 `AGENT_WEB_PASSWORD`、
`AGENT_WEB_SESSION_SECRET`、模型凭据、MCP、Baby Buddy 媒体地址和动作数据库配置，然后运行：

```bash
docker compose up --build -d
```

默认地址是 `http://<host>:18080/`；可通过 `.env` 中的 `HOME_JARVIS_PORT` 修改宿主端口，
容器内部始终监听 8000。持久数据保存在名为 `home-jarvis-data` 的 Docker volume，挂载为
`/data`；SQLite 数据库和审计日志分别保存为
`/data/agent-web.sqlite3` 和 `/data/audit/events.jsonl`。本地开发仍使用 `.env` 中的
`var/` 路径，不受 Compose 覆盖影响。可用 `GET /health` 检查 API 进程状态；该检查不需要
认证，也不会连接模型或 MCP 服务。

容器以 UID/GID `10001` 的非 root 用户运行，移除了 Linux capabilities，并启用了
`no-new-privileges`。Baby Buddy 图片由后端从 `BABYBUDDY_MEDIA_URL`（默认
`http://baby.home`）读取后同源代理给浏览器，因此该域名必须能从 Docker 容器内解析。

常用运维命令：

```bash
docker compose ps
docker compose logs -f app
docker compose up --build -d
docker compose down
```

`docker compose down` 不会删除聊天数据；只有显式执行 `docker compose down -v` 才会删除
持久化 volume。

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

服务使用 SQLite 保存会话归属、聊天文本、待确认操作的脱敏元数据和回复哈希，不复制
Baby Buddy 育儿记录。服务重启后会按 `session_id` 将消息恢复为 Home Jarvis 的主上下文；
不可安全恢复的工具调用确认会标记为过期，必须重新提交，绝不会在重启后自动写入。

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
- `src/agent/agents/`：Home Jarvis、专项 Agent、角色提示和团队装配
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
