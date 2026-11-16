# Fanout communication problems (several contestant processes)

Status: design approved 2026-11-16. Packaging is out of scope (see "Follow-ups").

## Goal

Support problems where **N copies of the contestant program run at once against one
interactor** -- the model of CMS `Communication` with `num_processes = N` (IOI 2022 Cards,
IOI 2024 Message, APIO 2022 Mars, IOI 2026 Classroom Game with 64 processes). Typical uses:
"run twice" encoder/decoder tasks, and tasks whose parties must not share memory.

Background research (Kattis multi-pass, CMS task types, Polygon run-twice, olympiad
precedents) was done in the brainstorming session that produced this doc. The decision was to
model CMS's concurrent processes, since CMS is the target judge; sequential multi-pass
(Kattis/Polygon) is not modelled.

## Model

```yaml
type: communication
interactor:
  path: interactor.cpp
  processes: 3        # optional, >= 2; set => fanout
```

- `Interactor.processes: Optional[int]`, `>= 2` when set (1 would be an alias for "unset",
  and CMS only passes the process index when N > 1). Works with modern and legacy
  interactors, with or without a grader.
- No new `TaskType`. Predicates on `Package`:

  | predicate | definition |
  | --- | --- |
  | `is_communication` | `type == communication` (the problem has an interactor) |
  | `is_interactive` | communication and `processes` unset |
  | `is_fanout` | communication and `processes` set |
  | `fanout_processes` | `Optional[int]` |

- `pkg.kind` in {`batch`, `interactive`, `fanout`}, derived from the predicates. Packagers
  declare `kinds()` instead of `task_types()`; `run_packager` gates on it. Runners get
  `RunnerCapabilities.supports_fanout`.
- **Refactor rule.** Every `TaskType.COMMUNICATION` comparison (34 sites, 18 files) and every
  dispatch on `interactor_digest is not None` is classified by hand:
  - "the problem has an interactor" (compile/pass it, answer from its output) ->
    `is_communication`. E.g. visualizers' `_compile_interactor`, output generation.
  - "exactly one pipe pair" (`.pin`/`.pout`, statement samples, single-process dispatch,
    packagers without fanout support) -> `is_interactive`.

  Replacing everything with `is_interactive` would make a fanout problem silently run
  batch-style wherever the site meant "has an interactor".

## Contestant processes

- All N run the same compiled solution (linked with the grader if any).
- Process i gets its 0-based index as `argv[1]` (what CMS appends in `std_io` mode).
- Each process's stdin/stdout is its own pipe pair to the interactor.

## Interactor contract

```
interactor <input> <output> <from_0> <to_0> ... <from_{N-1}> <to_{N-1}>
```

CMS's own argument order; N = (argc - 3) / 2.

`rbx::registerFanoutInteraction(argc, argv)`, emitted into `rbx.h` only for fanout problems
(like the grader judge helpers; testlib must be included first):

- sets up `inf` and `tout` as `registerInteraction` does, and consumes the grader input header
  when there is a grader;
- opens, for i ascending, `to_i` (write) **then** `from_i` (read) -- the order that cannot
  deadlock against a CMS sandbox, which opens a process's stdin before its stdout;
- wraps each `from_i` in an **unbuffered** `InStream` in `_output` mode. testlib's
  `InStream::init(path)` (and `init(FILE*)` for non-std files) picks
  `BufferedFileInputStreamReader`, whose `fread` of ~1 MB blocks on a pipe;
- exposes `rbx::fanout::count()`, `from(i)` (`InStream&`), `to(i)` (`std::ostream&`, flushed by
  the setter), `close_all()`.

```cpp
#include "testlib.h"
#include "rbx.h"

int main(int argc, char *argv[]) {
  rbx::registerFanoutInteraction(argc, argv);
  int x = inf.readInt();
  rbx::fanout::to(0) << x << std::endl;               // process 0 encodes
  int code = rbx::fanout::from(0).readInt(0, 1000000, "code");
  rbx::fanout::to(1) << code << std::endl;            // process 1 decodes
  int y = rbx::fanout::from(1).readInt();
  if (x != y) quitf(_wa, "expected %d, got %d", x, y);
  quitf(_ok, "ok");
}
```

