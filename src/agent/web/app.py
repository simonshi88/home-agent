"""Same-origin FastAPI adapter for the Baby Buddy AgentScope runtime."""

from __future__ import annotations

import asyncio
import hmac
import json
from contextlib import asynccontextmanager
from hashlib import sha256
from pathlib import Path
from typing import AsyncIterator
from urllib.parse import quote, urlparse
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from starlette.datastructures import Headers
from starlette.middleware.sessions import SessionMiddleware
from starlette.staticfiles import StaticFiles

from ..config import Settings
from ..runtime.service import (
    AgentService,
    BusySessionError,
    ChatOutcome,
    ConfirmationStateError,
    ServiceError,
)
from ..runtime.store import ChatMessageRecord, ConversationRecord
from .streaming import stream_event


class LoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=512)


class ChatRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2_000)
    session_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._-]+$")
    timezone: str = Field(min_length=1, max_length=64)


class ConfirmRequest(BaseModel):
    confirmation_id: str = Field(min_length=1, max_length=128)
    approved: bool
    timezone: str = Field(min_length=1, max_length=64)


class HomeAssistantChatRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2_000)
    conversation_id: str | None = Field(default=None, max_length=256)
    language: str = Field(default="zh-CN", max_length=32)
    timezone: str | None = Field(default=None, max_length=64)
    device_id: str | None = Field(default=None, max_length=256)
    satellite_id: str | None = Field(default=None, max_length=256)
    user_id: str | None = Field(default=None, max_length=256)
    confirmation_id: str | None = Field(default=None, max_length=128)
    approved: bool | None = None


class SameOriginMiddleware:
    """Reject cross-origin mutations without BaseHTTPMiddleware."""

    def __init__(self, app, *, allowed_origins: tuple[str, ...]) -> None:
        self.app = app
        self.allowed_origins = set(allowed_origins)

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http" and scope["method"] in {
            "POST",
            "PUT",
            "PATCH",
            "DELETE",
        }:
            headers = Headers(scope=scope)
            origin = headers.get("origin")
            if origin:
                dynamic_origin = (
                    f"{scope.get('scheme', 'http')}://{headers.get('host', '')}"
                )
                api_host = headers.get("host", "").split(":", maxsplit=1)[0]
                parsed_origin = urlparse(origin)
                vite_proxy_origin = (
                    parsed_origin.scheme == scope.get("scheme", "http")
                    and parsed_origin.hostname == api_host
                    and parsed_origin.port == 5173
                )
                allowed = self.allowed_origins or {dynamic_origin}
                if origin not in allowed and not vite_proxy_origin:
                    response = JSONResponse(
                        {"detail": "cross-origin requests are not allowed"},
                        status_code=status.HTTP_403_FORBIDDEN,
                    )
                    await response(scope, receive, send)
                    return
        await self.app(scope, receive, send)


