from __future__ import annotations

import pytest

from uniflora.narration import FallbackNarrator, NarrationTemplateError


def test_fallback_narration_is_deterministic_and_profile_specific() -> None:
    narrator = FallbackNarrator()
    surface = narrator.render(profile="surface_noise", narration_key="accepted", event_id="event-1")
    repeated = narrator.render(
        profile="surface_noise", narration_key="accepted", event_id="event-1"
    )
    coherent = narrator.render(
        profile="local_correlation", narration_key="accepted", event_id="event-1"
    )
    assert surface == repeated
    assert coherent != surface


def test_unknown_key_uses_non_spoilery_invalid_fallback() -> None:
    text = FallbackNarrator().render(
        profile="surface_noise", narration_key="not-a-real-key", event_id="event-2"
    )
    assert text == "pattern does not alter the network."


def test_unknown_profile_fails_closed() -> None:
    with pytest.raises(NarrationTemplateError, match="unknown response profile"):
        FallbackNarrator().render(profile="invented", narration_key="accepted", event_id="event-3")