Locally the paths are `/dev/fd/K` of inherited pipe ends (opening never blocks, Linux and
macOS); on CMS (future) the manager forwards its fifo arguments unchanged.

## Execution (interactive is the N = 1 case)

No fanout copies of the communication code: interactive becomes the single-process case of
generalized code. The existing interactive tests are the safety net and must pass unchanged
before fanout-specific code lands.

- **Sandbox.** `SandboxBase.run_fanout(...) -> (List[SandboxLog], SandboxLog)` is the only
  implementation. `run_communication` wraps it with N = 1, no index argument, the interactor on
  stdin/stdout instead of `/dev/fd` paths, and `.pin`/`.pout` copies. Shared: pipe setup, tees,
  per-process drainer, process-group reaping, kill rules. Docker client/agent forward the same
  request, parameterized by N.
  - Fanout: interactor stdin/stdout are `/dev/null`; each process's stderr goes to a scratch
    file in the sandbox.
  - Kill rules: interactor exits non-zero while processes run -> kill the group (as today);
    exits zero -> processes see EOF and are reaped within their own limits (CMS behaviour).
- **Tees.** `chunk_tee.py`/`line_tee.py` take a marker parameter: `<`/`>`/`!` for interactive,
  `[i]<`/`[i]>`/`[i]!` for fanout. 2N tees (+N with `--merge-stderr`). A single
  multiplexing relay would order lines better but needs non-blocking buffered writes to avoid
  new deadlocks -- deferred.
- **`tasks.py`.** `_run_communication_solution_on_testcase` builds N `CommunicationItem`s.

### Limits (CMS semantics)

| who | CPU | wall | memory |
| --- | --- | --- | --- |
| each process | TL (enforced per process) | problem wall limit, from spawn | ML |
| all processes | **sum >= TL -> TLE** | -- | -- |
| interactor | N x TL + margin | solution wall + existing 1 s margin | as today |

Reported time is the **sum** of process CPU times, so `rbx time`, reports and `_convert_tle`
read exactly what CMS judges.

### Verdict

`check_communication` is generalized to a list of solution logs (no `check_fanout`); for N = 1
every rule degenerates to today's. First match wins:

0. any sandbox failure -> `INTERNAL_ERROR`;
1. interactor crashed first (non-testlib exit) -> `JUDGE_FAILED`;
2. interactor over its own limits -> `JUDGE_FAILED`;
3. interactor rejected before any process failed -> its WA (CMS would report the processes it
   left behind as killed; both score 0);
4. a process failed: summed CPU >= TL or a process over CPU/wall -> TLE; over memory -> MLE;
   else non-zero exit/signal -> RTE. Applies **even if the interactor accepted** (CMS scores
   any user failure 0). The first process to exit decides; the message names it
   (`process 3: RTE (signal 11)`) when N > 1;
5. else the interactor's testlib verdict; a legacy interactor then runs the checker on `.out`.

## Artifacts, logs, caching

Same file set for every N -- no per-process files:

| file | fanout content |
| --- | --- |
| `.out` | interactor output |
| `.sol.err` | all processes' stderr, merged by the grading step, grouped by process, each line prefixed `[i] ` (interactive: untagged, unchanged) |
| `.sol.log` | YAML list of N run logs (interactive: one, unchanged) |
| `.int.err`, `.int.log` | interactor, unchanged |
| `.pio` | tagged capture when capturing; no `.pin`/`.pout` |
| `.log` / `.eval` | aggregated evaluation + per-process breakdown |

- `TestcaseLog` keeps aggregate fields (time = sum CPU; wall and memory = max; exit fields and
  `stderr_absolute_path` from the deciding process / the merged file) and gains
  `processes: Optional[List[TestcaseLog]]` (numbers and exit fields only). `None` for
  interactive, and `.eval` drops `None`, so interactive bytes are unchanged.
- `GradingLogsHolder.run` -> `runs: List[RunLog]` (a `run` property for batch callers); cache
  restore copies the list; `processes` joins the cache params; bump `CACHE_STEP_VERSION`.
- `testcase_artifacts(log)` lists every file of an evaluation. Used by
  `Retrier._move_logs_to_temp_dir` and by stress when keeping a failing test -- also fixing
  today's gap where `.pin`/`.pout`/`.pio`/`.int.*` were left behind or not kept.