def create_app(settings: Settings, service: AgentService | None = None) -> FastAPI:
    """Build the service app without leaking runtime configuration to the client."""
    web_settings = settings.web_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        runtime = service or AgentService(settings)
        app.state.agent_service = runtime
        await runtime.start()
        try:
            yield
        finally:
            await runtime.stop()

    app = FastAPI(
        title="Baby Buddy Phone Agent",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.add_middleware(
        SessionMiddleware,
        secret_key=web_settings.session_secret,
        session_cookie="agent_web_session",
        same_site="strict",
        https_only=False,
        max_age=60 * 60 * 24 * 14,
    )

    app.add_middleware(
        SameOriginMiddleware,
        allowed_origins=web_settings.allowed_origins,
    )

    def owner_id(request: Request) -> str:
        owner = request.session.get("owner_id")
        if not isinstance(owner, str):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="login required",
            )
        return owner

    def runtime(request: Request) -> AgentService:
        return request.app.state.agent_service

    def valid_timezone(value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="invalid IANA timezone",
            ) from exc
        return value

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Report process availability without touching model or MCP services."""
        return {"status": "ok"}

    @app.post("/api/login")
    async def login(payload: LoginRequest, request: Request) -> dict[str, str]:
        if not hmac.compare_digest(payload.password, web_settings.password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid password",
            )
        request.session.clear()
        request.session["owner_id"] = str(uuid4())
        return {"status": "authenticated"}

    @app.post("/api/logout")
    async def logout(request: Request) -> dict[str, str]:
        owner_id(request)
        request.session.clear()
        return {"status": "logged_out"}

    @app.get("/api/session")
    async def current_session(request: Request) -> dict[str, str]:
        return {"status": "authenticated", "owner_id": owner_id(request)}

    @app.get("/api/babybuddy-media/{media_path:path}")
    async def babybuddy_media(media_path: str, request: Request) -> StreamingResponse:
        """Proxy authenticated Baby Buddy images hidden behind its Docker hostname."""
        owner_id(request)
        parts = [part for part in media_path.split("/") if part]
        if not parts or any(part in {".", ".."} for part in parts):
            raise HTTPException(status_code=400, detail="invalid media path")
        upstream_url = (
            f"{settings.babybuddy_media_url}/media/"
            + "/".join(quote(part, safe="") for part in parts)
        )
        client = httpx.AsyncClient(
            timeout=settings.mcp_timeout,
            follow_redirects=False,
        )
        try:
            upstream = await client.send(
                client.build_request("GET", upstream_url),
                stream=True,
            )
        except httpx.HTTPError as exc:
            await client.aclose()
            raise HTTPException(status_code=502, detail="media unavailable") from exc
        content_type = upstream.headers.get("content-type", "").split(";", 1)[0]
        if upstream.status_code != 200 or not content_type.startswith("image/"):
            await upstream.aclose()
            await client.aclose()
            raise HTTPException(status_code=404, detail="image not found")

        async def content() -> AsyncIterator[bytes]:
            try:
                async for chunk in upstream.aiter_bytes():
                    yield chunk
            finally:
                await upstream.aclose()
                await client.aclose()

        return StreamingResponse(
            content(),
            media_type=content_type,
            headers={"Cache-Control": "private, max-age=300"},
        )

    @app.get("/api/conversations")
    async def conversations(request: Request) -> dict[str, object]:
        try:
            records = runtime(request).conversations(owner_id=owner_id(request))
        except ServiceError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="conversation history unavailable",
            ) from exc
        return {"conversations": [_conversation_payload(record) for record in records]}

    @app.get("/api/conversations/{session_id}/messages")
    async def conversation_messages(
        session_id: str,
        request: Request,
    ) -> dict[str, object]:
        try:
            messages = runtime(request).conversation_messages(
                session_id=session_id,
                owner_id=owner_id(request),
            )
        except ServiceError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="conversation history unavailable",
            ) from exc
        if messages is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="conversation not found",
            )
        return {"messages": [_chat_message_payload(message) for message in messages]}

    @app.delete("/api/conversations/{session_id}")
    async def delete_conversation(session_id: str, request: Request) -> dict[str, str]:
        deleted = await runtime(request).delete_conversation(
            session_id=session_id,
            owner_id=owner_id(request),
        )
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="conversation not found",
            )
        return {"status": "deleted"}

    @app.post("/api/chat")
    async def chat(payload: ChatRequest, request: Request) -> dict[str, object]:
        try:
            outcome = await runtime(request).chat(
                session_id=payload.session_id,
                owner_id=owner_id(request),
                text=payload.text.strip(),
                timezone=valid_timezone(payload.timezone),
            )
        except BusySessionError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc
        except PermissionError as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="session denied",
            ) from exc
        except ServiceError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="agent unavailable",
            ) from exc
        return _outcome_payload(outcome)

    @app.post("/api/chat/stream")
    async def chat_stream(payload: ChatRequest, request: Request) -> StreamingResponse:
        """Stream text and tool lifecycle events as newline-delimited JSON."""
        owner = owner_id(request)
        timezone = valid_timezone(payload.timezone)

        async def events():
            queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()

            async def emit(event: object) -> None:
                mapped = stream_event(event)
                if mapped is not None:
                    await queue.put(mapped)

            async def run() -> None:
                try:
                    outcome = await runtime(request).chat(
                        session_id=payload.session_id,
                        owner_id=owner,
                        text=payload.text.strip(),
                        timezone=timezone,
                        emit=emit,
                    )
                    await queue.put({"type": "outcome", **_outcome_payload(outcome)})
                except BusySessionError as exc:
                    await queue.put({"type": "error", "message": str(exc)})
                except Exception:
                    await queue.put({"type": "error", "message": "agent unavailable"})
                finally:
                    await queue.put({"type": "done"})

            task = asyncio.create_task(run())
            try:
                while True:
                    item = await queue.get()
                    yield json.dumps(item, ensure_ascii=False, default=str) + "\n"
                    if item["type"] == "done":
                        break
            finally:
                if not task.done():
                    task.cancel()

        return StreamingResponse(
            events(),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/confirm")
    async def confirm(payload: ConfirmRequest, request: Request) -> dict[str, object]:
        try:
            valid_timezone(payload.timezone)
            outcome = await runtime(request).confirm(
                confirmation_id=payload.confirmation_id,
                owner_id=owner_id(request),
                approved=payload.approved,
            )
        except ConfirmationStateError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc
        return _outcome_payload(outcome)

    def home_assistant_owner_id(payload: HomeAssistantChatRequest) -> str:
        identity = (
            payload.user_id or payload.device_id or payload.satellite_id or "default"
        )
        return f"ha-owner-{_stable_id(identity)}"

    def home_assistant_session_id(
        payload: HomeAssistantChatRequest,
        owner: str,
    ) -> tuple[str, str]:
        conversation_id = payload.conversation_id or f"ha-{uuid4().hex}"
        return conversation_id, f"ha-session-{_stable_id(f'{owner}:{conversation_id}')}"

    def require_home_assistant_token(request: Request) -> None:
        if not settings.ha_token:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Home Assistant integration is not configured",
            )
        authorization = request.headers.get("authorization", "")
        bearer = authorization.removeprefix("Bearer ")
        token = request.headers.get("x-agent-ha-token", bearer)
        if not hmac.compare_digest(token, settings.ha_token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid Home Assistant token",
            )

    @app.post("/chat")
    @app.post("/api/ha/chat")
    async def home_assistant_chat(
        payload: HomeAssistantChatRequest,
        request: Request,
    ) -> dict[str, object]:
        require_home_assistant_token(request)
        owner = home_assistant_owner_id(payload)
        conversation_id, session_id = home_assistant_session_id(payload, owner)
        try:
            timezone = valid_timezone(payload.timezone or settings.ha_timezone)
            if payload.confirmation_id is not None:
                if payload.approved is None:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                        detail="approved is required with confirmation_id",
                    )
                outcome = await runtime(request).confirm(
                    confirmation_id=payload.confirmation_id,
                    owner_id=owner,
                    approved=payload.approved,
                )
            else:
                outcome = await runtime(request).chat(
                    session_id=session_id,
                    owner_id=owner,
                    text=payload.text.strip(),
                    timezone=timezone,
                    voice_confirmation=True,
                )
        except BusySessionError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc
        except ConfirmationStateError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc
        except PermissionError as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="session denied",
            ) from exc
        except ServiceError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="agent unavailable",
            ) from exc
        return _home_assistant_outcome_payload(outcome, conversation_id)

    @app.get("/api/today")
    async def today(request: Request) -> dict[str, object]:
        try:
            snapshot = await runtime(request).today(owner_id=owner_id(request))
        except ServiceError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="today summary unavailable",
            ) from exc
        return {"status": "completed", **snapshot.as_dict()}

    @app.post("/api/audio")
    async def audio(request: Request) -> JSONResponse:
        owner_id(request)
        return JSONResponse(
            {
                "status": "audio_not_configured",
                "message": "语音转文字将在后续版本提供。",
            },
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
        )

    frontend_dir = Path("/app/web/dist")
    if frontend_dir.is_dir():
        app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")

    return app


def _conversation_payload(record: ConversationRecord) -> dict[str, object]:
    return {
        "session_id": record.session_id,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "title": record.title,
        "message_count": record.message_count,
    }


def _chat_message_payload(message: ChatMessageRecord) -> dict[str, str | None]:
    return {
        "id": message.id,
        "session_id": message.session_id,
        "role": message.role,
        "content": message.content,
        "status": message.status,
        "created_at": message.created_at,
    }


def _outcome_payload(outcome: ChatOutcome) -> dict[str, object]:
    payload: dict[str, object] = {"status": outcome.status, "message": outcome.message}
    if outcome.confirmation is not None:
        payload["confirmation_id"] = outcome.confirmation.id
        payload["confirmation"] = {
            "description": outcome.confirmation.description,
            "tool_names": list(outcome.confirmation.tool_names),
            "expires_at": outcome.confirmation.expires_at,
        }
    return payload


def _home_assistant_outcome_payload(
    outcome: ChatOutcome,
    conversation_id: str,
) -> dict[str, object]:
    payload = {
        "reply": outcome.message,
        "conversation_id": conversation_id,
        **_outcome_payload(outcome),
    }
    return payload


def _stable_id(value: str) -> str:
    return sha256(value.encode()).hexdigest()[:32]
