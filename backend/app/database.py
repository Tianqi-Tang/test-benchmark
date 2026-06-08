from __future__ import annotations

import os
from functools import lru_cache
from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def _database_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL is required for benchmark APIs.")
    if not (url.startswith("postgresql://") or url.startswith("postgresql+psycopg://")):
        raise RuntimeError("DATABASE_URL must point to PostgreSQL.")
    return url


@lru_cache(maxsize=1)
def get_engine():
    return create_engine(_database_url(), pool_pre_ping=True)


@lru_cache(maxsize=1)
def get_sessionmaker():
    return sessionmaker(bind=get_engine(), autoflush=False, autocommit=False)


def init_db() -> None:
    import app.models  # noqa: F401

    Base.metadata.create_all(bind=get_engine())
    _apply_lightweight_migrations()


def _apply_lightweight_migrations() -> None:
    statements = [
        "ALTER TABLE model_configs ADD COLUMN IF NOT EXISTS last_test_status VARCHAR(40)",
        "ALTER TABLE model_configs ADD COLUMN IF NOT EXISTS last_test_latency_ms INTEGER",
        "ALTER TABLE model_configs ADD COLUMN IF NOT EXISTS last_test_error TEXT",
        "ALTER TABLE model_configs ADD COLUMN IF NOT EXISTS last_tested_at TIMESTAMP WITH TIME ZONE",
    ]
    with get_engine().begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def get_db() -> Generator[Session, None, None]:
    db = get_sessionmaker()()
    try:
        yield db
    finally:
        db.close()
