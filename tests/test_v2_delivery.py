from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from uniflora.content.v2 import load_missing_interior_pack
from uniflora.engine.v2.application import V2PersistentInvestigationService
from uniflora.engine.v2.commands import (
    V2BeginInvestigationCommand,
    V2ExamineEvidenceCommand,
)
from uniflora.engine.v2.delivery import (
    build_position_guide,
    guided_suggestions,
    render_evidence,
)
from uniflora.engine.v2.kernel import initialize_investigation
from uniflora.engine.v2.parsing import parse_user_command
from uniflora.engine.v2.persistence import V2SQLiteEventStore
from uniflora.engine.v2.state import V2PlayerState
from uniflora.engine.v2.transport import V2TextCommandAdapter


def test_every_evidence_source_has_a_complete_delivery_record() -> None:
    pack = load_missing_interior_pack()
    state = initialize_investigation(pack, ["discord:1"])
    state = replace(
        state,
        available_location_ids=frozenset(item.id for item in pack.locations),
        available_evidence_ids=frozenset(item.id for item in pack.evidence_sources),
        examined_evidence_ids=frozenset(item.id for item in pack.evidence_sources),
    )

    for source in pack.evidence_sources:
        rendered = render_evidence(
            pack,
            state,
            "discord:1",
            source.id,
            reopened=True,
        )
        text = "\n".join((rendered.summary, *rendered.details))
        assert source.name in text
        assert source.provenance in text
        assert source.uncertainty in text
        for conclusion in source.supported_conclusions:
            assert conclusion in text
        for limitation in source.limitations:
            assert limitation in text
        for extrapolation in source.unsupported_extrapolations:
            assert extrapolation in text


def test_every_guided_autocomplete_value_is_a_real_parser_command() -> None:
    pack = load_missing_interior_pack()
    base = initialize_investigation(pack, ["discord:1"])
    all_locations = frozenset(item.id for item in pack.locations)
    all_evidence = frozenset(item.id for item in pack.evidence_sources)

    for position in pack.positions:
        state = replace(
            base,
            current_position_id=position.id,
            available_location_ids=all_locations,
            available_evidence_ids=all_evidence,
            players=(
                V2PlayerState(
                    player_id="discord:1",
                    current_location_id=position.focus_location_id,
                ),
            ),
        )
        guide = build_position_guide(pack, state, "discord:1")
        assert position.title in guide

        for suggestion in guided_suggestions(pack, state, "discord:1"):
            assert len(suggestion.command) <= 100
            parse_user_command(suggestion.command, player_id="discord:1")


def test_reopening_evidence_is_accepted_without_a_new_event(tmp_path: Path) -> None:
    pack = load_missing_interior_pack()
    with V2SQLiteEventStore(tmp_path / "events.sqlite3") as store:
        service = V2PersistentInvestigationService(pack, store)
        created = service.create_session("session", ["discord:1"])
        begun = service.execute(
            "session",
            V2BeginInvestigationCommand(player_id="discord:1"),
            expected_sequence=created.session.sequence,
        )
        examined = service.execute(
            "session",
            V2ExamineEvidenceCommand(
                player_id="discord:1",
                evidence_id="optical_record",
            ),
            expected_sequence=begun.session.sequence,
        )
        reopened = service.execute(
            "session",
            V2ExamineEvidenceCommand(
                player_id="discord:1",
                evidence_id="optical_record",
            ),
            expected_sequence=examined.session.sequence,
        )

        assert reopened.accepted is True
        assert reopened.code == "evidence_reopened"
        assert reopened.event is None
        assert reopened.session.sequence == examined.session.sequence
        assert store.latest_sequence("session") == examined.session.sequence


def test_transport_renders_source_content_and_actionable_next_step(tmp_path: Path) -> None:
    pack = load_missing_interior_pack()
    with V2SQLiteEventStore(tmp_path / "events.sqlite3") as store:
        service = V2PersistentInvestigationService(pack, store)
        service.create_session("session", ["discord:1"])
        adapter = V2TextCommandAdapter(service)

        begun = adapter.execute(
            "session",
            player_id="discord:1",
            text="begin-investigation",
            expected_sequence=0,
        )
        examined = adapter.execute(
            "session",
            player_id="discord:1",
            text="examine-evidence optical_record",
            expected_sequence=begun.sequence or 0,
        )
        text = examined.to_text()

        assert "Saturated Optical Array Record" in text
        assert "Supported conclusions" in text
        assert "Not established by this source" in text
        assert "assign-role field_observer" in text
