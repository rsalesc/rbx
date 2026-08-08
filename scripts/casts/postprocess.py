"""Post-processing of a recorded asciicast: scrubbing and verification.

An asciicast v2 file is a JSON header object on the first line followed by one
JSON array per line, each ``[time, code, data]`` where ``code`` is ``o``
(output), ``i`` (input) or ``m`` (marker).
"""

import json
from typing import List, Optional

# Environment variables worth keeping in the published header. Everything else
# describes the recording machine, not the demo.
_KEEP_ENV = ('TERM', 'SHELL')


class CastVerificationError(Exception):
    pass


def _scrub_str(value: str, tmpdir: str, display_root: str, home: Optional[str]) -> str:
    if home:
        value = value.replace(home, '~')
    return value.replace(tmpdir, display_root)


def scrub_cast(
    raw: str,
    tmpdir: str,
    display_root: str,
    home: Optional[str] = None,
    title: Optional[str] = None,
) -> str:
    lines = raw.splitlines()
    if not lines:
        raise ValueError('empty cast')

    header = json.loads(lines[0])
    header.pop('timestamp', None)
    header.pop('idle_time_limit', None)
    header['env'] = {
        key: value
        for key, value in (header.get('env') or {}).items()
        if key in _KEEP_ENV
    }
    header['env'].setdefault('TERM', 'xterm-256color')
    if title is not None:
        header['title'] = title

    out = [json.dumps(header, sort_keys=True)]
    for line in lines[1:]:
        if not line.strip():
            continue
        event = json.loads(line)
        event[2] = _scrub_str(event[2], tmpdir, display_root, home)
        out.append(json.dumps(event))
    return '\n'.join(out) + '\n'


def cast_text(raw: str) -> str:
    chunks: List[str] = []
    for line in raw.splitlines()[1:]:
        if not line.strip():
            continue
        event = json.loads(line)
        if event[1] == 'o':
            chunks.append(event[2])
    return ''.join(chunks)


def verify_cast(raw: str, expectations: List[str], name: str) -> None:
    text = cast_text(raw)
    missing = [expected for expected in expectations if expected not in text]
    if missing:
        raise CastVerificationError(
            f'recording `{name}` is missing {len(missing)} expected string(s): '
            + ', '.join(repr(item) for item in missing)
            + '\nThe CLI output likely changed. Watch the cast and update the spec.'
        )
