# `@moj/<cid>/<subid>` Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let `rbx run`, `rbx stress` and `rbx download remote` take `@moj/<cid>/<subid>` and pull that contestant's source out of MOJ, the way `@boca/<run>` already does for BOCA.

**Architecture:** A new `MojExpander` in `rbx/box/remote.py`. Preconditions and the caller's role come from shelling out to `moj contest -c <cid> --json whoami`; the two calls no CLI layer wraps -- the submission listing and the source download -- go over raw HTTP with the bearer token the `moj-contest` session left in `~/.config/moj/token-<cid>`.

**Tech Stack:** Python 3, `requests` (already a dependency), `pydantic` v2 for the whoami model, `pytest` with a stub shell script standing in for the CLI.

Design: [`2026-08-24-moj-submission-download-design.md`](2026-08-24-moj-submission-download-design.md).

---

## Things that will bite you

**`--json` placement.** `moj --json contest whoami` **silently loses the flag**: `moj` consumes `--json` into a shell variable, then `exec`s `moj-contest` without it, and `RAW` is not exported. The working invocation is `moj contest --json -c <cid> whoami` -- flag *after* the layer name. Verified live on 2026-08-24. This means `contest_whoami` must call `_run_moj` and parse the JSON itself; it must **not** use `_run_moj_json`, which prepends a global `--json`.

**Two failure modes, two different fixes.** `moj contest …` with no `moj-contest` on `PATH` exits 1 with `moj: camada 'contest' não instalada: curl -fLO https://moj.naquadah.com.br/moj-contest && chmod +x moj-contest`. With no session it exits 1 with `moj-contest: faça 'moj-contest login' primeiro.` The first message already carries its fix and is passed through. The second names a command that does not take a contest, so rbx replaces it with `moj-contest login <cid>`.

**Colon-bearing verdicts.** Do not split history lines positionally. See Task 3.

---

## Task 1: `contest_whoami` in the CLI wrapper

**Files:**
- Modify: `rbx/box/runners/moj/cli.py`
- Test: `tests/rbx/box/runners/moj/test_cli.py`

**Step 1: Write the failing tests**

Add to `test_cli.py`, next to the other stub-based tests. The canned body:

```python
_CONTEST_WHOAMI = (
    '{"success":true,"logged_in":true,"login":"ana.judge","name":"Ana A",'
    '"contest":"sbc2026","is_admin":false,"is_judge":true,"is_chief":false}\n'
)
```

Four tests:

```python
async def test_contest_whoami_reads_the_role_flags(monkeypatch, tmp_path):
    _stub_moj(monkeypatch, tmp_path, f"cat <<'EOF'\n{_CONTEST_WHOAMI}EOF\n")

    who = await cli.contest_whoami('sbc2026')

    assert who.login == 'ana.judge'
    assert who.can_read_any_submission
    # The flag goes AFTER `contest`: `moj --json contest ...` loses it entirely.
    assert _stub_calls(tmp_path) == [['contest', '--json', '-c', 'sbc2026', 'whoami']]


async def test_contest_whoami_says_how_to_log_in_when_there_is_no_session(
    monkeypatch, tmp_path
):
    _stub_moj(
        monkeypatch,
        tmp_path,
        "echo \"moj-contest: faça 'moj-contest login' primeiro.\" >&2\nexit 1\n",
    )

    with pytest.raises(MojCliError) as e:
        await cli.contest_whoami('sbc2026')
    # The CLI's own hint omits the contest, and so cannot be followed.
    assert 'moj-contest login sbc2026' in str(e.value)


async def test_contest_whoami_passes_through_the_missing_layer_message(
    monkeypatch, tmp_path
):
    _stub_moj(
        monkeypatch,
        tmp_path,
        "echo \"moj: camada 'contest' nao instalada: curl -fLO "
        'https://moj.naquadah.com.br/moj-contest\\" >&2\nexit 1\n',
    )

    with pytest.raises(MojCliError) as e:
        await cli.contest_whoami('sbc2026')
    assert 'curl -fLO' in str(e.value)
    assert 'moj-contest login' not in str(e.value)


async def test_contest_whoami_refuses_output_that_is_not_json(monkeypatch, tmp_path):
    _stub_moj(monkeypatch, tmp_path, "echo 'contest: sbc2026  login: ana'\n")

    with pytest.raises(MojCliError):
        await cli.contest_whoami('sbc2026')
```

**Step 2: Run to verify they fail**

`uv run pytest tests/rbx/box/runners/moj/test_cli.py -k contest_whoami -v` → FAIL, `module 'cli' has no attribute 'contest_whoami'`.

**Step 3: Implement**

In `cli.py`:

