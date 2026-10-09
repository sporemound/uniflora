from __future__ import annotations

from pathlib import Path

from uniflora.content.v2.investigation_loader import load_investigation_pack
from uniflora.content.v2.investigation_schema import V2InvestigationPack
from uniflora.content.v2.static_roles import build_static_roles_pack

MISSING_INTERIOR_PACK_PATH = (
    Path(__file__).resolve().parent / "packs" / "missing_interior" / "pack.yaml"
)


def load_missing_interior_pack() -> V2InvestigationPack:
    """Load the original 2.0 pack for existing Discord/event streams."""

    return load_investigation_pack(MISSING_INTERIOR_PACK_PATH)


def load_missing_interior_static_pack() -> V2InvestigationPack:
    """Load the separately identified 2.1 pack with three lasting roles."""

    return build_static_roles_pack(load_missing_interior_pack())
