"""
SQLite cache for generated assembly instructions.
Instructions are expensive to generate (Claude API call) so we cache
by (part_id, version) and invalidate when the version changes.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from sqlalchemy import Column, Float, Integer, String, Text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

_DB_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./market.db")
_CACHE_TTL = int(os.getenv("ASSEMBLY_CACHE_TTL_HOURS", "24")) * 3600

_engine = create_async_engine(_DB_URL, echo=False)
_Session = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class AssemblyCache(Base):
    __tablename__ = "assembly_cache"
    id = Column(String, primary_key=True)           # f"{part_id}:{version}"
    part_id = Column(String, nullable=False)
    version = Column(Integer, nullable=False)
    instructions_json = Column(Text, nullable=False)
    generated_at = Column(Float, nullable=False)    # Unix timestamp


async def init_cache() -> None:
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_cached(part_id: str, version: int) -> dict | None:
    """Return cached instructions if fresh, else None."""
    from sqlalchemy import select
    async with _Session() as db:
        row = (await db.execute(
            select(AssemblyCache).where(AssemblyCache.id == f"{part_id}:{version}")
        )).scalar_one_or_none()

        if not row:
            return None
        if time.time() - row.generated_at > _CACHE_TTL:
            return None
        return json.loads(row.instructions_json)


async def set_cached(part_id: str, version: int, instructions: dict) -> None:
    """Cache assembly instructions."""
    from sqlalchemy.dialects.sqlite import insert
    async with _Session() as db:
        stmt = insert(AssemblyCache).values(
            id=f"{part_id}:{version}",
            part_id=part_id,
            version=version,
            instructions_json=json.dumps(instructions),
            generated_at=time.time(),
        ).on_conflict_do_update(
            index_elements=["id"],
            set_={"instructions_json": json.dumps(instructions), "generated_at": time.time()},
        )
        await db.execute(stmt)
        await db.commit()
