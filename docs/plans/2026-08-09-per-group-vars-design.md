# Per-group vars — design

Date: 2026-08-09

## Problem

A setter wants a validator to enforce different constraints per test group
(subtask). The obvious attempt is to branch on the group inside the validator:

```cpp
std::string group = opt<std::string>("group", "");
if (group == "sub2") {
    ensuref(a + b >= a - b, "subtask 2 requires A+B >= A-B");
}
```

**This silently does nothing.** rbx does pass `--group <name>` to validators
(`rbx/box/validators.py:113-115`), but testlib's `opt<>()` reads from
`__testlib_opts`, which is populated only by `prepareOpts()` — and
`registerValidation` never calls it (only `registerGen` does,
`testlib.h:4627`). So `has_opt("group")` is false, `opt(..., "")` returns the
default, the branch is dead, and the build goes green.

Adding `prepareOpts(argc, argv)` makes `opt` see the group but then fails every
testcase with `FAIL Opts: unused key 'AB.max'`, because `opt(key, default)`
enables testlib's unused-opt check and rbx injects the package vars as
`--{k}={v}` — which setters read via `getVar`, not `opt`. The shipped preset
validator calls `prepareOpts` without ever calling `opt`, so the trap is armed
but not yet sprung.

Two failure modes are in play, and the second is the important one:

1. The wrong testlib API is used (`opt` instead of `validator.group()`).
2. **Group-name branching fails silently by construction.** Rename or split a
   group and every `if (group == "...")` quietly stops matching. Nothing errors;
   checks simply evaporate.

## What other formats do

| | Input validator | Checker | Interactor |
|---|---|---|---|
| Kattis | per-group setter-declared argv (`input_validator_args`); since 2025-09 also `.files` + testcase `args`, "same interface as a submission" | per-group `output_validator_args`; context otherwise must go in the `.ans` file | *is* the output validator, same treatment |
| DMOJ | offline only; testlib default arg format is literally `--group st{batch_no}` | Python checkers get `batch=<int>`; testlib/native checkers get only file paths | file paths only |
| CMS | not a concept in core | `input correct_output user_output`, nothing else | `manager <fifos...>`, nothing else |
| Polygon | `--group` | `--group` (stripped by `registerTestlibCmd`) | impossible (see below) |

Two findings drove this design.

