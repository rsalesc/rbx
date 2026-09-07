"""Tests for reading a template's block names without rendering it.

No package and no fixture: the point of `parse_jinja_block_names` is that it
compiles a template and stops, so a `tmp_path` and a `bytes` are the whole
input it needs.
"""

import pathlib

from rbx.box.statements.render import parse_jinja_block_names


def test_reads_latex_block_names(tmp_path: pathlib.Path):
    content = (
        b'%- block en\nThe answer is 42.\n%- endblock\n'
        b'%- block pt\nA resposta e 42.\n%- endblock\n'
    )

    assert parse_jinja_block_names(tmp_path, content) == ['en', 'pt']


def test_reads_markdown_block_names(tmp_path: pathlib.Path):
    content = b'{% block en %}The answer is 42.{% endblock %}'

    assert parse_jinja_block_names(tmp_path, content, mode='markdown') == ['en']


def test_drops_per_sample_explanation_blocks(tmp_path: pathlib.Path):
    # `render_jinja_blocks` splits these into `explanations`; they are a sample
    # index, never a language.
    content = b'%- block en\nhi\n%- endblock\n%- block explanation_0\nhi\n%- endblock\n'

    assert parse_jinja_block_names(tmp_path, content) == ['en']


def test_a_body_that_would_not_render_still_yields_its_names(tmp_path: pathlib.Path):
    """The whole reason this is not `render_jinja_blocks`.

    A block body referencing a var nothing defines raises on a real render, and
    a coverage check that needed a real render could not run before the vars
    exist -- which is exactly when a setter is authoring explanations.
    """
    content = b'%- block en\n\\VAR{vars.nothing.defines.this}\n%- endblock\n'

    assert parse_jinja_block_names(tmp_path, content) == ['en']


def test_leaves_no_temp_file_in_the_root(tmp_path: pathlib.Path):
    # This runs over every sample of every problem on `rbx summary`; a summary
    # has no business leaving files in the package root.
    parse_jinja_block_names(tmp_path, b'%- block en\nhi\n%- endblock\n')

    assert list(tmp_path.iterdir()) == []
