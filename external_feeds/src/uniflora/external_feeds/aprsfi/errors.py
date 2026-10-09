class AprsFiError(RuntimeError):
    """Base error for the aprs.fi integration."""


class AprsFiConfigurationError(AprsFiError):
    """The local integration configuration is invalid."""


class AprsFiApiError(AprsFiError):
    """The aprs.fi API rejected or failed a request."""
