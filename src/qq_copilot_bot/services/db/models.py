"""ORM models for persisted QQ chat messages and media.

Schema design: .agile/arch/DATABASE-SCHEMA.md
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from qq_copilot_bot.services.db import Base


class ChatMessage(Base):
    """A single QQ message (user or assistant) persisted to MySQL."""

    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    message_id: Mapped[str | None] = mapped_column(String(64), default=None)
    self_id: Mapped[int | None] = mapped_column(BigInteger, default=None)
    message_type: Mapped[str] = mapped_column(String(16), default="private")
    user_id: Mapped[int] = mapped_column(BigInteger)
    group_id: Mapped[int | None] = mapped_column(BigInteger, default=None)
    session_id: Mapped[str] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(16), default="user")
    sender_nickname: Mapped[str | None] = mapped_column(String(128), default=None)
    content: Mapped[str] = mapped_column(Text)
    raw_message: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
    )

    __table_args__ = (
        Index("idx_session_created", "session_id", "created_at"),
        Index("idx_user_created", "user_id", "created_at"),
        Index("idx_message_id", "message_id"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )


class LLMHealth(Base):
    """A single health-check result for the Copilot/LLM chat backend."""

    __tablename__ = "llm_health"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    model: Mapped[str] = mapped_column(String(128))
    endpoint: Mapped[str] = mapped_column(String(255))
    healthy: Mapped[bool] = mapped_column(Boolean, default=False)
    status_code: Mapped[int | None] = mapped_column(Integer, default=None)
    latency_ms: Mapped[int | None] = mapped_column(Integer, default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    checked_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
    )

    __table_args__ = (
        Index("idx_model_checked", "model", "checked_at"),
        Index("idx_healthy_checked", "healthy", "checked_at"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )


class MessageImage(Base):
    """An image attachment received in a QQ message, with optional local cache."""

    __tablename__ = "message_images"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # OneBot message containing this image; NULL when source is unknown
    message_id: Mapped[str | None] = mapped_column(String(64), default=None)
    # Stable file identifier / hash provided by OneBot (e.g. CQ:image,file=...)
    file_hash: Mapped[str] = mapped_column(String(128))
    # Sender context
    user_id: Mapped[int] = mapped_column(BigInteger)
    group_id: Mapped[int | None] = mapped_column(BigInteger, default=None)
    session_id: Mapped[str] = mapped_column(String(64))
    # Remote CDN URL (may expire); kept for re-download reference
    url: Mapped[str | None] = mapped_column(Text, default=None)
    # Path relative to the project data root, set after download; NULL = not downloaded
    local_path: Mapped[str | None] = mapped_column(String(512), default=None)
    # Image dimensions in pixels; NULL when unknown
    width: Mapped[int | None] = mapped_column(Integer, default=None)
    height: Mapped[int | None] = mapped_column(Integer, default=None)
    # File size in bytes; NULL when unknown
    file_size: Mapped[int | None] = mapped_column(Integer, default=None)
    # MIME type, e.g. "image/jpeg"
    mime_type: Mapped[str | None] = mapped_column(String(64), default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
    )

    __table_args__ = (
        Index("idx_img_session_created", "session_id", "created_at"),
        Index("idx_img_user_created", "user_id", "created_at"),
        Index("idx_img_file_hash", "file_hash"),
        Index("idx_img_message_id", "message_id"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )
