# Graders: function-call problems in rbx

Tracking issue: #952. Related research: #958 (IOI binary manager–stub protocol).

## Problem

rbx can only judge standalone programs. IOI-style problems are **function-call**
problems: the contestant implements functions, and a setter-provided **grader** owns
`main()`, reads the test and calls them. rbx can't author, run or package one.

It also can't give a checker per-subtask behaviour on a judge. No judge passes the
group to a checker (CMS runs `./checker input.txt correct_output.txt <output>` with no
extra args; Polygon's `--group` to checkers is unverified). Per-group `getVar` works
only in validators, through `--group`. IOI's answer is a **hidden field in the test
input**, read by the grader, checker or manager and never by the contestant (IOI 2026
Ball Machine: `t`, the subtask type, on line 1).

## What the judges support

| Judge | Batch grader | Grader + interactor | Source |
|---|---|---|---|
| Polygon | A resource with `forTypes=cpp.*`, `stages=COMPILE`, `assets=SOLUTION`, compiled with every solution | The same resource plus the problem's interactor | `polygon_api.ResourceAdvancedProperties`; the `problem.xml` spelling is still to be confirmed (spike 1) |
| CMS | `Batch`, `compilation="grader"`, `grader.%l` managers | `Communication [1, "stub", "std_io"]` with a stub and a manager | `cms/grading/tasktypes/{Batch,Communication}.py`; IOI 2026 packages |
| BOCA, DOMjudge, MOJ, PKG | No | No | — |

rbx reaches CMS through the Polygon zip plus `files/cms_conf.py`, which CMS's Polygon
importer runs and which can override the task type, parameters and managers.

IOI 2026 (`ioi/task-archive/2026`) is the reference for conventions: secrets on line
1 of the input, `<output secret>\nOK` at the start of the grader's output, PV/SV/WA
statuses, `// BEGIN SECRET` / `// END SECRET` blocks stripped to produce the public
grader, and two output secrets around the contestant's call to catch stray stdout.

## Scope

- **In:** C++ graders. A *batch grader* (owns `main()`, its output goes to the
  checker) and a *stub* (talks to a **modern** interactor over stdin/stdout, one
  contestant process). Generated secrets, hidden group header, rbx.h helpers,
  attachments with an opt-in public grader, Polygon and CMS packaging.
- **Out:** other grader languages; several contestant processes (CMS-only:
  Partition, Classroom); the IOI binary protocol (#958); arbitrary hidden fields
  beyond the group; legacy interactors with graders.

## Design

### Schema (`problem.rbx.yml`)

```yaml
type: batch            # or communication (requires a modern interactor)
grader:                # optional CodeItem; C++ only
  path: graders/grader.cpp
  compilationFiles: [graders/monuments.h]
attachments:           # optional; what contestants download, one zip per problem
  - path: graders/grader.cpp
    name: grader.cpp        # name inside the kit; defaults to the basename
    public: true            # opt-in: derive the public grader (below)
  - path: graders/monuments.h
  - path: graders/template.cpp
    name: monuments.cpp
  - samples: examples/      # every sample as examples/NN.in and examples/NN.out
```

- The mode is **inferred**: `batch` + `grader` is a batch grader; `communication` +
  `grader` is a stub. A `legacy: true` interactor together with a `grader` is a
  validation error. Grader problems are judged by the interactor alone, which keeps
  the CMS side free of the checker runner, `fexecve` and answer packing.
- The grader must be C++. A solution in another language is refused at compile time,
  naming the grader.
- `attachments` entries are either files (`path`, `name`, `public`) or one
  `samples: <dir>` entry. `public` is valid on C/C++ sources only.

### Hidden header and judge view

`judge_input(test)` is the **single** function that builds what a judge sees:

```
<input secret>
<declaring group name>
<raw input, unchanged>
```

- Materialized during generation as `NNN.in.judge`, next to the raw built `NNN.in`.
- Validators, statements, stress generation and visualizers keep reading the raw `.in`.
- Solution runs, the checker's `inf`, the interactor's input file, Polygon `tests/NN`
  and CMS testcases use `.in.judge`.
- Ad-hoc inputs (`rbx run` on a custom file, stress) are wrapped with an empty group.
- The group is the test's **declaring** group, so it is well defined even when
  dependencies make a test count for several groups.

### Secrets

`header.py` derives two secrets (input, output) from the package's `.rbx-id` slug, so
they are stable across builds without a new file. It emits them into the judge rbx.h
as `rbx::secrets::kInput` / `kOutput`. They never appear in anything contestants
receive.

### rbx.h helpers

**`rbx::grader::Grader`** is the API a grader is written against: its constructor
does `start()`, and `run(lambda)` does `close_input()` + `before_call()`, runs the
lambda (where contestant code runs, and where verdicts are given through
`wrong_answer()` / `protocol_violation()`), then `after_call()`, returning the
lambda's value. The free functions below stay available for finer control. The
public flavour has the same API with no checks and no framing, and is what
`public: true` pastes in place of `#include "rbx.h"`.


| Caller | API | Behaviour |
|---|---|---|
| batch grader | `rbx::grader::start()` | Reads line 1 and compares it with `kInput`; on a mismatch prints `kOutput`, `PV` and a message, then exits 0. Reads the group line and records it, leaving stdin at the raw input |
| batch grader | `rbx::grader::close_input()` | `fclose(stdin)` |
| batch grader | `rbx::grader::before_call()` / `after_call()` | Prints `kOutput` before the contestant's call; after it prints a second secret and `OK`. Stray contestant stdout lands between them |
| batch grader | `rbx::grader::verdict(kind, msg)` | Ends the run with a grader-decided `PV` or `WA` and a message |
| checker | `rbx::registerGraderChecker(argc, argv)` | `registerTestlibCmd`; strips the header from `inf` (recording the group) and the prologue from `ouf`/`ans`; maps the grader's `PV`/`WA` to testlib verdicts |
| interactor | `rbx::registerGraderInteraction(argc, argv)` | `registerInteraction`; strips the header from `inf` (recording the group). Otherwise an ordinary testlib interactor |

- `rbx::getGroup()` returns the group from the header once a helper has consumed it,
  and falls back to `--group` as today. The per-group `getVar` arms already in rbx.h
  therefore work in graders, checkers and interactors, locally and on every judge.
- Under `-DRBX_PUBLIC` every grader helper is a no-op: no secret check, no group line,
  no prologue.
- Stub mode needs no helpers in v1: the stub never sees the input file. A tamper
  token is deferred to #958.
- A grader `PV` surfaces as WA with a "protocol violation" message, since rbx has no
  PV outcome.

### Compiling and running

- Every `Solution` compile (`rbx run`, the main solution generating answers, stress)
  adds the grader and its `compilationFiles` as a **second translation unit**. The cpp
  compile command expands `{compilable}` into both sources, as judges do with
  `g++ grader.cpp sol.cpp`. A single concatenated unit would collide on `static` names.
  The grader is an input artifact, so it is part of the compile cache key.
- Batch: the solution reads `.in.judge` and the checker gets it as `inf`. Answers come
  from the main solution built with the grader, so `.ans` carries the prologue, as
  IOI's `.out` files do, and `registerGraderChecker` strips it from both sides.
  **Package answers are never post-processed.**
- Stub: `run_communication` is unchanged. The interactor's input file is `.in.judge`,
  and the solution binary (stub + contestant code) is piped to it.
- A manual output file on a grader problem is the *public* answer (statements only).
  The judge answer is always generated by running the main solution.

### Statement samples

For **sample** tests of a grader problem, output generation also runs the main
solution compiled with `-DRBX_PUBLIC` on the raw input. It writes the result as the
built `NNN.out.statement`, reusing the suffix setters already hand-write.
`_get_statement_sample_from_entry` gains one lookup, the built testcase's
`.out.statement`, ranked **below** a hand-written source `.out.statement`. Like those,
it is never checked against the answer.

### Attachments and the public grader

- `rbx package` (and the statements build) writes `build/attachments/<problem>.zip`
  from the `attachments` list.
- `public: true` derives the contestant version of a source:
  1. Remove every `// BEGIN SECRET … // END SECRET` block.
  2. Replace `#include "rbx.h"` with an inlined **public shim** (~20 lines): the
     `rbx::grader::*` helpers as no-ops and `getGroup()` returning `""`. It carries
     **no secrets and no vars**, so the kit stays single-file and leaks nothing.
  3. Compile-check the result (`g++ -c` with the attached headers). A public grader
     that still needs `getVar` or anything else outside the shim fails packaging,
     telling the setter to move that code into a SECRET block or use a literal.

### Packaging

| Target | Batch grader | Stub + interactor |
|---|---|---|
| Polygon zip | `files/grader.cpp` as a resource (`for-types="cpp.*"`, compile stage, solution asset); deps flattened as usual; judge rbx.h in `files/`; `tests/NN` and `.a` are the judge view; attachments in Polygon's attachments slot | Same, plus the existing `<interactor>` |
| Polygon API | `saveFile(RESOURCE, grader.cpp, ResourceAdvancedProperties(...))`; tests uploaded as the judge view | Same |
| CMS (`--cms`) | `cms_conf.py`: `task_type_parameters=["grader", ["",""], "comparator"]`, `grader.cpp` + headers + rbx.h as managers; checker build unchanged; attachments to `general['attachments']` | `Communication [1, <stub>, "std_io"]`, the stub stored under CMS's grader name, and the modern interactor compiled as the manager through a thin, faithful adapter: FIFOs as testlib's `ouf`/stdout, the verdict in CMS's stdout/stderr format. No checker runner, no packing, no `fexecve` |
| BOCA, DOMjudge, MOJ, PKG | Refused by name before the build, through a new `BasePackager.supports_graders()` gate next to `task_types()` | Refused |

## Testing and verification

**Spikes, before any code:**

1. Live Polygon API: set a grader resource and an attachment on a scratch problem,
   download its package and copy the exact `problem.xml` spelling of both.
2. CMS 1.5.1 harness: confirm Communication's compilation value (`stub` or `grader`,
   see `update_49`) and the stub manager's name, and that `general['attachments']`
   from `cms_conf.py` imports.

**Unit tests:**

- Secret derivation: stable for one `.rbx-id`, distinct across packages, absent from
  the public output.
- SECRET stripping, the public shim and its compile check (a `getVar` use is refused).
- The `judge_input` format.
- rbx.h C++ tests: header group beats `--group`; `registerGraderChecker` strips the
  prologue and maps PV/WA; `RBX_PUBLIC` makes the helpers no-ops.

**Testdata packages and e2e scenarios** (`tests/e2e/`):

- `grader-batch`: a checker that varies by group through `getVar`. Solutions: AC, WA,
  one printing to stdout (protocol violation reported as WA), one in Python (refused
  at compile).
- `grader-stub`: a modern interactor and a stub. Solutions: AC, WA, one calling
  `exit()` early.
- Both: statement samples come from `.out.statement` with no secrets, and BOCA,
  DOMjudge, MOJ and PKG refuse to package.

**Packaging tests:** `problem.xml` grader resource and attachments, judge-view
`tests/NN`, the `cms_conf.py` grader parameters and managers, and a single-file public
grader in the kit.

**Live:** Polygon upload with jury solutions judged there; the CMS harness imports
both `--cms` zips, and its scores must match the local run.

**Docs:** a "Graders" page in the setters guide and `attachments` in the schema
reference, written with the `docs-style` skill.

## Spike and live-test outcomes (2026-10-25)

- **Polygon** (live API, scratch problem 615129): a grader is
  `<file for-types="cpp.*" path="files/grader.cpp" type="..."><stages><stage name="compile"/></stages><assets><asset name="solution"/></assets></file>`,
  with a `files/grader.cpp.json` sidecar. `saveFile` refuses a `sourceType` on a
  resource. Attachments ("materials") have no API and could not be observed in
  `problem.xml`, so Polygon packages warn and leave them to the UI.
- **Polygon validates tests as stored**, i.e. the judge view, so the API upload skips
  the validator of a grader problem (rbx validated the raw inputs already).
- **CMS 1.5.1**: Batch `["grader", ["",""], "comparator"]` + `grader.cpp`;
  Communication `[1, "stub", "std_io"]` + `stub.cpp` (renamed `grader` only in later
  CMS); headers must be `.h` managers; `general['attachments']` imports and shows in
  CWS. Live scores matched rbx for both testdata problems. Interactive problems keep
  showing CMS's stock messages (`rbx_cms_report.h`), as before graders.
- **Polygon live**: both testdata problems built with `verify=true` (615132,
  615134).

## Open questions

- Whether Polygon passes `--group`/`--testset` to checkers. The header group makes
  this moot for grader problems.
- How a Polygon material appears in `problem.xml`, if rbx should ever emit one.
