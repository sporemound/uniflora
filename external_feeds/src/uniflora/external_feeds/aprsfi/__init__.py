"""On-demand, privacy-reduced aprs.fi integration."""

from .client import AprsFiClient
from .config import AprsFiSettings, AprsFiTarget, load_targets
from .errors import AprsFiApiError, AprsFiConfigurationError
from .models import (
    AprsFiLocationRecord,
    AprsFiWeatherRecord,
    ExteriorReport,
)
from .service import AprsFiExteriorService

__all__ = [
    "AprsFiApiError",
    "AprsFiClient",
    "AprsFiConfigurationError",
    "AprsFiExteriorService",
    "AprsFiLocationRecord",
    "AprsFiSettings",
    "AprsFiTarget",
    "AprsFiWeatherRecord",
    "ExteriorReport",
    "load_targets",
]

# The Discord bridge is intentionally not imported here so the API/data layer
# remains usable and testable without discord.py. Import it explicitly with:
# from uniflora.external_feeds.aprsfi.discord_bridge import AprsFiDiscordBridge