**Nobody injects group identity into checkers or interactors.** Kattis's stance
is documented in
[issue #393](https://github.com/Kattis/problem-package-format/issues/393) /
[PR #416](https://github.com/Kattis/problem-package-format/pull/416): five
mechanisms were considered (including environment variables, explicitly
rejected as "a new and additional input method" that "makes it a little bit
harder to run validators manually") and all were dropped in favour of "the
author already controls the `.ans` file; encode it there". The stated drivers
were 100% backwards compatibility and spec simplicity — not purity or
reproducibility. Note this is a documented `wontfix`, not a deep principle, and
there is **no** statement anywhere in the record arguing that programs should
not branch on group identity; the absence of that channel is incidental.

**Kattis's own preferred shape is semantic parameters, not identity.** Their
example package sets `input_validator_flags: nFive=1` in one group and
`nFive=0` in another, and the validator reads `Arg("nFive", 0)`. The
acknowledged wart is keeping those values in sync with the rest of the package;
a `%(args)s` substitution syntax was proposed in #393 and never implemented.
**rbx already solves that** — that is what `vars` + `getVar` is.

## Decision

Per-group **vars overrides**, selected at runtime by the group name, for
**validators only**.

Checkers and interactors are explicitly out of scope. They follow the Kattis
route: hint from the input/answer files, both of which are judge-controlled
data in rbx. This also sidesteps a hard testlib constraint —
`registerInteraction` (`testlib.h:4686-4737`) records `--group` but never strips
it, and `argv[3..5]` are hard-wired to answer-file / report-file / `-appes`, so
appending any flag to a testlib interactor corrupts its positional parse. There
is no argv position that works.

### Mechanism

`rbx.h` is generated per-package and already embeds every var's value. It gains
a second table holding the per-group overrides. The only thing that travels at
runtime is the group name, which rbx already passes as `--group`.

```
problem.rbx.yml            rbx.h (generated)              runtime
─────────────────          ─────────────────              ───────
vars:                      getIntVar("B.min"):            argv: … --group sub2
  AB: {min: -200,            group "sub2" -> 0                    │
       max: 200}             group "sub3" -> -200         .init_array captures argv
                             default     -> -200                  │
testcases:                                                rbx::getGroup() == "sub2"
  - name: sub2             rbx::getGroup():                       │
    vars: {AB: {min: 0}}     scans argv for --group        getVar<int>("AB.min") == 0
```

`getVar`'s signature does not change. An existing validator becomes group-aware
the moment the setter adds a `vars:` block to a group — no new API, no init
call in `main()`, no include-order rule.

### Reading the group inside rbx.h

`rbx.h` parses `--group` **itself**. It must not depend on testlib in any way:
no include, no symbol reference, no `_TESTLIB_H_` conditional. Matching
testlib's convention is a semantic choice, not a link-time one.

`argc`/`argv` are captured by a constructor-attribute hook, which glibc and
Apple's dyld both invoke with `(argc, argv, envp)`:

```cpp
namespace rbx {
namespace detail {
static int g_argc = 0;
static char** g_argv = nullptr;
__attribute__((constructor)) static void captureArgs(int argc, char** argv, char**) {
    g_argc = argc;
    g_argv = argv;
}
}  // namespace detail

inline const std::string& getGroup();  // parsed once, cached in a function-local static
}  // namespace rbx
```

Verified on macOS/clang at `-O2`: resolves correctly even when called from a
static initializer, before `main()`. **Not yet verified on Linux/glibc** (no
container available at design time) — the implementation adds a
`/proc/self/cmdline` fallback and a CI check rather than relying on the
documented convention alone.

Parsing accepts both `--group X` and `--group=X`, treats a trailing `--group`
with no value as absent, and returns `""` when the flag is missing (which
selects package defaults).

`rbx::getGroup()` is namespaced because **a global `getGroup()` is impossible**:
`testlib.h:4594` already defines one, and a second definition is an ODR
violation (confirmed: clang reports `redefinition of 'getGroup'`). `getVar`
stays global as the one name setters actually call.

### Package schema

```yaml
vars:
  AB: {min: -200, max: 200}

testcases:
  - name: "samples"
    testcaseGlob: "statement/samples/*.in"
  - name: "sub2"
    score: 20
    vars: {AB: {min: 0}}        # B >= 0 regime
  - name: "sub3"
    score: 20
    vars: {AB: {max: 0}}
  - name: "sub4"
    score: 60                    # no override: package defaults
```

- `vars` is a new field on `TestcaseGroup`, keyed implicitly by the group it
  sits in. Renaming a group cannot break it, because the override travels
  inside the group entry rather than naming it.
- **Merge is deep, at the leaf.** `{AB: {min: 0}}` overrides `AB.min` and leaves
  `AB.max` at 200. Whole-key replacement (Kattis's behaviour) would force
  setters to restate every sibling.
- **Overrides are not required to exist at package level.** A var meaningful
  only inside one group is legitimate. A group-only var read outside its group
  still fails loudly via the existing `getVar` runtime error
  (`"Variable X ... could not be found"`). A non-blocking warning for suspected
  typos is a possible follow-up, not part of this design.
- **Subgroups are not supported.** `--group` carries only the top-level name
  (`group_entry.group`; subgroup paths live on a separate `subgroup_entry`), so
  a subgroup override would be unrepresentable at runtime. Adding it later
  means teaching the flag to carry the qualified path.

### Statements

`groups` is already in the statement context (`context.py:117`, via
`JinjaGroupsGetter`), iterable in insertion order and addressable by name.
Group-resolved vars hang off it:

```latex
%- for g in problem.groups
  \subtask{\VAR{g.name}}{\VAR{g.score}}
  $\VAR{g.vars.AB.min} \le A, B \le \VAR{g.vars.AB.max}$
%- endfor
```

- `g.vars` is the **resolved** set, not the raw override:
  `problem.groups.sub4.vars.AB.max` yields `200` even though `sub4` overrides
  nothing. Exposing the raw override would make a subtasks table silently render
  blanks for every group that does not override that key — reintroducing the
  failure mode this design exists to remove. The raw override is not exposed to
  templates at all.
- `problem.vars` continues to mean package-level values.
- The `vars.` prefix stays mandatory, matching package-level access
  (`\VAR{vars.N.min}` in the preset statement). Statements v2 deliberately keeps
  `params` / `vars` / `contest` unmerged; a bare `g.AB.min` would also collide
  with group metadata the day someone names a var `score`.
- Implemented as a thin view over `TestcaseGroup` in `context.py` that proxies
  attribute access to the model but serves resolved vars wrapped in the existing
  `JinjaDictWrapper`, so a missing key raises strict-undefined with a hint
  instead of rendering empty. `g.name` / `g.score` access is unaffected.

### Ripple effects

1. **The `--{k}={v}` argv rbx passes to validators becomes group-resolved.**
   `validate_file` currently sends `pkg.expanded_vars`; it must send the group's
   effective vars, or an `opt`-based reader and a `getVar`-based reader would
   disagree — a worse trap than the one being fixed.
2. **`_has_group_specific_validator()` must return true when any group declares
   `vars`.** It gates whether the hit-bounds report is merged across groups;
   with per-group vars the same validator genuinely has different bounds per
   group, and merging them produces nonsense "min-value not hit" output.
3. Generators are unaffected — the `rbx-header` linter already forbids `rbx.h`
   there.

### Non-goals

- Group identity for checkers and interactors.
- Per-group extra argv (the literal Kattis mechanism). It duplicates constants
  that `vars` already owns.
- Subgroup-level overrides.
- Contest-level group vars.

## Correctness

**Caching needs no work.** The group and the resolved vars are both on the
validator's argv, and argv is part of the run cache key
(`steps_with_caching.run` hashes `[command]` + artifacts + sandbox params), so
two groups with different effective vars cannot share a cache entry.

**rbx.h regeneration needs no work.** It is regenerated on every compile
(`download.py:37` → `code.py:687`) and is already excluded from header
precompilation precisely because it embeds package vars
(`code.py:729-736`).

**Edge cases.**

- No group (interactive `rbx validate`, `rbx unit`, `cli.py:1236`) → package
  defaults, unchanged.
- `samples` group → package defaults unless it declares `vars`.
- Export: Polygon passes `--group`, so overrides stay live. BOCA/MOJ do not run
  validators, so nothing regresses.

## Testing

1. `tests/rbx/box/test_header.py` — generated header contains the per-group
   table; real compile+run (that file already compiles at line 373) asserting
   `getVar<int>("AB.min")` is `0` under `--group sub2`, `-200` under
   `--group sub3`, `-200` with no flag.
2. Argv capture: correct when read from a static initializer; `--group=X`;
   `--group X`; flag absent; `--group` as the final token with no value.
3. `tests/rbx/box/validators_test.py` — mirroring
   `test_validator_receives_group_argument` (line 560): a testcase legal in one
   group fails in another **with the same validator**.
4. `tests/rbx/box/statements/` — `problem.groups.sub2.vars.AB.min` renders the
   override; `groups.sub4.vars.AB.max` renders the inherited package value; a
   missing key raises strict-undefined rather than rendering empty.
5. Hit-bounds: `_has_group_specific_validator()` true when a group declares
   `vars`, so per-group bounds are not merged.
6. e2e fixture under `tests/e2e/` exercising build → validate with per-group
   vars.

## Docs

- `docs/setters/verification/validators.md` — the per-group vars section, and an
  explicit note on why checkers and interactors take the Kattis route instead.
- `docs/setters/reference/package/index.md` — the `vars` field on testcase
  groups; and that **`opt()` does not work in a validator**, because
  `registerValidation` never calls `prepareOpts` — the trap that motivated this
  work.
- The preset validator should stop calling `prepareOpts`, which today arms the
  unused-opt trap for no benefit.
