# DOMjudge runner caching -- design

Companion to [the DOMjudge remote runner design](2026-09-08-domjudge-remote-runner-design.md).
That document leaves every run paying full price; this one makes a re-run cost
nothing. It mirrors what the MOJ runner already does, and the parts where it
does not mirror it are the interesting parts.

## 1. The problem

`rbx time` is a command a setter runs *again*: tweak a solution, re-estimate,
change the profile, look at the table once more. Every re-run re-stages the whole
probe package -- four requests and a zip upload of the entire testset -- and
re-submits every solution, including ones whose source has not changed by a byte.

A submission occupies the judgehost for as long as the solution takes on every
test, and `MAX_INFLIGHT_SUBMISSIONS = 1` makes that strictly serial. The picker
also alternates between the two phases as it narrows, so a limit already probed
is re-measured from scratch every time it comes back around.

## 2. A real package fingerprint

Both caches turn on one question: *is the judge configured identically?* The
`rbxt-` problem id cannot answer it -- it names *which* problem, deliberately
stable across edits (see §5), and says nothing about what is in it.

So `_build_probe` now also returns `_directory_fingerprint` of the built package
tree: sorted relative POSIX paths and contents, lengths framed. It covers exactly
what the upload sends -- `domjudge-problem.ini` (which carries the pinned limit),
`problem.yaml`, `data/`, `output_validators/` -- and nothing else, because a probe
ships no statement and no submissions.

Taken over the tree rather than the zip: `shutil.make_archive` stamps every entry
with its mtime, so two builds of an identical package produce different archives.

The two questions stay separate on purpose: *which problem* is the slug's job and
must not move when a testcase changes, while *what is in it* is the
fingerprint's and must.

## 3. The upload fast path

`<problem cache>/domjudge-runner.json`, a map from `<server>|<problem id>` to the
fingerprint this machine last staged there. On a match `prepare` skips
`stage_problem` and says so in one durable line.

Two departures from MOJ's equivalent:

- **Keyed by server.** `rbxt-` ids are derived from the package, so the same id
  on a staging instance and on a production one collides by construction.
- **The record is not trusted alone.** The problem must also still be listed in
  the probe contest -- the server's own answer, which catches a probe problem
  deleted by hand or a record carried onto an instance that was wiped.
  `stage_problem` fetches that list anyway on the path this skips, so the check
  costs a request only when it is about to save an upload.

The record is cleared *before* an upload, so a crash mid-upload re-uploads next
time rather than trusting a stale record.

## 4. The judgement cache

`<problem cache>/domjudge-judgements/<key>.json`, one file per key, written whole
then `replace`d.

**The key** is everything the judge's answer depended on: the cache version, the
server, the contest, the problem id, the package fingerprint, the solution's
filename, the DOMjudge language id, and the exact amalgamated bytes submitted.
The pinned limit needs no term of its own -- it is in the ini, which the
fingerprint covers -- so the validation phase misses on every solution by
construction, which is right: a timing taken under a 2.5s kill is not a timing
under a 4s one.

**What is stored** is the API's own answer: the judgement object and the final
run list, never the derived evaluations. The derivation depends on which
testcases *this* run asked about, so storing its output would bake one run's
testset into an entry the next run reuses. A hit publishes the stored runs into
the same `_Judging` a fresh submission publishes into, so a hit and a miss are
provably the same measurement -- pairing, the mismatch guard and the
unknown-verdict refusal all still apply.

**A hit is consulted before the concurrency slot**, not inside it. It costs one
file read and no judge time, and with the cap at one, queueing it would make
every hit wait out every miss ahead of it.

**Never written** when the judging has no runs at all (a compile error, a
judgehost that fell over -- the analogue of MOJ's `ran_nothing`), when the run
list was refused as unpairable, or when any run carries a verdict outside
`_OUTCOMES`. Each is a thing the setter is about to *fix*, and a cached failure
would make the fix appear to change nothing.

A WA, an RE or a TLE **is** cached. Those are legitimate, reproducible
measurements -- the validation phase exists to measure exactly them -- and they
are the slowest solutions in the package, so they are what a re-run most wants
back for free.

## 5. One problem identity, shared with MOJ

The caches above are per package, so they raise a question the runner had been
answering badly: *what is this package called on the server?*

DOMjudge derived its `rbxt-` id from `sha256(f'{pkg.name}:{len(entries)}')[:8]`.
That moves whenever a testcase is added -- the run then stages a brand new
problem and abandons the previous one -- and two packages that happen to agree on
name and testcase count collide on a shared instance. MOJ, meanwhile, minted its
own slug into `.moj-id`. One package, two unrelated identities, neither stable
for the reason the other was.

`rbx.box.runners.problem_id` now holds the one identity: a random slug in
`.rbx-id` at the package root, minted once and then kept. Each backend renders
its own id from it -- `<login>#rbxt-<slug>` for MOJ, whose ids are scoped by org;
`rbxt-<slug>-<purpose>` for DOMjudge, whose ids are flat and whose two phases pin
different limits. `RBXT_PREFIX`, the marker for "a problem rbx may overwrite",
moves there too: it belongs to every backend rather than to one.

The slug is random rather than derived from anything, and both halves of that
matter. Not the package name: rbx names are not unique, so two setters working
through the same tutorial package would collide on a shared server and one would
write over the other's problem. Not the testset: it changes constantly, and every
change would strand a dead problem.

**Migration runs one way.** A `.moj-id` written before `.rbx-id` existed names a
problem MOJ already holds, so `ensure_moj_id` *adopts* its slug into the shared
file rather than overwriting it from there. An existing shared slug always wins,
so a package holding both keeps both and neither backend is moved off the problem
it has been using. A foreign binding -- `.moj-id` is written by `moj upload` too,
so a package may be bound to a real, published problem -- is neither adopted nor
rewritten.

DOMjudge probe problems staged before this change keep their old hash-derived
ids and are simply left behind: they are private, throwaway, and in a contest
with no scoreboard.

## 6. What this deliberately does not do

- **No `--no-cache` flag.** "I changed something" is what the key is for; "I want
  to see the variance" is not a workflow this backend supports at all, since
  `nruns > 1` is refused outright. The blind spot no flag could fix -- a park
  whose hardware or load moved underneath the numbers -- is answered by deleting
  a directory under the disposable problem cache.
- **No expiry, no size cap, no eviction.** An entry is a few hundred bytes, and a
  stale one is unreachable rather than wrong: its key names a package fingerprint
  no later run will ever produce again.
- **Nothing is committed.** Both caches say what *a* server answered at *a*
  moment, from *this* machine. Losing either must cost redundant work, never a
  wrong measurement, which is why they live in `.rbx/`.
