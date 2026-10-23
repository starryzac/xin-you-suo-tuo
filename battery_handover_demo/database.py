"""SQLAlchemy setup for the prototype."""

from __future__ import annotations

from collections.abc import Generator, Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from .config import settings


class Base(DeclarativeBase):
    """Declarative base shared by every persisted model."""


def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
    """Enable SQLite foreign-key enforcement for every DB-API connection."""

    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


def build_engine(database_url: str, *, echo: bool = False) -> Engine:
    """Create an engine with SQLite behavior suitable for UI and tests."""

    url = make_url(database_url)
    kwargs: dict[str, object] = {"echo": echo}

    if url.get_backend_name() == "sqlite":
        kwargs["connect_args"] = {"check_same_thread": False}
        if url.database in {None, "", ":memory:"}:
            # Keep a single in-memory database visible across sessions.
            kwargs["poolclass"] = StaticPool

    built_engine = create_engine(database_url, **kwargs)
    if built_engine.dialect.name == "sqlite":
        event.listen(built_engine, "connect", _enable_sqlite_foreign_keys)
    return built_engine


engine = build_engine(settings.database_url, echo=settings.database_echo)
SessionLocal = sessionmaker(
    bind=engine,
    class_=Session,
    autoflush=False,
    expire_on_commit=False,
)


def _ensure_sqlite_parent(bind: Engine) -> None:
    """Create only the configured SQLite database's immediate parent folder."""

    url = bind.url
    if url.get_backend_name() != "sqlite" or not url.database:
        return
    if url.database == ":memory:":
        return
    Path(url.database).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


def create_schema(bind: Engine | None = None) -> None:
    """Create all seven prototype tables on the selected engine."""

    selected_engine = bind or engine
    _ensure_sqlite_parent(selected_engine)

    # Import registers model metadata while avoiding a database/models cycle.
    from . import models as _models  # noqa: F401

    Base.metadata.create_all(selected_engine)


@contextmanager
def session_scope(
    session_factory: sessionmaker[Session] = SessionLocal,
) -> Iterator[Session]:
    """Provide a transactional session with rollback on failure."""

    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Generator[Session, None, None]:
    """Yield a session for callers that use dependency-style iteration."""

    with session_scope() as session:
        yield session