## Interaction format

```
<
>
[0]<3 5
[0]>8
[1]<-1
[1]>8
[1]!debug from process 1
```

- Optional `[k]` before the direction character, in `.pio` (no separator, as today) and
  `.interaction` (`[0]< 3 5`). Untagged = single process, so existing files are unchanged.
- `TestcaseInteractionEntry.process: Optional[int]`; mixing tagged and untagged lines is a
  parse error; the sample pipeline checks `k < N`.
- `merge_interaction_entries` merges on (direction, process).
- `print_interaction` shows the tag (one shared function).
- Ordering across processes is tee write order: exact in line-capture mode (samples), possibly
  interleaved mid-line in chunk mode.

## Consumers

| consumer | change |
| --- | --- |
| build / output generation | `is_communication` gate; `.out` of the interactor is the answer; samples capture tagged `.pio`; `_copy_testcase_outputs_over` uses `testcase_artifacts` |
| `rbx run` | unified path; failure names the process; `run_report.py` unchanged (aggregate) |
| `rbx time`, benchmark | summed time; `estimation_checksum` also fingerprints `processes` |
| `rbx irun` | unchanged, incl. typing the test input (it is the interactor's input); `-p` shows tags |
| `rbx stress` | transparent via `tasks`; keeps all artifacts |
| visualizers | `is_communication`; read `.out`/`.pio` as produced |
| `rbx summary` | shows "fanout, N processes" |
| `rbx.h` | fanout helper only for fanout problems; everything else byte-identical |
| statements | process index plumbed into sample chunks; templates render interactions only for `is_interactive` (fanout rendering deferred) |
| TUI | interaction pane only for `is_interactive`; fanout falls back to `.out`/`.sol.err` until the follow-up |
| VS Code | check that a tagged `.pio` degrades gracefully; if not, skip the interaction view on parse failure |
| packagers | none declares `fanout` -> all refuse before the build |
| remote runners | `supports_fanout = False` (MOJ, DOMjudge); `LocalRunner` True |

## Testing

- Unit: schema/predicates/kind; sandbox N = 3 echo interactor (argv index, `/dev/fd` order,
  tagged markers, kill rules, merged tagged stderr); steps/caching (`runs` round-trip, miss on
  N change); checker ladder (N = 1 unchanged; summed-CPU TLE; RTE after accept; interactor WA
  first; process named); `tasks` artifacts and interactive `.eval` bytes; interaction parsing;
  `testcase_artifacts` in retries/stress; header emitted only for fanout; gates in packagers,
  runners, `estimation_checksum`.
- e2e (`tests/e2e/testdata/`, `RBX_DOCKER=0`):
  - `fanout`: modern interactor, `processes: 3`, `alone`; solutions AC, WA, RTE-after-accept,
    TLE-by-sum, shared-state cheater; `rbx build`, `rbx run`, `rbx irun -p`, `-cp`.
  - `fanout-grader`: same protocol through a grader stub reading `argv[1]`.

## Docs

`docs/setters/grading/interactors.md` gets a **short, usability-first** section: one sentence
on what fanout is, the `processes` snippet, a small interactor snippet, and one line each on
`argv[1]`, the summed time limit, and "a failing process scores 0 even if the interactor
accepted". No verdict ladder, file layout or limits arithmetic. Written with the `docs-style`
skill. `rbx/box/CLAUDE.md` documents the predicates.

## Follow-ups

- CMS packaging via `rbx package polygon --cms` (#1043): the
  Polygon packager declares `fanout` only with `--cms` (refused without it and with `--upload`);
  `task_type_parameters` -> `[N, 'alone'|'stub', 'std_io']`; one `cms_manager.cpp` with
  `-DRBX_CMS_FANOUT` forwarding argv to the interactor and calling `rbx::fanout::close_all()`
  in `report_at_exit`; time limit written as is (CMS also sums CPU); grader stub unchanged;
  verified on the remote CMS 1.5.1 harness.
- TUI and VS Code support for the tagged format: #1044.
- Rendering fanout samples in statements: #1045.
- Fanout variant of the olympiad preset: #1042.
