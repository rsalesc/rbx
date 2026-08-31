"""Routing edits into the fragment that owns the value being edited."""

import pytest

from rbx.box.yaml_include import (
    EditSession,
    IncludeError,
    including_files,
    open_for_edit,
)


def test_edits_the_parent_file_when_the_key_is_inline(tmp_path):
    main = tmp_path / 'contest.rbx.yml'
    main.write_text('name: c\nproblems:\n- short_name: A\n')

    target = open_for_edit(main, 'problems')
    assert target.path == main
    target.value.append({'short_name': 'B'})
    target.save()

    assert 'short_name: B' in main.read_text()


def test_routes_the_edit_into_the_included_fragment(tmp_path):
    frag = tmp_path / 'shared.yml'
    frag.write_text('- short_name: A\n')
    main = tmp_path / 'contest.rbx.yml'
    main.write_text('name: c\nproblems: !include shared.yml\n')

    target = open_for_edit(main, 'problems')
    assert target.path == frag
    target.value.append({'short_name': 'B'})
    target.save()

    assert 'short_name: B' in frag.read_text()
    # The including file is untouched: the tag survives.
    assert main.read_text() == 'name: c\nproblems: !include shared.yml\n'


def test_routing_preserves_comments_in_the_fragment(tmp_path):
    frag = tmp_path / 'shared.yml'
    frag.write_text('# keep me\n- short_name: A\n')
    main = tmp_path / 'contest.rbx.yml'
    main.write_text('problems: !include shared.yml\n')

    target = open_for_edit(main, 'problems')
    target.value.append({'short_name': 'B'})
    target.save()

    assert '# keep me' in frag.read_text()


def test_follows_a_chain_of_includes_to_the_owning_file(tmp_path):
    inner = tmp_path / 'inner.yml'
    inner.write_text('- short_name: A\n')
    outer = tmp_path / 'outer.yml'
    outer.write_text('!include inner.yml\n')
    main = tmp_path / 'contest.rbx.yml'
    main.write_text('problems: !include outer.yml\n')

    target = open_for_edit(main, 'problems')

    assert target.path == inner


def test_descends_several_keys_before_routing(tmp_path):
    frag = tmp_path / 'titles.yml'
    frag.write_text('pt: hello\n')
    main = tmp_path / 'contest.rbx.yml'
    main.write_text('a:\n  b: !include titles.yml\n')

    target = open_for_edit(main, 'a', 'b')

    assert target.path == frag
    assert dict(target.value) == {'pt': 'hello'}


def test_missing_key_reports_no_value_and_can_be_created(tmp_path):
    main = tmp_path / 'contest.rbx.yml'
    main.write_text('name: c\n')

    target = open_for_edit(main, 'problems')
    assert target.value is None

    target.replace([{'short_name': 'A'}])
    target.save()

    assert 'short_name: A' in main.read_text()


def test_replace_on_a_routed_target_rewrites_the_fragment(tmp_path):
    frag = tmp_path / 'shared.yml'
    frag.write_text('- short_name: A\n')
    main = tmp_path / 'contest.rbx.yml'
    main.write_text('problems: !include shared.yml\n')

    target = open_for_edit(main, 'problems')
    target.replace([{'short_name': 'Z'}])
    target.save()

    assert 'short_name: Z' in frag.read_text()
    assert 'short_name: A' not in frag.read_text()
    assert '!include shared.yml' in main.read_text()


def test_a_file_using_the_merge_form_can_still_be_opened(tmp_path):
    """Plain ruyaml chokes on `<<: !include`; the editor must not."""
    (tmp_path / 'vars.yml').write_text('year: 2026\n')
    main = tmp_path / 'contest.rbx.yml'
    main.write_text('vars:\n  <<: !include vars.yml\n  warmup: true\nproblems: []\n')

    target = open_for_edit(main, 'problems')

    assert target.path == main
    assert list(target.value) == []


def test_editing_a_key_that_only_exists_via_a_merge_include_is_refused(tmp_path):
    """The value lives in the fragment's map, which this file merges wholesale."""
    (tmp_path / 'vars.yml').write_text('year: 2026\n')
    main = tmp_path / 'contest.rbx.yml'
    main.write_text('vars:\n  <<: !include vars.yml\n  warmup: true\n')

    with pytest.raises(IncludeError) as exc:
        open_for_edit(main, 'vars', 'year')

    message = str(exc.value)
    assert 'vars.yml' in message
    assert 'year' in message