```python
class ContestWhoami(BaseModel):
    """`/auth/status` for one contest, as `moj contest --json whoami` relays it."""

    model_config = ConfigDict(extra='ignore')

    login: str
    contest: Optional[str] = None
    is_admin: bool = False
    is_judge: bool = False
    is_chief: bool = False

    @property
    def can_read_any_submission(self) -> bool:
        """Whether this session may list submissions other than its own.

        A plain `.judge` is enough: the contest's own judge screen lists every
        submission through `/contest/allsubmissions` and links each one's source.
        What a plain judge loses is the *identity* behind a row, not the code.
        """
        return self.is_judge or self.is_chief or self.is_admin
```

and, defaulting every flag to `False` so an older server that omits one reads as
"no access" rather than failing to parse:

```python
_NO_SESSION_RE = re.compile(r'\blogin\b.*\bprimeiro\b', re.IGNORECASE)


async def contest_whoami(contest: str) -> ContestWhoami:
    try:
        out = await _run_moj(['contest', '--json', '-c', contest, 'whoami'])
    except MojNotInstalledError:
        raise
    except MojCliError as e:
        if _NO_SESSION_RE.search(str(e)):
            raise MojCliError(
                f'There is no `moj` session for the contest `{contest}`.\n'
                f'Log in with `moj-contest login {contest}` and try again.\n'
                f'Note this is a *different* session from the one `moj login` '
                f'creates, which only ever covers `treino`.'
            ) from e
        raise
    try:
        return ContestWhoami.model_validate(json.loads(out))
    except (json.JSONDecodeError, ValidationError) as e:
        raise MojCliError(
            f'Could not read the output of `{MOJ_BINARY} contest --json -c '
            f'{contest} whoami` as an auth status.\n{out.strip()}'
        ) from e
```

`--json` goes after `contest` deliberately; comment it at the call site.

**Step 4: Run to verify they pass**

`uv run pytest tests/rbx/box/runners/moj/test_cli.py -v`

**Step 5: Commit**

```bash
git add rbx/box/runners/moj/cli.py tests/rbx/box/runners/moj/test_cli.py
git commit -m "feat(moj): read a contest session's role via \`moj contest whoami\`"
```

---

## Task 2: Session file and base URL

**Files:**
- Create: `rbx/box/tooling/moj/__init__.py`, `rbx/box/tooling/moj/api.py`
- Test: `tests/rbx/box/tooling/moj/__init__.py`, `tests/rbx/box/tooling/moj/test_api.py`

**Step 1: Write the failing tests**

```python
def test_token_comes_from_the_per_contest_file(monkeypatch, tmp_path):
    monkeypatch.setenv('MOJ_CONFIG_DIR', str(tmp_path))
    (tmp_path / 'token-sbc2026').write_text('tok-abc')

    assert api.read_token('sbc2026') == 'tok-abc'


def test_treino_falls_back_to_the_legacy_unsuffixed_token(monkeypatch, tmp_path):
    # `lib/core.sh` keeps this fallback for `treino` and nothing else.
    monkeypatch.setenv('MOJ_CONFIG_DIR', str(tmp_path))
    (tmp_path / 'token').write_text('tok-legacy')

    assert api.read_token('treino') == 'tok-legacy'
    with pytest.raises(MojCliError):
        api.read_token('sbc2026')


def test_a_missing_token_says_which_login_command_makes_one(monkeypatch, tmp_path):
    monkeypatch.setenv('MOJ_CONFIG_DIR', str(tmp_path))

    with pytest.raises(MojCliError) as e:
        api.read_token('sbc2026')
    assert 'moj-contest login sbc2026' in str(e.value)


def test_base_url_honours_moj_url(monkeypatch):
    monkeypatch.setenv('MOJ_URL', 'http://localhost:8080/')
    assert api.base_url() == 'http://localhost:8080'
```

**Step 2: Run to verify they fail.**

**Step 3: Implement** in `api.py` -- mirroring `lib/core.sh`: `CFG = ${MOJ_CONFIG_DIR:-$HOME/.config/moj}`, `MOJ_URL` default `https://moj.naquadah.com.br` with trailing slashes stripped, and a `MOJ_HOST` header override. Token is `.strip()`ed (the CLI writes it with `printf`, no newline, but a hand-edited file may have one).

**Step 4: Run. Step 5: Commit.**

---

## Task 3: The history line parser

**Files:** same `api.py` / `test_api.py`.

This is the part most likely to be got wrong, so it is its own task with its own tests.

Both listings are colon-separated and **the verdict may contain colons**. The 7-field form is `tempo:user:probid:lang:verdict:epoch:subid`; the 9-field form appends `fullname:univ`, so it cannot be read from either end. Anchor on the `epoch:subid` pair instead -- a 10-digit number followed by a 32-hex digest -- and take `lang` as field 3 from the front, which is safe because the verdict is the only variable-width field and sits after it.

