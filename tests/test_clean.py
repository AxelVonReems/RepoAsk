from rag.indexing.clean import clean_readme


def test_removes_badges_and_images():
    readme = (
        "# Tool\n"
        "[![npm](https://img.shields.io/npm/v/x.svg)](https://npmjs.com/x) "
        "![build](https://ci/badge.svg)\n"
        '<img src="logo.png" alt="logo" width="200"/>\n'
        "A fast tool."
    )
    assert clean_readme(readme) == "# Tool\n\nA fast tool."


def test_strips_html_tags_but_keeps_their_text():
    readme = (
        '<p align="center">\n  <b>Fast</b> &amp; small\n</p>\n'
        "<details><summary>More</summary>Hidden text</details>"
    )

    cleaned = clean_readme(readme)

    assert "<" not in cleaned
    assert "Fast & small" in cleaned
    assert "MoreHidden text" in cleaned


def test_removes_html_comments():
    assert clean_readme("Intro\n<!-- TODO: fill in\nmore -->\nBody") == "Intro\n\nBody"


def test_replaces_links_with_their_text():
    readme = "Uses [Visual Studio Code](https://code.visualstudio.com) daily."
    assert clean_readme(readme) == "Uses Visual Studio Code daily."


def test_drops_reference_link_definitions():
    readme = "See [docs][1].\n\n[1]: https://example.com/docs"
    assert "https://" not in clean_readme(readme)


def test_drops_table_of_contents_lines():
    readme = "## Contents\n- [Install](#install)\n  - [macOS](#macos)\n\n## Install\nRun it."

    cleaned = clean_readme(readme)

    assert "## Contents" in cleaned
    assert "## Install" in cleaned
    assert "macOS" not in cleaned


def test_drops_link_walls():
    readme = (
        "**English** · [简体中文](zh.md) · [日本語](ja.md) · [Deutsch](de.md)\n"
        "[Docs](https://d) | [Discord](https://c) | [Twitter](https://t)\n"
        "Real content."
    )
    assert clean_readme(readme) == "Real content."


def test_keeps_list_items_with_descriptions():
    readme = "- [Node.js](https://github.com/x/awesome-nodejs) - Event-driven JavaScript runtime."
    assert clean_readme(readme) == "- Node.js - Event-driven JavaScript runtime."


def test_links_with_inline_code_or_brackets_in_text():
    readme = (
        "- [Useful `.htaccess` Snippets](https://github.com/phanan/htaccess#readme)\n"
        "- [ ] [[Review] Stacks in 3 minutes (video)](https://youtu.be/KcT3aVgrrpU)\n"
        "See [Foo](https://en.wikipedia.org/wiki/Foo_(bar)) too."
    )

    cleaned = clean_readme(readme)

    assert "](" not in cleaned
    assert "- Useful `.htaccess` Snippets" in cleaned
    assert "- [ ] [Review] Stacks in 3 minutes (video)" in cleaned
    assert "See Foo too." in cleaned


def test_link_text_wrapped_over_two_lines():
    readme = "> I got hired [as an engineer\n> at Amazon](https://example.com/story)!"
    assert clean_readme(readme) == "> I got hired as an engineer\n> at Amazon!"


def test_html_tags_spanning_several_lines():
    readme = (
        '<a href="https://discord.gg/x">\n'
        "    <img\n"
        '        src="https://img.shields.io/discord/1?logo=discord"\n'
        '        alt="chat on Discord"></a>\n'
        "Dify is an LLM app platform."
    )
    assert clean_readme(readme) == "Dify is an LLM app platform."


def test_code_blocks_and_inline_code_are_untouched():
    readme = (
        "Render with `<App />` like this:\n"
        "```jsx\n"
        '<div className="x">[link](#anchor) ![img](a.png)</div>\n'
        "```\n"
        "Done."
    )

    cleaned = clean_readme(readme)

    assert "`<App />`" in cleaned
    assert '<div className="x">[link](#anchor) ![img](a.png)</div>' in cleaned


def test_triple_backtick_inline_code_is_not_a_fence():
    readme = "Run ```youtube-dl 'url'``` now.\nSee [docs](https://example.com)."
    assert clean_readme(readme) == "Run ```youtube-dl 'url'``` now.\nSee docs."


def test_longer_fence_wraps_inner_triple_backticks():
    readme = (
        "````markdown\n"
        "```\n"
        "[kept](https://example.com)\n"
        "```\n"
        "````\n"
        "After [link](https://example.com)."
    )

    cleaned = clean_readme(readme)

    assert "[kept](https://example.com)" in cleaned
    assert cleaned.endswith("After link.")


def test_rst_and_asciidoc_images_removed():
    readme = (
        ".. image:: https://img.shields.io/discord/1.svg\n"
        "   :target: https://discord.gg/x\n"
        'image:https://ci/badge.svg["Build", link=https://ci]\n'
        "Home Assistant is home automation."
    )
    assert clean_readme(readme) == "Home Assistant is home automation."


def test_unclosed_fence_keeps_rest_as_code():
    readme = "Intro\n```\n<b>not html</b>"
    assert "<b>not html</b>" in clean_readme(readme)


def test_collapses_blank_runs():
    assert clean_readme("A\n\n\n\n\nB") == "A\n\nB"


def test_truncates_to_byte_limit_at_line_boundary():
    readme = "\n".join(f"line {i:03d}" for i in range(100))

    cleaned = clean_readme(readme, max_bytes=200)

    assert len(cleaned.encode("utf-8")) <= 200
    assert cleaned.endswith(cleaned.splitlines()[-1])
    assert cleaned.splitlines()[-1].startswith("line ")


def test_truncation_never_splits_a_multibyte_character():
    cleaned = clean_readme("é" * 100, max_bytes=51)

    assert len(cleaned.encode("utf-8")) <= 51
    assert cleaned == "é" * 25


def test_short_readme_is_not_truncated():
    assert clean_readme("# Small\nTiny README.", max_bytes=30_000) == "# Small\nTiny README."