def test_missing_fragment_is_reported(tmp_path):
    main = tmp_path / 'contest.rbx.yml'
    main.write_text('problems: !include nope.yml\n')

    with pytest.raises(IncludeError):
        open_for_edit(main, 'problems')


# ------------------------------- blast radius ---------------------------------


def test_including_files_finds_every_contest_reaching_a_fragment(tmp_path):
    frag = tmp_path / 'shared.yml'
    frag.write_text('- short_name: A\n')
    (tmp_path / 'contest.rbx.yml').write_text('problems: !include shared.yml\n')
    (tmp_path / 'contest.warmup.rbx.yml').write_text('problems: !include shared.yml\n')
    (tmp_path / 'contest.other.rbx.yml').write_text('problems: []\n')

    reachers = including_files(frag, tmp_path)

    assert {p.name for p in reachers} == {
        'contest.rbx.yml',
        'contest.warmup.rbx.yml',
    }


def test_including_files_follows_transitive_includes(tmp_path):
    inner = tmp_path / 'inner.yml'
    inner.write_text('- short_name: A\n')
    (tmp_path / 'outer.yml').write_text('!include inner.yml\n')
    (tmp_path / 'contest.rbx.yml').write_text('problems: !include outer.yml\n')

    reachers = including_files(inner, tmp_path)

    assert {p.name for p in reachers} == {'contest.rbx.yml'}


def test_including_files_returns_empty_for_an_unshared_file(tmp_path):
    lonely = tmp_path / 'lonely.yml'
    lonely.write_text('a: 1\n')
    (tmp_path / 'contest.rbx.yml').write_text('problems: []\n')

    assert including_files(lonely, tmp_path) == []


# -------------------------------- sessions ------------------------------------


def test_session_shares_one_tree_per_file_so_edits_do_not_clobber(tmp_path):
    """Two independent opens of the same file would each save a stale tree."""
    main = tmp_path / 'problem.rbx.yml'
    main.write_text('timeLimit: 1000\nmemoryLimit: 256\n')

    session = EditSession(main)
    session.target('timeLimit').replace(2000)
    session.target('memoryLimit').replace(512)
    session.save()

    text = main.read_text()
    assert 'timeLimit: 2000' in text
    assert 'memoryLimit: 512' in text


def test_session_writes_every_file_an_edit_touched(tmp_path):
    (tmp_path / 'mods.yml').write_text('cpp:\n  time: 1\n')
    main = tmp_path / 'problem.rbx.yml'
    main.write_text('timeLimit: 1000\nmodifiers: !include mods.yml\n')

    session = EditSession(main)
    session.target('timeLimit').replace(2000)
    session.target('modifiers', 'cpp', 'time').replace(9)
    session.save()

    assert 'timeLimit: 2000' in main.read_text()
    assert 'time: 9' in (tmp_path / 'mods.yml').read_text()
    # The include survives in the parent.
    assert '!include mods.yml' in main.read_text()


def test_session_reports_which_files_it_would_write(tmp_path):
    (tmp_path / 'mods.yml').write_text('cpp:\n  time: 1\n')
    main = tmp_path / 'problem.rbx.yml'
    main.write_text('timeLimit: 1000\nmodifiers: !include mods.yml\n')

    session = EditSession(main)
    session.target('timeLimit').replace(2000)
    session.target('modifiers', 'cpp', 'time').replace(9)

    assert session.touched_files() == {
        main.resolve(),
        (tmp_path / 'mods.yml').resolve(),
    }


def test_session_saves_nothing_when_no_edit_was_made(tmp_path):
    main = tmp_path / 'problem.rbx.yml'
    original = 'timeLimit: 1000\n'
    main.write_text(original)

    session = EditSession(main)
    session.target('timeLimit')  # read only
    session.save()

    assert main.read_text() == original


def test_including_files_ignores_a_broken_sibling(tmp_path):
    """One unparseable contest must not stop the blast-radius scan."""
    frag = tmp_path / 'shared.yml'
    frag.write_text('- short_name: A\n')
    (tmp_path / 'contest.rbx.yml').write_text('problems: !include shared.yml\n')
    (tmp_path / 'contest.broken.rbx.yml').write_text('problems: [unterminated\n')

    reachers = including_files(frag, tmp_path)

    assert {p.name for p in reachers} == {'contest.rbx.yml'}
