from __future__ import annotations

from scripts.verify_legacy_strategic_bootstrap import verify


def test_legacy_bootstrap_script_uses_one_event_and_exact_replay() -> None:
    report = verify()
    assert report["ok"] is True
    assert report["eventsAppended"] == 1
    assert report["previewAppendedEvent"] is False
    assert report["serializationSchema"] == 4
    assert report["replayExact"] is True
