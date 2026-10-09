from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from uniflora.storage.database import Database
from uniflora.storage.repository import GameRepository, SessionRef

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class BackupStatus:
    successful: bool
    path: str | None
    detail: str


class BackupService:
    def __init__(
        self,
        database: Database,
        repository: GameRepository,
        directory: Path,
        *,
        enabled: bool,
        interval_hours: int,
        refs: tuple[SessionRef, ...] = (),
    ) -> None:
        self.database = database
        self.repository = repository
        self.directory = directory
        self.enabled = enabled
        self.interval = timedelta(hours=interval_hours)
        self.refs = refs
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if not self.enabled:
            return
        self._task = asyncio.create_task(self._run(), name="daily-database-backup")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            await self._task

    async def is_due(self) -> bool:
        latest = await self.repository.latest_backup()
        if latest is None or latest["status"] != "success":
            return True
        created_at = datetime.fromisoformat(str(latest["created_at"]))
        return datetime.now(UTC) - created_at >= self.interval

    async def run_once(self) -> BackupStatus:
        if self.refs:
            feature_enabled = False
            for ref in self.refs:
                control = await self.repository.runtime_control(ref)
                if control["feature_flags"].get("daily_backup", True):
                    feature_enabled = True
                    break
            if not feature_enabled:
                return BackupStatus(False, None, "daily backup feature is disabled")
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        try:
            await asyncio.to_thread(self.directory.mkdir, parents=True, exist_ok=True)
            if self.database.url.startswith("sqlite+aiosqlite:///"):
                source = Path(self.database.url.removeprefix("sqlite+aiosqlite:///"))
                destination = self.directory / f"interior-{timestamp}.sqlite3"
                await asyncio.to_thread(self._sqlite_backup, source, destination)
            elif self.database.url.startswith("postgresql+asyncpg://"):
                destination = self.directory / f"interior-{timestamp}.dump"
                await self._postgres_backup(destination)
            else:
                raise RuntimeError("unsupported database backend")
            await self.repository.record_backup(
                status="success", path=str(destination), detail="daily backup completed"
            )
            logger.info(
                "database backup completed",
                extra={"environment": "system", "path": str(destination)},
            )
            return BackupStatus(True, str(destination), "daily backup completed")
        except Exception as exc:
            detail = f"{type(exc).__name__}: backup failed"
            try:
                await self.repository.record_backup(status="failed", path=None, detail=detail)
            except Exception:
                logger.exception(
                    "database backup status write failed", extra={"environment": "system"}
                )
            logger.exception("database backup failed", extra={"environment": "system"})
            return BackupStatus(False, None, detail)

    async def _run(self) -> None:
        try:
            if await self.is_due():
                await self.run_once()
        except Exception:
            logger.exception("initial backup scheduling failed", extra={"environment": "system"})
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=3600)
            except TimeoutError:
                try:
                    if await self.is_due():
                        await self.run_once()
                except Exception:
                    logger.exception(
                        "backup scheduling iteration failed", extra={"environment": "system"}
                    )

    @staticmethod
    def _sqlite_backup(source: Path, destination: Path) -> None:
        if not source.exists():
            raise FileNotFoundError("SQLite source does not exist")
        with sqlite3.connect(source) as source_db, sqlite3.connect(destination) as backup_db:
            source_db.backup(backup_db)

    async def _postgres_backup(self, destination: Path) -> None:
        url = self.database.url.replace("postgresql+asyncpg://", "postgresql://", 1)
        process = await asyncio.create_subprocess_exec(
            "pg_dump",
            "--format=custom",
            "--no-owner",
            f"--file={destination}",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            env={**os.environ, "PGDATABASE": url},
        )
        try:
            return_code = await asyncio.wait_for(process.wait(), timeout=900)
        except TimeoutError:
            process.kill()
            await process.wait()
            raise RuntimeError("pg_dump timed out") from None
        if return_code != 0:
            raise RuntimeError("pg_dump failed")
