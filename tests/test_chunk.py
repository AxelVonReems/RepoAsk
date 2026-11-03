from rag.indexing.chunk import Chunk, RepoInfo, chunk_readme


def words(text: str) -> int:
    """Stand-in token counter: one token per whitespace-separated word."""
    return len(text.split())


REPO = RepoInfo("ollama/ollama", "Run LLMs locally", ("llm", "ollama"))


def chunk(text: str, **kwargs) -> list[Chunk]:
    kwargs.setdefault("max_tokens", 20)
    kwargs.setdefault("overlap_tokens", 5)
    kwargs.setdefault("prefix_max_tokens", 50)
    return chunk_readme(text, REPO, words, **kwargs)


def paragraph(n: int, word: str = "w") -> str:
    return " ".join(f"{word}{i}" for i in range(n))


def test_every_chunk_has_the_metadata_prefix():
    chunks = chunk("# Ollama\nRun models.")

    assert len(chunks) == 1
    assert (
        chunks[0].text == "ollama/ollama — Run LLMs locally — llm, ollama\n\n# Ollama\nRun models."
    )
    assert chunks[0].body == "# Ollama\nRun models."


def test_small_sections_are_packed_together():
    readme = "# A\none two\n\n## B\nthree four\n\n## C\nfive six"

    chunks = chunk(readme)

    assert len(chunks) == 1
    assert chunks[0].heading == "A"
    assert "## C" in chunks[0].body


def test_sections_start_a_new_chunk_when_the_budget_is_full():
    readme = f"# A\n{paragraph(12)}\n\n# B\n{paragraph(12)}"

    chunks = chunk(readme)

    assert [c.heading for c in chunks] == ["A", "B"]


def test_heading_path_follows_nesting():
    readme = f"# Download\n{paragraph(15)}\n## macOS\n{paragraph(15)}\n# Usage\n{paragraph(15)}"

    assert [c.heading for c in chunk(readme)] == ["Download", "Download > macOS", "Usage"]


def test_long_section_is_split_with_overlap():
    paragraphs = [paragraph(4, f"p{i}x") for i in range(10)]  # 10 paragraphs x 4 words
    readme = "# Big\n" + "\n\n".join(paragraphs)

    chunks = chunk(readme)

    assert len(chunks) > 1
    assert all(words(c.body) <= 20 for c in chunks), "No body may exceed the budget"
    # The last paragraph of one window reappears at the start of the next
    first_last_para = chunks[0].body.split("\n\n")[-1]
    assert chunks[1].body.startswith(first_last_para)
    assert all(c.heading == "Big" for c in chunks)


def test_long_paragraph_falls_back_to_lines_then_words():
    one_line = paragraph(70)
    chunks = chunk(f"# Wall\n{one_line}")

    assert all(words(c.body) <= 20 for c in chunks)
    assert "w69" in chunks[-1].body, "Nothing at the end may be lost"


def test_giant_word_does_not_loop_forever():
    # One "word" that the counter scores far over budget, like a base64 blob
    def chars(text: str) -> int:
        return len(text)

    chunks = chunk_readme(
        "x" * 500, REPO, chars, max_tokens=50, overlap_tokens=5, prefix_max_tokens=100
    )

    assert "".join(c.body for c in chunks) == "x" * 500
    assert all(len(c.body) <= 50 for c in chunks)


def test_hash_lines_inside_code_blocks_are_not_headings():
    readme = "# Install\n```bash\n# install dependencies\nnpm ci\n```\nDone."

    chunks = chunk(readme)

    assert [c.heading for c in chunks] == ["Install"]
    assert "# install dependencies" in chunks[0].body


def test_text_before_first_heading_has_empty_heading():
    chunks = chunk(f"Intro text.\n# Later\n{paragraph(25)}")

    assert chunks[0].heading == ""
    assert chunks[0].body.startswith("Intro text.")


def test_empty_readme_still_yields_a_prefix_chunk():
    chunks = chunk("")

    assert chunks == [
        Chunk(heading="", body="", text="ollama/ollama — Run LLMs locally — llm, ollama")
    ]


def test_prefix_is_trimmed_to_its_budget():
    repo = RepoInfo("a/b", "word " * 30, tuple(f"t{i}" for i in range(30)))

    chunks = chunk_readme(
        "Body.", repo, words, max_tokens=20, overlap_tokens=5, prefix_max_tokens=10
    )

    prefix = chunks[0].text.split("\n\n")[0]
    assert words(prefix) <= 10
    assert prefix.startswith("a/b — word")


def test_prefix_without_description_or_topics():
    chunks = chunk_readme("Body.", RepoInfo("a/b", None), words, max_tokens=20)

    assert chunks[0].text == "a/b\n\nBody."