**Step 1: Write the failing tests**

```python
_SUB = 'd89e6b7735c675fd7b50b3354ba64097'

def test_parses_the_seven_field_own_history_form():
    line = f'1755000000:ana:A:cpp:Accepted:1755000000:{_SUB}'
    row = api.parse_submission_line(line)
    assert row == api.SubmissionRow(subid=_SUB, lang='cpp', epoch=1755000000)


def test_parses_the_nine_field_judge_form_with_trailing_identity():
    line = f'1755000000:ana:A:py:Wrong Answer:1755000000:{_SUB}:Ana A:UFPB'
    assert api.parse_submission_line(line).lang == 'py'


def test_survives_a_verdict_containing_a_colon():
    # MOJ documents this; its own judge.js splits positionally and gets it wrong.
    line = f'1755000000:ana:A:java:Judge Error: No_Servers:1755000000:{_SUB}:Ana:U'
    row = api.parse_submission_line(line)
    assert row.subid == _SUB
    assert row.lang == 'java'


def test_returns_none_for_a_line_with_no_submission_id():
    assert api.parse_submission_line('1755000000:ana:A:cpp:On queue::') is None
```

**Step 2: Run to verify they fail.**

**Step 3: Implement**

```python
_ROW_RE = re.compile(r':(\d{9,}):([0-9a-f]{32})(?::|$)')


def parse_submission_line(line: str) -> Optional[SubmissionRow]:
    match = _ROW_RE.search(line)
    if match is None:
        return None
    fields = line.split(':')
    if len(fields) < 4:
        return None
    return SubmissionRow(
        subid=match.group(2), lang=fields[3], epoch=int(match.group(1))
    )
```

**Step 4: Run. Step 5: Commit.**

---

## Task 4: `list_submissions` and `download_source`

**Files:** same `api.py` / `test_api.py`.

`list_submissions(contest, token, any_submission: bool)` GETs `/contest/allsubmissions` when `any_submission`, `/contest/history` otherwise, and returns `Dict[str, SubmissionRow]` keyed by subid. `download_source(contest, token, row)` GETs `/submission/source?contest=&id=&time=`.

Both send `Authorization: Bearer <token>`, add `Host` when `MOJ_HOST` is set, and raise `MojCliError` carrying the server's `error.message` when the body is the JSON error envelope. HTTP is mocked with `mock.patch('requests.get')`.

Tests: the judge path hits `allsubmissions`; the non-judge path hits `history`; a 401/403/404 surfaces the server's message; a successful source download returns the text verbatim.

Commit.

---

## Task 5: `MojExpander`

**Files:**
- Modify: `rbx/box/remote.py`, `rbx/box/completion/completers.py`
- Test: `tests/rbx/box/test_remote.py` (create if absent), `tests/rbx/box/completion/enum_consistency_test.py:31-32`

Reference grammar: `@moj/<cid>/<subid>` or `@moj/<subid>` with the contest from `MOJ_CONTEST`. `<subid>` must match `^[0-9a-f]{32}$` -- MOJ's own check, done locally so a typo costs no round-trip.

`expand()`:
1. Parse the ref; a bad one returns `None` (not this expander's).
2. `await cli.contest_whoami(cid)`.
3. `list_submissions(...)`; a subid that is not there errors with "not visible to `<login>` in `<cid>`" rather than letting the source call answer a bare `404`.
4. `download_source(...)`, write to `.remote/moj/<cid>/<subid>.<ext>`.

Extension: `normalize_moj_language` → `get_rbx_language_from_moj_language` → `Language.extension`, falling back to the raw `lang` lowercased.

`needs_review()` returns `True` and `cacheable_globs` returns `.remote/moj/<cid>/<subid>.*`, both as BOCA does.

Then update `_SOLUTION_PREFIXES` with `('@moj/', 'download a MOJ submission, e.g. @moj/<contest>/<id>')` and both assertions in `enum_consistency_test.py`.

Commit.

---

## Task 6: Docs

- `docs/setters/cheatsheet.md:38,56` -- a `@moj/` row beside each `@boca/` one.
- `docs/setters/packaging/moj.md` -- a section on downloading a submission: the ref grammar, that it needs `moj-contest login <cid>` (*not* `moj login`), and that a judge sees everyone's code while everyone else sees only their own.

Follow [`docs/plans/docs-writing-style-guide.md`](docs-writing-style-guide.md). Do not commit a regenerated `docs/setters/reference/cli.md`.

Commit.

---

## Task 7: Verify

1. `uv run pytest tests/rbx/box/runners/moj tests/rbx/box/tooling/moj tests/rbx/box/completion -v`
2. `uv run ruff check . && uv run ruff format --check .`
3. Manual end-to-end against `treino` with the live session, confirming the error path for an id that does not exist and the success path for one that does.
