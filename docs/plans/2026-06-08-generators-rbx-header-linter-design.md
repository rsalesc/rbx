# Design: block generators from depending on `rbx.h`

- **Issue**: [#386](https://github.com/rsalesc/rbx/issues/386) — "Don't allow generators to depend on `rbx.h`"
- **Date**: 2026-06-08

## Problem

`rbx.h` exposes `getVar<T>("NAME")`, which bakes the problem's **variables/constraints**
into a compiled program. It is auto-injected into the reserved `__internal__/` include
directory, so any `#include "rbx.h"` in a generator, validator, checker, etc. resolves.

Validators *should* depend on constraints. **Generators should not**: if a generator reads
a constraint via `getVar` and that constraint later changes, the generated tests change
**silently** — no diff in the generator source, no warning, but the testset is now different.
This makes generator calls fragile.

We want to **error** when a generator depends on `rbx.h`, while offering two escape hatches
and a docs link that explains why.

## Decisions (confirmed with the owner)

1. **Per-include escape hatch** = reuse the framework's existing whole-file directive
   `// rbx-header-linter: disable`, placed on the include line by convention. No new
   suppression mechanism.
2. **Detection scope** = direct include only (`#include "rbx.h"` / `<rbx.h>` in the
   generator's own source). No transitive/indirect detection.

## Approach

Add a new linter to the existing `rbx/box/linters/` framework, scoped to
`AssetKind.GENERATOR`, emitting an **ERROR** when the generator source directly includes
`rbx.h`. This reuses everything the framework already provides:

- **env-config on/off** — the "disable in `env.rbx.yml`" path is removing `rbx-header`
  from a language's `linters:` list.
- **per-include suppression** — the existing `// rbx-header-linter: disable` directive
  (`is_linter_suppressed`), placed after the include line.
- **error routing** — ERROR-severity linter messages already raise `RbxException` and print
  under "Linter errors in …", blocking the build.
- **tree-sitter-cpp** — already a dependency, used by the `testlib` linter and the cpp
  dependency scanner.

This mirrors exactly how the `testlib` linter was added.

### Alternatives considered & rejected

- **Bespoke check in the build/dependency layer** — would enable transitive detection, but
  the owner chose direct-only, and it would reinvent config + suppression + error routing.
- **Reuse the cpp dependency-scanner's resolved include list** — not asset-kind-scoped, no
  suppression plumbing.

## Components

1. **`rbx/box/linters/cpp/rbx_header.py`** — `RbxHeaderLinter(Linter)`:
   - `name = 'rbx-header'`, `applies_to = {AssetKind.GENERATOR}`.
   - Parses source with tree-sitter-cpp, walks `preproc_include` nodes, flags any include
     (quoted `string_literal` or angled `system_lib_string`) whose **basename** is `rbx.h`.
   - Reports an ERROR `LinterMessage` at the include's 1-based line/col.
   - `registry.register(RbxHeaderLinter)`.

2. **`rbx/box/linters/__init__.py`** — import the module so it self-registers (like `testlib`).

3. **Error message** (multi-line, in the `LinterMessage.message`):

   > Generators must not `#include "rbx.h"`. It exposes the problem's variables/constraints
   > via `getVar`, so a generator that reads them silently changes its tests whenever a
   > constraint changes.
   > • To intentionally allow it here: add `// rbx-header-linter: disable` after the include line.
   > • To turn this check off everywhere: remove `rbx-header` from `linters` in your `env.rbx.yml`.
   > • Why this matters: https://rbx.rsalesc.dev/generators-and-rbx-h/

4. **`rbx/resources/presets/default/env.rbx.yml`** — add `rbx-header` to the C++ `linters:`
   list (`[testlib, rbx-header]`). This file is both the default preset env and the bundled
   app-default env (`get_app_environment_path('default')`), so the check is on by default.

5. **Docs** — new `docs/generators-and-rbx-h.md` under the "Troubleshooting" nav in
   `mkdocs.yml`, explaining the silent-test-change failure mode with a concrete before/after
   example and both escape hatches.

## Testing

- Unit tests on the pure linter (`lint(code, source)`):
  - flags `#include "rbx.h"`, `#include <rbx.h>`, `#include "sub/rbx.h"`;
  - ignores other includes and the absence of any include;
  - handles multiple includes (one message per offending include).
- Through the runner (`run_linters_for_messages` / `is_linter_suppressed`):
  - the `// rbx-header-linter: disable` directive suppresses the linter;
  - the linter does **not** fire for non-generator asset kinds (scope respected).
- Verify no existing testdata **generator** includes `rbx.h` (validators do and are out of
  scope) so enabling it by default does not break fixtures.

## Risks

- Existing users with a **custom** `env.rbx.yml` that does not list `rbx-header` won't get
  the check until they add it — same opt-in situation as `testlib` today. Acceptable and
  consistent.
- A generator that hides `rbx.h` behind a local header is not caught (out of scope by design).
