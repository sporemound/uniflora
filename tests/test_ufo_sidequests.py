from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest

from uniflora.ufo_sidequests import (
    build_ufosint_sidequest_url,
    canonical_ufosint_report_id,
)


@pytest.mark.parametrize("report_id", ["618999", "ufosint:618999", "UFOSINT:618999"])
def test_sidequest_url_uses_one_canonical_provider_report_id(report_id: str) -> None:
    url = build_ufosint_sidequest_url(
        "123456789012345678",
        source_key="ufosint",
        report_id=report_id,
    )

    assert url is not None
    parsed = urlsplit(url)
    assert parsed.scheme == "https"
    assert parsed.netloc == "discord.com"
    assert parsed.path == "/activities/123456789012345678"
    assert parse_qs(parsed.query) == {"custom_id": ["ufosint:618999"]}


@pytest.mark.parametrize(
    ("source_key", "report_id"),
    [
        ("archive", "618999"),
        ("ufosint", "0"),
        ("ufosint", "618999 Portland witness"),
        ("ufosint", "ufosint:ufosint:618999"),
    ],
)
def test_sidequest_url_rejects_noncanonical_or_non_ufosint_ids(
    source_key: str,
    report_id: str,
) -> None:
    assert canonical_ufosint_report_id(source_key, report_id) is None
    assert (
        build_ufosint_sidequest_url(
            "123456789012345678",
            source_key=source_key,
            report_id=report_id,
        )
        is None
    )


@pytest.mark.parametrize(
    "application_id",
    [
        None,
        "",
        "0",
        "1234",
        "12345678901234567x",
        "123456789012345678901",
        True,
    ],
)
def test_sidequest_url_fails_closed_for_invalid_application_ids(
    application_id: int | str | None,
) -> None:
    assert (
        build_ufosint_sidequest_url(
            application_id,
            source_key="ufosint",
            report_id="618999",
        )
        is None
    )


def test_integer_discord_application_id_is_supported() -> None:
    assert build_ufosint_sidequest_url(
        123456789012345678,
        source_key="ufosint",
        report_id="618999",
    ) == (
        "https://discord.com/activities/123456789012345678"
        "?custom_id=ufosint%3A618999"
    )


def test_sidequest_report_id_bound_matches_activity_route_contract() -> None:
    assert canonical_ufosint_report_id("ufosint", "9" * 19) == "9" * 19
    assert canonical_ufosint_report_id("ufosint", "9" * 20) is None
