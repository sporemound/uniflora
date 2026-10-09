from __future__ import annotations

import pytest
from pydantic import ValidationError

from uniflora.content.v2 import V2InvestigationPack, load_missing_interior_pack


def test_schema_three_configures_every_investigation_position_and_major_action() -> None:
    pack = load_missing_interior_pack()
    assert pack.schema_version == 3
    assert pack.pack.content_version == "2.0.0-strategic-overhaul"
    assert pack.strategic is not None
    configured = {item.position_id for item in pack.strategic.positions}
    assert configured == {item.id for item in pack.positions if item.ordinal > 0}
    assert {item.id for item in pack.strategic.campaign_tracks} == {
        "case_integrity",
        "institutional_trust",
    }
    major = [
        item for item in pack.actions
        if item.strategic is not None and item.strategic.supporter_count > 0
    ]
    assert len(major) == 6
    assert {item.position_id for item in major} == configured
    assert all(item.strategic.stochastic_mode == "intervention_then_emit" for item in major)
    assert all(item.strategic.irreversible for item in major)


def test_schema_rejects_missing_position_rules_and_invalid_major_action() -> None:
    pack = load_missing_interior_pack()
    record = pack.model_dump(mode="json")
    record["strategic"]["positions"] = record["strategic"]["positions"][:-1]
    with pytest.raises(ValidationError):
        V2InvestigationPack.model_validate(record)

    record = pack.model_dump(mode="json")
    major = next(
        item for item in record["actions"]
        if (item.get("strategic") or {}).get("strategic_class") == "commit"
    )
    major["strategic"]["supporter_count"] = 0
    with pytest.raises(ValidationError):
        V2InvestigationPack.model_validate(record)
