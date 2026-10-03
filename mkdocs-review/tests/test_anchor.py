from mkdocs_review.anchor import (
    Anchor,
    anchor_comment,
    build_review,
    parse_unified_diff,
    strip_markdown,
)

DIFF = """\
diff --git a/docs/guide.md b/docs/guide.md
index 1111111..2222222 100644
--- a/docs/guide.md
+++ b/docs/guide.md
@@ -1,5 +1,6 @@
 # Guide

-Run the old command to build
+Run the **new** command to build
 your problem.
+Then read the [output](out.md) carefully.

diff --git a/docs/_partials/note.md b/docs/_partials/note.md
new file mode 100644
--- /dev/null
+++ b/docs/_partials/note.md
@@ -0,0 +1,2 @@
+!!! note
+    Partials are shared between many pages.
diff --git a/docs/gone.md b/docs/gone.md
deleted file mode 100644
--- a/docs/gone.md
+++ /dev/null
@@ -1 +0,0 @@
-This page was removed entirely.
"""


def test_parse_unified_diff():
    files = parse_unified_diff(DIFF)
    assert set(files) == {'docs/guide.md', 'docs/_partials/note.md', 'docs/gone.md'}
    guide = files['docs/guide.md']
    assert [(ln.kind, ln.old, ln.new) for ln in guide.lines] == [
        (' ', 1, 1),
        (' ', 2, 2),
        ('-', 3, None),
        ('+', None, 3),
        (' ', 4, 4),
        ('+', None, 5),
        (' ', 5, 6),
    ]
    assert guide.lines[3].text == 'Run the **new** command to build'
    assert files['docs/gone.md'].lines[0].old == 1


def test_parse_renamed_file():
    files = parse_unified_diff(
        'diff --git a/docs/a.md b/docs/b.md\n'
        'similarity index 90%\n'
        'rename from docs/a.md\n'
        'rename to docs/b.md\n'
        '--- a/docs/a.md\n'
        '+++ b/docs/b.md\n'
        '@@ -1 +1 @@\n'
        '-x\n'
        '+y\n'
    )
    assert set(files) == {'docs/b.md'}
    assert files['docs/b.md'].old_path == 'docs/a.md'


def test_strip_markdown():
    assert strip_markdown('- Read the [docs](a/b.md){: .x } and `code`') == (
        'Read the docs and code'
    )
    assert strip_markdown('## Heading {#id}') == 'Heading'


def test_anchor_prefers_added_line_with_changed_words():
    files = parse_unified_diff(DIFF)
    anchor = anchor_comment(
        files,
        side='head',
        source='docs/guide.md',
        block_text='Run the new command to build your problem.',
        words=['new'],
    )
    assert anchor == Anchor('docs/guide.md', 3, 'RIGHT')


def test_anchor_base_side_uses_removed_lines():
    files = parse_unified_diff(DIFF)
    anchor = anchor_comment(
        files,
        side='base',
        source='docs/guide.md',
        block_text='Run the old command to build your problem.',
        words=['old'],
    )
    assert anchor == Anchor('docs/guide.md', 3, 'LEFT')


def test_anchor_falls_back_to_context_lines_of_the_source():
    files = parse_unified_diff(DIFF)
    anchor = anchor_comment(
        files, side='head', source='docs/guide.md', block_text='Guide', words=[]
    )
    assert anchor == Anchor('docs/guide.md', 1, 'RIGHT')


def test_anchor_searches_other_files_when_page_source_is_unchanged():
    files = parse_unified_diff(DIFF)
    anchor = anchor_comment(
        files,
        side='head',
        source='docs/index.md',
        block_text='Partials are shared between many pages.',
        words=['shared'],
    )
    assert anchor == Anchor('docs/_partials/note.md', 2, 'RIGHT')


def test_anchor_gives_up_without_a_good_match():
    files = parse_unified_diff(DIFF)
    assert (
        anchor_comment(
            files,
            side='head',
            source='docs/index.md',
            block_text='Completely unrelated sentence about cats.',
            words=['cats'],
        )
        is None
    )


def test_build_review():
    payload = build_review(
        [
            {
                'anchor': Anchor('docs/guide.md', 3, 'RIGHT'),
                'source': 'docs/guide.md',
                'page': 'guide/index.html',
                'quote': 'Run the new command',
                'body': 'Nice.',
            },
            {
                'anchor': Anchor('docs/_partials/note.md', 2, 'RIGHT'),
                'source': 'docs/index.md',
                'page': 'index.html',
                'quote': 'Partials are shared',
                'body': 'Typo?',
            },
            {
                'anchor': None,
                'source': 'docs/index.md',
                'page': 'index.html',
                'quote': 'Some text',
                'body': 'Unclear.',
            },
        ],
        head_sha='abc',
        summary='Looks good overall.',
    )
    assert payload['commit_id'] == 'abc'
    assert payload['event'] == 'COMMENT'
    assert payload['comments'] == [
        {'path': 'docs/guide.md', 'line': 3, 'side': 'RIGHT', 'body': 'Nice.'},
        {
            'path': 'docs/_partials/note.md',
            'line': 2,
            'side': 'RIGHT',
            'body': 'On `index.html`:\n> Partials are shared\n\nTypo?',
        },
    ]
    assert payload['body'] == (
        'Looks good overall.\n\n---\n\nOn `index.html`:\n> Some text\n\nUnclear.'
    )
