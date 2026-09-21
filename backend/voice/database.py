"""
Voice module — database engine, session factory, init helper.

Kept deliberately separate from the main platform's `database.py`
(sync SQLAlchemy / students.db). The voice feature uses its own
async engine and its own SQLite file so the two data layers never
have to share a session or a Base.metadata.
"""

import os
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from voice.models import Base

DB_URL = os.getenv("VOICE_DATABASE_URL", "sqlite+aiosqlite:///./voice.db")

engine = create_async_engine(
    DB_URL,
    echo=False,
    connect_args={"check_same_thread": False} if DB_URL.startswith("sqlite") else {},
)

AsyncSessionFactory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncSession:
    async with AsyncSessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Voice DB tables created / verified.")
