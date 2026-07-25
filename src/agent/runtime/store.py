"""Small SQLite store for web-session and confirmation metadata."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4


@dataclass(frozen=True)
class ConfirmationRecord:
    """Durable metadata for a confirmation that may be shown to the phone UI."""

    id: str
    session_id: str
    owner_id: str
    state: str
    created_at: str
    expires_at: str
    tool_names: tuple[str, ...]
    description: str


@dataclass(frozen=True)
class ConversationRecord:
    """One browser-owned conversation available in the history view."""

    session_id: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ChatMessageRecord:
    """A browser-visible message retained for one conversation."""

    id: str
    session_id: str
    owner_id: str
    role: str
    content: str
    status: str | None
    created_at: str


class ServiceStore:
    """Persist non-secret service state without duplicating Baby Buddy records."""

    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS web_sessions (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS confirmations (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    tool_names_json TEXT NOT NULL,
                    description TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES web_sessions(id)
                );
                CREATE INDEX IF NOT EXISTS confirmations_owner_state
                    ON confirmations(owner_id, state);
                CREATE TABLE IF NOT EXISTS turn_audit (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    text_sha256 TEXT,
                    text_length INTEGER,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES web_sessions(id)
                );
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    status TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES web_sessions(id)
                );
                CREATE INDEX IF NOT EXISTS chat_messages_session_created
                    ON chat_messages(session_id, created_at, id);
                """,
            )

    def expire_pending_confirmations(self) -> int:
        """Invalidate pending work after startup; live continuations are gone."""
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE confirmations SET state = 'expired' WHERE state = 'pending'",
            )
            return cursor.rowcount

    def ensure_session(self, session_id: str, owner_id: str) -> None:
        now = _now()
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT owner_id FROM web_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            if existing is None:
                connection.execute(
                    "INSERT INTO web_sessions(id, owner_id, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?)",
                    (session_id, owner_id, now, now),
                )
            elif existing["owner_id"] != owner_id:
                raise PermissionError("session belongs to another browser session")
            else:
                connection.execute(
                    "UPDATE web_sessions SET updated_at = ? WHERE id = ?",
                    (now, session_id),
                )

    def list_conversations(self, *, owner_id: str) -> list[ConversationRecord]:
        """Return the browser owner's conversations in most-recent-first order."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, created_at, updated_at FROM web_sessions "
                "WHERE owner_id = ? AND EXISTS ("
                "SELECT 1 FROM chat_messages WHERE session_id = web_sessions.id"
                ") ORDER BY updated_at DESC, id DESC",
                (owner_id,),
            ).fetchall()
        return [
            ConversationRecord(
                session_id=row["id"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    def list_chat_messages(
        self,
        *,
        session_id: str,
        owner_id: str,
    ) -> list[ChatMessageRecord] | None:
        """Return ordered messages when the conversation belongs to this owner."""
        with self._connect() as connection:
            session = connection.execute(
                "SELECT 1 FROM web_sessions WHERE id = ? AND owner_id = ?",
                (session_id, owner_id),
            ).fetchone()
            if session is None:
                return None
            rows = connection.execute(
                "SELECT * FROM chat_messages WHERE session_id = ? AND owner_id = ? "
                "ORDER BY created_at, id",
                (session_id, owner_id),
            ).fetchall()
        return [_chat_message_from_row(row) for row in rows]

    def record_chat_message(
        self,
        *,
        session_id: str,
        owner_id: str,
        role: str,
        content: str,
        status: str | None = None,
    ) -> ChatMessageRecord:
        """Persist one browser-visible message after its session ownership is known."""
        record = ChatMessageRecord(
            id=str(uuid4()),
            session_id=session_id,
            owner_id=owner_id,
            role=role,
            content=content,
            status=status,
            created_at=_now(),
        )
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO chat_messages("
                "id, session_id, owner_id, role, content, status, created_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    record.id,
                    record.session_id,
                    record.owner_id,
                    record.role,
                    record.content,
                    record.status,
                    record.created_at,
                ),
            )
            connection.execute(
                "UPDATE web_sessions SET updated_at = ? WHERE id = ?",
                (record.created_at, session_id),
            )
        return record

    def create_confirmation(
        self,
        *,
        session_id: str,
        owner_id: str,
        tool_names: tuple[str, ...],
        description: str,
        ttl_seconds: int,
    ) -> ConfirmationRecord:
        created = datetime.now(timezone.utc)
        expires = created + timedelta(seconds=ttl_seconds)
        record = ConfirmationRecord(
            id=str(uuid4()),
            session_id=session_id,
            owner_id=owner_id,
            state="pending",
            created_at=created.isoformat(),
            expires_at=expires.isoformat(),
            tool_names=tool_names,
            description=description,
        )
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO confirmations("
                "id, session_id, owner_id, state, created_at, expires_at, "
                "tool_names_json, description"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record.id,
                    record.session_id,
                    record.owner_id,
                    record.state,
                    record.created_at,
                    record.expires_at,
                    json.dumps(record.tool_names, ensure_ascii=False),
                    record.description,
                ),
            )
        return record

    def get_confirmation(self, confirmation_id: str) -> ConfirmationRecord | None:
        self._expire_due()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM confirmations WHERE id = ?",
                (confirmation_id,),
            ).fetchone()
        return _confirmation_from_row(row) if row else None

    def expire_confirmation(self, confirmation_id: str) -> ConfirmationRecord | None:
        """Expire a pending confirmation without ever approving the tool call."""
        with self._connect() as connection:
            connection.execute(
                "UPDATE confirmations SET state = 'expired' "
                "WHERE id = ? AND state = 'pending'",
                (confirmation_id,),
            )
        return self.get_confirmation(confirmation_id)

    def resolve_confirmation(
        self,
        confirmation_id: str,
        *,
        owner_id: str,
        approved: bool,
    ) -> ConfirmationRecord | None:
        """Move one pending confirmation exactly once and return its latest state."""
        self._expire_due()
        target_state = "allowed" if approved else "denied"
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM confirmations WHERE id = ?",
                (confirmation_id,),
            ).fetchone()
            if row is None or row["owner_id"] != owner_id:
                connection.execute("COMMIT")
                return None
            if row["state"] == "pending":
                connection.execute(
                    "UPDATE confirmations SET state = ? WHERE id = ?",
                    (target_state, confirmation_id),
                )
                row = connection.execute(
                    "SELECT * FROM confirmations WHERE id = ?",
                    (confirmation_id,),
                ).fetchone()
            connection.execute("COMMIT")
        return _confirmation_from_row(row)

    def record_turn(
        self,
        *,
        session_id: str,
        owner_id: str,
        status: str,
        text_sha256: str | None = None,
        text_length: int | None = None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO turn_audit("
                "id, session_id, owner_id, status, text_sha256, text_length, created_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    str(uuid4()),
                    session_id,
                    owner_id,
                    status,
                    text_sha256,
                    text_length,
                    _now(),
                ),
            )

    def _expire_due(self) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE confirmations SET state = 'expired' "
                "WHERE state = 'pending' AND expires_at <= ?",
                (_now(),),
            )


def _confirmation_from_row(row: sqlite3.Row) -> ConfirmationRecord:
    return ConfirmationRecord(
        id=row["id"],
        session_id=row["session_id"],
        owner_id=row["owner_id"],
        state=row["state"],
        created_at=row["created_at"],
        expires_at=row["expires_at"],
        tool_names=tuple(json.loads(row["tool_names_json"])),
        description=row["description"],
    )


def _chat_message_from_row(row: sqlite3.Row) -> ChatMessageRecord:
    return ChatMessageRecord(
        id=row["id"],
        session_id=row["session_id"],
        owner_id=row["owner_id"],
        role=row["role"],
        content=row["content"],
        status=row["status"],
        created_at=row["created_at"],
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
