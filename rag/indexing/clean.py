"""Turns raw README Markdown into plain, embeddable text.

Removes what carries no meaning for retrieval (badges, images, HTML wrappers, comments,
link URLs, tables of contents, link walls) and keeps what does: prose, headings, tables
and code blocks. Fenced code and inline code are never modified.
"""

import html
import re

from rag import config

# CommonMark fences: 3+ backticks or tildes; a backtick fence's info string has no backticks
FENCE_OPEN = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")
COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)

# Link text may contain one level of [brackets]; URLs may contain one level of (parens),
# e.g. [[Review] Stacks](https://youtu.be/x) or [Foo](https://en.wikipedia.org/wiki/Foo_(bar))
_TEXT = r"(?:[^\[\]\n]|\[[^\[\]\n]*\])*"
_URL = r"\((?:[^()\n]|\([^()\n]*\))*\)"

# [![alt](img)](link) first, then plain ![alt](img): badges, logos, screenshots
LINKED_IMAGE = re.compile(rf"\[!\[{_TEXT}\]{_URL}\]{_URL}")
IMAGE = re.compile(rf"!\[{_TEXT}\]{_URL}")
HTML_IMAGE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)

# Any HTML tag, also when split over several lines; the text between tags is kept
HTML_TAG = re.compile(r"</?[a-zA-Z][a-zA-Z0-9-]*(?:\s[^<>]*)?/?>")

LINK = re.compile(rf"\[({_TEXT})\]{_URL}")
# Rare: link text wrapped onto the next line
MULTILINE_LINK = re.compile(r"\[([^\[\]]*\n[^\[\]]*)\]\((?:[^()\n]|\([^()\n]*\))*\)")
ANCHOR_LINK = re.compile(rf"\[{_TEXT}\]\(#[^)\n]*\)")
REFERENCE_DEFINITION = re.compile(r"^\s*\[[^\]]+\]:\s*\S+.*$")

# Images in the other README formats GitHub renders (reStructuredText, AsciiDoc)
RST_IMAGE = re.compile(r"^\.\. (?:\|[^|]+\| )?(?:image|figure)::")
RST_OPTION = re.compile(r"^\s+:(?:target|alt|width|height|align|scale|class):")
ASCIIDOC_IMAGE = re.compile(r"image::?\S+?\[[^\]\n]*\]")

# Inline code is swapped for a placeholder while cleaning, then restored verbatim
INLINE_CODE = re.compile(r"`[^`\n]+`")
PLACEHOLDER = re.compile(r"\x00(\d+)\x00")

# A line with at least this many links and almost no other text is navigation, not content
LINK_WALL_MIN_LINKS = 3
LINK_WALL_MAX_OTHER_CHARS = 20


def clean_readme(text: str, max_bytes: int = config.README_MAX_BYTES) -> str:
    """Cleans README Markdown and truncates the result to at most max_bytes (UTF-8)."""
    text = COMMENT.sub("", text)
    parts = []
    for is_code, block in split_code_fences(text):
        parts.append(block if is_code else _clean_prose(block))
    return _truncate("".join(parts).strip(), max_bytes)


def split_code_fences(text: str) -> list[tuple[bool, str]]:
    """Splits text into (is_code, block) segments on ``` / ~~~ fences, keeping the fences.

    Follows CommonMark: a fence closes only with the same character, at least as many
    times as it opened, so ```` can wrap an example that itself contains ```.
    """
    segments: list[tuple[bool, str]] = []
    current: list[str] = []
    open_marker: str | None = None

    for line in text.splitlines(keepends=True):
        if open_marker is None:
            opening = _fence_opening(line)
            if opening:
                segments.append((False, "".join(current)))
                current = [line]
                open_marker = opening
            else:
                current.append(line)
        else:
            current.append(line)
            if _closes_fence(line, open_marker):
                segments.append((True, "".join(current)))
                current = []
                open_marker = None

    # An unclosed fence keeps the rest as code, like GitHub renders it
    segments.append((open_marker is not None, "".join(current)))
    return segments


def _fence_opening(line: str) -> str | None:
    match = FENCE_OPEN.match(line)
    if not match:
        return None
    marker, info = match.groups()
    # ```code``` on one line is inline code, not a fence
    if marker[0] == "`" and "`" in info:
        return None
    return marker


def _closes_fence(line: str, marker: str) -> bool:
    stripped = line.strip()
    return len(stripped) >= len(marker) and set(stripped) == {marker[0]}


def _clean_prose(block: str) -> str:
    code_spans: list[str] = []

    def stash(match: re.Match[str]) -> str:
        code_spans.append(match.group(0))
        return f"\x00{len(code_spans) - 1}\x00"

    block = INLINE_CODE.sub(stash, block)

    # Constructs that can span lines are removed from the whole block first
    block = LINKED_IMAGE.sub("", block)
    block = IMAGE.sub("", block)
    block = HTML_IMAGE.sub("", block)
    block = HTML_TAG.sub("", block)
    block = ASCIIDOC_IMAGE.sub("", block)
    block = MULTILINE_LINK.sub(r"\1", block)

    lines = [_clean_line(line) for line in block.splitlines()]
    cleaned = "\n".join(line for line in lines if line is not None)
    # Collapse the blank runs left behind by removed lines
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned) + "\n"

    return PLACEHOLDER.sub(lambda m: code_spans[int(m.group(1))], cleaned)


def _clean_line(line: str) -> str | None:
    """Returns the cleaned line, or None when the whole line is noise."""
    if any(p.match(line) for p in (REFERENCE_DEFINITION, RST_IMAGE, RST_OPTION)):
        return None
    if _is_navigation(line):
        return None
    return html.unescape(LINK.sub(r"\1", line)).rstrip()


def _is_navigation(text: str) -> bool:
    """Table-of-contents lines and link walls (badge rows, language switchers, nav bars)."""
    links = LINK.findall(text)
    if not links:
        return False

    without_links = LINK.sub("", text)
    other_chars = re.sub(r"[\s\-*•·|/,>]+", "", without_links)

    if ANCHOR_LINK.search(text) and len(other_chars) == 0:
        return True
    return len(links) >= LINK_WALL_MIN_LINKS and len(other_chars) <= LINK_WALL_MAX_OTHER_CHARS


def _truncate(text: str, max_bytes: int) -> str:
    """Cuts to max_bytes without splitting a UTF-8 character, preferably at a line break."""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text

    cut = encoded[:max_bytes].decode("utf-8", errors="ignore")
    last_newline = cut.rfind("\n")
    # Prefer a clean line boundary unless it would throw away most of the budget
    if last_newline > len(cut) // 2:
        cut = cut[:last_newline]
    return cut.rstrip()
