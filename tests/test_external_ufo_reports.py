from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

from uniflora.external_ufo_reports import (
    UfoReportFeed,
    UfoReportFeedService,
    UfoReportSettings,
    parse_ufo_report_feed,
    parse_ufosint_records,
)

NOW = datetime(2026, 7, 28, 6, 0, tzinfo=UTC)


def ufosint_search(*ids: int) -> dict[str, object]:
    return {
        "total": len(ids),
        "returned": len(ids),
        "results": [
            {
                "id": identifier,
                "date_event": "2026-07-27",
                "shape": "Triangle",
                "source": "MUFON",
                "city": "Vancouver",
                "state": "BC",
                "country": "CA",
                "latitude": 49.2827,
                "longitude": -123.1207,
                "description": (
                    "Two triangular lights hovered above the ridge before accelerating. "
                    "Contact test@example.com or https://example.com."
                ),
            }
            for identifier in ids
        ],
    }


def ufosint_detail(identifier: int, quality: int, **updates: object) -> dict[str, object]:
    value: dict[str, object] = {
        "id": identifier,
        "date_event": "2026-07-27",
        "quality_score": quality,
        "standardized_shape": "Triangle",
        "source_name": "MUFON",
        "city": "Vancouver",
        "state": "BC",
        "country": "CA",
        "latitude": 49.2827,
        "longitude": -123.1207,
        "duration": "about two minutes",
        "num_witnesses": 2,
        "hynek": "NL",
        "movement_categories": ["hovering", "accelerating"],
        "description": (
            "Two triangular lights hovered above the ridge before accelerating. "
            "Contact test@example.com or https://example.com."
        ),
        "summary": "unused source summary",
    }
    value.update(updates)
    return value


def test_ufosint_quality_must_be_above_fifty() -> None:
    feed = parse_ufosint_records(
        ufosint_search(50, 51),
        [ufosint_detail(50, 50), ufosint_detail(51, 51)],
        retrieved_at=NOW,
    )

    assert [report.report_id for report in feed.reports] == ["51"]
    assert feed.reports[0].quality_score == 51


def test_ufosint_witness_summary_is_bounded_and_sanitized() -> None:
    feed = parse_ufosint_records(
        ufosint_search(101),
        [ufosint_detail(101, 77)],
        retrieved_at=NOW,
    )

    report = feed.reports[0]
    assert "triangular lights hovered" in report.summary
    assert "test@example.com" not in report.summary
    assert "https://example.com" not in report.summary
    assert "[contact removed]" in report.summary
    assert "[link removed]" in report.summary
    assert len(report.summary) <= 500


def test_ufosint_incomplete_event_dates_are_discarded() -> None:
    feed = parse_ufosint_records(
        ufosint_search(1, 2, 3),
        [
            ufosint_detail(1, 90, date_event="2026"),
            ufosint_detail(2, 90, date_event="2026-07"),
            ufosint_detail(3, 90, date_event="2026-07-27"),
        ],
        retrieved_at=NOW,
    )

    assert [report.report_id for report in feed.reports] == ["3"]


def test_coordinates_are_reduced_to_approximate_city_precision() -> None:
    feed = parse_ufosint_records(
        ufosint_search(201),
        [ufosint_detail(201, 80, latitude=49.2827123, longitude=-123.1207389)],
        retrieved_at=NOW,
    )

    report = feed.reports[0]
    assert report.latitude == 49.3
    assert report.longitude == -123.1
    assert report.coordinate_precision == "city"


def test_approved_json_compatibility_mode_applies_same_quality_gate() -> None:
    feed = parse_ufo_report_feed(
        {
            "schemaVersion": "1.1.0",
            "source": {
                "key": "partner",
                "name": "Approved Partner",
                "pageUrl": "https://partner.example/reports",
                "license": "API metadata reuse",
            },
            "authorization": {
                "mode": "api",
                "reference": "https://partner.example/api-docs",
            },
            "reports": [
                {
                    "id": "quality-50",
                    "observedAt": "2026-07-27T12:00:00Z",
                    "indexedAt": "2026-07-28T05:00:00Z",
                    "latitude": 49.28,
                    "longitude": -123.12,
                    "title": "Rejected",
                    "locationName": "Vancouver, BC",
                    "coordinatePrecision": "city",
                    "summary": "Rejected by threshold.",
                    "status": "unverified",
                    "qualityScore": 50,
                },
                {
                    "id": "quality-51",
                    "observedAt": "2026-07-27T12:00:00Z",
                    "indexedAt": "2026-07-28T05:00:00Z",
                    "latitude": 49.28,
                    "longitude": -123.12,
                    "title": "Accepted",
                    "locationName": "Vancouver, BC",
                    "coordinatePrecision": "city",
                    "summary": "Accepted by threshold.",
                    "status": "unverified",
                    "qualityScore": 51,
                },
            ],
        },
        now=NOW,
    )

    assert [report.report_id for report in feed.reports] == ["quality-51"]


