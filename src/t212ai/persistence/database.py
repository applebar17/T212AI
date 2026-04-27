"""Minimal SQLAlchemy runtime helpers."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def build_engine(database_url: str) -> Engine:
    resolved_url = str(database_url or "").strip()
    if not resolved_url:
        raise RuntimeError("DATABASE_URL is required.")
    _ensure_sqlite_parent_directory(resolved_url)
    connect_args: dict[str, object] = {}
    if resolved_url.startswith("sqlite:///"):
        connect_args["check_same_thread"] = False
    return create_engine(resolved_url, future=True, connect_args=connect_args)


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def ensure_schema(engine: Engine) -> None:
    Base.metadata.create_all(engine)


def _ensure_sqlite_parent_directory(database_url: str) -> None:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        return
    local_path = database_url.removeprefix(prefix).strip()
    if not local_path or local_path == ":memory:":
        return
    path = Path(local_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
