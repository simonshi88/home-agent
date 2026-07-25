"""LAN-only HTTP service and phone UI entry point."""

from __future__ import annotations

from dotenv import load_dotenv

from ..config import Settings
from .app import create_app


def main() -> int:
    """Run the password-protected phone service with Uvicorn."""
    import uvicorn

    load_dotenv()
    settings = Settings.from_env()
    web_settings = settings.web_settings()
    uvicorn.run(
        create_app(settings),
        host=web_settings.host,
        port=web_settings.port,
        proxy_headers=False,
    )
    return 0


__all__ = ["create_app", "main"]
