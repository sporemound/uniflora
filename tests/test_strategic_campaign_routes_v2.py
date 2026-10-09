from __future__ import annotations

import pytest

from scripts.verify_stochastic_campaign import CampaignVerifier


@pytest.mark.parametrize(("mode", "sequence"), (("primary", 158), ("alternate", 167)))
def test_full_campaign_records_six_strategic_outcomes_and_exact_replay(
    mode: str,
    sequence: int,
) -> None:
    verifier = CampaignVerifier(seed=f"strategic-{mode}", route_mode=mode)
    report = verifier.run()
    state = verifier.state

    assert report["ok"] is True
    assert report["contentVersion"] == "2.0.0-strategic-overhaul"
    assert report["finalSequence"] == sequence
    assert len(state.strategic_position_outcomes) == 6
    assert all(item.grade == "controlled" for item in state.strategic_position_outcomes)
    assert len(state.campaign_modifier_ids) == 6
    assert state.strategic_board is None
    assert {item.track_id for item in state.campaign_tracks} == {
        "case_integrity",
        "institutional_trust",
    }
