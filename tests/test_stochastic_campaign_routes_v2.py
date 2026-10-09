from __future__ import annotations

from scripts.verify_stochastic_campaign import CampaignVerifier


def _assert_complete(report: dict[str, object], expected_route_mode: str) -> None:
    assert report["ok"] is True
    assert report["routeMode"] == expected_route_mode
    assert report["contentVersion"] == "2.0.0-strategic-overhaul"
    assert len(report["positions"]) == 6
    assert report["totalObservations"] >= 6
    assert report["completedPositions"] == [
        "aeronautical_incident",
        "archive_convergence",
        "boundary_event",
        "holographic_reconstruction",
        "network_orientation",
        "quantum_state",
        "subsurface_resonance",
    ]


def test_primary_routes_complete_full_campaign_with_exact_replay() -> None:
    report = CampaignVerifier(
        seed="formal-primary-campaign",
        route_mode="primary",
    ).run()
    _assert_complete(report, "primary")


def test_alternate_routes_complete_full_campaign_with_exact_replay() -> None:
    report = CampaignVerifier(
        seed="formal-alternate-campaign",
        route_mode="alternate",
    ).run()
    _assert_complete(report, "alternate")
