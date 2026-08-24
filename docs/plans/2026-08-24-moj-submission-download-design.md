# Downloading a MOJ submission: `@moj/<cid>/<subid>`

`@boca/<run>` pulls a contestant's submission out of BOCA and hands it to `rbx run`,
`rbx stress` and `rbx download remote` as an ordinary solution path. MOJ has no
counterpart. This design adds one.

The shape is deliberately the same as BOCA's -- a new `Expander` in
[`rbx/box/remote.py`](../../rbx/box/remote.py), the same review gate, the same cache
directory. What differs is everything underneath, because MOJ is a REST API with roles
rather than a scraped PHP form.

## What MOJ actually offers

Read from the **public OpenAPI spec** (`https://moj.naquadah.com.br/api/openapi.json`,
221 paths, served by the Swagger page at `/api/`), the shipped CLI layers (`moj`,
`moj-contest`, `moj-judges`, `moj-comp`, build `b6b0c21-20260821`), the contest
front-end (`/contest/**/*.js`, `/shared/submission-links.js`) and live probes against
`treino` on 2026-08-24.

| Endpoint | What it gives |
|---|---|
| `GET /api/v1/submission/source?contest=&id=&time=` | The submission's source, `text/plain`. Bearer auth. |
| `GET /api/v1/contest/history?contest=` | **Your own** submissions, 7-field TXT. |
| `GET /api/v1/contest/allsubmissions?contest=` | **Everyone's**, 9-field TXT. Judge-gated. |
| `GET /api/v1/auth/status?contest=` | `login` + the role booleans. |

Verified behaviour of `/submission/source`:

| Case | Response |
|---|---|
| No `Authorization` header | `401 auth_required` |
| Unknown contest | `404 contest_notfound` |
| Missing `id` | `400 id_missing` |
| `id` not 32 lowercase hex | `400 id_invalid` |
| Well-formed `id`, no such source | `404 source_notfound` |
| Success | `200 text/plain`, **no `Content-Disposition`** |

The id is an md5 digest: `handlers/submit.sh` "valida + gera id (md5)" and the daemon
archives the source at `users/<login>/submissions/<id>.<ext>` (`FLOW.md`). The `time`
parameter is the submission's epoch and is **optional** -- format validation passes
without it -- but MOJ's own front-end always sends it, so rbx does too.

### A pending submission has no source yet

Found by the end-to-end run, not by reading: the daemon archives the source at **step 5**
of judging, *after* it has a verdict. Ask for a submission still showing
`Not Answered Yet` and the server answers `404 source_notfound` -- byte for byte the reply
for an id that does not exist, about a submission rbx has just listed from the same
server.

So the listing row carries its verdict, and rbx refuses a pending download by name rather
than passing that 404 on. The pending vocabulary is `moj-comp`'s own `_watch_verdict` set
(`Not Answered Yet`, `On queue`, `Running`, empty), matched case-insensitively because
that loop lists `On queue` and `on queue` both.

### Who may read a submission

Roles are a login suffix **inside a contest**: `.admin`, `.judge`, `.cjudge` (chief),
`.staff`, `.cstaff`, `.mon`, `.animeitor`. A plain `.judge` is enough: `contest/judge/judge.js`
lists every submission through `/contest/allsubmissions` and renders `srcLink()` -- the
same `/submission/source` call -- for each row. What a plain judge loses is **identity,
not code**: the server blanks `username`/`fullname`/`univ` for judge and monitor, and
fills them only for admin and chief.

Confirmed live with a non-judge account: `/contest/allsubmissions` and
`/contest/review/list` both answer `403 judge_required`.

**Not verified, deliberately:** whether a plain participant is refused a *stranger's*
source given a valid id. `/submission/summary` documents itself as "same gate as the log;
third-party ids omitted", so `/submission/source` is near-certainly gated the same way --
but a positive result from probing it would be a MOJ vulnerability report, not an rbx
feature, so it went untested. Nothing below depends on the answer: rbx gates on the
listing lookup regardless.

### Sessions are per contest, and `moj login` does not create them

`lib/core.sh` -- shared by all four CLI layers -- keeps **one token per contest**:

- `CFG = ${MOJ_CONFIG_DIR:-$HOME/.config/moj}`, mode 700
- `$CFG/token-<contest>`, umask 077
- `$CFG/hdr-<contest>`, literally `Authorization: Bearer <tok>`, for `curl -H @file`
- Legacy fallback `$CFG/token` / `$CFG/hdr`, **`treino` only**
- Base URL `${MOJ_URL:-https://moj.naquadah.com.br}`; `MOJ_HOST` overrides the `Host` header

`moj login` writes `token-treino` and nothing else. The command that creates a contest
session is **`moj-contest login <cid>`**, which is a *separate artifact* from `moj`:
`moj contest …` delegates to a `moj-contest` executable beside the script or on `PATH`,
and dies with an install command when there is none.

No CLI layer wraps `/submission/*` or `/contest/history`. Those two calls must be made
directly; everything else goes through `moj-contest`.

## Design

### Reference syntax

`@moj/<cid>/<subid>`, with `@moj/<subid>` resolving the contest from `MOJ_CONTEST`.

The contest is part of the reference because a reference gets committed into
`problem.rbx.yml`, where it has to still mean something a month later on someone else's
machine. `<subid>` is checked against `^[0-9a-f]{32}$` before any network call: it is
MOJ's own validation, so matching it locally turns a typo into an immediate error instead
of a round-trip.

