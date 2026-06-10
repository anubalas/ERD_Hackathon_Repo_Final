import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from typing import AsyncGenerator

from src.db.models import Base

SQLITE_DB_PATH = os.getenv("SQLITE_DB_PATH", "telemetry.db")
DATABASE_URL = f"sqlite+aiosqlite:///{SQLITE_DB_PATH}"

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def migrate_db() -> None:
    """Add new columns to existing tables without data loss (idempotent)."""
    new_columns = [
        ("alerts", "severity",        "VARCHAR(32)"),
        ("alerts", "dismissed",       "BOOLEAN NOT NULL DEFAULT 0"),
        ("alerts", "acknowledged",    "BOOLEAN NOT NULL DEFAULT 0"),
        ("alerts", "acknowledged_at", "DATETIME"),
    ]
    async with engine.begin() as conn:
        for table, col, definition in new_columns:
            try:
                await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {definition}"))
            except Exception:
                pass  # column already exists


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
