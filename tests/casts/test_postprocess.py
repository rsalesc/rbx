import json

import pytest

from scripts.casts.postprocess import (
    CastVerificationError,
    cast_text,
    scrub_cast,
    verify_cast,
)


def _cast(*outputs: str) -> str:
    lines = [
        json.dumps(
            {
                'version': 2,
                'width': 100,
                'height': 30,
                'timestamp': 1234,
                'env': {'SHELL': '/bin/bash', 'USER': 'me'},
            }
        )
    ]
    for index, output in enumerate(outputs):
        lines.append(json.dumps([index * 0.5, 'o', output]))
    return '\n'.join(lines) + '\n'


def test_scrub_rewrites_the_tmpdir_to_a_stable_path():
    raw = _cast('$ pwd\r\n/private/var/folders/ab/T/tmpxyz/ab-problem\r\n')

    scrubbed = scrub_cast(
        raw, tmpdir='/private/var/folders/ab/T/tmpxyz', display_root='~/problems'
    )

    assert '/private/var/folders' not in scrubbed
    assert '~/problems/ab-problem' in scrubbed


def test_scrub_rewrites_the_home_directory_too():
    raw = _cast('cache at /tmp/rec-home/.cache/rbx\r\n')

    scrubbed = scrub_cast(
        raw, tmpdir='/nope', display_root='~/problems', home='/tmp/rec-home'
    )

    assert '/tmp/rec-home' not in scrubbed
    assert '~/.cache/rbx' in scrubbed


def test_scrub_sets_a_stable_header():
    raw = _cast('hello\r\n')

    scrubbed = scrub_cast(
        raw, tmpdir='/nope', display_root='~/problems', title='Running solutions'
    )

    header = json.loads(scrubbed.splitlines()[0])
    assert header['title'] == 'Running solutions'
    assert 'timestamp' not in header
    assert header['env'] == {'TERM': 'xterm-256color', 'SHELL': '/bin/bash'}


def test_scrub_leaves_event_timings_untouched():
    raw = _cast('a\r\n', 'b\r\n')

    scrubbed = scrub_cast(raw, tmpdir='/nope', display_root='~/problems')

    events = [json.loads(line) for line in scrubbed.splitlines()[1:]]
    assert [event[0] for event in events] == [0.0, 0.5]


def test_cast_text_concatenates_output_events_only():
    raw = '\n'.join(
        [
            json.dumps({'version': 2, 'width': 100, 'height': 30}),
            json.dumps([0.0, 'o', 'Accep']),
            json.dumps([0.1, 'i', 'x']),
            json.dumps([0.2, 'o', 'ted']),
        ]
    )

    assert cast_text(raw) == 'Accepted'


def test_verify_passes_when_every_expectation_appears():
    verify_cast(_cast('Accepted\r\n'), ['Accepted'], name='run-basic')


def test_verify_reports_every_missing_expectation():
    with pytest.raises(CastVerificationError) as excinfo:
        verify_cast(
            _cast('Accepted\r\n'), ['Accepted', 'Wrong answer'], name='run-basic'
        )

    message = str(excinfo.value)
    assert 'run-basic' in message
    assert "'Wrong answer'" in message
    assert "'Accepted'" not in message


def test_scrub_strips_volatile_osc8_hyperlink_ids():
    raw = _cast('\x1b]8;id=660217;file:///wd/gen.cpp\x1b\\gen.cpp\x1b]8;;\x1b\\\r\n')

    scrubbed = scrub_cast(raw, tmpdir='/wd', display_root='~/problems')

    assert 'id=660217' not in scrubbed
    assert '\\u001b]8;;file:///~/problems/gen.cpp' in scrubbed or 'gen.cpp' in scrubbed


def test_scrub_is_idempotent():
    raw = _cast('\x1b]8;id=1;file:///wd/a\x1b\\a\r\n/wd/b\r\n')

    once = scrub_cast(raw, tmpdir='/wd', display_root='~/problems')
    twice = scrub_cast(once, tmpdir='/wd', display_root='~/problems')

    assert once == twice
