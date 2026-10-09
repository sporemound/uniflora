from __future__ import annotations

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from uniflora.storage.models import Base


class Database:
    def __init__(self, url: str, *, echo: bool = False) -> None:
        self.url = url
        self.engine: AsyncEngine = create_async_engine(url, echo=echo, pool_pre_ping=True)
        if url.startswith("sqlite+"):
            event.listen(self.engine.sync_engine, "connect", self._configure_sqlite)
        self.sessions = async_sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
        )

    async def create_schema_for_tests(self) -> None:
        """Tests only. Deployed startup uses Alembic migrations."""
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def drop_schema_for_tests(self) -> None:
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)

    async def dispose(self) -> None:
        await self.engine.dispose()

    async def integrity_check(self) -> tuple[bool, str]:
        try:
            async with self.engine.connect() as connection:
                if self.url.startswith("sqlite+"):
                    result = await connection.scalar(text("PRAGMA integrity_check"))
                    ok = str(result).casefold() == "ok"
                    return ok, str(result)
                result = await connection.scalar(text("SELECT 1"))
                return result == 1, "connection and query succeeded"
        except Exception as exc:
            return False, f"{type(exc).__name__}: integrity query failed"

    @staticmethod
    def _configure_sqlite(dbapi_connection: object, connection_record: object) -> None:
        del connection_record
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()
