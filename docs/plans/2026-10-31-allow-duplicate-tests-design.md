# Intentionally duplicate tests

## Problem

`generate_testcases` warns when two tests are duplicates, across every group:

1. **Same call** -- two tests come from the same `gen args` string.
2. **Same hash** -- byte-identical inputs (only checked when (1) did not fire).

Neither warning could be silenced, yet some duplicates are deliberate: a subtask
reusing a small case of an earlier one, or a random generator landing on the same
tiny input.

## Design

Two opt-outs, nothing else (no per-test YAML flags, no package-wide switch):

- **Group flag.** `allowDuplicate: Optional[bool]` on `TestcaseSubgroup` (so
  `TestcaseGroup` has it too). A subgroup takes its own value when set, its
  group's otherwise; unset means `false`. Resolved in `testcase_extractors` into
  `GenerationTestcaseEntry.group_allows_duplicate`.
- **Line annotation.** A trailing `@allow-duplicate` on an rbx-format testplan
  line: generator calls, `@copy` and `@input`. Only the **last**
  whitespace-separated token counts (`split_allow_duplicate`), so the keyword
  elsewhere stays a generator argument. For `@input` it is a grammar token after
  the string or block, and must sit on the line the content ends on (checked in
  `parse`, since the grammar ignores newlines). Carried as
  `GenerationInput.allow_duplicate`. `box`-format scripts do not support it.

**Symmetric rule.** A pair is silent when *either* test allows duplicates
(`GenerationTestcaseEntry.allows_duplicate()`). So a new test is compared against
every earlier test with the same call or hash, and the warning names the first
one that does not allow it -- the result does not depend on generation order.

## Keeping the annotation

Anything that re-reads or rewrites a testplan line must not lose or misread it:

- `testplan_edit` strips it from a `@copy` statement's `copy_path`.
- `promotion_plan` re-appends it to the recipe or `@copy` line a promoted test
  becomes, when the source line carried it (not when only its group allowed it).
- The VS Code extension's `generatorCallFrom` strips it before running a call;
  its line scanner is unaffected, and `testplan.cases.json` pins both scanners.
