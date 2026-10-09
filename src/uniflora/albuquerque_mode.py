"""Deterministic Albuquerque Mode rendering for a single chat reply.

The model writes an ordinary reply. This module decorates the visible prose after
generation, so prompt compliance cannot cause a partial or recursive conversion.
Markdown code and link targets are deliberately left intact.
"""

from __future__ import annotations

import re

_INSERTION = "Albuquerque"
_VOWELS = frozenset("aeiouAEIOU")
_FENCE = re.compile(
    r"^[ ]{0,3}(?:>[ ]{0,3})*"
    r"(?:(?:[-+*]|[0-9]{1,9}[.)])[ \t]+)?[ ]{0,3}(`{3,}|~{3,})"
)
_LINK_DEFINITION = re.compile(r"^[ ]{0,3}\[[^\]\n]+\]:[ \t]*\S")
_URL_START = re.compile(r"(?:https?://|ftp://|file://|mailto:|www\.)", re.IGNORECASE)
_AUTOLINK = re.compile(r"<(?:https?://|ftp://|file://|mailto:)[^>\n]+>", re.IGNORECASE)
_HTML_TAG = re.compile(r"</?[A-Za-z][^>\n]*>")
_ENTITY = re.compile(r"&(?:#[0-9]+|#x[0-9a-fA-F]+|[A-Za-z][A-Za-z0-9]+);")
_DRIVE_PATH = re.compile(r"[A-Za-z]:[\\/][^\s<>\"']+")
_UNC_PATH = re.compile(r"\\\\[^\s<>\"']+")
_ROOTED_PATH = re.compile(r"(?:\.\.?|~)?/[A-Za-z0-9_.-][^\s<>\"']*")
_RELATIVE_PATH = re.compile(r"[A-Za-z0-9_.-]+(?:[\\/][A-Za-z0-9_.-]+)+")
_FILE_NAME = re.compile(
    r"(?:\.[A-Za-z0-9_-]+|[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*\.[A-Za-z][A-Za-z0-9]{0,9})"
    r"(?![A-Za-z0-9_/\\]|\.[A-Za-z0-9])"
)


def _closing_ticks(text: str, start: int, count: int) -> int | None:
    """Return the end of a matching CommonMark-style backtick run, if present."""

    cursor = start + count
    while cursor < len(text):
        cursor = text.find("`", cursor)
        if cursor < 0:
            return None
        end = cursor
        while end < len(text) and text[end] == "`":
            end += 1
        if end - cursor == count:
            return end
        cursor = end
    return None


def _closing_destination(text: str, start: int) -> int | None:
    """Find the end of a Markdown link target, including balanced parentheses."""

    depth = 0
    escaped = False
    for cursor in range(start, len(text)):
        char = text[cursor]
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return cursor + 1
        elif char == "\n":
            return None
    return None


def _protected_token(text: str, cursor: int) -> int | None:
    """Return the end of a URL or path beginning here, otherwise None."""

    # Do not mistake a fragment within a normal word for a URL or path.
    if cursor and (text[cursor - 1].isalnum() or text[cursor - 1] == "_"):
        return None

    url = _URL_START.match(text, cursor)
    if url:
        end = url.end()
        while end < len(text) and not text[end].isspace() and text[end] not in '<>"\'':
            end += 1
        return end

    for pattern in (_DRIVE_PATH, _UNC_PATH, _ROOTED_PATH, _RELATIVE_PATH, _FILE_NAME):
        match = pattern.match(text, cursor)
        if match:
            return match.end()
    return None


def _transform_inline(text: str) -> str:
    output: list[str] = []
    cursor = 0
    open_brackets = 0
    while cursor < len(text):
        char = text[cursor]

        if char == "\\" and cursor + 1 < len(text) and not text[cursor + 1].isalnum():
            output.append(text[cursor : cursor + 2])
            cursor += 2
            continue

        if char == "`":
            count = 1
            while cursor + count < len(text) and text[cursor + count] == "`":
                count += 1
            end = _closing_ticks(text, cursor, count)
            if end is not None:
                output.append(text[cursor:end])
                cursor = end
                continue

        if char == "[":
            open_brackets += 1
        elif char == "]" and open_brackets:
            open_brackets -= 1
            if cursor + 1 < len(text):
                if text[cursor + 1] == "(":
                    end = _closing_destination(text, cursor + 1)
                    if end is not None:
                        output.append(text[cursor:end])
                        cursor = end
                        continue
                elif text[cursor + 1] == "[":
                    end = text.find("]", cursor + 2)
                    if end >= 0:
                        output.append(text[cursor : end + 1])
                        cursor = end + 1
                        continue

        if char == "<":
            matched = False
            for pattern in (_AUTOLINK, _HTML_TAG):
                match = pattern.match(text, cursor)
                if match:
                    output.append(match.group())
                    cursor = match.end()
                    matched = True
                    break
            if matched:
                continue

        if char == "&":
            entity = _ENTITY.match(text, cursor)
            if entity:
                output.append(entity.group())
                cursor = entity.end()
                continue

        protected_end = _protected_token(text, cursor)
        if protected_end is not None:
            output.append(text[cursor:protected_end])
            cursor = protected_end
            continue

        output.append(char + _INSERTION if char in _VOWELS else char)
        cursor += 1
    return "".join(output)


def transform_albuquerque_markdown(text: str) -> str:
    """Insert ``Albuquerque`` after each ASCII vowel in visible Markdown prose.

    Fenced and indented code, inline code, link destinations, URL/path tokens,
    HTML tags, and entities are kept byte-for-byte. The original string is the
    only input pass, so inserted text is never transformed again.
    """

    output: list[str] = []
    plain: list[str] = []
    fence_char: str | None = None
    fence_length = 0

    def flush_plain() -> None:
        if plain:
            output.append(_transform_inline("".join(plain)))
            plain.clear()

    for line in text.splitlines(keepends=True):
        fence = _FENCE.match(line)
        if fence_char is not None:
            output.append(line)
            if (
                fence
                and fence.group(1)[0] == fence_char
                and len(fence.group(1)) >= fence_length
                and not line[fence.end() :].strip()
            ):
                fence_char = None
                fence_length = 0
            continue
        if fence:
            flush_plain()
            fence_char = fence.group(1)[0]
            fence_length = len(fence.group(1))
            output.append(line)
            continue
        if line.startswith(("    ", "\t")) or _LINK_DEFINITION.match(line):
            flush_plain()
            output.append(line)
            continue
        plain.append(line)
    flush_plain()
    return "".join(output)
