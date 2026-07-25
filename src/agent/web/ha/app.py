from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI(
    title="AgentScope Home Assistant API",
)


class ChatRequest(BaseModel):
    text: str = Field(min_length=1)
    conversation_id: str | None = None
    language: str = "zh-CN"
    device_id: str | None = None
    satellite_id: str | None = None
    user_id: str | None = None


class ChatResponse(BaseModel):
    reply: str


@app.get("/health")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
    }


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    return ChatResponse(
        reply=f"AgentScope 收到了：{request.text}",
    )