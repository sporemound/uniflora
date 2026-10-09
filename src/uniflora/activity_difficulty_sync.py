from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import secrets
import time
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from uniflora.runtime import Environment
from uniflora.storage.repository import GameRepository, SessionRef

logger = logging.getLogger(__name__)
_PATH = "/api/hypha/difficulty"


class ActivityDifficultySync:
    """Copy saved private Discord preferences to the authenticated Activity view."""

    def __init__(
        self,
        base_url: str,
        secret: str,
        repository: GameRepository,
        refs: dict[Environment, SessionRef],
    ) -> None:
        parsed = urlsplit(base_url)
        local_http = parsed.scheme == "http" and parsed.hostname in {
            "localhost", "127.0.0.1", "::1"
        }
        if (parsed.scheme != "https" and not local_http) or not parsed.netloc or not secret:
            raise ValueError("Activity difficulty sync needs an HTTPS origin and secret")
        self._origin = f"{parsed.scheme}://{parsed.netloc}"
        self._secret = secret.encode("utf-8")
        self._repository = repository
        self._refs = refs

    def _post(self, payload: dict[str, object]) -> None:
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        timestamp = str(int(time.time()))
        nonce = secrets.token_hex(16)
        digest = hashlib.sha256(body).hexdigest()
        canonical = "\n".join(("POST", _PATH, timestamp, nonce, digest))
        signature = hmac.new(self._secret, canonical.encode(), hashlib.sha256).hexdigest()
        request = Request(
            self._origin + _PATH,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "User-Agent": "TheMissingInterior-HyphaRelay/1.0",
                "X-Hypha-Timestamp": timestamp,
                "X-Hypha-Nonce": nonce,
                "X-Hypha-Content-SHA256": digest,
                "X-Hypha-Signature": f"v1={signature}",
            },
        )
        with urlopen(request, timeout=15) as response:  # noqa: S310
            if response.status != 200:
                raise RuntimeError(f"Activity difficulty sync returned {response.status}")

    async def sync_once(self) -> None:
        for environment, ref in self._refs.items():
            rows = await self._repository.difficulty_preferences(ref)
            for offset in range(0, len(rows), 100):
                choices = [
                    {"discordUserId": str(user_id), "level": level, "revision": revision}
                    for user_id, level, revision in rows[offset : offset + 100]
                ]
                await asyncio.to_thread(
                    self._post, {"environment": environment.value, "choices": choices}
                )

    async def run(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            try:
                await self.sync_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("Activity difficulty sync failed; retrying", exc_info=True)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=30)
            except TimeoutError:
                pass
