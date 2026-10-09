from __future__ import annotations

import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url


def _upgrade(database_url: str) -> None:
    candidates = (Path.cwd(), Path(__file__).resolve().parents[3])
    root = next((path for path in candidates if (path / "alembic.ini").exists()), None)
    if root is None:
        raise RuntimeError("alembic.ini could not be located from the working directory")
    parsed = make_url(database_url)
    if parsed.get_backend_name() == "sqlite" and parsed.database not in {None, ":memory:"}:
        Path(parsed.database).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
    config = Config(str(root / "alembic.ini"))
    config.attributes["configure_logger"] = False
    config.set_main_option("script_location", str(root / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")


async def run_startup_migrations(database_url: str) -> None:
    await asyncio.to_thread(_upgrade, database_url)
