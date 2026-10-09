from hypothesis import given, strategies as st
from rapidfuzz import fuzz


@given(st.text())
def test_rapidfuzz_handles_arbitrary_text(value: str) -> None:
    """RapidFuzz should safely compare any Unicode string with itself."""
    score = fuzz.ratio(value, value)

    assert score == 100.0