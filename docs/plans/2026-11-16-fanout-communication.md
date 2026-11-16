# Fanout Communication Problems Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let a `communication` problem whose interactor sets `processes: N` (N >= 2) run N copies of the contestant program at once against one interactor, locally, with CMS `Communication` semantics.

**Architecture:** Interactive problems become the N = 1 case of one generalized code path: one sandbox primitive (`run_fanout`), one coordinated grading step, one verdict ladder fed with the processes' logs folded into one (`combine_process_logs`). Per-process differences are parameters (command-line index, `/dev/fd` channel paths, `[i]` capture markers, merged tagged stderr), never a parallel code path. The interactor talks to the processes through a new `rbx::registerFanoutInteraction` helper emitted into `rbx.h` for fanout problems only.

**Tech Stack:** Python 3 (pydantic v2, subprocess/os pipes, asyncio), C++ testlib, the rbx sandbox (`StupidSandbox`, `DockerSandbox` + agent), the e2e YAML DSL.

**Design:** `docs/plans/2026-11-16-fanout-communication-design.md`. Follow-ups out of scope: CMS packaging (#1043), TUI/VS Code (#1044), sample rendering (#1045), preset (#1042).

---

## How this plan is meant to be executed

**Not TDD.** Every task is: **implement -> verify by hand, extensively (real `rbx` runs on a scratch problem, plus stress where it applies) -> run the regression gate -> commit.** Unit tests are a *contract* written at the end (Task 14) that pins behaviour already verified by hand. Don't write them earlier.

**Regression gate** (run after every task that touches shared code; it must stay green -- it is the safety net that interactive problems, now the N = 1 case, behave exactly as before):

```bash
cd /Users/rsalesc/Dev/robox.io
uv run pytest -q \
  tests/rbx/grading/judge/test_run_communication.py \
  tests/rbx/grading/judge/test_chunk_tee.py \
  tests/rbx/grading/steps_run_coordinated_test.py \
  tests/rbx/grading/steps_with_caching_run_test.py \
  tests/rbx/box/checkers_communication_test.py \
  tests/rbx/box/tasks_test.py \
  tests/rbx/box/walltime_test.py \
  tests/rbx/box/testcase_utils_test.py \
  tests/rbx/box/test_testcase_sample_utils.py \
  tests/rbx/box/statements/test_sample_staging.py \
  tests/rbx/box/test_graders.py \
  tests/rbx/box/test_header.py \
  tests/rbx/box/runners/test_capabilities.py
RBX_DOCKER=0 uv run pytest -q \
  tests/e2e/testdata/interactive \
  tests/e2e/testdata/interactive-slow-interactor \
  tests/e2e/testdata/interactive-trailing-output \
  tests/e2e/testdata/grader-stub \
  tests/e2e/testdata/default-preset-interactive
```

Never run the full suite (slow, and it causes spurious sandbox wall timeouts). Never run a filesystem-wide `find /`.

**Docker.** The setter config on this machine has Docker enabled, so a plain `rbx run` goes through the Docker sandbox, and every edit under `rbx/` changes the image fingerprint (the first run after an edit rebuilds the image -- slow, expected). Verify every execution change **both** with `RBX_DOCKER=0` (native `StupidSandbox`) and with the default (Docker). e2e always needs `RBX_DOCKER=0`.

**Shell setup** used by every manual step (put it in your shell once per session):

```bash
export REPO=/Users/rsalesc/Dev/robox.io
export RBX="uv run --project $REPO rbx"
# Your session scratchpad (outside the repo). This path is the planning
# session's; use your own session's scratchpad if it differs.
export SCRATCH=/private/tmp/claude-501/-Users-rsalesc-Dev-robox-io/9ef4414a-cb29-43aa-b90c-bccd66d43374/scratchpad
export FANOUT=$SCRATCH/fanout-scratch       # the fanout problem (Task 1)
export IACT=$SCRATCH/iact-scratch           # an interactive baseline (Task 1)
export STUB=$SCRATCH/stub-scratch           # an interactive grader baseline (Task 1)
```

Run artifacts land in `<problem>/.rbx/runs/<solution index>/<group>/<NNN>.*` (`.out`, `.sol.err`, `.sol.log`, `.int.err`, `.int.log`, `.pio`, `.eval`, `.log`). Inspect them with `ls`, `cat`, `head`; `find .rbx/runs -name '*.pio'` scoped to the problem dir is fine.

**Commits** follow `.claude/skills/commit.md` (Conventional Commits; stage files by name; trailer `Co-Authored-By: Claude <noreply@anthropic.com>`). Never stage the untracked `tests/e2e/testdata/interactive/manual_tests/` or `tests/e2e/testdata/interactive/statement/`.

---

### Task 0: Branch

```bash
cd $REPO
git switch docs/fanout-communication-design
git switch -c feat/fanout-communication
```

---

### Task 1: Scratch problems for manual testing

Three problems outside the repo, used by every later task. The fanout one only loads once Task 2 lands, and only runs once Task 7 lands -- that is expected.

**Step 1: Interactive baselines (copies of e2e fixtures, no network needed)**

```bash
mkdir -p $SCRATCH
rm -rf $IACT $STUB
cp -R $REPO/tests/e2e/testdata/interactive-trailing-output $IACT
cp -R $REPO/tests/e2e/testdata/grader-stub $STUB
```

**Step 2: The fanout problem.** A relay: each round the judge's value visits processes 0, 1, ..., P-1 in order, and process `i` must answer `value + i + 1` -- so a solution must read its index from `argv[1]`, and the processes are used one after another (process i blocked while the others work), the run-twice shape.

Create `$FANOUT/problem.rbx.yml`:

```yaml
name: fanout-scratch
type: communication
timeLimit: 1000
memoryLimit: 256
interactor:
  path: interactor.cpp
  processes: 3
validator:
  path: validator.cpp
generators:
  - name: gen
    path: gens/gen.cpp
testcases:
  - name: samples
    testcaseGlob: manual/*.in
  - name: main
    generators:
      - name: gen
        args: 10 1
      - name: gen
        args: 1000 2
      - name: gen
        args: 5000 3
solutions:
  - path: sols/main.cpp
    outcome: ACCEPTED
  - path: sols/chatty.cpp
    outcome: ACCEPTED
  - path: sols/wa-ignores-index.cpp
    outcome: WRONG_ANSWER
  - path: sols/wa-shared-state.cpp
    outcome: WRONG_ANSWER
  - path: sols/re-after-accept.cpp
    outcome: RUNTIME_ERROR
  - path: sols/re-process-1.cpp
    outcome: RUNTIME_ERROR
  - path: sols/tle-sum.cpp
    outcome: TIME_LIMIT_EXCEEDED
```

`$FANOUT/interactor.cpp`:

```cpp
#include "testlib.h"
#include "rbx.h"

// Each round the value visits processes 0..P-1 in order; process i must
// answer value + i + 1 (it learns i from argv[1]).
int main(int argc, char *argv[]) {
  rbx::registerFanoutInteraction(argc, argv);
  int p = rbx::fanout::count();
  int k = inf.readInt();
  for (int round = 0; round < k; round++) {
    long long v = inf.readLong();
    for (int i = 0; i < p; i++) {
      rbx::fanout::to(i) << v << std::endl;
      long long got = rbx::fanout::from(i).readLong();
      if (got != v + i + 1) {
        quitf(_wa, "round %d: process %d answered %lld to %lld, expected %lld",
              round, i, got, v, v + i + 1);
      }
      v = got;
    }
  }
  // Every process waits for its next value: -1 tells it to stop.
  for (int i = 0; i < p; i++) rbx::fanout::to(i) << -1 << std::endl;
  tout << "ok" << std::endl;
  quitf(_ok, "%d rounds through %d processes", k, p);
}
```

`$FANOUT/validator.cpp`:

```cpp
#include "testlib.h"

int main(int argc, char *argv[]) {
  registerValidation(argc, argv);
  int k = inf.readInt(1, 200000, "K");
  inf.readEoln();
  for (int i = 0; i < k; i++) {
    inf.readInt(0, 1000000000, "v");
    inf.readEoln();
  }
  inf.readEof();
}
```

`$FANOUT/gens/gen.cpp`:

```cpp
#include "testlib.h"
#include <cstdlib>

int main(int argc, char *argv[]) {
  registerGen(argc, argv, 1);
  int k = std::atoi(argv[1]);
  println(k);
  for (int i = 0; i < k; i++) println(rnd.next(0, 1000000000));
}
```

`$FANOUT/manual/0.in`:

```
2
5
7
```

Solutions (all under `$FANOUT/sols/`):

`main.cpp` -- correct:

```cpp
#include <cstdio>
#include <cstdlib>

int main(int argc, char *argv[]) {
  int index = std::atoi(argv[1]);
  long long v;
  while (std::scanf("%lld", &v) == 1 && v != -1) {
    std::printf("%lld\n", v + index + 1);
    std::fflush(stdout);
  }
  return 0;
}
```

`chatty.cpp` -- correct, but writes ~1 KB of stderr per message (merged stderr volume, `--merge-stderr`):

```cpp
#include <cstdio>
#include <cstdlib>
#include <string>

int main(int argc, char *argv[]) {
  int index = std::atoi(argv[1]);
  std::string noise(1000, 'x');
  long long v;
  while (std::scanf("%lld", &v) == 1 && v != -1) {
    std::fprintf(stderr, "process %d got %lld %s\n", index, v, noise.c_str());
    std::printf("%lld\n", v + index + 1);
    std::fflush(stdout);
  }
  return 0;
}
```

`wa-ignores-index.cpp` -- answers `v + 1` everywhere (process 0 right, process 1 wrong):

```cpp
#include <cstdio>

int main() {
  long long v;
  while (std::scanf("%lld", &v) == 1 && v != -1) {
    std::printf("%lld\n", v + 1);
    std::fflush(stdout);
  }
  return 0;
}
```

`wa-shared-state.cpp` -- the cheater: assumes one process plays every role in turn and counts calls in a global. Correct if all roles shared one memory; wrong under real isolation:

```cpp
#include <cstdio>

static int calls = 0;

int main() {
  long long v;
  while (std::scanf("%lld", &v) == 1 && v != -1) {
    int role = calls++ % 3;
    std::printf("%lld\n", v + role + 1);
    std::fflush(stdout);
  }
  return 0;
}
```

`re-after-accept.cpp` -- answers correctly, then exits non-zero once told to stop (the interactor has already accepted):

```cpp
#include <cstdio>
#include <cstdlib>

int main(int argc, char *argv[]) {
  int index = std::atoi(argv[1]);
  long long v;
  while (std::scanf("%lld", &v) == 1 && v != -1) {
    std::printf("%lld\n", v + index + 1);
    std::fflush(stdout);
  }
  return 1;
}
```

`re-process-1.cpp` -- process 1 crashes on its first message:

```cpp
#include <cstdio>
#include <cstdlib>

int main(int argc, char *argv[]) {
  int index = std::atoi(argv[1]);
  long long v;
  while (std::scanf("%lld", &v) == 1 && v != -1) {
    if (index == 1) std::abort();
    std::printf("%lld\n", v + index + 1);
    std::fflush(stdout);
  }
  return 0;
}
```

`tle-sum.cpp` -- each process burns ~400 ms of CPU once: each stays under the 1 s limit, the three together don't:

```cpp
#include <cstdio>
#include <cstdlib>
#include <ctime>

int main(int argc, char *argv[]) {
  int index = std::atoi(argv[1]);
  bool burnt = false;
  long long v;
  while (std::scanf("%lld", &v) == 1 && v != -1) {
    if (!burnt) {
      burnt = true;
      volatile unsigned long long sink = 0;
      std::clock_t start = std::clock();
      while (std::clock() - start < CLOCKS_PER_SEC * 4 / 10) sink += 1;
    }
    std::printf("%lld\n", v + index + 1);
    std::fflush(stdout);
  }
  return 0;
}
```

**Step 3: Baseline the interactive problems (before any code change)**

Record what interactive problems look like today, to diff against after every refactor:

```bash
for P in $IACT $STUB; do
  (cd $P && RBX_DOCKER=0 $RBX -cp run > $P.baseline-run.txt 2>&1;
   find .rbx/runs -name '*.pio' | sort | head -3 > $P.baseline-pio-list.txt;
   for f in $(cat $P.baseline-pio-list.txt); do echo "== $f"; head -20 $f; done >> $P.baseline-pio-list.txt)
done
```

Expected: both runs pass their declared verdicts. Keep these files; later tasks compare against them (verdicts must match; `.pio` must keep the untagged `<`/`>` format).

**Step 4: Commit** -- nothing to commit (scratch lives outside the repo).

---

### Task 2: Schema -- `Interactor.processes` and the predicates

**Files:**
- Modify: `rbx/box/schema.py:538-551` (`Interactor`), `rbx/box/schema.py:~1863` (Package properties, next to `expanded_vars`)

**Step 1: Implement.** In `Interactor`, after `capture`:

```python
    processes: Optional[int] = Field(
        default=None,
        ge=2,
        description="""
How many copies of the solution run at once against this interactor, as in CMS
`Communication` with `num_processes`. Each copy gets its 0-based index as its
first command-line argument, and the interactor talks to them through
`rbx::registerFanoutInteraction`. Unset means a single process.
""",
    )
```

In `Package`, next to `expanded_vars`:

```python
    @property
    def is_communication(self) -> bool:
        """Whether an interactor judges this problem, with one process or several.

        Ask this when the code needs *an interactor* (compile it, pass it along,
        take the answer from its output); ask `is_interactive` / `is_fanout`
        when it depends on how many processes it talks to.
        """
        return self.type == TaskType.COMMUNICATION

    @property
    def fanout_processes(self) -> Optional[int]:
        """How many contestant processes the interactor talks to, when more than one."""
        if not self.is_communication or self.interactor is None:
            return None
        return self.interactor.processes

    @property
    def is_fanout(self) -> bool:
        """A communication problem whose interactor talks to several processes."""
        return self.fanout_processes is not None

    @property
    def is_interactive(self) -> bool:
        """A communication problem with a single contestant process."""
        return self.is_communication and not self.is_fanout
```

No extra validator is needed: an interactor is already refused on batch problems (`check_checker_and_interactor_for_task_type`), and `ge=2` refuses `processes: 1`.

**Step 2: Verify by hand**

```bash
cd $FANOUT && $RBX summary            # loads now; processes: 3 accepted
sed -i '' 's/processes: 3/processes: 1/' problem.rbx.yml && $RBX summary   # expect a validation error naming interactor.processes (>= 2)
sed -i '' 's/processes: 1/processes: 3/' problem.rbx.yml
cd $REPO && uv run python -c "
from rbx.box.schema import Package
p = Package.model_validate({'name':'x','timeLimit':1000,'memoryLimit':256,'type':'communication','interactor':{'path':'i.cpp','processes':4}})
print(p.is_communication, p.is_interactive, p.is_fanout, p.fanout_processes)
q = Package.model_validate({'name':'x','timeLimit':1000,'memoryLimit':256,'type':'communication','interactor':{'path':'i.cpp'}})
print(q.is_communication, q.is_interactive, q.is_fanout, q.fanout_processes)"
```

Expected: `True False True 4` then `True True False None`.

**Step 3: Regression gate** (only `tests/rbx/box/test_schema.py` and the gate list are relevant; run the gate).

**Step 4: Commit** -- `feat(schema): add interactor.processes for fanout communication problems`

---

### Task 3: Classify every communication site; refuse fanout where it cannot work

Behaviour-preserving for batch and interactive problems. Fanout problems get refused everywhere they cannot run yet (packagers, remote runners) -- and, until Task 7, the local runner.

**Files:**
- Modify: the sites below; `rbx/box/packaging/packager.py:72-100,315-331`; `rbx/box/runners/base.py:56-88`; `rbx/box/runners/local.py:16`; `rbx/box/solutions.py:996-1001`

**Step 1: Site classification.** Replace each `pkg.type == TaskType.COMMUNICATION` with the predicate below (and `!=` with `not`). "Unchanged" sites keep the type comparison, for the reason given.

| Site | Predicate | Why |
| --- | --- | --- |
| `rbx/box/package.py:377` `get_default_checker` | `is_communication` | fanout also judges with the interactor; no-op checker |
| `rbx/box/package.py:415` `get_interactor_or_nil` | `is_communication` | needs an interactor |
| `rbx/box/visualizers.py:164` `_compile_interactor` | `is_communication` | `output_from` must run against the interactor (else batch-style garbage) |
| `rbx/box/summary.py:197` `is_interactive` flag | `is_communication` | the "I" flag means "has an interactor"; Task 11 adds the process count |
| `rbx/box/generators.py:716` output generation | `is_communication` | answers come from the interactor's output |
| `rbx/box/solutions.py:855` `_compile_checking_digests` | `is_communication` | |
| `rbx/box/solutions.py:996` capability check | `is_communication` | + new fanout check, Step 3 |
| `rbx/box/solutions.py:1306` irun output generation | `is_communication` | |
| `rbx/box/solutions.py:1363` `_run_interactive_solutions` | `is_communication` | |
| `rbx/box/solutions.py:1597`, `:1606` irun printing | `is_communication` | prints the interaction; `.pout` fallback is simply absent for fanout |
| `rbx/box/stresses.py:652` | `is_communication` | |
| `rbx/box/packaging/packager.py:276` `_sources_awarding_points` | `is_communication` | a fanout interactor may award points too |
| `rbx/box/ui/screens/test_explorer.py:95`, `:140` | `is_interactive` | the interaction pane parses two-party captures; fanout falls back to `.out`/`.sol.err` until #1044 |
| `rbx/box/ui/screens/run_test_explorer.py:137`, `:228` | `is_interactive` | same |
| `rbx/box/testcase_utils.py:311` | unchanged | takes a `TaskType` argument; the "no interaction" warning is right for fanout too |
| `rbx/box/graders.py:263`, `:283`; `rbx/box/generators.py:757`, `:830` | unchanged | `BATCH`-only grader logic |
| `rbx/box/tasks.py:152` dispatch on `interactor_digest is not None` | unchanged | means "has an interactor" -- the communication path, which Task 7 generalizes to N |
| packagers: `boca/packager.py:69,164,331,363,425`, `domjudge/packager.py:193,265`, `polygon/packager.py:198`, `polygon/upload.py:155,912,989`, `cms/communication.py:39`, `pkg/packager.py:22`, `moj/packager.py:656,1806` | unchanged | unreachable for fanout: refused before the build (Step 2) |
| `packaging/polygon/importer.py:180`, `testset_manifest.py:84`, `schema.py` validators | unchanged | assignments/defaults/the type itself |

Sites that get the package object differently (`package.find_problem_package_or_die()` inline) keep doing so; only the comparison changes.

**Step 2: Packager gate (before the build, like the grader gate).** In `BasePackager` (`packager.py`, next to `supports_graders`):

```python
    @classmethod
    def supports_fanout(cls) -> bool:
        """Whether the judge can run several contestant processes against one
        interactor (`interactor.processes`). None can yet: CMS is #1043."""
        return False
```

In `run_packager`, right after the grader refusal:

```python
    # Also before the build: no judge runs several processes against one interactor yet.
    if (
        package.find_problem_package_or_die().is_fanout
        and not packager_cls.supports_fanout()
    ):
        console.console.print(
            f'[error]Packager [item]{packager_cls.name()}[/item] does not support '
            'problems whose interactor talks to several processes '
            '([item]interactor.processes[/item]).[/error]'
        )
        raise typer.Exit(1)
```

(The design's `kinds()` replacement for `task_types()` is not needed: a pre-build `supports_fanout()` hook mirrors `supports_graders()`/`supports_points()`, refuses before the build -- which the post-build `task_types()` check does not -- and leaves every packager and its tests untouched.)

**Step 3: Runner gate.** In `RunnerCapabilities` (`runners/base.py`), after `supports_interactive`:

```python
    # Can run several contestant processes against one interactor
    # (`interactor.processes`). Off unless a backend says so: no remote judge
    # rbx drives has the model.
    supports_fanout: bool = False
```

In `solutions._check_capabilities`, after the interactive check:

```python
    if pkg.is_fanout and not caps.supports_fanout:
        raise RunnerCapabilityError(
            f'Runner `{runner.name}` cannot run several processes against one '
            f'interactor, but this problem sets `interactor.processes`. Run this '
            f'locally.'
        )
```

`LocalRunner` stays at the default (`False`) until Task 7 flips it.

**Step 4: Verify by hand**

```bash
cd $IACT && RBX_DOCKER=0 $RBX -cp run    # verdicts identical to $IACT.baseline-run.txt
cd $STUB && RBX_DOCKER=0 $RBX -cp run    # identical to $STUB.baseline-run.txt
cd $FANOUT && $RBX package pkg           # refused BEFORE any build output: "does not support problems whose interactor talks to several processes"
cd $FANOUT && $RBX package polygon       # same refusal
cd $FANOUT && $RBX run                   # refused: "Runner `local` cannot run several processes ..."
cd $FANOUT && $RBX summary               # still shows the interactive flag
```

Check `ls $FANOUT/build` is empty/absent after the package attempts (refused before the build).

**Step 5: Regression gate**, plus `uv run pytest -q tests/rbx/box/packaging/test_points_support.py tests/rbx/box/test_summary.py tests/rbx/box/runners`.

**Step 6: Commit** -- `refactor(box): ask is_communication / is_interactive instead of comparing task types`

---

### Task 4: `rbx.h` fanout helper

**Files:**
- Create: `rbx/resources/templates/rbx_fanout.h`
- Modify: `rbx/resources/templates/rbx.h:408` (add a sentinel), `rbx/box/header.py:106-118`

**Step 1: The template.** `rbx/resources/templates/rbx_fanout.h`:

```cpp
// Fanout interactors: talk to several copies of the solution at once.
//
// rbx (and CMS) call the interactor as
//   interactor <input> <output> <from_0> <to_0> ... <from_{N-1}> <to_{N-1}>
// where from_i carries what process i writes and to_i what it reads.
#if defined(_TESTLIB_H_) && !defined(RBX_PUBLIC) && !defined(_WIN32)
#include <cerrno>
#include <csignal>
#include <fcntl.h>
#include <memory>
#include <ostream>
#include <streambuf>
#include <string>
#include <unistd.h>
#include <vector>

namespace rbx {
namespace fanout {
namespace detail {

// A std::streambuf over a file descriptor, flushed on std::endl / flush.
class FdBuf : public std::streambuf {
public:
  explicit FdBuf(int fd) : fd_(fd) { setp(buf_, buf_ + sizeof buf_); }
  ~FdBuf() override { closeFd(); }

  void closeFd() {
    flushBuffer();
    if (fd_ >= 0) {
      ::close(fd_);
      fd_ = -1;
    }
  }

protected:
  int overflow(int ch) override {
    if (flushBuffer() < 0) return traits_type::eof();
    if (ch != traits_type::eof()) {
      *pptr() = static_cast<char>(ch);
      pbump(1);
    }
    return traits_type::not_eof(ch);
  }

  int sync() override { return flushBuffer() < 0 ? -1 : 0; }

private:
  int flushBuffer() {
    const char *p = pbase();
    int status = 0;
    while (fd_ >= 0 && p < pptr()) {
      ssize_t k = ::write(fd_, p, pptr() - p);
      if (k < 0) {
        if (errno == EINTR) continue;
        // The process is gone. SIGPIPE is ignored, so this is how it shows;
        // its missing answer is what the interactor reports.
        status = -1;
        break;
      }
      p += k;
    }
    setp(buf_, buf_ + sizeof buf_);
    return status;
  }

  int fd_;
  char buf_[1 << 16];
};

struct Channel {
  std::unique_ptr<InStream> from;
  std::unique_ptr<FdBuf> buf;
  std::unique_ptr<std::ostream> to;
};

inline std::vector<Channel> &channels() {
  static std::vector<Channel> value;
  return value;
}

inline int openChannel(const char *path, int flags) {
  int fd;
  do {
    fd = ::open(path, flags);
  } while (fd < 0 && errno == EINTR);
  if (fd < 0) quitf(_fail, "rbx: cannot open fanout channel %s", path);
  return fd;
}

inline Channel &channel(int i) {
  int n = static_cast<int>(channels().size());
  if (i < 0 || i >= n) quitf(_fail, "rbx: no process %d (there are %d)", i, n);
  return channels()[i];
}

} // namespace detail

// How many processes the interactor talks to.
inline int count() { return static_cast<int>(detail::channels().size()); }

// What process i writes, read like `ouf`: malformed output is a wrong answer.
inline InStream &from(int i) { return *detail::channel(i).from; }

// What process i reads. Flush (std::endl) after each message.
inline std::ostream &to(int i) { return *detail::channel(i).to; }

// Closes every channel, so processes still reading see end of file.
inline void close_all() {
  for (auto &c : detail::channels()) {
    if (c.to) c.to->flush();
    if (c.buf) c.buf->closeFd();
    if (c.from) c.from->close();
  }
}

} // namespace fanout

// registerInteraction for an interactor that talks to several processes.
inline void registerFanoutInteraction(int argc, char *argv[]) {
  // `inf` and `tout` exactly as registerInteraction sets them up.
  registerInteraction(3, argv);
  {{CONSUME_GRADER_HEADER}}
  // A process that exits early must not take the interactor down with it.
  std::signal(SIGPIPE, SIG_IGN);
  if (argc < 7 || (argc - 3) % 2 != 0) {
    quitf(_fail,
          "rbx: expected <input> <output> and a <from> <to> pair per process "
          "(at least two), got %d arguments",
          argc - 1);
  }
  int n = (argc - 3) / 2;
  auto &channels = fanout::detail::channels();
  channels.resize(n);
  for (int i = 0; i < n; i++) {
    const char *fromPath = argv[3 + 2 * i];
    const char *toPath = argv[4 + 2 * i];
    // A CMS sandbox opens a process's stdin before its stdout, so the channel
    // to it must be opened first, or both sides block forever.
    int toFd = fanout::detail::openChannel(toPath, O_WRONLY);
    int fromFd = fanout::detail::openChannel(fromPath, O_RDONLY);
    std::FILE *fromFile = fdopen(fromFd, "rb");
    if (fromFile == nullptr) quitf(_fail, "rbx: cannot read fanout channel %s", fromPath);

    auto &c = channels[i];
    c.buf.reset(new fanout::detail::FdBuf(toFd));
    c.to.reset(new std::ostream(c.buf.get()));
    c.from.reset(new InStream());
    c.from->name = "process " + std::to_string(i);
    c.from->mode = _output;
    // testlib reads only stdin unbuffered; its buffered reader waits for about
    // 1 MB and would block on a pipe. Marking the stream standard picks the
    // unbuffered one.
    c.from->stdfile = true;
    c.from->reset(fromFile);
  }
}

} // namespace rbx
#endif
```

**Step 2: Emit it for fanout problems only.** In `rbx/resources/templates/rbx.h`, add a sentinel line right after `//<rbx::grader>` (it must follow the grader block, whose header consumption it calls):

```
//<rbx::grader>
//<rbx::fanout>
#endif
```

In `rbx/box/header.py`, add (near `_replace_sentinel`):

```python
def _fanout_block() -> str:
    """What replaces rbx.h's `//<rbx::fanout>` sentinel: the fanout interactor
    helpers for a fanout problem, nothing otherwise -- so every other problem's
    rbx.h stays byte-identical."""
    pkg = package.find_problem_package_or_die()
    if not pkg.is_fanout:
        return ''
    with importlib.resources.as_file(
        importlib.resources.files('rbx') / 'resources' / 'templates' / 'rbx_fanout.h'
    ) as file:
        template = file.read_text()
    consume = (
        'grader::detail::consumeInputHeader();' if pkg.grader is not None else ''
    )
    return template.replace('{{CONSUME_GRADER_HEADER}}', consume)
```

and in `preprocess_header`, after the grader replacement:

```python
    header = _replace_sentinel(header, 'fanout', _fanout_block())
```

**Step 3: Verify the header is byte-identical elsewhere**

```bash
cd $IACT && cp rbx.h /tmp/never-mind 2>/dev/null; $RBX header && md5 rbx.h
cd $REPO && git stash && (cd $IACT && $RBX header && md5 rbx.h) ; git stash pop
```

Expected: same md5 before and after the change (do the same in `$STUB`).

**Step 4: Verify the helper standalone, exactly as CMS would drive it (fifos, CMS open order)**

```bash
cd $FANOUT && $RBX header && grep -c registerFanoutInteraction rbx.h   # >= 1
TL=$REPO/rbx/resources/predownloaded
g++ -std=gnu++20 -O2 -I. -I$TL interactor.cpp -o /tmp/fan-int
g++ -std=gnu++20 -O2 sols/main.cpp -o /tmp/fan-main
g++ -std=gnu++20 -O2 sols/wa-ignores-index.cpp -o /tmp/fan-wa
run_cms_like() {  # $1 = solution binary, $2 = processes
  D=$(mktemp -d); args=""
  for i in $(seq 0 $(($2-1))); do mkfifo $D/u${i}_to_m $D/m_to_u$i; args="$args $D/u${i}_to_m $D/m_to_u$i"; done
  /tmp/fan-int manual/0.in $D/out $args 2>$D/int.err & IP=$!
  # Like a CMS std_io sandbox: stdin (from the manager) is opened before stdout.
  for i in $(seq 0 $(($2-1))); do $1 $i < $D/m_to_u$i > $D/u${i}_to_m & done
  wait $IP; echo "interactor exit=$?"; cat $D/int.err; cat $D/out; wait
}
run_cms_like /tmp/fan-main 3      # exit=0, "ok 2 rounds through 3 processes", out = ok
run_cms_like /tmp/fan-wa 3        # exit=1, "wrong answer round 0: process 1 answered 6 to 6, expected 7"
run_cms_like /tmp/fan-main 64     # exit=0 with 64 processes, no hang
```

Also check the guard: `g++ ... interactor.cpp` with an `rbx.h` from `$IACT` (no fanout block) fails to compile with "registerFanoutInteraction was not declared" -- confirms the helper only appears for fanout problems.

**Step 5: Regression gate.**

**Step 6: Commit** -- `feat(header): add rbx::registerFanoutInteraction for fanout interactors`

---

### Task 5: Sandbox -- one primitive for one process or N

`run_communication` becomes the N = 1 case of a new `run_fanout`. Do it in two passes: first the generalized implementation with N = 1 only (regression gate must be green, interactive verified by hand), then N > 1.

**Files:**
- Modify: `rbx/grading/judge/sandbox.py:229-237` (`CommunicationParams`), `:646-655` (abstract methods)
- Modify: `rbx/grading/judge/program.py:86-96` (`ProgramParams`), `:437-452` (`Popen`)
- Modify: `rbx/grading/judge/sandboxes/stupid_sandbox.py:349-526` (replace `run_communication`)
- Modify: `rbx/grading/judge/sandboxes/docker_sandbox.py:101-120`, `rbx/grading/judge/sandboxes/docker_agent.py:440-450,738-760`

**Step 1: Params.** `CommunicationParams` gains:

```python
    # How many contestant processes run against the interactor. One is an
    # interactive problem; more is fanout (`interactor.processes`).
    processes: int = pydantic.Field(default=1, ge=1)
```

`ProgramParams` gains `pass_fds: Tuple[int, ...] = ()` (import `Tuple`), and `Program._run` passes `pass_fds=self.params.pass_fds` to `subprocess.Popen`.

**Step 2: The abstract API** (`sandbox.py`). Replace the abstract `run_communication` with an abstract `run_fanout` plus a concrete wrapper:

```python
    def run_communication(
        self,
        command: List[str],
        params: SandboxParams,
        interactor_command: List[str],
        interactor_params: SandboxParams,
        communication_params: Optional[CommunicationParams] = None,
    ) -> Tuple[SandboxLog, SandboxLog]:
        """One contestant process against the interactor: `run_fanout` with N = 1."""
        communication_params = (
            communication_params or CommunicationParams()
        ).model_copy(update={'processes': 1})
        logs, interactor_log = self.run_fanout(
            command, params, interactor_command, interactor_params, communication_params
        )
        return logs[0], interactor_log

    @abc.abstractmethod
    def run_fanout(
        self,
        command: List[str],
        params: SandboxParams,
        interactor_command: List[str],
        interactor_params: SandboxParams,
        communication_params: Optional[CommunicationParams] = None,
    ) -> Tuple[List[SandboxLog], SandboxLog]:
        """Run `communication_params.processes` copies of `command` against one
        interactor, all at once. With more than one, copy i gets `i` as its
        last argument and the interactor gets a `<from_i> <to_i>` pair of
        paths per copy; with one, the interactor talks over its stdin/stdout."""
        pass
```

**Step 3: `StupidSandbox.run_fanout`.** Module level in `stupid_sandbox.py` (add `import dataclasses`, `import fcntl`):

```python
def _make_pipe() -> Tuple[typing.IO[bytes], typing.IO[bytes]]:
    """A pipe as two unbuffered file objects (read end, write end).

    File objects, never bare fds: a `Program` closes what it was given more than
    once, and a second `os.close` could hit an unrelated fd that reused the
    number. Sized like the pipes `subprocess` makes for us (Linux only).
    """
    read_fd, write_fd = os.pipe()
    if BUFFER_SIZE_BYTES > 0 and hasattr(fcntl, 'F_SETPIPE_SZ'):
        try:
            fcntl.fcntl(write_fd, fcntl.F_SETPIPE_SZ, BUFFER_SIZE_BYTES)
        except OSError:
            pass
    return open(read_fd, 'rb', buffering=0), open(write_fd, 'wb', buffering=0)


@dataclasses.dataclass
class _Channel:
    """The pipes between the interactor and one contestant process.

    One pipe each way, or, with a capture tee, two each way with the tee in the
    middle. Every end is ours until handed to the program that owns it.
    """

    interactor_reads: typing.IO[bytes]
    interactor_writes: typing.IO[bytes]
    process_reads: typing.IO[bytes]
    process_writes: typing.IO[bytes]
    # (reads, writes) of the tee on each direction, when teeing.
    tee_to_process: Optional[Tuple[typing.IO[bytes], typing.IO[bytes]]] = None
    tee_to_interactor: Optional[Tuple[typing.IO[bytes], typing.IO[bytes]]] = None

    @staticmethod
    def open(teed: bool) -> '_Channel':
        if not teed:
            to_r, to_w = _make_pipe()
            from_r, from_w = _make_pipe()
            return _Channel(from_r, to_w, to_r, from_w)
        i2t_r, i2t_w = _make_pipe()
        t2p_r, t2p_w = _make_pipe()
        p2t_r, p2t_w = _make_pipe()
        t2i_r, t2i_w = _make_pipe()
        return _Channel(
            interactor_reads=t2i_r,
            interactor_writes=i2t_w,
            process_reads=t2p_r,
            process_writes=p2t_w,
            tee_to_process=(i2t_r, t2p_w),
            tee_to_interactor=(p2t_r, t2i_w),
        )
```

Replace `StupidSandbox.run_communication` with:

```python
    def run_fanout(
        self,
        command: List[str],
        params: SandboxParams,
        interactor_command: List[str],
        interactor_params: SandboxParams,
        communication_params: Optional[CommunicationParams] = None,
    ) -> Tuple[List[SandboxLog], SandboxLog]:
        communication_params = communication_params or CommunicationParams()
        n = communication_params.processes
        fanout = n > 1
        self.exec_num += 1

        logger.debug(
            "Executing program in sandbox with command: `%s'.", ' '.join(command)
        )
        with open(
            self.relative_path(self.cmd_file), 'at', encoding='utf-8'
        ) as commands:
            commands.write('%s\n' % command)

        merged_capture = communication_params.merged_capture
        should_tee = self._needs_teeing(params, interactor_params, merged_capture)
        # Tee the solutions' stderr into the merged capture (marked '!') only
        # when we already have a merged file to append to.
        should_tee_stderr = (
            should_tee
            and communication_params.tee_stderr
            and merged_capture is not None
        )
        if should_tee and merged_capture:
            self.create_file_from_string(merged_capture, '<\n>\n', override=True)

        def marker(i: int, direction: str) -> str:
            return f'[{i}]{direction}' if fanout else direction

        def stderr_path(i: int) -> Optional[pathlib.Path]:
            # Several processes write to scratch files, merged once all are done.
            if params.stderr_file is None or not fanout:
                return params.stderr_file
            return params.stderr_file.with_name(f'{params.stderr_file.name}.{i}')

        channels = [_Channel.open(should_tee) for _ in range(n)]

        # The interactor first: everything else joins its process group.
        interactor_program_params = self._get_program_params(interactor_params)
        interactor_io = self._get_io(interactor_params, pipe_io=True)
        if fanout:
            interactor_io.input = subprocess.DEVNULL
            interactor_io.output = subprocess.DEVNULL
            fds: List[int] = []
            for channel in channels:
                fds += [channel.interactor_reads.fileno(), channel.interactor_writes.fileno()]
            interactor_command = interactor_command + [f'/dev/fd/{fd}' for fd in fds]
            interactor_program_params.pass_fds = tuple(fds)
        else:
            interactor_io.input = channels[0].interactor_reads
            interactor_io.output = channels[0].interactor_writes
        interactor_program_params.io = interactor_io
        interactor = Program(interactor_command, interactor_program_params)
        group_id = os.getpgid(interactor.pid)
        for channel in channels:
            channel.interactor_reads.close()
            channel.interactor_writes.close()

        tees: List[Program] = []
        if should_tee:
            for i, channel in enumerate(channels):
                assert channel.tee_to_process is not None
                assert channel.tee_to_interactor is not None
                tees.append(
                    self._get_tee_program(
                        marker(i, '<'),
                        stdin=channel.tee_to_process[0],
                        stdout=channel.tee_to_process[1],
                        capture=None if fanout else self._get_pathlike_stdout(self._get_io(interactor_params)),
                        pgid=group_id,
                        communication_params=communication_params,
                    )
                )
                tees.append(
                    self._get_tee_program(
                        marker(i, '>'),
                        stdin=channel.tee_to_interactor[0],
                        stdout=channel.tee_to_interactor[1],
                        capture=None if fanout else self._get_pathlike_stdout(self._get_io(params)),
                        pgid=group_id,
                        communication_params=communication_params,
                    )
                )
                for end in (*channel.tee_to_process, *channel.tee_to_interactor):
                    end.close()

        programs: List[Program] = []
        for i, channel in enumerate(channels):
            program_params = self._get_program_params(params)
            program_params.io = self._get_io(params, pipe_io=True)
            # The process gets its own copy of the read end it consumes. Ours
            # stays open, so the interactor -- or its capture tee -- never writes
            # into a pipe nobody holds: a process may answer and exit without
            # reading everything the interactor still has to say, and once it is
            # gone we drain the rest (as BAPCtools' relay and problemtools do)
            # instead of letting the interactor die of SIGPIPE, or block forever
            # on a full pipe.
            program_params.io.input = open(
                os.dup(channel.process_reads.fileno()), 'rb', buffering=0
            )
            program_params.io.output = channel.process_writes
            path = stderr_path(i)
            stderr_writer: Optional[typing.IO[bytes]] = None
            if should_tee_stderr:
                # The tee writes the clean copy to the process's stderr file and
                # the marked copy to the merged capture.
                stderr_reader, stderr_writer = _make_pipe()
                tees.append(
                    self._get_tee_program(
                        marker(i, '!'),
                        stdin=stderr_reader,
                        stdout=subprocess.DEVNULL,
                        capture=path,
                        pgid=group_id,
                        communication_params=communication_params,
                    )
                )
                stderr_reader.close()
                program_params.io.stderr = stderr_writer
            elif path is not None:
                program_params.io.stderr = self.relative_path(path)
            program_params.pgid = group_id
            programs.append(
                Program(command + [str(i)] if fanout else command, program_params)
            )
            channel.process_writes.close()
            if stderr_writer is not None:
                stderr_writer.close()

        results: List[Optional[SandboxLog]] = [None] * n
        interactor_result: Optional[SandboxLog] = None
        drainers: List[threading.Thread] = []
        pids = {program.pid: i for i, program in enumerate(programs)}
        tee_pids = {tee.pid for tee in tees}

        for idx in range(1 + n + len(tees)):
            pid, status, ru = os.wait4(-group_id, 0)
            if pid == interactor.pid:
                program_result = interactor.process_exit(status, ru)
                interactor_result = self._get_sandbox_log(program_result, interactor_params)
                interactor_result.exit_index = idx
                # Kill the processes still running if the interactor failed,
                # whatever was reaped before: a capture tee may exit (and be
                # reaped) ahead of the interactor it reads from.
                if any(r is None for r in results) and program_result.exitcode != 0:
                    try:
                        os.killpg(group_id, signal.SIGKILL)
                    except Exception:
                        pass
            elif pid in pids:
                i = pids[pid]
                program_result = programs[i].process_exit(status, ru)
                results[i] = self._get_sandbox_log(program_result, params)
                results[i].exit_index = idx
                if interactor_result is None:
                    drainer = threading.Thread(
                        target=_drain, args=(channels[i].process_reads,), daemon=True
                    )
                    drainer.start()
                    drainers.append(drainer)
                else:
                    channels[i].process_reads.close()
            elif pid in tee_pids:
                pass
            else:
                raise RuntimeError(f'Unknown pid: {pid}')

        # Every writer has been reaped by now, so the drainers are at EOF --
        # unless something the interactor spawned still holds a write end.
        for drainer in drainers:
            drainer.join(DRAIN_GRACE_SECONDS)
            if drainer.is_alive():
                try:
                    os.killpg(group_id, signal.SIGKILL)
                except Exception:
                    pass
                drainer.join()
        for channel in channels:
            channel.process_reads.close()
        for program in (interactor, *programs, *tees):
            program.close()

        if fanout and params.stderr_file is not None:
            self._merge_process_stderr(params.stderr_file, [stderr_path(i) for i in range(n)])

        assert interactor_result is not None
        return typing.cast(List[SandboxLog], results), interactor_result

    def _merge_process_stderr(
        self, into: pathlib.Path, parts: List[Optional[pathlib.Path]]
    ) -> None:
        """Fold each process's stderr into one file, grouped by process, every
        line tagged `[i] ` like the merged capture's `[i]` markers."""
        with self.relative_path(into).open('wb') as merged:
            for i, part in enumerate(parts):
                if part is None or not self.relative_path(part).is_file():
                    continue
                data = self.relative_path(part).read_bytes()
                for line in data.splitlines(keepends=True):
                    merged.write(b'[%d] ' % i + line)
                if data and not data.endswith(b'\n'):
                    merged.write(b'\n')
                self.relative_path(part).unlink()
```

Notes for the implementer:
- `_get_tee_program`'s `capture` is a `pathlib.Path | None`; passing `None` already writes the clean copy to `/dev/null` (`_get_tee_command`).
- The marker is already a free string for both tee scripts (`sys.argv[1]`), so `[3]<` needs no change to `chunk_tee.py` / `line_tee.py`. `chunk_tee.py` writes only complete marked lines to the merged capture, so even chunk mode never splits a line across tees.
- `_get_tee_program` opens the merged capture for append itself (`io.stderr`); 2N tees appending concurrently is the same situation as today's two.
- Kept from today on purpose: the drainer per process, killing the group when the interactor fails, `DRAIN_GRACE_SECONDS`.

**Step 4: Docker.** `DockerSandbox` overrides `run_fanout` instead of `run_communication` (the base wrapper then serves `run_communication` for free):

```python
    def run_fanout(
        self,
        command: List[str],
        params: SandboxParams,
        interactor_command: List[str],
        interactor_params: SandboxParams,
        communication_params: Optional[CommunicationParams] = None,
    ) -> Tuple[List[SandboxLog], SandboxLog]:
        return (
            self._backend()
            .client()
            .run_fanout(
                self.get_root_path(),
                command,
                params,
                interactor_command,
                interactor_params,
                communication_params or CommunicationParams(),
            )
        )
```

Agent client (`docker_agent.py:738`): rename `run_communication` to `run_fanout`, send `'op': 'run_fanout'`, and return `([SandboxLog.model_validate(s) for s in solutions], SandboxLog.model_validate(interactor))` from `solutions, interactor = self.request({...})`. Agent server (`_run_request`, `:440`): replace the `run_communication` op with

```python
    if op == 'run_fanout':
        solution_logs, interactor_log = sandbox.run_fanout(
            request['command'],
            params,
            request['interactor_command'],
            SandboxParams.model_validate(request['interactor_params']),
            CommunicationParams.model_validate(request['communication_params']),
        )
        return [
            [log.model_dump(mode='json') for log in solution_logs],
            interactor_log.model_dump(mode='json'),
        ]
```

(The old op can go: the agent always runs from the same rbx sources as the client -- an edit under `rbx/` rebuilds the image.)

**Step 5: Verify N = 1 by hand (interactive is unchanged)**

```bash
cd $IACT && RBX_DOCKER=0 $RBX -cp run && $RBX -cp run          # native and Docker
cd $STUB && RBX_DOCKER=0 $RBX -cp run && $RBX -cp run
cd $STUB && RBX_DOCKER=0 $RBX -cp irun --testcase samples/0 -p --merge-stderr
```

Compare with Task 1's baselines: same verdicts; `.pio` still starts with `<`/`>` header lines and untagged `<`/`>`/`!` lines; `.pin`/`.pout` still written with `-cp`. Run `RBX_DOCKER=0 $RBX -cp run` in `$IACT` ten times in a row (`for i in $(seq 10); do ...; done`) -- no flake, no hang (watch for a run stuck at a test: that is a leaked pipe end).

**Step 6: Verify N > 1 directly against the sandbox** (rbx can't run fanout end to end until Task 7). Save as `$SCRATCH/sandbox_fanout.py` and run with `cd $REPO && uv run python $SCRATCH/sandbox_fanout.py`:

```python
import pathlib, sys, tempfile
from rbx.grading.judge.cacher import FileCacher
from rbx.grading.judge.sandbox import CommunicationParams, SandboxParams
from rbx.grading.judge.sandboxes.stupid_sandbox import StupidSandbox
from rbx.grading.judge.storage import FilesystemStorage

INTERACTOR = '''
import sys
paths = sys.argv[3:]
n = len(paths) // 2
# CMS order: to_i (write) before from_i (read).
chans = []
for i in range(n):
    to = open(paths[2 * i + 1], 'w')
    frm = open(paths[2 * i], 'r')
    chans.append((frm, to))
for i, (frm, to) in enumerate(chans):
    to.write(f'{i * 10}\\n'); to.flush()
    got = int(frm.readline())
    sys.stderr.write(f'process {i} -> {got}\\n')
    if got != i * 10 + i + 1: sys.exit(1)
for frm, to in chans:
    to.write('-1\\n'); to.flush()
open(sys.argv[2], 'w').write('ok\\n')
'''
SOLUTION = '''
import sys
i = int(sys.argv[1])
for line in sys.stdin:
    v = int(line)
    if v == -1: break
    sys.stderr.write(f'i am {i}\\n')
    print(v + i + 1, flush=True)
'''

n = int(sys.argv[1]) if len(sys.argv) > 1 else 3
merged = len(sys.argv) > 2 and sys.argv[2] == 'merged'
with tempfile.TemporaryDirectory() as d:
    sandbox = StupidSandbox(file_cacher=FileCacher(FilesystemStorage(pathlib.Path(d))))
    sandbox.create_file_from_string(pathlib.Path('i.py'), INTERACTOR)
    sandbox.create_file_from_string(pathlib.Path('s.py'), SOLUTION)
    logs, ilog = sandbox.run_fanout(
        [sys.executable, 's.py'],
        SandboxParams(timeout=5000, wallclock_timeout=10000, stderr_file=pathlib.Path('sol.err')),
        [sys.executable, 'i.py', 'in.txt', 'out.txt'],
        SandboxParams(timeout=5000, wallclock_timeout=10000, stderr_file=pathlib.Path('int.err')),
        CommunicationParams(processes=n, merged_capture=pathlib.Path('m.pio') if merged else None, tee_stderr=merged, tee_mode='line'),
    )
    print('interactor', ilog.exitstatus, ilog.exitcode, 'exit_index', ilog.exit_index)
    for i, log in enumerate(logs):
        print('process', i, log.exitstatus, log.exitcode, 'exit_index', log.exit_index)
    print(sandbox.relative_path(pathlib.Path('sol.err')).read_text())
    print(sandbox.relative_path(pathlib.Path('int.err')).read_text())
    if merged:
        print(sandbox.relative_path(pathlib.Path('m.pio')).read_text())
    sandbox.cleanup(delete=True)
```

Check `FileCacher`/`FilesystemStorage` constructor signatures against `tests/rbx/grading/conftest.py` (`storage`, `file_cacher` fixtures) and adjust the two constructor lines if they differ. Run:

```bash
uv run python $SCRATCH/sandbox_fanout.py 3           # all 'ok', exit 0; sol.err grouped [0] / [1] / [2], each 'i am k'
uv run python $SCRATCH/sandbox_fanout.py 3 merged    # m.pio: '<','>' header then [0]< 0, [0]!i am 0, [0]> 1, [1]< 10 ... in that order
uv run python $SCRATCH/sandbox_fanout.py 64          # 64 processes, no hang, < a few seconds
uv run python $SCRATCH/sandbox_fanout.py 64 merged
```

**Check of `/dev/fd` reopen semantics (unverified from reading):** on macOS, opening `/dev/fd/K` duplicates the descriptor; on Linux it reopens the pipe through `/proc/self/fd`. Both should work for pipes. The runs above on macOS check the first; check Linux through Docker (default, not `RBX_DOCKER=0`) once Task 7 lands. If `open('/dev/fd/K', 'w')` fails on either, pass `/proc/self/fd/K` on Linux instead (`sys.platform`).

Also break it on purpose: edit the scratch `SOLUTION` so process 1 `sys.exit(3)` before answering -> interactor fails reading -> group killed, process 1 `nonzero return`, others killed by signal, no hang.

**Step 7: Regression gate**, plus `uv run pytest -q tests/rbx/grading/judge/test_docker_sandbox.py` (skips without Docker; that's fine).

**Step 8: Commit** -- `feat(sandbox): run N solution processes against one interactor`

---

### Task 6: Grading steps and caching for N processes

**Files:**
- Modify: `rbx/grading/steps.py:115-119` (`GradingLogsHolder`), `:1215-1279` (`run_coordinated`), add `combine_process_logs` near `_build_run_log`
- Modify: `rbx/grading/steps_with_caching.py:115-185`
- Modify: `rbx/grading/caching.py:502-516`

**Step 1: Logs holder.** `GradingLogsHolder` gains:

```python
    # Every solution process of a coordinated run, in process order. `run` is
    # the first, kept for the callers and caches that only know one.
    runs: Optional[List['RunLog']] = None
```

Cache restore (`caching.py`, inside the `zip(fingerprint.logs, ...)` loop):

```python
                if logs.runs is not None:
                    reference_logs.runs = [log.model_copy(deep=True) for log in logs.runs]
```

No `CACHE_STEP_VERSION` bump: an entry cached before this change restores with `runs=None`, and the readers below fall back to `[run]` -- which is exactly the one-process run it was. (The design's bump would wipe every setter's cache for nothing.)

**Step 2: `steps.run_fanout_coordinated`** -- rename the body of `run_coordinated` to it, generalized, and make `run_coordinated` the N = 1 wrapper:

```python
async def run_fanout_coordinated(
    interactor: CoordinatedRunParams,
    solution: CoordinatedRunParams,
    artifacts: GradingArtifacts,
    sandbox: SandboxBase,
    processes: int = 1,
    merged_capture: Optional[pathlib.Path] = None,
    line_capture: bool = False,
    tee_stderr: bool = False,
) -> Tuple[Optional[RunLog], List[Optional[RunLog]]]:
    """Run `processes` copies of the solution against the interactor.

    Returns the interactor's log and one log per process, in process order.
    """
    sandbox.reset()

    await _process_input_artifacts(artifacts, sandbox)
    _process_fifos(artifacts, sandbox)

    interactor_cmd = _split_and_expand(interactor.command, sandbox, interactor.params)
    solution_cmd = _split_and_expand(solution.command, sandbox, solution.params)

    interactor_params = interactor.params.model_copy(deep=True)
    solution_params = solution.params.model_copy(deep=True)

    # Solution only, on purpose: the interactor's limits are left exactly as
    # given, so an interactor-only `stackLimit` is neither relaxed for the JVM nor
    # diagnosed. `steps_run_coordinated_test.py` pins that behaviour.
    _finalize_limits(solution.command, solution_params, sandbox)

    solution_logs: List[Optional[RunLog]]
    try:
        solution_sandbox_logs, interactor_sandbox_log = await asyncio.to_thread(
            sandbox.run_fanout,
            solution_cmd,
            solution_params,
            interactor_cmd,
            interactor_params,
            CommunicationParams(
                merged_capture=merged_capture,
                tee_mode='line' if line_capture else 'chunk',
                tee_stderr=tee_stderr,
                processes=processes,
            ),
        )

        if not await _process_output_artifacts(artifacts, sandbox):
            return None, [None] * processes

        solution_logs = [
            _build_run_log(log, sandbox, solution.params, solution.metadata)
            for log in solution_sandbox_logs
        ]
        interactor_log = _build_run_log(
            interactor_sandbox_log, sandbox, interactor.params, interactor.metadata
        )
    except ProgramError as e:
        solution_logs = [
            _build_program_error_run_log(e, solution.metadata, sandbox)
            for _ in range(processes)
        ]
        interactor_log = _build_program_error_run_log(e, interactor.metadata, sandbox)

    if artifacts.logs is not None:
        artifacts.logs.run = solution_logs[0]
        artifacts.logs.runs = solution_logs
        artifacts.logs.interactor_run = interactor_log

    return interactor_log, solution_logs


async def run_coordinated(
    interactor: CoordinatedRunParams,
    solution: CoordinatedRunParams,
    artifacts: GradingArtifacts,
    sandbox: SandboxBase,
    merged_capture: Optional[pathlib.Path] = None,
    line_capture: bool = False,
    tee_stderr: bool = False,
) -> Tuple[Optional[RunLog], Optional[RunLog]]:
    """One solution process against the interactor. Returns (solution, interactor)."""
    interactor_log, solution_logs = await run_fanout_coordinated(
        interactor,
        solution,
        artifacts,
        sandbox,
        merged_capture=merged_capture,
        line_capture=line_capture,
        tee_stderr=tee_stderr,
    )
    return solution_logs[0], interactor_log
```

Check `_build_program_error_run_log` returns a fresh object per call (it builds a new `RunLog`); the comprehension then gives distinct objects.

**Step 3: `combine_process_logs`** (steps.py, after `_build_run_log`; import `typing` if needed):

```python
def combine_process_logs(
    logs: List[Optional[RunLog]],
) -> Tuple[Optional[RunLog], Optional[int]]:
    """Fold the logs of a fanout run's processes into the one log judged.

    One log comes back as is. Otherwise CPU time is summed, as CMS judges it
    against the time limit; wall time and memory are the maxima, since both are
    limited per process; and the exit fields come from the process that decides
    the verdict -- the first to exit having failed, else the last to exit. Its
    index comes back too, when a process failed.
    """
    if len(logs) == 1:
        return logs[0], None
    if any(log is None for log in logs):
        return None, None
    present = typing.cast(List[RunLog], logs)
    errored = [
        i for i, log in enumerate(present)
        if log.exitstatus == SandboxBase.EXIT_SANDBOX_ERROR
    ]
    failed = [i for i, log in enumerate(present) if log.exitstatus != SandboxBase.EXIT_OK]
    if errored:
        decider: Optional[int] = errored[0]
    elif failed:
        decider = min(failed, key=lambda i: present[i].exitindex)
    else:
        decider = None
    base = present[
        decider if decider is not None
        else max(range(len(present)), key=lambda i: present[i].exitindex)
    ]
    combined = base.model_copy(deep=True)
    times = [log.time for log in present]
    combined.time = None if any(t is None for t in times) else sum(times)  # type: ignore[arg-type]
    walls = [log.wall_time for log in present if log.wall_time is not None]
    combined.wall_time = max(walls) if walls else None
    memories = [log.memory for log in present if log.memory is not None]
    combined.memory = max(memories) if memories else None
    combined.warnings = any(log.warnings for log in present)
    return combined, decider
```

Why this is enough for the verdict (Task 7): `check_communication`'s ladder already reads TLE off `run_log.time * 1000 > timelimit` (`_check_pre_output`) and orders the interactor against `run_log.exitindex` / a SIGPIPE'd `run_log`. Fed this combined log, the ladder applies the design's rules unchanged: summed CPU over the limit is TLE, the first failing process decides, and a process failing after the interactor accepted still fails.

**Step 4: `steps_with_caching.run_fanout_coordinated`** -- same split: rename the body to `run_fanout_coordinated(..., processes: int = 1, ...)`, pass `processes` through to `steps.run_fanout_coordinated`, add the param to the cache key only when it is not 1 (one-process keys stay exactly as they were):

```python
    if processes != 1:
        cacheable_params['processes'] = processes
```

and return

```python
    runs = artifacts.logs.runs
    return artifacts.logs.interactor_run, (
        runs if runs is not None else [artifacts.logs.run]
    )
```

Then `run_coordinated` becomes the wrapper returning `(interactor_log, solution_logs[0])` (this module's order).

**Step 5: Verify by hand** -- this layer has no end-to-end entry point until Task 7, so verify through the interactive path (now going through `run_fanout_coordinated` with N = 1) and its cache:

```bash
cd $IACT && rm -rf .rbx && RBX_DOCKER=0 $RBX run   # cold
cd $IACT && RBX_DOCKER=0 $RBX run                  # warm: same verdicts, much faster (cache hits)
cd $STUB && RBX_DOCKER=0 $RBX run && $RBX run      # native, then Docker
```

Also: with an rbx cache populated *before* this task (use `git stash` to run the old code once, then `git stash pop`), the first run after the change must reuse those entries (fast) and give the same verdicts -- that exercises the `runs=None` fallback.

**Step 6: Regression gate.**

**Step 7: Commit** -- `feat(grading): coordinate N solution processes with one interactor`

---

### Task 7: Run fanout problems end to end

**Files:**
- Modify: `rbx/box/code.py:1047-1104` (`run_communication`)
- Modify: `rbx/box/tasks.py:333-466` (`_run_communication_solution_on_testcase`)
- Modify: `rbx/grading/steps.py:325-340` (`TestcaseLog.processes`)
- Modify: `rbx/box/runners/local.py:16`

**Step 1: `code.run_communication`** gains `processes: int = 1` and returns `Tuple[Optional[RunLog], List[Optional[RunLog]]]` (interactor, processes): call `steps_with_caching.run_fanout_coordinated(..., processes=processes, ...)` instead of `run_coordinated`. Its only caller is `tasks.py:414`.

**Step 2: `TestcaseLog`** gains:

```python
    # One log per process of a fanout run, in process order; the fields above
    # are their aggregate (CPU time summed, wall time and memory maxima). `None`
    # -- every other run -- is dropped from the `.eval`.
    processes: Optional[List[RunLog]] = None
```

**Step 3: `tasks._run_communication_solution_on_testcase`.** Inside `run_fn`:

```python
        processes = package.find_problem_package_or_die().fanout_processes or 1
```

- `.pin` / `.pout` capture paths only when `processes == 1` (`interactor_capture_path` / `solution_capture_path` become `None` otherwise).
- The call becomes

```python
        interactor_run_log, run_logs = await run_communication(
            interactor=interactor_item,
            solution=solution_item,
            retry_index=retry_index,
            merged_capture=...,          # unchanged
            line_capture=line_capture or merge_stderr,
            tee_stderr=merge_stderr,
            processes=processes,
        )
        run_log, decider = steps.combine_process_logs(run_logs)
```

  (import `combine_process_logs` from `rbx.grading.steps` alongside the existing imports).
- After `checker_result = await checkers.check_communication(...)` (unchanged call, fed the combined `run_log`):

```python
        checker_result = _name_failing_process(checker_result, decider, processes)
```

  with, at module level:

```python
# Verdicts a contestant process earns by itself, as opposed to the interactor's.
_PROCESS_FAILURES = (
    Outcome.TIME_LIMIT_EXCEEDED,
    Outcome.IDLENESS_LIMIT_EXCEEDED,
    Outcome.MEMORY_LIMIT_EXCEEDED,
    Outcome.RUNTIME_ERROR,
    Outcome.OUTPUT_LIMIT_EXCEEDED,
)


def _name_failing_process(
    result: CheckerResult, decider: Optional[int], processes: int
) -> CheckerResult:
    """Say which process a fanout verdict is about."""
    if processes == 1 or result.outcome not in _PROCESS_FAILURES:
        return result
    if decider is not None:
        who = f'process {decider}'
    elif result.outcome == Outcome.TIME_LIMIT_EXCEEDED:
        # No process failed alone: only their summed CPU time can be over.
        who = 'the processes together'
    else:
        return result
    result.message = f'{who}: {result.message}' if result.message else who
    return result
```

- `TestcaseLog(**run_log.model_dump(), ..., processes=run_logs if processes > 1 else None, ...)`.
- `.sol.log`: one process writes `model_to_yaml(run_log)` as today; several write

```python
class _ProcessLogs(BaseModel):
    processes: List[RunLog]
```

  (module level) via `model_to_yaml(_ProcessLogs(processes=[log for log in run_logs if log is not None]))`.

The interactor's limits are unchanged (`_get_interactor_execution_config`): the processes all start together, so the session ends with the slowest process's wall clock, which the interactor's wall (solution wall + 1 s) already outlives; a single-threaded interactor cannot spend more CPU than wall time. (The design's "N x TL" interactor CPU budget would never bind.)

**Step 4: Turn it on.** `LocalRunner.caps = RunnerCapabilities(supports_fanout=True)`.

**Step 5: Verify by hand -- the full matrix.** For each of `RBX_DOCKER=0` and the default (Docker):

```bash
cd $FANOUT && rm -rf .rbx build && $RBX build
$RBX run
```

Expected `rbx run` verdicts:

| Solution | Verdict | Message mentions |
| --- | --- | --- |
| `sols/main.cpp` | AC everywhere | |
| `sols/chatty.cpp` | AC | |
| `sols/wa-ignores-index.cpp` | WA | `process 1 answered` |
| `sols/wa-shared-state.cpp` | WA | `process 1 answered` |
| `sols/re-after-accept.cpp` | RTE (interactor accepted first) | `process <k>` |
| `sols/re-process-1.cpp` | RTE | `process 1` |
| `sols/tle-sum.cpp` | TLE | `the processes together` |

Then inspect artifacts of one test of each (`.rbx/runs/<idx>/main/001.*`):
- `.eval`: `log.time` ~ the sum of the three `log.processes[*].time`; `log.processes` has 3 entries; for `tle-sum` each `time` < 1.0 and the sum >= 1.0.
- `.sol.err` for `chatty`: every line starts with `[0] `, then `[1] `, then `[2] ` (grouped, in that order).
- `.sol.log`: a `processes:` list of 3 logs.
- no `.pin` / `.pout`.
- Interactive `.eval`s (`$IACT`, `$STUB` runs) still have **no** `processes:` key.

Capture and stderr merging:

```bash
cd $FANOUT && $RBX -cp run -s sols/main.cpp
head -20 .rbx/runs/*/samples/000.pio    # header '<','>' then [0]<5, [0]>6, [1]<6, [1]>8, [2]<8, [2]>11, ...
$RBX -cp irun --testcase samples/0 -p --merge-stderr
```

In the last one the interaction view interleaves `[k]!` stderr lines in order (the tag rendering lands in Task 8; for now just check the file content).

Timing: `$RBX time` -- the estimate for `main.cpp` reflects summed time (compare with `$RBX run -s sols/main.cpp` per-test times, which are sums).

Retries: `$RBX run -s sols/main.cpp --runs 3` (or whatever `nruns` flag `rbx run --help` names) -- verdicts stable.

Process count extremes: set `processes: 2`, then `processes: 64` (with `tle-sum` expected to TLE much harder, and `main.cpp`'s tests still AC), rebuild and run; restore `3`.

Interactor rejecting early with many processes blocked: `wa-ignores-index` at `processes: 64` -- verdict WA, run finishes promptly (no wall-clock hang).

**Step 6: Regression gate.**

**Step 7: Commit** -- `feat(tasks): judge fanout problems with N solution processes`

---

### Task 8: `[k]`-tagged interactions, printing and the sample plumbing

**Files:**
- Modify: `rbx/box/testcase_utils.py:84-200` (`TestcaseInteractionEntry`, `merge_interaction_entries`, `parse_interaction`, `print_interaction`)
- Modify: `rbx/box/testcase_sample_utils.py:59-77,168-178`
- Modify: `rbx/box/statements/engine.py:77-90`, `rbx/box/statements/sample_staging.py:35-60,174-182`, `rbx/box/statements/context.py:110-126`

**Step 1: Parsing.** `TestcaseInteractionEntry` gains:

```python
    # Which contestant process this line belongs to, for a fanout problem's
    # `[k]`-tagged capture; `None` for a single-process one.
    process: Optional[int] = None
```

In `testcase_utils.py` add (module level; `import re`):

```python
# A fanout capture tags each line with its process before the direction:
# `[3]<5`, `[3]>6`, `[3]!debug`.
_PROCESS_TAG = re.compile(r'\[(\d+)\]')


def _split_process_tag(line: str) -> Tuple[Optional[int], str]:
    match = _PROCESS_TAG.match(line)
    if match is None:
        return None, line
    return int(match.group(1)), line[match.end() :]
```

In `parse_interaction`'s loop, first thing per line: `process, line = _split_process_tag(line)`; keep a `tagged: Optional[bool] = None` before the loop and, per line,

```python
            if tagged is None:
                tagged = process is not None
            elif tagged != (process is not None):
                raise TestcaseInteractionParsingError(
                    f'Invalid interaction file {file}: it mixes lines tagged with a '
                    'process ([k]) and untagged ones.'
                ) from None
```

and pass `process=process` to each `TestcaseInteractionEntry(...)`.

`merge_interaction_entries`: merge only when `merged_entries[-1].pipe == entry.pipe and merged_entries[-1].process == entry.process`.

`print_interaction`:

```python
def print_interaction(interaction: TestcaseInteraction):
    for entry in interaction.entries:
        text = rich.text.Text(entry.data)
        text.stylize(interaction_entry_style(entry.pipe))
        if entry.process is not None:
            text = rich.text.Text.assemble((f'[{entry.process}] ', 'dim'), text)
        console.console.print(text)
```

**Step 2: Samples carry the process; templates don't render fanout yet.**
- `_build_sample_interaction` passes `process=chunk_entry.process` to `SampleInteractionChunk`.
- After `interaction = parse_interaction(interaction_path)` in `testcase_sample_utils.py`, check the tags against the problem:

```python
def _check_interaction_processes(interaction: TestcaseInteraction, path: pathlib.Path) -> None:
    """A fanout sample's lines name processes that exist; nobody else's do."""
    pkg = package.find_problem_package_or_die()
    tagged = any(entry.process is not None for entry in interaction.entries)
    if pkg.is_fanout:
        n = pkg.fanout_processes
        if interaction.entries and not tagged:
            raise TestcaseInteractionParsingError(
                f'{path}: tag every line with the process it belongs to, e.g. `[0]< 3`.'
            )
        for entry in interaction.entries:
            if entry.process is not None and entry.process >= n:
                raise TestcaseInteractionParsingError(
                    f'{path}: names process {entry.process}, but the interactor talks to {n} (0 to {n - 1}).'
                )
    elif tagged:
        raise TestcaseInteractionParsingError(
            f'{path}: tags lines with a process ([k]), but this problem\'s interactor talks to one process.'
        )
```

  called inside the existing `try`, so it reports through the same `Error parsing interactive sample` path.
- `engine.to_sample_source`: `chunks = [(chunk.path, int(chunk.pipe), chunk.process) for chunk in sample.interaction.chunks]`; `SampleSource.interaction_chunks: List[Tuple]` documented as `(path, pipe, process)`.
- `sample_staging.SampleInteractionChunkHandle` gains `process: Optional[int] = None`; the staging loop unpacks `chunk_path, pipe, *rest = chunk` with `process = rest[0] if rest else None` (existing 2-tuples keep working) and builds handles with `process=process`. Then:

```python
            interaction = SampleInteractionHandle(chunks=chunks)
            if any(chunk.process is not None for chunk in chunks):
                # Fanout: templates do not render several processes yet (#1045),
                # so the data stays out of `interaction`, which they do render.
                handle.fanout_interaction = interaction
            else:
                handle.interaction = interaction
```

- `SampleHandle` (`context.py`) gains `fanout_interaction: Optional[Any] = None` with a one-line comment pointing at #1045.

**Step 3: Verify by hand**

```bash
cd $FANOUT && $RBX build
cat build/tests/samples/000.pio          # tagged, line mode
$RBX -cp irun --testcase samples/0 -p    # Interaction section shows dim "[0] " / "[1] " prefixes
$RBX -cp irun --testcase samples/0 -p --merge-stderr -s sols/chatty.cpp   # [k] stderr lines interleaved
```

Hand-written samples:
- Write `$FANOUT/manual/0.interaction` with `[0]< 5` / `[0]> 6` / `[1]< 6` ... and add a `statements:` entry (copy one from `$STUB/problem.rbx.yml`, `type: rbx-tex`, plus a minimal `statement/statement.rbx.tex` from `$STUB/statement`), then `$RBX statements build` (PDF stubbing not available here -- if pdflatex is missing, build to tex/markdown with `--output` per `rbx statements build --help`). Expected: builds; the sample shows no interaction block (not rendered yet).
- Change one line to `[5]< 5` -> build fails "names process 5, but the interactor talks to 3".
- Remove the tags from one line -> "mixes lines tagged ... and untagged ones".
- In `$IACT`, add a `[0]`-tagged `.interaction` next to a sample -> "talks to one process".
- `$IACT`/`$STUB` statements and `rbx irun -p` output unchanged (no tags anywhere).

**Step 4: Regression gate**, plus `uv run pytest -q tests/rbx/box/statements/test_engine.py tests/rbx/box/statements/test_sample_staging.py`.

**Step 5: Commit** -- `feat(interaction): tag fanout captures with their process`

---

### Task 9: One list of a testcase's files (retries, stress)

**Files:**
- Modify: `rbx/grading/steps.py` (`TestcaseLog`), `rbx/box/retries.py:73-91`, `rbx/box/stresses.py:131-140`

**Step 1: Implement.** In `steps.py` above `TestcaseLog`:

```python
# Files a communication run leaves next to a testcase's output, besides the
# ones a `TestcaseLog` points at directly.
_SIBLING_ARTIFACT_SUFFIXES = ('.pin', '.pout', '.pio', '.int.err', '.int.log', '.sol.log')
```

and on `TestcaseLog`:

```python
    def artifact_paths(self) -> List[pathlib.Path]:
        """Every file of this evaluation that exists on disk."""
        candidates = [
            self.stdout_absolute_path,
            self.stderr_absolute_path,
            self.log_absolute_path,
            self.eval_absolute_path,
            self.checker_stderr_absolute_path,
        ]
        if self.stdout_absolute_path is not None:
            candidates += [
                self.stdout_absolute_path.with_suffix(suffix)
                for suffix in _SIBLING_ARTIFACT_SUFFIXES
            ]
        paths: List[pathlib.Path] = []
        for path in candidates:
            if path is not None and path.exists() and path not in paths:
                paths.append(path)
        return paths
```

`retries._move_logs_to_temp_dir` becomes:

```python
def _move_logs_to_temp_dir(
    eval: Evaluation, temp_dir: pathlib.Path
) -> List[FileToRecover]:
    # Every file of the attempt, so the one kept never pairs its verdict with
    # another attempt's capture or interactor log.
    return [_move_to_temp_dir(path, temp_dir) for path in eval.log.artifact_paths()]
```

`stresses` (the finding copier at `:131`): also copy the capture and the interactor's stderr beside the kept `<index>.out`:

```python
        stdout = evaluation.log.stdout_absolute_path
        copies = [
            (stdout, out_path),
            (evaluation.log.stderr_absolute_path, out_path.with_suffix('.err')),
        ]
        if stdout is not None:
            copies += [
                (stdout.with_suffix(suffix), out_path.with_suffix(suffix))
                for suffix in ('.pio', '.int.err')
            ]
        for src, dst in copies:
            if src is not None and src.is_file():
                shutil.copyfile(src, dst)
```

**Step 2: Verify by hand**

```bash
cd $FANOUT && $RBX -cp run -s sols/main.cpp --runs 3      # use the repeats flag `rbx run --help` names
ls .rbx/runs/*/main/                                       # every test has .out .sol.err .sol.log .int.err .int.log .pio .eval .log, all from the same attempt
cd $IACT && RBX_DOCKER=0 $RBX -cp run --runs 3             # .pin/.pout/.pio present and consistent with the .eval (no leftovers)
cd $FANOUT && $RBX -cp stress -g "gens/gen [1..30] @" -f sols/wa-ignores-index.cpp -n 1 -t 30
```

The stress run finds a failing test immediately; the kept finding directory (path printed by `rbx stress`) holds `<i>.out`, `<i>.err` (tagged), `<i>.pio` (tagged), `<i>.int.err`, `<i>.eval`. `rbx stress -g "gens/gen [1..30] @" -f sols/main.cpp -t 20` finds nothing.

**Step 3: Regression gate**, plus `uv run pytest -q tests/rbx/box/stresses_test.py tests/rbx/box/stress_manifest_test.py`.

**Step 4: Commit** -- `fix(runs): keep every file of a testcase across retries and stress findings`

---

### Task 10: Stress and soak testing

No code unless something breaks (then fix, re-verify, and commit the fix on its own). Run each item with `RBX_DOCKER=0` and with Docker.

1. **Many runs:** `for i in $(seq 30); do (cd $FANOUT && rm -rf .rbx && $RBX run > /tmp/fan-$i.txt 2>&1 || echo FAIL $i); done` -- identical verdicts every time (`diff` the outputs modulo timings), no hang.
2. **N = 64:** `processes: 64`, generator args `200 1`, `2000 2`; `main` AC, `wa-*` WA promptly, `re-process-1` RTE naming process 1, `tle-sum` TLE.
3. **Volume:** `processes: 8`, `timeLimit: 5000`, a test `gen 50000 9`; `main` AC with and without `-cp`; with `-cp` the `.pio` has 50000 x 8 x 2 tagged lines in order (`grep -c '^\[7\]>' file` = 50000). `chatty` with `--merge-stderr` on `irun`: `.sol.err` ~ 400 MB? -- if so, lower K; the point is that it completes and stays grouped.
4. **Interactor rejecting early with everyone blocked:** `wa-ignores-index` at 64 processes, 200 times in a loop -- never a wall-timeout verdict, never a hang.
5. **Crash storms:** a solution where every odd process aborts on its first message; verdict RTE naming the lowest-exit-index process.
6. **Capture on/off parity:** for every solution, the verdicts with `-cp` equal those without.
7. **Interactive soak:** `$IACT` and `$STUB` with `-cp`, 30 runs each, verdicts unchanged.

Record any timing anomaly (e.g. tees making a 64-process run much slower) in the PR description.

---

### Task 11: Remaining consumers

**Files:**
- Modify: `rbx/box/summary.py:217`, `rbx/box/estimation_checksum.py:94-96,184-191`

**Step 1: Summary.**

```python
        interactor_display=_interactor_display(pkg),
```

with

```python
def _interactor_display(pkg: Package) -> Optional[str]:
    if pkg.interactor is None:
        return None
    if pkg.is_fanout:
        return f'{pkg.interactor.display()} (fanout, {pkg.fanout_processes} processes)'
    return pkg.interactor.display()
```

**Step 2: Estimation checksum.** A separate segment model for fanout, so every one-process problem keeps the checksum it has:

```python
class _FanoutInteractorSegment(BaseModel):
    interactor: _CodeFingerprint
    # The process count moves the times an estimate was taken from.
    processes: int
```

and in `_interactor_segment`:

```python
    fingerprint = _fingerprint_code(pkg.interactor)
    if pkg.is_fanout:
        assert pkg.fanout_processes is not None
        return _digest_model(
            _FanoutInteractorSegment(interactor=fingerprint, processes=pkg.fanout_processes)
        )
    return _digest_model(_InteractorSegment(interactor=fingerprint))
```

(Visualizers' `_compile_interactor` and irun's printing were already switched to `is_communication` in Task 3.)

**Step 3: Verify by hand**

```bash
cd $FANOUT && $RBX summary                   # Interactor: interactor.cpp (fanout, 3 processes)
cd $FANOUT && $RBX time                      # saves a profile; then:
sed -i '' 's/processes: 3/processes: 4/' problem.rbx.yml
$RBX run                                     # a warning that the saved estimate is stale ("the interactor has changed")
sed -i '' 's/processes: 4/processes: 3/' problem.rbx.yml
cd $IACT && $RBX time && $RBX run            # no stale warning: one-process checksum unchanged
```

(Locate the stale-estimate warning with `grep -n warn_if_stale rbx/box/*.py`; if `rbx run` does not print it, use the command that does.) Visualizers: add an output visualizer with `output_from` to `$FANOUT` only if quick (copy the shape from `tests/e2e/testdata` -- `grep -rl output_from tests/e2e/testdata`); expected: it runs the solution against the interactor, not batch-style.

**Step 4: Regression gate**, plus `uv run pytest -q tests/rbx/box/test_summary.py tests/rbx/box/estimation_checksum_test.py`.

**Step 5: Commit** -- `feat(summary): show the fanout process count; fingerprint it for estimates`

---

### Task 12: e2e fixtures

**Files:**
- Create: `tests/e2e/testdata/fanout/` and `tests/e2e/testdata/fanout-grader/`

**Step 1: `fanout`** -- copy the scratch problem (sources, `manual/`, `problem.rbx.yml`, all seven solutions) into `tests/e2e/testdata/fanout/` (no `.rbx/`, `build/`, `rbx.h`). Keep the `main` group small (`gen 10 1`, `gen 200 2`) so the scenario stays fast. `e2e.rbx.yml`:

```yaml
scenarios:
  - name: fanout-run
    description: |
      Three copies of each solution relay a value through a testlib
      interactor (rbx::registerFanoutInteraction); process i answers
      value + i + 1, reading i from argv[1]. Pins the CMS judging rules:
      CPU time summed across processes, a process failing after the
      interactor accepted still fails, and real isolation between processes.
    steps:
      - cmd: run
        expect:
          solutions:
            sols/main.cpp: ac
            sols/chatty.cpp: ac
            sols/wa-ignores-index.cpp: wa
            sols/wa-shared-state.cpp: wa
            sols/re-after-accept.cpp: re
            sols/re-process-1.cpp: re
            sols/tle-sum.cpp: tle

  - name: fanout-capture
    description: The capture tags every line with its process.
    steps:
      - cmd: build
        expect:
          file_contains:
            build/tests/samples/000.pio: '/\[0\]<5\n\[0\]>6\n\[1\]<6\n\[1\]>8\n/'
      - cmd: -cp irun --testcase samples/0 -p -s sols/main.cpp
        expect:
          stdout_contains: "[2] 11"

  - name: fanout-refused-by-packagers
    steps:
      - cmd: package pkg
        expect_exit: 1
        expect:
          stdout_contains: interactor talks to several processes
```

Check the verdict shorthands (`re`, `tle`) and the `irun` flags against `tests/e2e/spec.py` / `rbx irun --help`, and where `-cp` goes (`rbx -cp irun ...` vs `cmd: -cp irun`) against another fixture that captures (`grep -rn -- '-cp' tests/e2e/testdata/*/e2e.rbx.yml`).

**Step 2: `fanout-grader`** -- the same protocol through a grader stub. Copy `fanout/` and change:
- `problem.rbx.yml`: add

```yaml
grader:
  path: graders/grader.cpp
  secret: fanout-relay-3f9a1c7e5b2d4086
```

  and keep only `sols/main.cpp` (ac) and `sols/wa.cpp` (wa).
- `graders/relay.h`: `long long relay(int index, long long value);`
- `graders/grader.cpp`:

```cpp
#include <csignal>
#include <cstdio>
#include <cstdlib>

#include "relay.h"

int main(int argc, char *argv[]) {
  // The interactor may finish while we still write: exit quietly instead.
  std::signal(SIGPIPE, SIG_IGN);
  int index = std::atoi(argv[1]);
  long long v;
  while (std::scanf("%lld", &v) == 1 && v != -1) {
    std::printf("%lld\n", relay(index, v));
    std::fflush(stdout);
  }
  return 0;
}
```

- `sols/main.cpp`: `#include "relay.h"` + `long long relay(int index, long long value) { return value + index + 1; }`; `sols/wa.cpp`: returns `value + 1`.
- The interactor is unchanged: `registerFanoutInteraction` consumes the grader's hidden input header itself when the problem has a grader.

`e2e.rbx.yml`: one `run` scenario expecting `sols/main.cpp: ac`, `sols/wa.cpp: wa`.

**Step 3: Verify**

```bash
cd $REPO/tests/e2e/testdata/fanout && RBX_DOCKER=0 uv run rbx build && git status --short .   # clean afterwards (gitignore covers build output)
cd $REPO && RBX_DOCKER=0 uv run pytest -q tests/e2e/testdata/fanout tests/e2e/testdata/fanout-grader
for i in $(seq 5); do RBX_DOCKER=0 uv run pytest -q tests/e2e/testdata/fanout || break; done   # not flaky
```

**Step 4: Commit** -- `test(e2e): add fanout fixtures with and without a grader`

---

### Task 13: Docs

Use the `docs-style` skill (Vale + `docs-style-reviewer`). The section is **short and usability-first** (user's explicit request): one sentence on what fanout is, the YAML snippet, a small interactor snippet, and one line each on `argv[1]`, the summed time limit, and "a process that fails scores 0 even after the interactor accepted". No verdict ladder, file layout, or limits arithmetic.

**Files:**
- Modify: `docs/setters/grading/interactors.md` -- new `## Several processes (fanout)` section before `## Do I need to write a checker?`
- Modify: `rbx/box/CLAUDE.md` -- under `### ScoreType / TaskType`, a bullet: "`TaskType` alone does not say how many processes an interactor talks to: ask `pkg.is_communication` (has an interactor), `pkg.is_interactive` (one process) or `pkg.is_fanout` (`interactor.processes`, several) -- never compare `pkg.type` for those."

Draft for `interactors.md` (adapt to the house voice; `{{rbx}}`/`{{testlib}}` macros):

````markdown
## Several processes (fanout)

Some problems run several copies of the solution at once against one interactor
-- "run twice" encoder/decoder tasks, for instance. Set `processes` on the
interactor:

```yaml
type: communication
interactor:
  path: interactor.cpp
  processes: 2
```

Each copy gets its index (`0`, `1`, ...) as its first command-line argument.
The interactor registers with `rbx::registerFanoutInteraction` and talks to
copy `i` through `rbx::fanout::to(i)` and `rbx::fanout::from(i)`:

```cpp
#include "testlib.h"
#include "rbx.h"

int main(int argc, char *argv[]) {
  rbx::registerFanoutInteraction(argc, argv);
  int x = inf.readInt();
  rbx::fanout::to(0) << x << std::endl;          // copy 0 encodes
  int code = rbx::fanout::from(0).readInt();
  rbx::fanout::to(1) << code << std::endl;       // copy 1 decodes
  if (rbx::fanout::from(1).readInt() != x) quitf(_wa, "decoded wrong");
  quitf(_ok, "ok");
}
```

- The time limit applies to the CPU time of all copies together.
- If any copy fails -- crashes, exits with a non-zero code, or runs out of
  time or memory -- the test fails, even if the interactor already accepted.
- Captured interactions (`rbx -cp`) tag each line with its copy: `[1]>`.
````

Steps: write, `mise run docs:lint docs/setters/grading/interactors.md`, fix errors, dispatch `docs-style-reviewer` with the path and "short section introducing fanout interactors", address BLOCKER/MAJOR, re-lint. Build the site non-strict to see it renders (`mise run docs:build` or the docs build task in `mise.toml`; ~9 pre-existing strict warnings are unrelated).

Commit -- `docs(interactors): document fanout interactors`

---

### Task 14: Contract unit tests

Pin what Tasks 2-12 verified by hand. Reuse fixtures (`testing_pkg`, `file_cacher`, `cleandir`), `mock.patch` from stdlib, assert behaviour. Tests that compile C++ through rbx call `get_testlib()`: patch it to the predownloaded testlib (`rbx/resources/predownloaded/testlib.h`), or each stalls ~300 s on DNS.

1. **Schema** (`tests/rbx/box/test_schema.py`, new class `TestFanoutPredicates`): `processes: 1` -> `ValidationError`; `processes: 3` -> `is_fanout`, `fanout_processes == 3`, not `is_interactive`, `is_communication`; no `processes` -> `is_interactive`; batch -> none of them.
2. **`combine_process_logs`** (`tests/rbx/grading/steps_combine_process_logs_test.py`, new): one log returned as is; three OK logs -> time summed, wall/memory maxima, `decider is None`, exit fields of the last to exit; a failing process -> its exit fields and index; the first to exit among several failures wins; any `None` -> `(None, None)`; a sandbox error wins over a later RTE.
3. **Verdict through the ladder** (`tests/rbx/box/checkers_communication_test.py`, new cases feeding `check_communication` the combined log built with `combine_process_logs`, following the file's existing log-building helpers): summed CPU >= TL with each process under it -> TLE; interactor AC then a process exits 1 -> RTE; interactor WA first then processes SIGKILL'd -> WA.
4. **`_name_failing_process`** (`tests/rbx/box/tasks_test.py`): N = 1 untouched; `process 2: ...` prefix; TLE with no decider -> `the processes together`; WA never prefixed.
5. **Sandbox** (`tests/rbx/grading/judge/test_run_fanout.py`, new, modelled on `test_run_communication.py`): the Task 5 Step 6 Python interactor/solution as fixtures; N = 3 all OK; argv index; `/dev/fd` paths in contract order; `sol.err` grouped and tagged; with a merged capture, `[i]<`, `[i]>`, `[i]!` lines in order; interactor failing kills the group promptly; `run_communication` still returns a `(solution, interactor)` pair.
6. **Steps/caching** (`tests/rbx/grading/steps_with_caching_run_test.py`): `run_fanout_coordinated` with `processes=3` caches and restores all three logs; changing `processes` misses the cache; a holder with `runs=None` restores as `[run]`.
7. **Interaction parsing** (`tests/rbx/box/testcase_utils_test.py`): tagged `.pio` and `.interaction`; mixed tags raise; `merge_interaction_entries` splits on a process change with the same direction; untagged files parse exactly as before.
8. **Sample checks** (`tests/rbx/box/test_testcase_sample_utils.py`): fanout sample with `[5]` and N = 3 errors; untagged fanout sample errors; tagged sample in an interactive problem errors.
9. **Staging** (`tests/rbx/box/statements/test_sample_staging.py`): process-tagged chunks land in `fanout_interaction`, not `interaction`; 2-tuples still stage into `interaction`.
10. **Artifacts** (`tests/rbx/box/tasks_test.py` or a new `tests/rbx/grading/testcase_log_artifacts_test.py`): `artifact_paths` lists existing siblings only, without duplicates.
11. **Header** (`tests/rbx/box/test_header.py`): a fanout package's `rbx.h` contains `registerFanoutInteraction`; an interactive one's is byte-identical to the template without the fanout sentinel line; with a grader, the fanout block contains `consumeInputHeader`.
12. **Gates** (`tests/rbx/box/packaging/test_fanout_support.py`, new, modelled on `test_points_support.py`): every packager refuses a fanout problem before `builder.verify` is called; `tests/rbx/box/runners/test_capabilities.py`: `LocalRunner` supports fanout, MOJ/DOMjudge runners don't, `_check_capabilities` raises naming `interactor.processes`.
13. **Checksum** (`tests/rbx/box/estimation_checksum_test.py`): changing `processes` changes the interactor segment; an interactive problem's segment equals the pre-change digest (compute it with `_InteractorSegment` directly).
14. **Summary** (`tests/rbx/box/test_summary.py`): fanout display string.

Run exactly these files, then the regression gate. Commit -- `test: pin fanout judging behaviour`

---

## Notes the executor should know before starting

- Task order matters: Task 4 (header) comes before the sandbox so the scratch interactor compiles from the start; Tasks 5-6 are verified through the interactive path plus a direct sandbox script because nothing runs fanout end to end before Task 7.
- `LocalRunner` refuses fanout from Task 3 until Task 7, so an accidental `rbx run` on `$FANOUT` in between fails loudly instead of running one process.
- Output generation (`rbx build`) does not go through a runner, so do not `rbx build` the fanout scratch problem before Task 7.
