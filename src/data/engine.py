"""Abstracción del motor de base de datos (SQLite por defecto; PostgreSQL/MySQL vía DATABASE_URL)."""
from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from src import config


class Base(DeclarativeBase):
    pass


def resolve_db_url(url: str | None = None) -> str:
    raw = url or config.DATABASE_URL
    if raw.startswith("sqlite:///") and raw != "sqlite:///:memory:":
        rel_path = raw.removeprefix("sqlite:///")
        path = Path(rel_path)
        if not path.is_absolute():
            path = config.ROOT / path
        path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{path.as_posix()}"
    return raw


def build_engine(url: str | None = None) -> Engine:
    resolved = resolve_db_url(url)
    connect_args = {"check_same_thread": False} if resolved.startswith("sqlite") else {}
    return create_engine(resolved, connect_args=connect_args, future=True)


def build_session_factory(engine: Engine):
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
