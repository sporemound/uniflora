# BEGIN SOURCE-REVIEW LEGACY PUZZLE SKIPS
from pathlib import Path as _LegacyPath

_LEGACY_PUZZLES_ROOT = (
    _LegacyPath(__file__).parents[1]
    / "src"
    / "uniflora"
    / "content"
    / "puzzles"
)

_LEGACY_TEST_HINTS = (
    "PuzzleRegistry",
    "load_packaged",
    "legacy_cycle",
    "provision_arc",
    "maintenance_cycle",
)


def pytest_collection_modifyitems(config, items):
    """Skip V1-only tests when the sanitized distribution omits V1 puzzles."""
    del config

    if _LEGACY_PUZZLES_ROOT.is_dir():
        return

    import pytest

    reason = (
        "Legacy v1 packaged puzzles are not included in this "
        "source-review distribution."
    )

    source_cache = {}

    for item in items:
        test_path = _LegacyPath(str(item.fspath))

        try:
            source = source_cache.setdefault(
                test_path,
                test_path.read_text(encoding="utf-8"),
            )
        except OSError:
            continue

        if any(hint in source for hint in _LEGACY_TEST_HINTS):
            item.add_marker(pytest.mark.skip(reason=reason))
# END SOURCE-REVIEW LEGACY PUZZLE SKIPS
