"""ORM model for persisted QQ chat messages.

Schema design: .agile/arch/DATABASE-SCHEMA.md
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, String, Text, func
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
