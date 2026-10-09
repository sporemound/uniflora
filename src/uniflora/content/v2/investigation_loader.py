from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from uniflora.content.v2.investigation_schema import V2InvestigationPack


class V2InvestigationContentError(ValueError):
    """Raised when a v2 investigation content pack is invalid."""


def load_investigation_pack(path: Path) -> V2InvestigationPack:
    if not path.is_file():
        raise V2InvestigationContentError(f"v2 investigation pack does not exist: {path}")

    try:
        text = path.read_text(encoding="utf-8")
        raw: Any = yaml.safe_load(text)

        if not isinstance(raw, dict):
            raise TypeError("top-level YAML value must be a mapping")

        return V2InvestigationPack.model_validate(raw)
    except (
        OSError,
        UnicodeError,
        TypeError,
        yaml.YAMLError,
        ValidationError,
    ) as exc:
        raise V2InvestigationContentError(
            f"invalid v2 investigation pack {path.name}: {exc}"
        ) from exc
