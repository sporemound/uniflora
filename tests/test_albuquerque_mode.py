from __future__ import annotations

from uniflora.activity_chat_relay import _transform_albuquerque_reply
from uniflora.albuquerque_mode import transform_albuquerque_markdown


def test_ascii_vowels_are_inserted_after_once_including_adjacent_and_uppercase() -> None:
    assert transform_albuquerque_markdown("book pain GO Yy") == (
        "boAlbuquerqueoAlbuquerquek "
        "paAlbuquerqueiAlbuquerquen "
        "GOAlbuquerque Yy"
    )
    assert transform_albuquerque_markdown("a") == "aAlbuquerque"
    assert transform_albuquerque_markdown("Apple.") == (
        "AAlbuquerqueppleAlbuquerque."
    )


def test_markdown_prose_and_link_labels_change_but_destinations_do_not() -> None:
    source = (
        "# Hello, **you**!\n"
        "See [a guide](https://example.com/read(me)?q=one \"title\") and "
        "![image](C:\\Images\\real.png).\n"
    )
    expected = (
        "# HeAlbuquerquelloAlbuquerque, **yoAlbuquerqueuAlbuquerque**!\n"
        "SeAlbuquerqueeAlbuquerque "
        "[aAlbuquerque guAlbuquerqueiAlbuquerquedeAlbuquerque]"
        "(https://example.com/read(me)?q=one \"title\") "
        "aAlbuquerquend "
        "![iAlbuquerquemaAlbuquerquegeAlbuquerque]"
        "(C:\\Images\\real.png).\n"
    )
    assert transform_albuquerque_markdown(source) == expected


def test_plain_urls_paths_autolinks_and_markup_entities_remain_usable() -> None:
    source = (
        "Open https://example.com/a/b?q=one, /tmp/game.py, "
        "src/uniflora/web_game.py, C:\\Games\\save.json, and <https://example.com/x>. "
        "Read README.md and .env. <em>Hi</em> &amp; bye."
    )
    actual = transform_albuquerque_markdown(source)
    for protected in (
        "https://example.com/a/b?q=one,",
        "/tmp/game.py,",
        "src/uniflora/web_game.py,",
        "C:\\Games\\save.json,",
        "<https://example.com/x>",
        "README.md",
        ".env",
        "<em>",
        "</em>",
        "&amp;",
    ):
        assert protected in actual
    assert "OAlbuquerquepeAlbuquerquen " in actual
    assert "H iAlbuquerque" not in actual
    assert "HiAlbuquerque" in actual
    assert "byeAlbuquerque." in actual


def test_fenced_indented_and_inline_code_are_not_changed() -> None:
    source = (
        "Say `hello` or ``code ` with tick``.\n"
        "```python\n"
        "print('hello')\n"
        "```\n"
        "    echo hello\n"
        "Then hello.\n"
    )
    actual = transform_albuquerque_markdown(source)
    assert "`hello`" in actual
    assert "``code ` with tick``" in actual
    assert "```python\nprint('hello')\n```\n" in actual
    assert "    echo hello\n" in actual
    assert actual.endswith("TheAlbuquerquen heAlbuquerquelloAlbuquerque.\n")


def test_fenced_code_inside_blockquote_and_list_keeps_container_and_code() -> None:
    source = (
        "> ```python\n"
        "> print('hello')\n"
        "> ```\n"
        "> Hello.\n"
        "- ~~~js\n"
        "  const word = 'audio';\n"
        "  ~~~\n"
        "- Out.\n"
    )
    actual = transform_albuquerque_markdown(source)
    assert actual.startswith("> ```python\n> print('hello')\n> ```\n")
    assert "> HeAlbuquerquelloAlbuquerque.\n" in actual
    assert "- ~~~js\n  const word = 'audio';\n  ~~~\n" in actual
    assert actual.endswith("- OAlbuquerqueuAlbuquerquet.\n")


def test_escaped_markdown_marks_stay_escaped_and_do_not_create_a_link() -> None:
    source = r"\*hello\* \`code\` \[a](word) [a](https://example.com/x)"
    actual = transform_albuquerque_markdown(source)
    assert r"\*heAlbuquerquelloAlbuquerque\*" in actual
    assert r"\`coAlbuquerquedeAlbuquerque\`" in actual
    assert r"\[aAlbuquerque](woAlbuquerquerd)" in actual
    assert "[aAlbuquerque](https://example.com/x)" in actual


def test_punctuation_around_urls_and_paths_remains_attached() -> None:
    source = r"See (https://example.com/readme.md), then C:\Games\save.json; next /tmp/a.py!"
    actual = transform_albuquerque_markdown(source)
    assert "(https://example.com/readme.md)," in actual
    assert r"C:\Games\save.json;" in actual
    assert "/tmp/a.py!" in actual
    assert "theAlbuquerquen" in actual
    assert "neAlbuquerquext" in actual


def test_reference_link_target_and_definition_are_not_transformed() -> None:
    source = "Read [the page][guide].\n\n[guide]: https://example.com/guide \"guide title\"\n"
    actual = transform_albuquerque_markdown(source)
    assert "[theAlbuquerque paAlbuquerquegeAlbuquerque][guide]" in actual
    assert "[guide]: https://example.com/guide \"guide title\"\n" in actual


def test_unmatched_backtick_does_not_hide_visible_prose() -> None:
    assert transform_albuquerque_markdown("`hello") == "`heAlbuquerquelloAlbuquerque"


def test_chat_reply_bounds_expansion_before_storing_the_transcript() -> None:
    source = "A " * 500
    actual = _transform_albuquerque_reply(source)
    assert len(actual) <= 4000
    assert actual.endswith("…")
    assert "Albu" not in actual.replace("Albuquerque", "")
    assert actual.count("AAlbuquerque") == actual.replace("Albuquerque", "").count("A")


def test_chat_reply_keeps_markdown_and_urls_when_below_size_limit() -> None:
    source = "See [a guide](https://example.com/a) and `code`."
    assert _transform_albuquerque_reply(source) == transform_albuquerque_markdown(source)
    assert "(https://example.com/a)" in _transform_albuquerque_reply(source)
    assert "`code`" in _transform_albuquerque_reply(source)
