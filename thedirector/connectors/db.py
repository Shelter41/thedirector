import logging
from contextlib import asynccontextmanager

from psycopg_pool import AsyncConnectionPool
from psycopg.rows import dict_row

from ..config import settings

logger = logging.getLogger("thedirector.db")

_pool: AsyncConnectionPool | None = None


async def init_pool() -> AsyncConnectionPool:
    global _pool
    _pool = AsyncConnectionPool(
        conninfo=settings.database_url,
        min_size=2,
        max_size=10,
        kwargs={"row_factory": dict_row},
    )
    await _pool.open()
    logger.info("Postgres pool opened")
    return _pool


async def close_pool():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("Postgres pool closed")


def get_pool() -> AsyncConnectionPool:
    if not _pool:
        raise RuntimeError("Database pool not initialized")
    return _pool


@asynccontextmanager
async def get_conn():
    if not _pool:
        raise RuntimeError("Database pool not initialized")
    async with _pool.connection() as conn:
        yield conn


async def fetch_all(query: str, params: tuple = ()) -> list[dict]:
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(query, params)
            return await cur.fetchall()


async def fetch_one(query: str, params: tuple = ()) -> dict | None:
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(query, params)
            return await cur.fetchone()


async def execute(query: str, params: tuple = ()):
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(query, params)