def test_first_successful_poll_returns_unseen_reports_for_delivery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report_feed = parse_ufosint_records(
        ufosint_search(301),
        [ufosint_detail(301, 88)],
        retrieved_at=NOW,
    )
    settings = UfoReportSettings(
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

    def fake_fetch(_settings: UfoReportSettings) -> UfoReportFeed:
        return report_feed

    monkeypatch.setattr(
        "uniflora.external_ufo_reports._fetch_ufosint_feed",
        fake_fetch,
    )
    service = UfoReportFeedService(settings)

    first = asyncio.run(service.poll())
    service.mark_seen(first.unseen_reports)
    second = asyncio.run(service.poll())

    assert first.first_successful_poll is True
    assert [report.report_id for report in first.unseen_reports] == ["301"]
    assert second.first_successful_poll is False
    assert second.unseen_reports == ()


def test_latest_qualifying_report_uses_fresh_ufosint_fetch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report_feed = parse_ufosint_records(
        ufosint_search(401, 402, 403),
        [
            ufosint_detail(401, 99, date_event="2026-07-25"),
            ufosint_detail(402, 50, date_event="2026-07-28"),
            ufosint_detail(403, 88, date_event="2026-07-27"),
        ],
        retrieved_at=NOW,
    )
    settings = UfoReportSettings(
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

    def fake_fetch(_settings: UfoReportSettings) -> UfoReportFeed:
        return report_feed

    monkeypatch.setattr(
        "uniflora.external_ufo_reports._fetch_ufosint_feed",
        fake_fetch,
    )
    service = UfoReportFeedService(settings)

    latest = asyncio.run(service.latest_qualifying_report())

    assert latest is not None
    assert latest.report_id == "403"
    assert latest.quality_score == 88

def test_latest_qualifying_reports_are_sorted_newest_first(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report_feed = parse_ufosint_records(
        ufosint_search(501, 502, 503),
        [
            ufosint_detail(501, 99, date_event="2026-07-25"),
            ufosint_detail(502, 50, date_event="2026-07-28"),
            ufosint_detail(503, 88, date_event="2026-07-27"),
        ],
        retrieved_at=NOW,
    )
    settings = UfoReportSettings(
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

    def fake_fetch(_settings: UfoReportSettings) -> UfoReportFeed:
        return report_feed

    monkeypatch.setattr(
        "uniflora.external_ufo_reports._fetch_ufosint_feed",
        fake_fetch,
    )
    service = UfoReportFeedService(settings)

    reports = asyncio.run(service.latest_qualifying_reports())

    assert [report.report_id for report in reports] == ["503", "501"]

def test_latest_qualifying_reports_use_source_id_when_observed_dates_match(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report_feed = parse_ufosint_records(
        ufosint_search(701, 703, 702),
        [
            ufosint_detail(701, 99, date_event="2026-04-15"),
            ufosint_detail(703, 99, date_event="2026-04-15"),
            ufosint_detail(702, 99, date_event="2026-04-15"),
        ],
        retrieved_at=NOW,
    )
    settings = UfoReportSettings(
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

    def fake_fetch(_settings: UfoReportSettings) -> UfoReportFeed:
        return report_feed

    monkeypatch.setattr(
        "uniflora.external_ufo_reports._fetch_ufosint_feed",
        fake_fetch,
    )
    service = UfoReportFeedService(settings)

    reports = asyncio.run(service.latest_qualifying_reports())

    assert [report.report_id for report in reports] == ["703", "702", "701"]


def test_poll_returns_unseen_reports_newest_first_when_observed_dates_match(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report_feed = parse_ufosint_records(
        ufosint_search(801, 803, 802),
        [
            ufosint_detail(801, 99, date_event="2026-04-15"),
            ufosint_detail(803, 99, date_event="2026-04-15"),
            ufosint_detail(802, 99, date_event="2026-04-15"),
        ],
        retrieved_at=NOW,
    )
    settings = UfoReportSettings(
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

    def fake_fetch(_settings: UfoReportSettings) -> UfoReportFeed:
        return report_feed

    monkeypatch.setattr(
        "uniflora.external_ufo_reports._fetch_ufosint_feed",
        fake_fetch,
    )
    service = UfoReportFeedService(settings)

    result = asyncio.run(service.poll())

    assert [report.report_id for report in result.unseen_reports] == [
        "803",
        "802",
        "801",
    ]

def test_report_seen_state_tracks_intake_delivery(
    tmp_path: Path,
) -> None:
    report_feed = parse_ufosint_records(
        ufosint_search(601),
        [ufosint_detail(601, 88, date_event="2026-07-27")],
        retrieved_at=NOW,
    )
    settings = UfoReportSettings(
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
    service = UfoReportFeedService(settings)
    report = report_feed.reports[0]

    assert service.is_seen(report) is False

    service.mark_seen((report,))

    assert service.is_seen(report) is True