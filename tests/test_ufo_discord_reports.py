from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import discord

from uniflora.discord_adapter import (
    _first_unposted_ufo_report,
    _ufo_report_embed_matches_posted,
    _ufo_report_sidequest_view,
)
from uniflora.external_ufo_reports import ExternalUfoReport, UfoReportFeedService, UfoReportSettings


def _report() -> ExternalUfoReport:
    return ExternalUfoReport(
        report_id="618999",
        source_key="ufosint",
        source_name="UFOSINT Explorer",
        source_page_url="https://ufosint.com/",
        source_url=None,
        authorization_mode="api",
        observed_at=datetime(2026, 7, 28, tzinfo=UTC),
        indexed_at=datetime(2026, 7, 28, 6, tzinfo=UTC),
        latitude=45.0,
        longitude=-122.0,
        title="Light observation near Portland, Oregon, United States",
        location_name="Portland, Oregon, United States",
        coordinate_precision="city",
        summary="UFOSINT indexed a quality-screened sighting.",
        status="unverified",
        quality_score=88,
    )


def _field(name: str, value: str) -> SimpleNamespace:
    return SimpleNamespace(name=name, value=value)


def test_ufo_report_sidequest_view_contains_only_the_canonical_report_key() -> None:
    report = replace(
        _report(),
        report_id="ufosint:618999",
        title="Witness name that must not enter the URL",
        summary="Witness contact details that must not enter the URL",
        location_name="Private-looking location text",
    )

    view = _ufo_report_sidequest_view(report, "123456789012345678")

    assert view is not None
    button = view.children[0]
    assert isinstance(button, discord.ui.Button)
    assert button.style is discord.ButtonStyle.link
    assert button.url == (
        "https://discord.com/activities/123456789012345678"
        "?custom_id=ufosint%3A618999"
    )
    assert report.title not in button.url
    assert report.summary not in button.url
    assert report.location_name not in button.url


def test_ufo_report_sidequest_view_is_omitted_without_a_safe_application_id() -> None:
    assert _ufo_report_sidequest_view(_report(), None) is None
    assert _ufo_report_sidequest_view(_report(), "not-a-discord-application-id") is None


def test_ufo_report_embed_matches_stable_report_id_field() -> None:
    report = _report()
    embed = SimpleNamespace(
        footer=SimpleNamespace(text=""),
        description="Different title is still safe when the stable ID matches.",
        fields=[_field("Report ID", "ufosint:618999")],
    )

    assert _ufo_report_embed_matches_posted(report, embed, report.marker) is True


def test_ufo_report_embed_matches_legacy_content_without_report_id() -> None:
    report = _report()
    embed = SimpleNamespace(
        footer=SimpleNamespace(text="legacy footer"),
        description=report.title,
        fields=[
            _field("Observed", discord.utils.format_dt(report.observed_at, style="F")),
            _field("Data quality", "88/100 · required >= 51"),
            _field("Location", "Portland, Oregon, United States\nApproximation: city"),
        ],
    )

    assert _ufo_report_embed_matches_posted(report, embed, report.marker) is True


def test_ufo_report_embed_legacy_match_requires_location() -> None:
    report = _report()
    embed = SimpleNamespace(
        footer=SimpleNamespace(text="legacy footer"),
        description=report.title,
        fields=[
            _field("Observed", discord.utils.format_dt(report.observed_at, style="F")),
            _field("Data quality", "88/100 · required >= 51"),
            _field("Location", "Seattle, Washington, United States\nApproximation: city"),
        ],
    )

    assert _ufo_report_embed_matches_posted(report, embed, report.marker) is False

def test_latest_candidate_selection_skips_seen_reports(tmp_path) -> None:
    seen = _report()
    next_report = replace(
        seen,
        report_id="619000",
        title="Triangle observation near Salem, Oregon, United States",
        location_name="Salem, Oregon, United States",
    )
    service = UfoReportFeedService(
        UfoReportSettings(
            enabled=True,
            source_mode="ufosint",
            feed_url=None,
            channel_id=123,
            poll_seconds=21_600,
            event_max_age_hours=48,
            max_announcements_per_poll=3,
            state_path=tmp_path / "seen.json",
            voice_enabled=True,
            minimum_quality_score=51,
            ufosint_lookback_days=365,
            ufosint_candidate_limit=32,
        )
    )
    service.mark_seen((seen,))
    checked: list[str] = []

    async def already_posted(channel, marker, report):
        del channel, marker
        checked.append(report.report_id)
        return False

    selected = asyncio.run(
        _first_unposted_ufo_report(
            service,
            None,
            (seen, next_report),
            already_posted,
        )
    )

    assert selected == next_report
    assert checked == ["619000"]

def test_manual_latest_candidate_selection_ignores_seen_state(tmp_path) -> None:
    report = _report()
    service = UfoReportFeedService(
        UfoReportSettings(
            enabled=True,
            source_mode="ufosint",
            feed_url=None,
            channel_id=123,
            poll_seconds=21_600,
            event_max_age_hours=48,
            max_announcements_per_poll=3,
            state_path=tmp_path / "seen.json",
            voice_enabled=True,
            minimum_quality_score=51,
            ufosint_lookback_days=365,
            ufosint_candidate_limit=32,
        )
    )
    service.mark_seen((report,))
    checked: list[str] = []

    async def already_posted(channel, marker, candidate):
        del channel, marker
        checked.append(candidate.report_id)
        return False

    selected = asyncio.run(
        _first_unposted_ufo_report(
            service,
            None,
            (report,),
            already_posted,
            respect_seen_state=False,
        )
    )

    assert selected == report
    assert checked == ["618999"]


def test_latest_candidate_selection_marks_history_matches_seen(tmp_path) -> None:
    report = _report()
    service = UfoReportFeedService(
        UfoReportSettings(
            enabled=True,
            source_mode="ufosint",
            feed_url=None,
            channel_id=123,
            poll_seconds=21_600,
            event_max_age_hours=48,
            max_announcements_per_poll=3,
            state_path=tmp_path / "seen.json",
            voice_enabled=True,
            minimum_quality_score=51,
            ufosint_lookback_days=365,
            ufosint_candidate_limit=32,
        )
    )

    async def already_posted(channel, marker, candidate):
        del channel, marker, candidate
        return True

    selected = asyncio.run(
        _first_unposted_ufo_report(service, None, (report,), already_posted)
    )

    assert selected is None
    assert service.is_seen(report) is True
