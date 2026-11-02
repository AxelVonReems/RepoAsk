"""Splits a cleaned README into chunks sized for the embedding model.

Sections are found at Markdown headings (outside code blocks). Small consecutive sections
are packed together up to the token budget; a section over the budget is split into
overlapping windows at paragraph, then line, then word boundaries. Every chunk is
prefixed with "repo — description — topics" so repository metadata is searchable too.

Token counting is passed in, so tests can use a word count instead of loading a model.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass

from rag import config
from rag.indexing.clean import split_code_fences

TokenCounter = Callable[[str], int]

HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")


@dataclass(frozen=True)
class RepoInfo:
    full_name: str
    description: str | None
    topics: tuple[str, ...] = ()


@dataclass(frozen=True)
class Chunk:
    heading: str  # heading path, e.g. "Download > macOS"; "" before the first heading
    body: str  # README text, used as the source snippet
    text: str  # prefix + body: what gets embedded


@dataclass(frozen=True)
class _Unit:
    text: str
    separator: str  # what joined this unit to the next one in the original text
    tokens: int


def chunk_readme(
    text: str,
    repo: RepoInfo,
    count_tokens: TokenCounter,
    max_tokens: int = config.CHUNK_MAX_TOKENS,
    overlap_tokens: int = config.CHUNK_OVERLAP_TOKENS,
    prefix_max_tokens: int = config.CHUNK_PREFIX_MAX_TOKENS,
) -> list[Chunk]:
    """Chunks one cleaned README. Body tokens never exceed max_tokens."""
    prefix = _prefix(repo, count_tokens, prefix_max_tokens)
    sections = _sections(text)

    # A README that cleaned down to nothing still gets one chunk, so its description is findable
    if not sections:
        return [Chunk(heading="", body="", text=prefix)]

    pieces = _pack(sections, max_tokens, overlap_tokens, count_tokens)
    return [Chunk(heading=h, body=body, text=f"{prefix}\n\n{body}") for h, body in pieces]


def _prefix(repo: RepoInfo, count_tokens: TokenCounter, max_tokens: int) -> str:
    parts = [repo.full_name]
    if repo.description:
        parts.append(repo.description.strip())
    if repo.topics:
        parts.append(", ".join(repo.topics))
    prefix = " — ".join(parts)

    # Long descriptions or topic lists are trimmed from the end (topics go first)
    words = prefix.split()
    while len(words) > 1 and count_tokens(" ".join(words)) > max_tokens:
        words.pop()
    return " ".join(words)


def _sections(text: str) -> list[tuple[str, str]]:
    """Splits text at Markdown headings into (heading path, section text) pairs."""
    sections: list[tuple[str, str]] = []
    stack: list[tuple[int, str]] = []
    lines: list[str] = []

    def heading_path() -> str:
        return " > ".join(title for _, title in stack)

    def flush() -> None:
        body = "".join(lines).strip()
        if body:
            sections.append((heading_path(), body))
        lines.clear()

    for is_code, block in split_code_fences(text):
        # "# install deps" inside a code block is a shell comment, not a heading
        if is_code:
            lines.append(block)
            continue
        for line in block.splitlines(keepends=True):
            match = HEADING.match(line)
            if match:
                flush()
                level = len(match.group(1))
                while stack and stack[-1][0] >= level:
                    stack.pop()
                stack.append((level, match.group(2)))
            lines.append(line)

    flush()
    return sections


def _pack(
    sections: list[tuple[str, str]],
    max_tokens: int,
    overlap_tokens: int,
    count_tokens: TokenCounter,
) -> list[tuple[str, str]]:
    """Packs small sections together and splits large ones. Returns (heading, body) pairs."""
    chunks: list[tuple[str, str]] = []
    heading, parts, used = "", [], 0

    def flush() -> None:
        nonlocal parts, used
        if parts:
            chunks.append((heading, "\n\n".join(parts)))
        parts, used = [], 0

    for section_heading, body in sections:
        tokens = count_tokens(body)

        if tokens > max_tokens:
            flush()
            for window in _split(body, max_tokens, overlap_tokens, count_tokens):
                chunks.append((section_heading, window))
            continue

        if parts and used + tokens > max_tokens:
            flush()
        if not parts:
            heading = section_heading
        parts.append(body)
        used += tokens

    flush()
    return chunks


def _split(
    text: str, max_tokens: int, overlap_tokens: int, count_tokens: TokenCounter
) -> list[str]:
    """Splits one long section into windows of at most max_tokens, overlapping at the seams."""
    units = _units(text, max_tokens, count_tokens)
    windows: list[str] = []
    start = 0

    while start < len(units):
        end, used = start, 0
        while end < len(units) and used + units[end].tokens <= max_tokens:
            used += units[end].tokens
            end += 1
        # Guarantees progress even if a single unit is somehow over the budget
        end = max(end, start + 1)
        windows.append(_join(units[start:end]))
        if end >= len(units):
            break

        # Step back over trailing units that fit in the overlap, but always move forward
        next_start, overlap = end, 0
        while next_start - 1 > start and overlap + units[next_start - 1].tokens <= overlap_tokens:
            next_start -= 1
            overlap += units[next_start].tokens
        start = next_start

    return windows


def _units(text: str, max_tokens: int, count_tokens: TokenCounter) -> list[_Unit]:
    """Breaks text into pieces no larger than max_tokens: paragraphs, else lines, else words."""
    units: list[_Unit] = []
    for paragraph in text.split("\n\n"):
        tokens = count_tokens(paragraph)
        if tokens <= max_tokens:
            units.append(_Unit(paragraph, "\n\n", tokens))
            continue
        for line in paragraph.split("\n"):
            tokens = count_tokens(line)
            if tokens <= max_tokens:
                units.append(_Unit(line, "\n", tokens))
            else:
                for word in line.split(" "):
                    if word:
                        units.extend(_word_units(word, max_tokens, count_tokens))
        # The last piece of a paragraph is followed by a paragraph break
        last = units[-1]
        units[-1] = _Unit(last.text, "\n\n", last.tokens)
    return units


def _word_units(word: str, max_tokens: int, count_tokens: TokenCounter) -> list[_Unit]:
    """A "word" over the budget (base64, minified code) is cut into character slices."""
    tokens = count_tokens(word)
    if tokens <= max_tokens:
        return [_Unit(word, " ", tokens)]
    size = max(1, len(word) * max_tokens // (tokens * 2))
    return [
        _Unit(word[i : i + size], "", count_tokens(word[i : i + size]))
        for i in range(0, len(word), size)
    ]


def _join(units: list[_Unit]) -> str:
    return "".join(u.text + u.separator for u in units).strip()
