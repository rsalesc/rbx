"""Post-processing of a recorded asciicast: scrubbing and verification.

An asciicast v2 file is a JSON header object on the first line followed by one
JSON array per line, each ``[time, code, data]`` where ``code`` is ``o``
(output), ``i`` (input) or ``m`` (marker).
"""

import json
import re
from typing import List, Optional, Sequence

# Rich emits OSC-8 hyperlinks carrying a random `id=NNNN` that changes on every
# run. Left alone, an otherwise identical re-recording would diff on every
# clickable path. The id is decoration -- the link still works without it.
_OSC8_ID = re.compile(r'\x1b]8;id=\d+;')

# Environment variables worth keeping in the published header. Everything else
# describes the recording machine, not the demo.
_KEEP_ENV = ('TERM', 'SHELL')

# Where a residual scratch path is rewritten to. The random directory name is
# dropped along with the machine-specific temp root, so re-recordings agree.
SCRATCH_ROOT = '/tmp/scratch'


class CastVerificationError(Exception):
    pass


def _scrub_str(
    value: str,
    tmpdir: str,
    display_root: str,
    home: Optional[str],
    scratch: Optional[re.Pattern],
) -> str:
    if home:
        value = value.replace(home, '~')
    # The recording's own tmpdir first: it also lives under the temp root, and
    # it is the one path with a meaningful name to show.
    value = value.replace(tmpdir, display_root)
    if scratch is not None:
        value = scratch.sub(SCRATCH_ROOT, value)
    return _OSC8_ID.sub('\x1b]8;;', value)


def scrub_cast(
    raw: str,
    tmpdir: str,
    display_root: str,
    home: Optional[str] = None,
    title: Optional[str] = None,
    temp_roots: Sequence[str] = (),
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

    # rbx creates its own temp directories (`rbx validate` stages the typed
    # testcase in one), which are siblings of the recording's tmpdir rather
    # than children -- so the rewrite above never reaches them.
    # More than one root because macOS reports the same directory as both
    # `/var/folders/...` and `/private/var/folders/...` depending on whether
    # the path was resolved; a cast can contain either spelling.
    alternatives = '|'.join(
        re.escape(root.rstrip('/')) for root in sorted(set(temp_roots), reverse=True)
    )
    scratch = (
        re.compile(f'(?:{alternatives})' + r'/[^/\s"\')\]]+') if alternatives else None
    )

    out = [json.dumps(header, sort_keys=True)]
    for line in lines[1:]:
        if not line.strip():
            continue
        event = json.loads(line)
        event[2] = _scrub_str(event[2], tmpdir, display_root, home, scratch)
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
