from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text

from uniflora.storage.database import Database
from uniflora.storage.migrations import run_startup_migrations


@pytest.mark.asyncio
async def test_alembic_startup_migration_is_idempotent(tmp_path: Path) -> None:
    url = f"sqlite+aiosqlite:///{(tmp_path / 'migration.db').as_posix()}"
    await run_startup_migrations(url)
    await run_startup_migrations(url)
    database = Database(url)
    async with database.engine.connect() as connection:
        revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
        control_table = await connection.scalar(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='runtime_controls'")
        )
        removed_context_table = await connection.scalar(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='gpt_context_records'")
        )
    assert revision == "0004_difficulty"
    assert control_table == "runtime_controls"
    assert removed_context_table is None
    await database.dispose()
