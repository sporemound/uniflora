from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from dotenv import load_dotenv

from .errors import AprsFiConfigurationError


_TARGET_PATTERN = re.compile(r"^[A-Za-z0-9-]{1,20}$")


@dataclass(frozen=True, slots=True)
class AprsFiTarget:
    name: str
    location: bool = True
    weather: bool = False
    enabled: bool = True

    def __post_init__(self) -> None:
        cleaned = self.name.strip().upper()
        object.__setattr__(self, "name", cleaned)

        if not _TARGET_PATTERN.fullmatch(cleaned):
            raise AprsFiConfigurationError(
                f"Invalid aprs.fi target name: {self.name!r}"
            )
        if not self.location and not self.weather:
            raise AprsFiConfigurationError(
                f"Target {self.name} must enable location, weather, or both"
            )


@dataclass(frozen=True, slots=True)
class AprsFiSettings:
    api_key: str
    alias_secret: str
    project_url: str
    targets: tuple[AprsFiTarget, ...]
    application_name: str = "uniflora-aprsfi"
    application_version: str = "0.1.0"
    endpoint: str = "https://api.aprs.fi/api/get"
    center_latitude: float = 25.728333
    center_longitude: float = 32.601389
    cache_ttl_seconds: int = 1800
    timeout_seconds: float = 8.0
    max_public_entries: int = 4

    def __post_init__(self) -> None:
        if not self.api_key.strip():
            raise AprsFiConfigurationError("APRSFI API key is required")
        if len(self.alias_secret) < 16:
            raise AprsFiConfigurationError(
                "alias_secret must contain at least 16 characters"
            )

        parsed = urlparse(self.project_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise AprsFiConfigurationError(
                "project_url must be a public http(s) URL for the required User-Agent"
            )

        if not self.endpoint.startswith("https://"):
            raise AprsFiConfigurationError("aprs.fi endpoint must use HTTPS")
        if not -90 <= self.center_latitude <= 90:
            raise AprsFiConfigurationError("invalid center latitude")
        if not -180 <= self.center_longitude <= 180:
            raise AprsFiConfigurationError("invalid center longitude")
        if self.cache_ttl_seconds < 60:
            raise AprsFiConfigurationError("cache TTL must be at least 60 seconds")
        if not 1 <= self.max_public_entries <= 10:
            raise AprsFiConfigurationError("max_public_entries must be 1–10")

        enabled = tuple(target for target in self.targets if target.enabled)
        if len(enabled) > 20:
            raise AprsFiConfigurationError(
                "This integration supports at most 20 enabled targets"
            )

    @property
    def user_agent(self) -> str:
        return (
            f"{self.application_name}/{self.application_version} "
            f"(+{self.project_url})"
        )

    @classmethod
    def from_environment(
        cls,
        targets_path: str | Path,
    ) -> "AprsFiSettings":
        env_path = Path(__file__).resolve().parents[4] / ".env"
        load_dotenv(dotenv_path=env_path, override=False)

        required = (
            "UNIFLORA_APRSFI_API_KEY",
            "UNIFLORA_APRSFI_ALIAS_SECRET",
            "UNIFLORA_APRSFI_PROJECT_URL",
        )
        missing = [name for name in required if not os.getenv(name)]

        if missing:
            raise AprsFiConfigurationError(
                f"Missing environment variables in {env_path}: "
                + ", ".join(missing)
            )

        return cls(
            api_key=os.environ["UNIFLORA_APRSFI_API_KEY"],
            alias_secret=os.environ["UNIFLORA_APRSFI_ALIAS_SECRET"],
            project_url=os.environ["UNIFLORA_APRSFI_PROJECT_URL"],
            targets=load_targets(targets_path),
            cache_ttl_seconds=int(
                os.getenv("UNIFLORA_APRSFI_CACHE_SECONDS", "1800")
            ),
            max_public_entries=int(
                os.getenv("UNIFLORA_APRSFI_MAX_ENTRIES", "4")
            ),
        )


def load_targets(path: str | Path) -> tuple[AprsFiTarget, ...]:
    target_path = Path(path)
    if not target_path.exists():
        raise AprsFiConfigurationError(
            f"aprs.fi target file does not exist: {target_path}"
        )

    try:
        payload = json.loads(target_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AprsFiConfigurationError(
            f"Could not load aprs.fi targets: {exc}"
        ) from exc

    raw_targets = payload.get("targets")
    if not isinstance(raw_targets, list):
        raise AprsFiConfigurationError(
            "Target file must contain a top-level 'targets' list"
        )

    targets: list[AprsFiTarget] = []
    for item in raw_targets:
        if not isinstance(item, dict):
            raise AprsFiConfigurationError("Each target must be an object")
        targets.append(
            AprsFiTarget(
                name=str(item.get("name", "")),
                location=bool(item.get("location", True)),
                weather=bool(item.get("weather", False)),
                enabled=bool(item.get("enabled", True)),
            )
        )
    return tuple(targets)
