"""Database engine, session factory, and declarative base for MySQL storage."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from settings import mysql_settings


class Base(DeclarativeBase):
    """Declarative base shared by all ORM models."""


engine = create_engine(
    mysql_settings.url,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)
