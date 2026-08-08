# Asciinema Recording Pipeline Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the manual record-upload-paste-an-ID workflow with committed, regenerable
`.cast` files produced from YAML specs by a single local command.

**Architecture:** Recording specs and fixture packages live in `casts/` (outside `docs/`, so
MkDocs does not copy them into the built site). A Python wrapper in `scripts/casts/` copies a
fixture to a tmpdir, normalizes the environment, drives the external `autocast` binary, scrubs
machine-specific paths out of the result, and writes `docs/assets/casts/<name>.cast`. The
`asciinema()` MkDocs macro in `main.py` renders a vendored `asciinema-player` instance pointed
at that local file, while still accepting legacy asciinema.org IDs so pages migrate one at a
time.

**Tech Stack:** Python 3, Pydantic v2, PyYAML, pytest, MkDocs + `mkdocs-macros-plugin`,
[autocast](https://github.com/k9withabone/autocast) (external Rust binary),
[asciinema-player](https://github.com/asciinema/asciinema-player) v3.17.0 (vendored JS/CSS).

**Design doc:** `docs/plans/2026-08-08-asciinema-recording-pipeline-design.md`

---

## Background the implementer needs

### What autocast is

`autocast <input.yaml> <output.cast>` spawns a real shell in a pty, types each instruction,
and waits for the shell prompt before moving on. Its input schema (see
[`full-example.yaml`](https://github.com/k9withabone/autocast/blob/main/full-example.yaml)) has
two top-level keys, `settings` and `instructions`. Instructions are YAML tagged unions:
`!Command`, `!Interactive`, `!Wait`, `!Marker`, `!Clear`.

Two non-obvious details that the wrapper must get right:

1. **`settings.shell.prompt` must match the shell's *actual* prompt string**, because autocast
   detects command completion by matching it. The canonical trick from `full-example.yaml` is to
   force a sentinel prompt via `PROMPT_COMMAND`:

   ```yaml
   environment:
     - name: PROMPT_COMMAND
       value: "PS1=AUTOCAST_PROMPT; unset PROMPT_COMMAND; bind 'set enable-bracketed-paste off'"
   ```

   and set `shell.prompt: AUTOCAST_PROMPT`. `settings.prompt` (a separate key) is the *cosmetic*
   prompt written into the cast — that is what viewers see.

2. **`settings.shell.quit_command`** must be set (`exit`), or autocast hangs after the last
   instruction.

### Why the wrapper exists

autocast records whatever the shell prints, including the tmpdir it runs in. Without
post-processing, published casts contain `/private/var/folders/xy/…/T/tmpab12cd/` and whatever
`PS1`/locale/env the recording machine happened to have. Steps 2 and 4 of the wrapper
(normalize, scrub) are the difference between a reproducible artifact and a snapshot of one
laptop.

### Asciicast format

autocast emits **asciicast v2**: a JSON header object on line 1, then one JSON array per line,
each `[time, "o"|"i"|"m", data]`. The player supports v2 and v3. All parsing in this plan is
line-oriented JSON — do not pull in an asciicast library.

### Repo conventions

- Single quotes, absolute imports only, `ruff check .` and `ruff format .` must pass.
- Commits follow Conventional Commits — use the `/commit` skill (`.claude/skills/commit.md`).
- Wheel packaging is `packages = ["rbx"]`, so nothing under `scripts/` ships. Safe to put
  tooling there.
- Run tests with `uv run pytest`.

---

## Task 1: Make `scripts/` importable from tests

**Files:**
- Create: `scripts/__init__.py` (empty)
- Create: `scripts/casts/__init__.py` (empty)
- Modify: `pytest.ini`

**Step 1: Add the packages**

```bash
touch scripts/__init__.py scripts/casts/__init__.py
```

**Step 2: Add `pythonpath` to `pytest.ini`**

Add this line inside the existing `[pytest]` block, directly under `testpaths = tests`:

```ini
pythonpath = .
```

**Step 3: Verify the import resolves**

Run: `uv run python -c "import scripts.casts; print('ok')"`
Expected: `ok`

**Step 4: Commit**

```bash
git add scripts/__init__.py scripts/casts/__init__.py pytest.ini
git commit -m "build(casts): make scripts importable from tests"
```

---

## Task 2: The recording spec model

The spec is a thin header over autocast's instruction schema. Instructions are passed through
untouched so the engine stays swappable.

**Files:**
- Create: `scripts/casts/spec.py`
- Create: `tests/casts/__init__.py` (empty)
- Test: `tests/casts/test_spec.py`

**Step 1: Write the failing tests**

```python
import pathlib

import pytest
from pydantic import ValidationError

from scripts.casts.spec import RecordingSpec, load_spec


def test_minimal_spec_applies_defaults():
    spec = RecordingSpec(fixture='ab-problem', instructions=['rbx run'])

    assert spec.fixture == 'ab-problem'
    assert spec.width == 100
    assert spec.height == 30
    assert spec.type_speed == '60ms'
    assert spec.timeout == '120s'
    assert spec.setup == []
    assert spec.expect_contains == []


def test_unknown_field_is_rejected():
    with pytest.raises(ValidationError):
        RecordingSpec(fixture='ab-problem', instructions=['rbx run'], colour='red')


def test_empty_instructions_are_rejected():
    with pytest.raises(ValidationError):
        RecordingSpec(fixture='ab-problem', instructions=[])


def test_load_spec_derives_name_from_filename(tmp_path: pathlib.Path):
    path = tmp_path / 'run-basic.yml'
    path.write_text(
        'fixture: ab-problem\n'
        'title: Running solutions\n'
        'setup:\n'
        '  - rbx build\n'
        'instructions:\n'
        '  - rbx run\n'
        'expect_contains:\n'
        '  - Accepted\n'
    )

    spec = load_spec(path)

    assert spec.name == 'run-basic'
    assert spec.title == 'Running solutions'
    assert spec.setup == ['rbx build']
    assert spec.expect_contains == ['Accepted']


def test_load_spec_preserves_autocast_tagged_instructions(tmp_path: pathlib.Path):
    path = tmp_path / 'ui.yml'
    path.write_text(
        'fixture: ab-problem\n'
        'instructions:\n'
        '  - rbx run\n'
        '  - !Wait 3s\n'
        '  - !Interactive\n'
        '    command: rbx ui\n'
        '    keys: [j, j, "^C"]\n'
    )

    spec = load_spec(path)

    assert spec.instructions[0] == 'rbx run'
    assert spec.instructions[1].tag == 'Wait'
    assert spec.instructions[1].value == '3s'
    assert spec.instructions[2].tag == 'Interactive'
    assert spec.instructions[2].value == {'command': 'rbx ui', 'keys': ['j', 'j', '^C']}
```

**Step 2: Run to verify they fail**

Run: `uv run pytest tests/casts/test_spec.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.casts.spec'`

**Step 3: Implement**

```python
"""Parsing for docs recording specs (``casts/*.yml``)."""

import pathlib
from typing import Any, List, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field


class Tagged:
    """A YAML tagged scalar/mapping preserved verbatim for autocast.

    autocast's instruction schema is a tagged union (``!Command``, ``!Wait``, ...).
    We never interpret those tags -- we round-trip them so the spec files stay
    valid autocast input if the wrapper is ever replaced.
    """

    def __init__(self, tag: str, value: Any):
        self.tag = tag
        self.value = value

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, Tagged)
            and self.tag == other.tag
            and self.value == other.value
        )

    def __repr__(self) -> str:
        return f'Tagged({self.tag!r}, {self.value!r})'


class _SpecLoader(yaml.SafeLoader):
    pass


def _construct_tagged(loader: yaml.Loader, tag_suffix: str, node: yaml.Node) -> Tagged:
    if isinstance(node, yaml.MappingNode):
        value: Any = loader.construct_mapping(node, deep=True)
    elif isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node, deep=True)
    else:
        value = loader.construct_scalar(node)
    return Tagged(tag_suffix, value)


_SpecLoader.add_multi_constructor('!', _construct_tagged)


class _TaggedDumper(yaml.SafeDumper):
    pass


def _represent_tagged(dumper: yaml.Dumper, data: Tagged) -> yaml.Node:
    if isinstance(data.value, dict):
        return dumper.represent_mapping(f'!{data.tag}', data.value)
    if isinstance(data.value, list):
        return dumper.represent_sequence(f'!{data.tag}', data.value)
    return dumper.represent_scalar(f'!{data.tag}', str(data.value))


_TaggedDumper.add_representer(Tagged, _represent_tagged)


class RecordingSpec(BaseModel):
    model_config = ConfigDict(extra='forbid', arbitrary_types_allowed=True)

    # Filled in by `load_spec` from the filename; not present in the YAML.
    name: str = ''

    fixture: str
    title: Optional[str] = None
    width: int = 100
    height: int = 30
    type_speed: str = '60ms'
    timeout: str = '120s'
    setup: List[str] = Field(default_factory=list)
    instructions: List[Any] = Field(min_length=1)
    expect_contains: List[str] = Field(default_factory=list)


def load_spec(path: pathlib.Path) -> RecordingSpec:
    data = yaml.load(path.read_text(), Loader=_SpecLoader)
    if not isinstance(data, dict):
        raise ValueError(f'{path}: expected a YAML mapping at the top level')
    if 'name' in data:
        raise ValueError(f'{path}: `name` is derived from the filename, remove it')
    return RecordingSpec(name=path.stem, **data)


def dump_autocast_yaml(data: Any) -> str:
    """Serialize a dict that may contain `Tagged` values back to YAML."""
    return yaml.dump(data, Dumper=_TaggedDumper, sort_keys=False, default_flow_style=False)
```

**Step 4: Run to verify they pass**

Run: `uv run pytest tests/casts/test_spec.py -v`
Expected: PASS (5 tests)

**Step 5: Commit**

```bash
git add scripts/casts/spec.py tests/casts/__init__.py tests/casts/test_spec.py
git commit -m "feat(casts): add recording spec model"
```

---

## Task 3: Build the autocast input

**Files:**
- Create: `scripts/casts/autocast_input.py`
- Test: `tests/casts/test_autocast_input.py`

**Step 1: Write the failing tests**

```python
from scripts.casts.autocast_input import build_autocast_input
from scripts.casts.spec import RecordingSpec, Tagged, dump_autocast_yaml


def _spec(**kwargs) -> RecordingSpec:
    base = dict(name='run-basic', fixture='ab-problem', instructions=['rbx run'])
    base.update(kwargs)
    return RecordingSpec(**base)


def test_settings_carry_spec_values():
    data = build_autocast_input(_spec(title='Running solutions'), workdir='/tmp/wd')

    settings = data['settings']
    assert settings['width'] == 100
    assert settings['height'] == 30
    assert settings['title'] == 'Running solutions'
    assert settings['type_speed'] == '60ms'
    assert settings['timeout'] == '120s'
    assert settings['prompt'] == '$ '


def test_shell_uses_a_sentinel_prompt_so_autocast_can_detect_completion():
    data = build_autocast_input(_spec(), workdir='/tmp/wd')

    shell = data['settings']['shell']
    assert shell['program'] == 'bash'
    assert shell['prompt'] == 'AUTOCAST_PROMPT'
    assert shell['quit_command'] == 'exit'

    env = {pair['name']: pair['value'] for pair in data['settings']['environment']}
    assert 'PS1=AUTOCAST_PROMPT' in env['PROMPT_COMMAND']


def test_environment_is_normalized_for_reproducibility():
    data = build_autocast_input(_spec(), workdir='/tmp/wd', home='/tmp/home')

    env = {pair['name']: pair['value'] for pair in data['settings']['environment']}
    assert env['TERM'] == 'xterm-256color'
    assert env['COLUMNS'] == '100'
    assert env['LINES'] == '30'
    assert env['LC_ALL'] == 'C.UTF-8'
    assert env['TZ'] == 'UTC'
    assert env['HOME'] == '/tmp/home'


def test_workdir_and_setup_are_hidden_leading_commands():
    data = build_autocast_input(
        _spec(setup=['rbx build']), workdir='/tmp/wd'
    )

    instructions = data['instructions']
    assert instructions[0].tag == 'Command'
    assert instructions[0].value['command'] == 'cd /tmp/wd'
    assert instructions[0].value['hidden'] is True
    assert instructions[1].value['command'] == 'rbx build'
    assert instructions[1].value['hidden'] is True


def test_plain_string_instructions_become_visible_commands():
    data = build_autocast_input(_spec(instructions=['rbx run']), workdir='/tmp/wd')

    last = data['instructions'][-1]
    assert last.tag == 'Command'
    assert last.value == {'command': 'rbx run', 'hidden': False}


def test_tagged_instructions_pass_through_untouched():
    wait = Tagged('Wait', '3s')
    data = build_autocast_input(_spec(instructions=[wait]), workdir='/tmp/wd')

    assert data['instructions'][-1] is wait


def test_output_is_serializable_with_tags_intact():
    data = build_autocast_input(
        _spec(instructions=['rbx run', Tagged('Wait', '3s')]), workdir='/tmp/wd'
    )

    text = dump_autocast_yaml(data)

    assert '!Command' in text
    assert '!Wait' in text
```

**Step 2: Run to verify they fail**

Run: `uv run pytest tests/casts/test_autocast_input.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement**

```python
"""Translation from a `RecordingSpec` into autocast's input schema."""

from typing import Any, Dict, List, Optional

from scripts.casts.spec import RecordingSpec, Tagged

SENTINEL_PROMPT = 'AUTOCAST_PROMPT'

# Forcing PS1 to a sentinel is how autocast detects that a command finished;
# disabling bracketed paste keeps stray escape sequences out of the cast.
_PROMPT_COMMAND = (
    f"PS1={SENTINEL_PROMPT}; unset PROMPT_COMMAND; "
    "bind 'set enable-bracketed-paste off'"
)


def _env_pairs(spec: RecordingSpec, home: Optional[str]) -> List[Dict[str, str]]:
    env = {
        'PROMPT_COMMAND': _PROMPT_COMMAND,
        'TERM': 'xterm-256color',
        'COLUMNS': str(spec.width),
        'LINES': str(spec.height),
        'LC_ALL': 'C.UTF-8',
        'LANG': 'C.UTF-8',
        'TZ': 'UTC',
    }
    if home is not None:
        env['HOME'] = home
    return [{'name': name, 'value': value} for name, value in env.items()]


def _hidden(command: str) -> Tagged:
    return Tagged('Command', {'command': command, 'hidden': True})


def build_autocast_input(
    spec: RecordingSpec, workdir: str, home: Optional[str] = None
) -> Dict[str, Any]:
    settings: Dict[str, Any] = {
        'width': spec.width,
        'height': spec.height,
        'type_speed': spec.type_speed,
        'timeout': spec.timeout,
        'prompt': '$ ',
        'secondary_prompt': '> ',
        'shell': {
            'program': 'bash',
            'args': ['--norc', '--noprofile'],
            'prompt': SENTINEL_PROMPT,
            'quit_command': 'exit',
        },
        'environment': _env_pairs(spec, home),
    }
    if spec.title is not None:
        settings['title'] = spec.title

    instructions: List[Any] = [_hidden(f'cd {workdir}')]
    instructions.extend(_hidden(command) for command in spec.setup)
    for instruction in spec.instructions:
        if isinstance(instruction, str):
            instructions.append(
                Tagged('Command', {'command': instruction, 'hidden': False})
            )
        else:
            instructions.append(instruction)

    return {'settings': settings, 'instructions': instructions}
```

**Step 4: Run to verify they pass**

Run: `uv run pytest tests/casts/test_autocast_input.py -v`
Expected: PASS (7 tests)

**Step 5: Commit**

```bash
git add scripts/casts/autocast_input.py tests/casts/test_autocast_input.py
git commit -m "feat(casts): build autocast input from a recording spec"
```

---

## Task 4: Scrub and verify the recorded cast

The cast is a JSON header line plus `[time, code, data]` event lines. Scrubbing rewrites the
tmpdir into a stable fake path; verification asserts the spec's `expect_contains` strings
actually appear in the recorded output.

**Files:**
- Create: `scripts/casts/postprocess.py`
- Test: `tests/casts/test_postprocess.py`

**Step 1: Write the failing tests**

```python
import json

import pytest

from scripts.casts.postprocess import (
    CastVerificationError,
    cast_text,
    scrub_cast,
    verify_cast,
)


def _cast(*outputs: str) -> str:
    lines = [json.dumps({'version': 2, 'width': 100, 'height': 30, 'env': {'SHELL': '/bin/bash'}})]
    for index, output in enumerate(outputs):
        lines.append(json.dumps([index * 0.5, 'o', output]))
    return '\n'.join(lines) + '\n'


def test_scrub_rewrites_the_tmpdir_to_a_stable_path():
    raw = _cast('$ pwd\r\n/private/var/folders/ab/T/tmpxyz/ab-problem\r\n')

    scrubbed = scrub_cast(raw, tmpdir='/private/var/folders/ab/T/tmpxyz', display_root='~/problems')

    assert '/private/var/folders' not in scrubbed
    assert '~/problems/ab-problem' in scrubbed


def test_scrub_rewrites_the_home_directory_too():
    raw = _cast('cache at /tmp/rec-home/.cache/rbx\r\n')

    scrubbed = scrub_cast(raw, tmpdir='/nope', display_root='~/problems', home='/tmp/rec-home')

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
        verify_cast(_cast('Accepted\r\n'), ['Accepted', 'Wrong answer'], name='run-basic')

    message = str(excinfo.value)
    assert 'run-basic' in message
    assert 'Wrong answer' in message
    assert 'Accepted' not in message.split('missing')[-1]
```

**Step 2: Run to verify they fail**

Run: `uv run pytest tests/casts/test_postprocess.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement**

```python
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


def _scrub_str(
    value: str, tmpdir: str, display_root: str, home: Optional[str]
) -> str:
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
        key: value for key, value in (header.get('env') or {}).items() if key in _KEEP_ENV
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
```

**Step 4: Run to verify they pass**

Run: `uv run pytest tests/casts/test_postprocess.py -v`
Expected: PASS (7 tests)

**Step 5: Commit**

```bash
git add scripts/casts/postprocess.py tests/casts/test_postprocess.py
git commit -m "feat(casts): scrub and verify recorded casts"
```

---

## Task 5: The recorder

Ties it together: copy fixture → normalize → run autocast → scrub → verify → write.

**Files:**
- Create: `scripts/casts/recorder.py`
- Test: `tests/casts/test_recorder.py`

**Step 1: Write the failing tests**

These use a fake autocast (a Python script on `PATH`) so they run everywhere and stay fast. No
real `rbx` involved.

```python
import pathlib
import shutil
import stat
import textwrap

import pytest

from scripts.casts.postprocess import CastVerificationError
from scripts.casts.recorder import AutocastMissingError, record
from scripts.casts.spec import RecordingSpec


@pytest.fixture
def fake_autocast(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """A stand-in `autocast` binary that writes a canned cast.

    It echoes the working directory it was told about so tests can assert the
    scrubbing actually happened.
    """

    bindir = tmp_path / 'bin'
    bindir.mkdir()
    script = bindir / 'autocast'
    script.write_text(
        textwrap.dedent(
            '''\
            #!/usr/bin/env python3
            import json, pathlib, sys, yaml

            args = [a for a in sys.argv[1:] if not a.startswith('-')]
            spec = yaml.safe_load(pathlib.Path(args[0]).read_text().replace('!', '#'))
            workdir = 'UNKNOWN'
            for line in pathlib.Path(args[0]).read_text().splitlines():
                if 'cd /' in line:
                    workdir = line.split('cd ', 1)[1].strip().strip('\\'"')
            lines = [json.dumps({'version': 2, 'width': 100, 'height': 30,
                                 'timestamp': 1234, 'env': {'TERM': 'x', 'USER': 'me'}})]
            lines.append(json.dumps([0.0, 'o', '$ pwd\\r\\n' + workdir + '\\r\\n']))
            lines.append(json.dumps([0.5, 'o', 'Accepted\\r\\n']))
            pathlib.Path(args[1]).write_text('\\n'.join(lines) + '\\n')
            '''
        )
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv('PATH', f'{bindir}:{shutil.os.environ["PATH"]}')
    return script


@pytest.fixture
def fixtures_root(tmp_path: pathlib.Path) -> pathlib.Path:
    root = tmp_path / 'fixtures'
    (root / 'ab-problem').mkdir(parents=True)
    (root / 'ab-problem' / 'problem.rbx.yml').write_text('name: ab-problem\n')
    return root


def _spec(**kwargs) -> RecordingSpec:
    base = dict(name='run-basic', fixture='ab-problem', instructions=['rbx run'])
    base.update(kwargs)
    return RecordingSpec(**base)


def test_record_writes_a_cast(
    fake_autocast, fixtures_root: pathlib.Path, tmp_path: pathlib.Path
):
    out = tmp_path / 'out' / 'run-basic.cast'

    record(_spec(), fixtures_root=fixtures_root, out_path=out)

    assert out.exists()
    assert out.read_text().startswith('{')


def test_record_scrubs_the_tmpdir_out_of_the_cast(
    fake_autocast, fixtures_root: pathlib.Path, tmp_path: pathlib.Path
):
    out = tmp_path / 'out' / 'run-basic.cast'

    record(_spec(), fixtures_root=fixtures_root, out_path=out)

    text = out.read_text()
    assert '~/problems/ab-problem' in text
    assert '/var/folders' not in text
    assert str(tmp_path) not in text


def test_record_never_mutates_the_source_fixture(
    fake_autocast, fixtures_root: pathlib.Path, tmp_path: pathlib.Path
):
    before = sorted(p.name for p in (fixtures_root / 'ab-problem').iterdir())

    record(_spec(), fixtures_root=fixtures_root, out_path=tmp_path / 'o.cast')

    assert sorted(p.name for p in (fixtures_root / 'ab-problem').iterdir()) == before


def test_record_fails_when_an_expectation_is_missing(
    fake_autocast, fixtures_root: pathlib.Path, tmp_path: pathlib.Path
):
    out = tmp_path / 'run-basic.cast'

    with pytest.raises(CastVerificationError):
        record(
            _spec(expect_contains=['Wrong answer']),
            fixtures_root=fixtures_root,
            out_path=out,
        )

    assert not out.exists()


def test_record_reports_a_missing_fixture(
    fake_autocast, fixtures_root: pathlib.Path, tmp_path: pathlib.Path
):
    with pytest.raises(FileNotFoundError, match='nope'):
        record(
            _spec(fixture='nope'), fixtures_root=fixtures_root, out_path=tmp_path / 'o.cast'
        )


def test_record_reports_a_missing_autocast_binary(
    fixtures_root: pathlib.Path, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv('PATH', str(tmp_path / 'empty'))

    with pytest.raises(AutocastMissingError, match='cargo binstall autocast'):
        record(_spec(), fixtures_root=fixtures_root, out_path=tmp_path / 'o.cast')
```

**Step 2: Run to verify they fail**

Run: `uv run pytest tests/casts/test_recorder.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement**

```python
"""Records a docs cast: fixture -> tmpdir -> autocast -> scrub -> verify."""

import pathlib
import shutil
import subprocess
import tempfile

from scripts.casts.autocast_input import build_autocast_input
from scripts.casts.postprocess import scrub_cast, verify_cast
from scripts.casts.spec import RecordingSpec, dump_autocast_yaml

DISPLAY_ROOT = '~/problems'

_INSTALL_HINT = (
    'autocast is required to record docs casts but was not found on PATH.\n'
    'Install it with one of:\n'
    '  cargo binstall autocast\n'
    '  cargo install autocast\n'
    '  https://github.com/k9withabone/autocast/releases'
)


class AutocastMissingError(RuntimeError):
    pass


class AutocastFailedError(RuntimeError):
    pass


def record(
    spec: RecordingSpec, fixtures_root: pathlib.Path, out_path: pathlib.Path
) -> pathlib.Path:
    if shutil.which('autocast') is None:
        raise AutocastMissingError(_INSTALL_HINT)

    fixture = fixtures_root / spec.fixture
    if not fixture.is_dir():
        raise FileNotFoundError(
            f'recording `{spec.name}` references fixture `{spec.fixture}`, '
            f'but {fixture} does not exist'
        )

    with tempfile.TemporaryDirectory(prefix='rbx-cast-') as tmp:
        tmpdir = pathlib.Path(tmp).resolve()
        # The fixture is copied so recording side effects (build/, .rbx/) never
        # touch the source tree, and HOME is redirected so the real rbx cache is
        # neither used nor leaked into the cast.
        workdir = tmpdir / spec.fixture
        home = tmpdir / 'home'
        shutil.copytree(fixture, workdir)
        home.mkdir()

        data = build_autocast_input(spec, workdir=str(workdir), home=str(home))
        input_path = tmpdir / 'autocast.yml'
        cast_path = tmpdir / 'out.cast'
        input_path.write_text(dump_autocast_yaml(data))

        process = subprocess.run(
            ['autocast', str(input_path), str(cast_path), '--overwrite'],
            capture_output=True,
            text=True,
        )
        if process.returncode != 0:
            raise AutocastFailedError(
                f'autocast failed while recording `{spec.name}` '
                f'(exit {process.returncode}):\n{process.stderr}'
            )

        raw = cast_path.read_text()
        scrubbed = scrub_cast(
            raw,
            tmpdir=str(tmpdir),
            display_root=DISPLAY_ROOT,
            home=str(home),
            title=spec.title,
        )
        verify_cast(scrubbed, spec.expect_contains, name=spec.name)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(scrubbed)
    return out_path
```

Note the ordering: `verify_cast` runs *before* `out_path.write_text`, so a failed recording
never overwrites a good committed cast.

**Step 4: Run to verify they pass**

Run: `uv run pytest tests/casts/test_recorder.py -v`
Expected: PASS (6 tests)

**Step 5: Commit**

```bash
git add scripts/casts/recorder.py tests/casts/test_recorder.py
git commit -m "feat(casts): record a cast from a spec via autocast"
```

---

## Task 6: The link check

Catches the rot already in the docs: `REPLACE_ME_CAST_ID` and orphaned casts. Local-only — do
**not** add it to any workflow, and do not make it a pytest test of the docs tree.

**Files:**
- Create: `scripts/casts/links.py`
- Test: `tests/casts/test_links.py`

**Step 1: Write the failing tests**

```python
import pathlib

from scripts.casts.links import LinkReport, check_links, iter_references

LEGACY_ID = 'cqUTWgIRFA1P7VsV39uJTorKC'


def _docs(tmp_path: pathlib.Path, **pages: str) -> pathlib.Path:
    root = tmp_path / 'docs'
    root.mkdir()
    for name, body in pages.items():
        path = root / f'{name}.md'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
    return root


def test_iter_references_finds_macros_with_and_without_kwargs(tmp_path: pathlib.Path):
    docs = _docs(
        tmp_path,
        page='{{ asciinema("run-basic") }}\n{{ asciinema("ui-nav", speed=1.5) }}\n',
    )

    refs = sorted(ref.target for ref in iter_references(docs))

    assert refs == ['run-basic', 'ui-nav']


def test_legacy_asciinema_org_ids_are_reported_but_not_errors(tmp_path: pathlib.Path):
    docs = _docs(tmp_path, page=f'{{{{ asciinema("{LEGACY_ID}") }}}}\n')
    casts = tmp_path / 'casts'
    casts.mkdir()

    report = check_links(docs, casts)

    assert report.legacy == [LEGACY_ID]
    assert report.missing == []
    assert report.ok


def test_a_reference_without_a_cast_file_is_missing(tmp_path: pathlib.Path):
    docs = _docs(tmp_path, page='{{ asciinema("run-basic") }}\n')
    casts = tmp_path / 'casts'
    casts.mkdir()

    report = check_links(docs, casts)

    assert [item.target for item in report.missing] == ['run-basic']
    assert not report.ok


def test_a_cast_nobody_references_is_an_orphan(tmp_path: pathlib.Path):
    docs = _docs(tmp_path, page='no casts here\n')
    casts = tmp_path / 'casts'
    casts.mkdir()
    (casts / 'stale.cast').write_text('{}\n')

    report = check_links(docs, casts)

    assert report.orphans == ['stale']
    assert not report.ok


def test_pending_placeholders_are_reported(tmp_path: pathlib.Path):
    docs = _docs(
        tmp_path,
        page='{{ asciinema("REPLACE_ME_CAST_ID") }}\n<!-- TODO(record): a cast -->\n',
    )
    casts = tmp_path / 'casts'
    casts.mkdir()

    report = check_links(docs, casts)

    assert len(report.pending) == 2
    assert not report.ok


def test_a_fully_wired_cast_is_clean(tmp_path: pathlib.Path):
    docs = _docs(tmp_path, page='{{ asciinema("run-basic") }}\n')
    casts = tmp_path / 'casts'
    casts.mkdir()
    (casts / 'run-basic.cast').write_text('{}\n')

    report = check_links(docs, casts)

    assert report.ok
    assert isinstance(report, LinkReport)
```

**Step 2: Run to verify they fail**

Run: `uv run pytest tests/casts/test_links.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement**

```python
"""Local lint tying `{{ asciinema(...) }}` references to committed casts."""

import dataclasses
import pathlib
import re
from typing import Iterator, List

# `{{ asciinema("name") }}` / `{{ asciinema("name", speed=1.5) }}`
_MACRO = re.compile(r'{{\s*asciinema\(\s*[\'"]([^\'"]+)[\'"]')
# asciinema.org url tokens are 25 chars of [A-Za-z0-9].
_LEGACY_ID = re.compile(r'^[A-Za-z0-9]{25}$')
_TODO = re.compile(r'<!--\s*TODO\(record\)')
_PLACEHOLDER = 'REPLACE_ME_CAST_ID'


@dataclasses.dataclass(frozen=True)
class Reference:
    target: str
    page: pathlib.Path
    line: int


@dataclasses.dataclass(frozen=True)
class Pending:
    page: pathlib.Path
    line: int
    detail: str


@dataclasses.dataclass(frozen=True)
class LinkReport:
    missing: List[Reference]
    orphans: List[str]
    legacy: List[str]
    pending: List[Pending]

    @property
    def ok(self) -> bool:
        return not (self.missing or self.orphans or self.pending)


def iter_references(docs_root: pathlib.Path) -> Iterator[Reference]:
    for page in sorted(docs_root.rglob('*.md')):
        for number, line in enumerate(page.read_text().splitlines(), start=1):
            for match in _MACRO.finditer(line):
                yield Reference(target=match.group(1), page=page, line=number)


def _iter_pending(docs_root: pathlib.Path) -> Iterator[Pending]:
    for page in sorted(docs_root.rglob('*.md')):
        for number, line in enumerate(page.read_text().splitlines(), start=1):
            if _PLACEHOLDER in line:
                yield Pending(page, number, f'placeholder {_PLACEHOLDER}')
            if _TODO.search(line):
                yield Pending(page, number, 'unrecorded TODO(record) marker')


def check_links(docs_root: pathlib.Path, casts_root: pathlib.Path) -> LinkReport:
    available = {path.stem for path in casts_root.glob('*.cast')}

    missing: List[Reference] = []
    legacy: List[str] = []
    referenced = set()

    for reference in iter_references(docs_root):
        if reference.target == _PLACEHOLDER:
            continue
        if _LEGACY_ID.match(reference.target):
            legacy.append(reference.target)
            continue
        referenced.add(reference.target)
        if reference.target not in available:
            missing.append(reference)

    return LinkReport(
        missing=missing,
        orphans=sorted(available - referenced),
        legacy=legacy,
        pending=list(_iter_pending(docs_root)),
    )
```

**Step 4: Run to verify they pass**

Run: `uv run pytest tests/casts/test_links.py -v`
Expected: PASS (6 tests)

**Step 5: Commit**

```bash
git add scripts/casts/links.py tests/casts/test_links.py
git commit -m "feat(casts): lint asciinema references against committed casts"
```

---

## Task 7: The CLI entry point

**Files:**
- Create: `scripts/record.py`
- Modify: `mise.toml`

**Step 1: Write the CLI**

```python
"""Record the documentation's asciinema casts.

Usage:
    python scripts/record.py                # record everything
    python scripts/record.py run-basic ...  # record only the named specs
    python scripts/record.py --check        # lint references, record nothing
"""

import argparse
import pathlib
import sys
from typing import List

from scripts.casts.links import check_links
from scripts.casts.recorder import record
from scripts.casts.spec import load_spec

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SPECS_ROOT = REPO_ROOT / 'casts'
FIXTURES_ROOT = SPECS_ROOT / 'fixtures'
DOCS_ROOT = REPO_ROOT / 'docs'
CASTS_OUT = DOCS_ROOT / 'assets' / 'casts'


def _spec_paths(names: List[str]) -> List[pathlib.Path]:
    if not names:
        return sorted(SPECS_ROOT.glob('*.yml'))
    paths = []
    for name in names:
        path = SPECS_ROOT / f'{name}.yml'
        if not path.exists():
            raise SystemExit(f'no such recording spec: {path}')
        paths.append(path)
    return paths


def _run_check() -> int:
    report = check_links(DOCS_ROOT, CASTS_OUT)
    for reference in report.missing:
        print(f'{reference.page}:{reference.line}: no cast named {reference.target!r}')
    for orphan in report.orphans:
        print(f'{CASTS_OUT / (orphan + ".cast")}: not referenced by any page')
    for pending in report.pending:
        print(f'{pending.page}:{pending.line}: {pending.detail}')
    if report.legacy:
        print(f'{len(report.legacy)} cast(s) still hosted on asciinema.org, not yet migrated')
    print('OK' if report.ok else 'FAILED')
    return 0 if report.ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('names', nargs='*', help='recording names (default: all)')
    parser.add_argument(
        '--check', action='store_true', help='lint references only, record nothing'
    )
    args = parser.parse_args()

    if args.check:
        return _run_check()

    for path in _spec_paths(args.names):
        spec = load_spec(path)
        print(f'recording {spec.name}...', flush=True)
        out = record(spec, fixtures_root=FIXTURES_ROOT, out_path=CASTS_OUT / f'{spec.name}.cast')
        print(f'  wrote {out.relative_to(REPO_ROOT)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
```

**Step 2: Add mise tasks**

Append to `mise.toml`:

```toml
[tasks.record]
description = "Record documentation asciinema casts (all, or the named ones)"
run = "python scripts/record.py"

[tasks.record-check]
description = "Lint asciinema references against committed casts (local only)"
run = "python scripts/record.py --check"
```

**Step 3: Verify the check runs against the real docs**

Run: `uv run python scripts/record.py --check`
Expected: exit 1, listing the 21 legacy asciinema.org IDs as not-yet-migrated, the
`REPLACE_ME_CAST_ID` placeholder in `setters/stress-testing-walkthrough.md`, and the two
`TODO(record)` markers in `setters/custom-checker-walkthrough.md`. This is the baseline —
it is *supposed* to fail today.

**Step 4: Verify help works**

Run: `uv run python scripts/record.py --help`
Expected: usage text, exit 0

**Step 5: Commit**

```bash
git add scripts/record.py mise.toml
git commit -m "feat(casts): add the record and record-check commands"
```

---

## Task 8: Vendor the player and rewrite the macro

**Files:**
- Create: `docs/assets/asciinema-player.min.js`
- Create: `docs/assets/asciinema-player.css`
- Modify: `mkdocs.yml` (`extra_css`, `extra_javascript`)
- Modify: `main.py`
- Test: `tests/casts/test_macro.py`

**Step 1: Download the player (v3.17.0)**

```bash
mkdir -p docs/assets
curl -fsSL -o docs/assets/asciinema-player.min.js \
  https://github.com/asciinema/asciinema-player/releases/download/v3.17.0/asciinema-player.min.js
curl -fsSL -o docs/assets/asciinema-player.css \
  https://github.com/asciinema/asciinema-player/releases/download/v3.17.0/asciinema-player.css
```

**Step 2: Write the failing tests**

```python
import re

from main import define_env

LEGACY_ID = 'cqUTWgIRFA1P7VsV39uJTorKC'


class _Env:
    def __init__(self):
        self.macros = {}

    def macro(self, fn):
        self.macros[fn.__name__] = fn
        return fn


def _asciinema():
    env = _Env()
    define_env(env)
    return env.macros['asciinema']


def test_local_name_renders_a_player_pointed_at_the_committed_cast():
    html = _asciinema()('run-basic')

    assert '/assets/casts/run-basic.cast' in html
    assert 'AsciinemaPlayer.create' in html
    assert 'asciinema.org' not in html


def test_speed_and_idleness_map_onto_player_options():
    html = _asciinema()('run-basic', idleness=2, speed=1.5)

    assert '"speed": 1.5' in html
    assert '"idleTimeLimit": 2' in html


def test_each_player_gets_a_unique_container_id():
    macro = _asciinema()
    first = re.search(r'id="(cast-[^"]+)"', macro('run-basic')).group(1)
    second = re.search(r'id="(cast-[^"]+)"', macro('run-basic')).group(1)

    assert first != second


def test_a_legacy_asciinema_org_id_still_renders_the_old_embed():
    html = _asciinema()(LEGACY_ID)

    assert f'asciinema.org/a/{LEGACY_ID}.js' in html
    assert 'AsciinemaPlayer.create' not in html
```

**Step 3: Run to verify they fail**

Run: `uv run pytest tests/casts/test_macro.py -v`
Expected: FAIL — the current macro always emits the asciinema.org script tag.

**Step 4: Rewrite `main.py`**

```python
"""
File for defining mkdocs macros.
"""

import itertools
import json
import re

# asciinema.org url tokens are 25 chars of [A-Za-z0-9]. Anything else is the
# basename of a cast committed under docs/assets/casts.
_LEGACY_ID = re.compile(r'^[A-Za-z0-9]{25}$')

_counter = itertools.count()


def define_env(env):
    @env.macro
    def asciinema(id: str, idleness: float = 1, speed: float = 1):
        if _LEGACY_ID.match(id):
            return f"""<div style="width: 90%; margin: 0 auto;">
<script src="https://asciinema.org/a/{id}.js" id="asciicast-{id}" async="true" data-autoplay data-loop data-idle-time-limit="{idleness}" data-speed="{speed}"></script>
</div>
"""

        element_id = f'cast-{id}-{next(_counter)}'
        options = json.dumps(
            {
                'autoPlay': True,
                'loop': True,
                'idleTimeLimit': idleness,
                'speed': speed,
                'fit': 'width',
            },
            sort_keys=True,
        )
        return f"""<div style="width: 90%; margin: 0 auto;">
<div id="{element_id}"></div>
<script>
  AsciinemaPlayer.create('/assets/casts/{id}.cast', document.getElementById('{element_id}'), {options});
</script>
</div>
"""
```

Note: `json.dumps` with `sort_keys=True` puts `idleTimeLimit` before `speed`, which is what the
tests assert on.

**Step 5: Wire the assets into `mkdocs.yml`**

`extra_css` already exists — add the player stylesheet, and add a new `extra_javascript` block
directly after it:

```yaml
extra_css:
  - extra.css
  - assets/asciinema-player.css
extra_javascript:
  - assets/asciinema-player.min.js
```

**Step 6: Run tests**

Run: `uv run pytest tests/casts/test_macro.py -v`
Expected: PASS (4 tests)

**Step 7: Verify the docs still build**

Run: `uv run mkdocs build`
Expected: build succeeds. (Per project memory there are ~9 pre-existing warnings unrelated to
this change — do not use `--strict`.)

**Step 8: Commit**

```bash
git add docs/assets/asciinema-player.min.js docs/assets/asciinema-player.css \
        mkdocs.yml main.py tests/casts/test_macro.py
git commit -m "feat(docs): render casts with a vendored asciinema player"
```

---

## Task 9: The first fixture and the first recording

This is the validation gate for the whole approach. Stop and report if it fails — the design
doc names falling back to an in-repo `pexpect` recorder as the escape hatch.

**Files:**
- Create: `casts/fixtures/ab-problem/` (a real rbx package)
- Create: `casts/run-basic.yml`
- Create: `casts/.gitignore`
- Create: `docs/assets/casts/run-basic.cast` (generated)

**Step 1: Build the fixture**

Base it on `tests/e2e/testdata/simple-ac/`, but shaped for teaching: the classic A+B problem
with a readable generator and a solution whose output is worth looking at. Copy that package,
rename to `ab-problem`, and give `problem.rbx.yml` a `name: ab-problem`.

Verify it builds standalone:

```bash
cd casts/fixtures/ab-problem && uv run rbx build && cd -
```

**Step 2: Keep build artefacts out of git**

Create `casts/.gitignore`:

```gitignore
fixtures/*/.rbx/
fixtures/*/build/
fixtures/*/rbx.h
```

Then clean up: `git status --short` inside `casts/` must be empty except the intended files.

**Step 3: Write the spec**

`casts/run-basic.yml`:

```yaml
fixture: ab-problem
title: Running solutions with rbx run
setup:
  - rbx build
instructions:
  - rbx run
  - !Wait 3s
expect_contains:
  - rbx run
```

Start `expect_contains` minimal. Widen it in step 5 once you have seen the real output.

**Step 4: Install autocast and record**

```bash
cargo binstall autocast   # or: cargo install autocast
uv run python scripts/record.py run-basic
```

Expected: `wrote docs/assets/casts/run-basic.cast`

**If autocast times out or the prompt is never detected**, the likely cause is `rbx`'s Rich
progress output interfering with prompt matching. Try, in order: raise `timeout`, set
`RICH_NO_COLOR`/`TERM=dumb` for the setup command only, or add `--norc --noprofile` handling.
If none work, this is the documented trigger to escalate to the fallback engine — write up what
you saw and stop.

**Step 5: Watch it and tighten the expectations**

```bash
asciinema play docs/assets/casts/run-basic.cast
```

Confirm: no absolute machine paths, colors present, output readable at 100 columns. Then add
the real verdict strings you saw (for example `Accepted`) to `expect_contains` and re-record.

**Step 6: Wire it into a page**

In `docs/setters/running/index.md:13`, replace
`{{ asciinema("x8NJUtmob4uSHUUFppxUn64Kn") }}` with `{{ asciinema("run-basic") }}`.

**Step 7: Verify end to end**

```bash
uv run mkdocs serve
```

Open `/setters/running/` and confirm the player loads, autoplays, and loops.

**Step 8: Commit**

```bash
git add casts docs/assets/casts/run-basic.cast docs/setters/running/index.md
git commit -m "feat(docs): record the rbx run cast from a committed spec"
```

---

## Task 10: Validate the TUI path

The second risk named in the design: whether `rbx ui`'s Textual TUI records cleanly through
autocast's `Interactive` mode.

**Files:**
- Create: `casts/ui-navigation.yml`
- Create: `docs/assets/casts/ui-navigation.cast` (generated)
- Modify: `docs/setters/running/index.md:54`

**Step 1: Write the spec**

```yaml
fixture: ab-problem
title: Inspecting results with rbx ui
setup:
  - rbx build
  - rbx run
instructions:
  - !Interactive
    command: rbx ui
    keys:
      - 1s
      - j
      - 500ms
      - j
      - 1s
      - '^C'
  - !Wait 2s
```

`keys` must leave the TUI *exited* — autocast waits for the shell prompt afterwards and will
time out otherwise. If `^C` does not quit `rbx ui`, substitute the key the TUI actually binds
to quit (check `rbx/box/ui/` bindings).

**Step 2: Record**

Run: `uv run python scripts/record.py ui-navigation`

**Step 3: Watch it**

Run: `asciinema play docs/assets/casts/ui-navigation.cast`
Expected: the TUI renders, the navigation is visible, and the session returns to a prompt. If
the TUI's alternate-screen handling produces a garbled cast, record what you saw and stop —
this is the second escalation trigger.

**Step 4: Wire it in and commit**

Replace `{{ asciinema("6XYQ11Cv1HZ8TuTiCFXBXXM29") }}` at `docs/setters/running/index.md:54`.

```bash
git add casts/ui-navigation.yml docs/assets/casts/ui-navigation.cast docs/setters/running/index.md
git commit -m "feat(docs): record the rbx ui cast from a committed spec"
```

---

## Task 11: Record the three rotting placeholders

The immediate payoff — these references are broken in the published docs today.

**Files:**
- Create: `casts/fixtures/custom-checker/` (a real rbx package with a custom checker)
- Create: `casts/custom-checker-run.yml`, `casts/custom-checker-unit.yml`,
  `casts/stress-finds-counterexample.yml`
- Modify: `docs/setters/custom-checker-walkthrough.md:140,190`
- Modify: `docs/setters/stress-testing-walkthrough.md:53`

**Step 1: Read what each placeholder promises**

- `docs/setters/custom-checker-walkthrough.md:140` — `rbx run` showing the custom WA message.
- `docs/setters/custom-checker-walkthrough.md:190` — a short `rbx unit` run.
- `docs/setters/stress-testing-walkthrough.md:53` — `rbx stress` finding a counterexample.

The prose around each says exactly what must appear on screen. Use those strings as
`expect_contains`.

**Step 2: Build the `custom-checker` fixture**

It needs a deliberately wrong solution so `rbx run` produces the custom WA message, and unit
tests so `rbx unit` has something to run. `tests/e2e/testdata/` has checker packages to crib
from.

**Step 3: Write and record the three specs, one at a time**

```bash
uv run python scripts/record.py custom-checker-run
uv run python scripts/record.py custom-checker-unit
uv run python scripts/record.py stress-finds-counterexample
```

For the stress recording, pin the seed if `rbx stress` accepts one — otherwise the counter-
example differs on every re-record and the cast churns for no reason.

**Step 4: Replace the placeholders**

Swap the two `<!-- TODO(record): ... -->` comments and the `REPLACE_ME_CAST_ID` macro for real
`{{ asciinema("<name>") }}` calls.

**Step 5: Verify**

Run: `uv run python scripts/record.py --check`
Expected: no `pending` entries left; the only remaining output is the count of legacy
asciinema.org IDs still to migrate.

**Step 6: Commit**

```bash
git add casts docs/assets/casts docs/setters/custom-checker-walkthrough.md \
        docs/setters/stress-testing-walkthrough.md
git commit -m "docs: record the three pending walkthrough casts"
```

---

## Task 12: Document the workflow

**Files:**
- Create: `casts/README.md`
- Modify: `CLAUDE.md`

**Step 1: Write `casts/README.md`**

Cover: what lives here, how to install autocast, how to add a recording (fixture → spec →
record → embed), the spec schema with a link to autocast's `full-example.yaml` for the
instruction grammar, why `expect_contains` matters, and the fact that casts are committed
artifacts refreshed deliberately rather than in CI.

**Step 2: Add a pointer in `CLAUDE.md`**

Under "Detailed Module Guides", add:

```markdown
- [`casts/README.md`](casts/README.md) -- Documentation asciinema recordings: specs, fixtures, `mise run record`
```

**Step 3: Verify the docs build**

Run: `uv run mkdocs build`
Expected: succeeds. `casts/` sits outside `docs/`, so nothing new is copied into the site.

**Step 4: Commit**

```bash
git add casts/README.md CLAUDE.md
git commit -m "docs(casts): document the recording workflow"
```

---

## Task 13: Final verification

**Step 1: Full check**

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest tests/casts -v
uv run mkdocs build
uv run python scripts/record.py --check
```

Expected: lint and format clean, all cast tests pass, docs build, and `--check` reports only
the not-yet-migrated legacy IDs.

**Step 2: Confirm nothing leaked into the site**

```bash
ls site/assets/casts/
grep -rl "var/folders" site/ || echo "no machine paths in the built site"
```

Expected: the `.cast` files are present; no machine paths.

**Step 3: Confirm the source fixtures are clean**

Run: `git status --short casts/`
Expected: empty — recording never mutates the fixtures.

---

## Remaining work after this plan

18 casts still reference asciinema.org. Migrating each is mechanical: add a spec, record, swap
the macro argument. Do them opportunistically as pages are touched. When the last one is gone,
delete the legacy branch from the `asciinema` macro in `main.py` and the `legacy` field from
`LinkReport`.
