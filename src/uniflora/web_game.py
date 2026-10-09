"""Small authenticated HTTP boundary for the authoritative v2 game engine.

The Cloudflare Worker authenticates players and signs each internal request.
This service accepts only opaque web player IDs supplied by that Worker.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import time
from contextlib import suppress
from pathlib import Path

from aiohttp import web

from uniflora.activity_chat_relay import ActivityChatRelay
from uniflora.content.v2 import load_missing_interior_static_pack
from uniflora.gemini_chat import GeminiGameChatProvider, GeminiVoiceReplyService
from uniflora.v2_activity_projection import V2ActivityPublisher
from uniflora.v2_test_runtime import V2TestRuntime
from uniflora.voice_service import (
    EspeakVoiceService,
    VoiceSynthesisBusyError,
    VoiceSynthesisError,
    VoiceUnavailableError,
    model_voice_filename,
)

logger = logging.getLogger(__name__)

_PLAYER_ID = re.compile(r"web:participant_[a-f0-9]{24}\Z")
_NONCE = re.compile(r"[a-f0-9]{32}\Z")
_HEX = re.compile(r"[a-f0-9]{64}\Z")
_MAX_BODY_BYTES = 4096
_MAX_SKEW_SECONDS = 60
_MAX_NONCES = 10_000
_MAX_VOICE_TEXT_CHARS = 1000
_MAX_VOICE_BYTES = 1_500_000
_PUBLISH_TIMEOUT_SECONDS = 10.0
_PUBLISH_RETRY_INITIAL_SECONDS = 1.0
_PUBLISH_RETRY_MAX_SECONDS = 60.0


class WebGameApi:
    def __init__(
        self,
        runtime: V2TestRuntime,
        secret: str,
        *,
        publisher: V2ActivityPublisher | None = None,
        voice: EspeakVoiceService | None = None,
    ) -> None:
        if len(secret) < 32:
            raise ValueError("GAME_API_SECRET must contain at least 32 characters")
        self.runtime = runtime
        self.secret = secret.encode("utf-8")
        self.publisher = publisher
        self.voice = voice
        self.seen_nonces: dict[str, int] = {}
        self.nonce_lock = asyncio.Lock()
        self.publish_lock = asyncio.Lock()
        self._needs_publish = False
        self._publish_retry_event = asyncio.Event()
        self._publish_retry_task: asyncio.Task[None] | None = None
        self._closing = False

    async def _authenticate(
        self, request: web.Request, *, require_player: bool = True,
    ) -> dict[str, object]:
        if request.content_length is not None and request.content_length > _MAX_BODY_BYTES:
            raise web.HTTPRequestEntityTooLarge(
                max_size=_MAX_BODY_BYTES, actual_size=request.content_length
            )
        body = await request.read()
        if len(body) > _MAX_BODY_BYTES:
            raise web.HTTPRequestEntityTooLarge(max_size=_MAX_BODY_BYTES, actual_size=len(body))
        timestamp_text = request.headers.get("X-Game-Timestamp", "")
        nonce = request.headers.get("X-Game-Nonce", "")
        declared_hash = request.headers.get("X-Game-Content-SHA256", "")
        signature = request.headers.get("X-Game-Signature", "")
        if (
            not timestamp_text.isascii()
            or not timestamp_text.isdigit()
            or not _NONCE.fullmatch(nonce)
            or not _HEX.fullmatch(declared_hash)
            or not signature.startswith("v1=")
            or not _HEX.fullmatch(signature[3:])
        ):
            raise web.HTTPUnauthorized(text="Invalid game request signature")
        timestamp = int(timestamp_text)
        now = int(time.time())
        if abs(now - timestamp) > _MAX_SKEW_SECONDS:
            raise web.HTTPUnauthorized(text="Stale game request")
        actual_hash = hashlib.sha256(body).hexdigest()
        if not hmac.compare_digest(actual_hash, declared_hash):
            raise web.HTTPUnauthorized(text="Game request body mismatch")
        canonical = "\n".join((request.method, request.path, timestamp_text, nonce, actual_hash))
        expected = hmac.new(self.secret, canonical.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature[3:]):
            raise web.HTTPUnauthorized(text="Invalid game request signature")
        async with self.nonce_lock:
            self.seen_nonces = {
                key: expiry for key, expiry in self.seen_nonces.items() if expiry > now
            }
            if nonce in self.seen_nonces:
                raise web.HTTPConflict(text="Game request was already used")
            if len(self.seen_nonces) >= _MAX_NONCES:
                raise web.HTTPServiceUnavailable(text="Game request cache is full")
            self.seen_nonces[nonce] = now + _MAX_SKEW_SECONDS
        try:
            value = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise web.HTTPBadRequest(text="Game request must be JSON") from exc
        if not isinstance(value, dict):
            raise web.HTTPBadRequest(text="Game request must be an object")
        if value.get("environment") != "live":
            raise web.HTTPForbidden(text="Only the live website campaign is available")
        if require_player:
            player_id = value.get("playerId")
            if not isinstance(player_id, str) or not _PLAYER_ID.fullmatch(player_id):
                raise web.HTTPBadRequest(text="Invalid web player identity")
        return value

    async def synthesize_voice(self, request: web.Request) -> web.Response:
        """Serve the existing eSpeak/FFmpeg voice to the signed website Worker."""

        value = await self._authenticate(request, require_player=False)
        if self.voice is None or not self.voice.enabled:
            raise web.HTTPServiceUnavailable(text="Hypha voice is not configured")
        text = value.get("text")
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= _MAX_VOICE_TEXT_CHARS:
            raise web.HTTPBadRequest(text="Voice text must contain 1 to 1000 characters")
        title = value.get("filenameTitle")
        if title is not None and not isinstance(title, str):
            raise web.HTTPBadRequest(text="Voice filename title must be text")
        try:
            clip = await self.voice.synthesize(text)
        except VoiceSynthesisBusyError as exc:
            raise web.HTTPTooManyRequests(text="Hypha voice is busy") from exc
        except VoiceUnavailableError as exc:
            raise web.HTTPServiceUnavailable(text="Hypha voice is unavailable") from exc
        except VoiceSynthesisError as exc:
            raise web.HTTPBadGateway(text="Hypha voice could not be rendered") from exc
        if not clip.audio.startswith(b"OggS") or len(clip.audio) > _MAX_VOICE_BYTES:
            raise web.HTTPBadGateway(text="Hypha voice returned invalid OGG audio")
        filename = model_voice_filename(title) if isinstance(title, str) else None
        return web.Response(
            body=clip.audio,
            content_type="audio/ogg",
            headers={
                "Cache-Control": "private, no-store",
                "Content-Disposition": f'inline; filename="{filename or clip.filename}"',
                "X-Content-Type-Options": "nosniff",
            },
        )

    def _wake_publish_retry(self) -> None:
        if self._closing:
            return
        if self._publish_retry_task is None or self._publish_retry_task.done():
            self._publish_retry_task = asyncio.create_task(
                self._retry_publication(), name="web-game-publication-retry",
            )
        self._publish_retry_event.set()

    async def _attempt_publish(self, *, schedule_retry: bool) -> bool:
        if self.publisher is None or self._closing:
            return False
        # Serialize active attempts and load the newest committed session for
        # each retry, instead of replaying a stale snapshot captured at failure.
        async with self.publish_lock:
            try:
                session = await self.runtime.session()
                await asyncio.wait_for(
                    self.publisher.publish(self.runtime.pack, session),
                    timeout=_PUBLISH_TIMEOUT_SECONDS,
                )
            except Exception:
                self._needs_publish = True
                logger.warning("public web game projection is stale", exc_info=True)
                if schedule_retry:
                    self._wake_publish_retry()
                return False
            self._needs_publish = False
            return True

    async def _publish(self) -> bool:
        return await self._attempt_publish(schedule_retry=True)

    async def _retry_publication(self) -> None:
        try:
            while not self._closing:
                await self._publish_retry_event.wait()
                self._publish_retry_event.clear()
                delay = _PUBLISH_RETRY_INITIAL_SECONDS
                while self._needs_publish and not self._closing:
                    await asyncio.sleep(delay)
                    if not self._needs_publish or self._closing:
                        break
                    try:
                        await self._attempt_publish(schedule_retry=False)
                    except Exception:
                        # A transient runtime/read failure must not strand an
                        # already committed action until another player arrives.
                        logger.warning("public web game publication retry failed", exc_info=True)
                    if self._needs_publish:
                        delay = min(delay * 2, _PUBLISH_RETRY_MAX_SECONDS)
        except asyncio.CancelledError:
            raise

    async def close(self) -> None:
        self._closing = True
        if self._publish_retry_task is not None:
            self._publish_retry_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._publish_retry_task

    async def status(self, request: web.Request) -> web.Response:
        value = await self._authenticate(request)
        player_id = str(value["playerId"])
        response = await self.runtime.public_status(player_id=player_id)
        session = await self.runtime.session()
        player = session.state.get_player(player_id)
        suggestions = await self.runtime.available_public_commands(player_id=player_id)
        published = await self._publish()
        return web.json_response({
            "accepted": response.accepted,
            "code": response.code,
            "summary": response.summary,
            "details": response.details,
            "sequence": response.sequence,
            "projectionCurrent": published,
            "suggestions": [
                {"command": command, "label": label}
                for command, label in suggestions
            ],
            "player": {
                "roleId": player.active_role_id if player else None,
                "positionId": session.state.current_position_id,
                "locationId": player.current_location_id if player else None,
            },
        })

    async def command(self, request: web.Request) -> web.Response:
        value = await self._authenticate(request)
        text = value.get("text")
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 1000:
            raise web.HTTPBadRequest(text="Command must contain 1 to 1000 characters")
        response = await self.runtime.execute_public(player_id=str(value["playerId"]), text=text)
        session = await self.runtime.session()
        player = session.state.get_player(str(value["playerId"]))
        suggestions = await self.runtime.available_public_commands(
            player_id=str(value["playerId"])
        )
        published = await self._publish() if response.accepted else True
        return web.json_response({
            "accepted": response.accepted,
            "code": response.code,
            "summary": response.summary,
            "details": response.details,
            "sequence": response.sequence,
            "projectionCurrent": published,
            "suggestions": [
                {"command": command, "label": label}
                for command, label in suggestions
            ],
            "player": {
                "roleId": player.active_role_id if player else None,
                "positionId": session.state.current_position_id,
                "locationId": player.current_location_id if player else None,
            },
        })


def create_app(
    api: WebGameApi,
    *,
    chat_relay: ActivityChatRelay | None = None,
    chat_reply: GeminiVoiceReplyService | None = None,
) -> web.Application:
    @web.middleware
    async def json_errors(request: web.Request, handler):
        try:
            return await handler(request)
        except web.HTTPException as exc:
            return web.json_response(
                {"error": exc.reason, "message": exc.text},
                status=exc.status,
            )
        except Exception:
            logger.exception("web game request failed", extra={"environment": "live"})
            return web.json_response(
                {"error": "internal_error", "message": "The game request could not be completed."},
                status=500,
            )

    app = web.Application(client_max_size=_MAX_BODY_BYTES, middlewares=[json_errors])
    app.router.add_post("/internal/game/status", api.status)
    app.router.add_post("/internal/game/command", api.command)
    app.router.add_post("/internal/voice/synthesize", api.synthesize_voice)

    async def health(_: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})

    async def ready(_: web.Request) -> web.Response:
        return web.json_response({"ready": True})

    app.router.add_get("/healthz", health)
    app.router.add_get("/readyz", ready)

    async def publish_on_start(_: web.Application) -> None:
        if api.publisher is not None:
            # Republish a committed stream after restart without waiting for a
            # player request. _publish schedules its own retry on failure.
            await api._publish()

    app.on_startup.append(publish_on_start)

    if chat_relay is not None:
        stop_chat = asyncio.Event()
        chat_task: asyncio.Task[None] | None = None

        async def start_chat(_: web.Application) -> None:
            nonlocal chat_task
            chat_task = asyncio.create_task(chat_relay.run(stop_chat), name="web-hypha-chat")

        async def close_chat(_: web.Application) -> None:
            stop_chat.set()
            if chat_task is not None:
                await chat_task
            if chat_reply is not None:
                await chat_reply.close()

        app.on_startup.append(start_chat)
        app.on_cleanup.append(close_chat)

    async def close_runtime(_: web.Application) -> None:
        await api.close()
        await api.runtime.close()

    app.on_cleanup.append(close_runtime)
    return app


def main() -> None:
    secret = os.environ.get("GAME_API_SECRET", "")
    if len(secret) < 32:
        raise SystemExit("GAME_API_SECRET must contain at least 32 characters")
    db_path = Path(os.environ.get("GAME_DB_PATH", "./data/web-live-events.sqlite3"))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    runtime = V2TestRuntime(
        db_path,
        stream_id=os.environ.get("GAME_STREAM_ID", "web-live"),
        initial_player_ids=(),
        pack=load_missing_interior_static_pack(),
    )
    base_url = os.environ.get("V2_ACTIVITY_BASE_URL", "").strip()
    publish_secret = os.environ.get("HYPHA_ACTIVITY_SECRET", "").strip()
    publisher = (
        V2ActivityPublisher(base_url, publish_secret, environment="live")
        if base_url and publish_secret else None
    )
    voice = EspeakVoiceService(
        espeak_path=os.environ.get("HYPHA_ESPEAK_COMMAND") or "espeak-ng",
        espeak_data_root=os.environ.get("HYPHA_ESPEAK_DATA_ROOT"),
        ffmpeg_path=os.environ.get("HYPHA_FFMPEG_COMMAND") or "ffmpeg",
        enabled=os.environ.get("HYPHA_VOICE_ENABLED", "false").casefold() == "true",
    )
    api = WebGameApi(runtime, secret, publisher=publisher, voice=voice)
    chat_relay: ActivityChatRelay | None = None
    chat_reply: GeminiVoiceReplyService | None = None
    if os.environ.get("WEB_HYPHA_CHAT_ENABLED", "false").casefold() == "true":
        if not base_url or not publish_secret:
            raise SystemExit("Web Hypha chat requires Activity URL and shared secret")
        dry_run = os.environ.get("GEMINI_DRY_RUN", "false").casefold() == "true"
        if dry_run:
            provider = GeminiGameChatProvider(
                None,
                os.environ.get("GEMINI_CHAT_MODEL", "gemini-3.8-flash"),
                timeout_seconds=12.0,
                max_output_tokens=1500,
                temperature=0.65,
                dry_run=True,
            )
        else:
            api_key = os.environ.get("GEMINI_API_KEY", "")
            acknowledged = (
                os.environ.get("GEMINI_PRIVACY_ACKNOWLEDGED", "false").casefold() == "true"
            )
            if not api_key or not acknowledged:
                raise SystemExit("Web Hypha chat requires Gemini API key and privacy approval")
            from google import genai

            provider = GeminiGameChatProvider(
                genai.Client(api_key=api_key),
                os.environ.get("GEMINI_CHAT_MODEL", "gemini-3.8-flash"),
                timeout_seconds=12.0,
                max_output_tokens=1500,
                temperature=0.65,
                network_authorized=True,
            )
        chat_reply = GeminiVoiceReplyService(provider, voice)
        chat_relay = ActivityChatRelay(
            base_url,
            publish_secret,
            runtime,
            chat_reply,
            runtime.stream_id,
            environment="live",
        )
    web.run_app(
        create_app(api, chat_relay=chat_relay, chat_reply=chat_reply),
        host=os.environ.get("GAME_API_HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8080")),
        access_log=None,
    )


if __name__ == "__main__":
    main()
