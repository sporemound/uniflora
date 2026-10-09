from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import sysconfig
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _load_stdlib_logging() -> Any:
    stdlib_dir = Path(sysconfig.get_path("stdlib"))
    stdlib_init = stdlib_dir / "logging" / "__init__.py"
    if not stdlib_init.exists():
        raise RuntimeError("Unable to locate the standard library logging module")
    spec = importlib.util.spec_from_file_location("_stdlib_logging", stdlib_init)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load the standard library logging module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_stdlib_logging = _load_stdlib_logging()
for _name in dir(_stdlib_logging):
    if _name.startswith("__"):
        continue
    globals()[_name] = getattr(_stdlib_logging, _name)
logging = _stdlib_logging

_SAFE_EXTRAS = {
    "command_count",
    "daily_cost",
    "environment",
    "host",
    "monthly_cost",
    "port",
    "purpose",
}


class JsonFormatter(logging.Formatter):
    """Small dependency-free JSON formatter with support for structured extras."""

    def format(self, record: logging.LogRecord) -> str:
        template = str(record.msg)
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": hashlib.sha256(template.encode("utf-8", "replace")).hexdigest()[:12],
        }
        for key in _SAFE_EXTRAS:
            if key in record.__dict__:
                payload[key] = record.__dict__[key]
        if record.exc_info:
            exception_type = record.exc_info[0]
            payload["exception_type"] = getattr(exception_type, "__name__", "Exception")
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
