#!/usr/bin/env python3
"""Verify lazy strategic initialization on a legacy schema-2/3 event stream."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from uniflora.content.v2 import load_missing_interior_pack  # noqa: E402
from uniflora.engine.v2 import (  # noqa: E402
    V2AssignRoleCommand,
    V2BeginInvestigationCommand,
    V2ExamineEvidenceCommand,
    V2PerformActionCommand,
    V2ReleaseRoleCommand,
    V2ViewStrategicBoardCommand,
    execute_command,
    initialize_event_stream,
    replay_events,
    serialize_event,
    serialize_state,
    deserialize_event,
    deserialize_state,
)
from uniflora.engine.v2.stochastic import V2SeededRandomSource  # noqa: E402

A = "discord:legacy-bootstrap-a"
B = "discord:legacy-bootstrap-b"


def _execute(pack, stream, command, source):
    result = execute_command(pack, stream, command, random_source=source)
    if not result.accepted:
        raise RuntimeError(f"{result.code}: {result.message}")
    return result


def verify() -> dict[str, object]:
    current_pack = load_missing_interior_pack()
    legacy_pack = current_pack.model_copy(update={"schema_version": 2, "strategic": None})
    source = V2SeededRandomSource("legacy-strategic-bootstrap")
    stream = initialize_event_stream(
        legacy_pack,
        (A, B),
        stream_id="legacy-strategic-bootstrap",
    )
    for command in (
        V2BeginInvestigationCommand(player_id=A),
        V2ExamineEvidenceCommand(player_id=A, evidence_id="optical_record"),
        V2ExamineEvidenceCommand(player_id=A, evidence_id="radio_return"),
        V2AssignRoleCommand(player_id=A, role_id="field_observer"),
        V2PerformActionCommand(player_id=A, action_id="inspect_optical_record"),
        V2ReleaseRoleCommand(player_id=A),
        V2AssignRoleCommand(player_id=A, role_id="instrument_operator"),
    ):
        stream = _execute(legacy_pack, stream, command, source).stream

    legacy_revision = stream.state.revision
    legacy_event_count = len(stream.events)
    if stream.state.strategic_board is not None:
        raise RuntimeError("legacy stream unexpectedly contains a strategic board")

    preview = _execute(
        current_pack,
        stream,
        V2ViewStrategicBoardCommand(player_id=A),
        source,
    )
    if preview.event is not None or preview.stream != stream:
        raise RuntimeError("board preview mutated the legacy event stream")

    first = _execute(
        current_pack,
        stream,
        V2PerformActionCommand(
            player_id=A,
            action_id="calibrate_radio_receiver",
        ),
        source,
    )
    stream = first.stream
    board = stream.state.strategic_board
    if first.event is None or first.event.strategic_resolution is None:
        raise RuntimeError("first strategic action did not persist its complete resolution")
    if stream.state.revision != legacy_revision + 1:
        raise RuntimeError("legacy bootstrap appended more than one event")
    if len(stream.events) != legacy_event_count + 1:
        raise RuntimeError("legacy bootstrap changed the historical event count")
    if board is None or board.capacity_remaining != 2:
        raise RuntimeError("strategic board did not initialize with one operation spent")
    if board.get_player(A) is None or board.get_player(A).operation_count != 1:
        raise RuntimeError("the bootstrap action was not recorded against its actor")
    if replay_events(stream.events) != stream.state:
        raise RuntimeError("legacy plus strategic event replay diverged")
    if deserialize_state(serialize_state(stream.state)) != stream.state:
        raise RuntimeError("schema-4 state round trip diverged")
    if deserialize_event(serialize_event(first.event)) != first.event:
        raise RuntimeError("bootstrap event round trip diverged")

    return {
        "ok": True,
        "legacySchemaVersion": legacy_pack.schema_version,
        "currentSchemaVersion": current_pack.schema_version,
        "legacyRevision": legacy_revision,
        "newRevision": stream.state.revision,
        "eventsAppended": len(stream.events) - legacy_event_count,
        "previewAppendedEvent": preview.event is not None,
        "capacityRemaining": board.capacity_remaining,
        "serializationSchema": stream.state.serialization_schema,
        "replayExact": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        report = verify()
    except Exception as error:
        report = {"ok": False, "error": str(error)}
        code = 1
    else:
        code = 0
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json or code:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(
            "Legacy strategic bootstrap PASS — one event appended, "
            "schema 4 replay exact"
        )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
