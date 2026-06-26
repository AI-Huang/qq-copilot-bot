"""Service layer for persisting and reading QQ chat messages in MySQL."""

from __future__ import annotations

import re

from nonebot.log import logger
from sqlalchemy import create_engine, select, text

from qq_copilot_bot.services.db import Base, SessionLocal, engine
from qq_copilot_bot.services.db.models import ChatMessage, LLMHealth, MessageImage

# Valid MySQL identifier for the database name (defensive guard before DDL).
_VALID_DB_NAME = re.compile(r"^[A-Za-z0-9_]+$")


def _ensure_database() -> None:
    """Create the target database if it does not yet exist."""
    db_name = engine.url.database
    if not db_name:
        return
    if not _VALID_DB_NAME.match(db_name):
        msg = f"Refusing to create database with unsafe name: {db_name!r}"
        raise ValueError(msg)
    # Connect to the server without selecting a database.
    server_engine = create_engine(engine.url.set(database=""))
    try:
        with server_engine.connect() as conn:
            conn.execute(
                text(
                    f"CREATE DATABASE IF NOT EXISTS `{db_name}` "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci",
                ),
            )
            conn.commit()
    finally:
        server_engine.dispose()


def init_db() -> None:
    """Ensure the database and chat message table exist."""
    _ensure_database()
    Base.metadata.create_all(bind=engine)


def save_message(
    *,
    user_id: int,
    session_id: str,
    role: str,
    content: str,
    message_type: str = "private",
    message_id: str | None = None,
    self_id: int | None = None,
    group_id: int | None = None,
    sender_nickname: str | None = None,
    raw_message: str | None = None,
) -> None:
    """Persist a single chat message.

    Failures are logged and swallowed so the bot's event flow is never broken.
    """
    try:
        with SessionLocal() as session:
            session.add(
                ChatMessage(
                    user_id=user_id,
                    session_id=session_id,
                    role=role,
                    content=content,
                    message_type=message_type,
                    message_id=message_id,
                    self_id=self_id,
                    group_id=group_id,
                    sender_nickname=sender_nickname,
                    raw_message=raw_message,
                ),
            )
            session.commit()
    except Exception:
        logger.exception("Failed to save chat message to MySQL")


def load_recent_history(session_id: str, max_turns: int = 10) -> list[dict]:
    """Return up to ``2 * max_turns`` recent messages for a session, oldest first."""
    try:
        with SessionLocal() as session:
            rows = session.execute(
                select(ChatMessage.role, ChatMessage.content)
                .where(ChatMessage.session_id == session_id)
                .order_by(ChatMessage.id.desc())
                .limit(2 * max_turns),
            ).all()
        return [{"role": role, "content": content} for role, content in reversed(rows)]
    except Exception:
        logger.exception("Failed to load chat history from MySQL")
        return []


def save_image(
    *,
    file_hash: str,
    user_id: int,
    session_id: str,
    url: str | None = None,
    message_id: str | None = None,
    group_id: int | None = None,
    local_path: str | None = None,
    width: int | None = None,
    height: int | None = None,
    file_size: int | None = None,
    mime_type: str | None = None,
) -> None:
    """Persist an image attachment record.

    Failures are logged and swallowed so the bot's event flow is never broken.
    """
    try:
        with SessionLocal() as session:
            session.add(
                MessageImage(
                    file_hash=file_hash,
                    user_id=user_id,
                    session_id=session_id,
                    url=url,
                    message_id=message_id,
                    group_id=group_id,
                    local_path=local_path,
                    width=width,
                    height=height,
                    file_size=file_size,
                    mime_type=mime_type,
                ),
            )
            session.commit()
    except Exception:
        logger.exception("Failed to save image record to MySQL")


def save_llm_health(
    endpoint: str,
    healthy: bool,
    status_code: int | None = None,
    latency_ms: int | None = None,
    error: str | None = None,
) -> None:
    """Persist a single LLM health-check result.

    Failures are logged and swallowed so health probing never breaks the caller.
    """
    try:
        with SessionLocal() as session:
            session.add(
                LLMHealth(
                    model=model,
                    endpoint=endpoint,
                    healthy=healthy,
                    status_code=status_code,
                    latency_ms=latency_ms,
                    error=error,
                ),
            )
            session.commit()
    except Exception:
        logger.exception("Failed to save LLM health record to MySQL")