There is deliberately **no** `extensions.moj.contest` field for the shorthand.
`MOJ_CONTEST` is MOJ's own convention and every CLI layer already honours it; a second
source of truth for "which contest" is the ambient state the explicit form exists to
avoid.

### Preconditions

1. `moj contest -c <cid> --json whoami`. With `--json` before the subcommand this returns
   the raw `/auth/status` body:

   ```json
   {"success":true,"logged_in":true,"login":"rsalesc","name":"Roberto Sales",
    "contest":"treino","is_admin":false,"is_judge":false,"is_chief":false, …}
   ```

   Two failure modes, both exit 1: `camada 'contest' não instalada: curl -fLO …` when the
   layer is missing, and `faça 'moj-contest login' primeiro.` when there is no session.
   The first already carries its own fix and is passed through untouched. The second is
   **replaced**, because the command it names does not take the contest and so does not
   actually help; rbx says `moj-contest login <cid>` instead.

2. Read `is_judge` / `is_admin` / `is_chief` out of that JSON. This is what selects the
   listing endpoint below -- which is why shelling out here is load-bearing rather than a
   presence check that could be an HTTP call instead.

### Fetching

1. Judge, chief or admin → `GET /contest/allsubmissions?contest=<cid>`.
   Otherwise → `GET /contest/history?contest=<cid>`.
2. Find the row whose subid matches; take `lang` and `epoch` from it. **A miss is the
   error**: rbx reports that `<subid>` is not visible to `<login>` in `<cid>`, rather than
   letting the source call answer a bare `404 source_notfound`, which cannot tell "no such
   submission" from "not yours".
3. `GET /submission/source?contest=<cid>&id=<subid>&time=<epoch>`.

Both raw calls use `requests` (already a dependency) with the bearer token read from the
token file, honouring `MOJ_CONFIG_DIR`, `MOJ_URL` and `MOJ_HOST` exactly as `lib/core.sh`
does.

### Parsing the history lines

Both listings are colon-separated, and **the verdict may itself contain colons** -- MOJ
documents this and its own `contest/contest.js` slices from the end to survive it. The
7-field form (`tempo:user:probid:lang:verdict:epoch:subid`) is end-anchored parseable; the
9-field form appends `fullname:univ`, so it is not. MOJ's `judge.js` splits the 9-field
form positionally (`v[4]` verdict, `v[6]` id) and would mis-read such a row.

rbx anchors on the pair instead, scanning for `:(\d{9,}):([0-9a-f]{32})(?::|$)`. A
10-digit epoch followed by a 32-hex digest is unmistakable, and `lang` is field 3 from the
front -- unambiguous, because the verdict is the only variable-width field and it sits
*after* `lang`. One parser serves both formats.

### Naming the file

The endpoint sends no filename, so rbx builds one: `<subid>.<ext>` under
`.remote/moj/<cid>/`. The extension comes from MOJ's `lang` through the mapping that
already exists for packaging -- `normalize_moj_language` → `get_rbx_language_from_moj_language`
→ `Language.extension` -- falling back to the raw `lang` lowercased, which is what the MOJ
web UI does.

`cacheable_globs` returns `.remote/moj/<cid>/<subid>.*`, so a second run does not
re-download. `needs_review()` is `True`, as for BOCA: this is untrusted third-party code
entering the package, which is the whole reason that hook exists.

### Layout

| File | Change |
|---|---|
| `rbx/box/runners/moj/cli.py` | `MOJ_CONTEST_ARGV`, `contest_whoami(cid) -> ContestWhoami` |
| `rbx/box/tooling/moj/api.py` | token/base-URL resolution, `list_submissions`, `download_source` |
| `rbx/box/remote.py` | `MojExpander`, registered after `BocaExpander` |
| `rbx/box/completion/completers.py` | `('@moj/', …)` prefix |

The completer is not optional: `enum_consistency_test.py` asserts that its prefix list
mirrors `REGISTERED_EXPANDERS`.

## Testing

Stub-binary tests for `contest_whoami` -- success, missing layer, missing session, missing
`-c` -- mirroring the existing MOJ CLI stub tests. Unit tests for the line parser (both
widths, colon-bearing verdicts, absent id) and the reference parser (valid, bad hex, wrong
length, shorthand with and without `MOJ_CONTEST`). HTTP mocked with `mock.patch`.

No live-API test in the suite, matching how the rest of the MOJ integration is tested; a
manual end-to-end run against `treino` gates the work instead.

### What the live run confirmed (2026-08-24)

Against `treino`, as `rsalesc` (a plain competitor there):

| Path | Result |
|---|---|
| `moj contest --json -c treino whoami` | the raw `/auth/status` JSON, role flags included |
| no session for a contest | rbx's own `moj-contest login <cid>` message |
| `/contest/allsubmissions` as a non-judge | `403 judge_required`, surfaced with MOJ's wording |
| well-formed id, no such submission | reported by rbx before the download is attempted |
| malformed id | refused locally, no request made |
| `MOJ_CONTEST` shorthand | resolves, end to end through `rbx download remote` |
| pending submission | "still judging", not MOJ's `404` |
| **judged submission** | **downloaded byte-identical, named `<subid>.cpp`** |

The success path was verified by submitting a throwaway to `rsalesc#rbxt-3b302f1b` -- one
of rbx's own private, disposable problems -- and downloading it back. Note the history row
spells the language `CPP`, uppercase, which is why the extension is derived through
`normalize_moj_language` rather than used as it arrives.

Still unverified: the judge listing (`/contest/allsubmissions` with a judge account) and
therefore a download of *someone else's* submission. No judge account was available.
