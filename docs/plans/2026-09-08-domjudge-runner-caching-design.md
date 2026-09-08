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

Both caches turn on one question: *is the judge configured identically?* Neither
the `rbxt-` problem id nor `_package_fingerprint` can answer it -- the latter
hashes the package name and testcase count only, deliberately, so the probe
problem does not churn and strand dead problems on the server.

So `_build_probe` now also returns `_directory_fingerprint` of the built package
tree: sorted relative POSIX paths and contents, lengths framed. It covers exactly
what the upload sends -- `domjudge-problem.ini` (which carries the pinned limit),
`problem.yaml`, `data/`, `output_validators/` -- and nothing else, because a probe
ships no statement and no submissions.

Taken over the tree rather than the zip: `shutil.make_archive` stamps every entry
with its mtime, so two builds of an identical package produce different archives.

The problem id is left exactly as it was.

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

## 5. What this deliberately does not do

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
