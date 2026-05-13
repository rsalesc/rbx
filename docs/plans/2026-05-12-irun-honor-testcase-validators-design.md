# Design: `rbx irun -t` honors per-testcase validators (#405)

## Problem

`generators.generate_standalone()` always validates the generated input against the
package-level validators (`package.get_all_validators()` — i.e. `Package.validator` +
`Package.extraValidators`). It ignores the validator configuration that applies to the
*specific* testcase being generated.

When `rbx irun -t <group>/<index>` runs, `solutions._generate_testcase_interactively()`
already extracts the full `GenerationTestcaseEntry` for that testcase via
`extract_generation_testcases_from_generic_entries()`. That entry knows its effective
input validators — `entry.validator` (the group-level override, if any, otherwise the
package validator) and `entry.extra_validators` (package + group + subgroup
`extraValidators`). But `_generate_testcase_interactively()` only forwards
`interactive_entry.metadata` to `generate_standalone()`, so the per-group validator
configuration is dropped and validation falls back to the package-level validators.

The normal build pipeline (`builder.build()` → `validators.validate_testcases()`) already
honors the per-entry validators; `irun` should behave consistently.

## Scope

- **In scope:** input validators only (`entry.validator` + `entry.extra_validators`),
  which is exactly what `generate_standalone()` validates today.
- **Out of scope:** `entry.output_validators` (irun's output handling is a separate path),
  the `rbx stress` validation path, and the ad-hoc interactive flows.

## Change

### 1. `generators.generate_standalone()`

Add an optional parameter `entry: Optional[GenerationTestcaseEntry] = None`.

- If `entry is not None`: validate against
  `([entry.validator] if entry.validator is not None else []) + entry.extra_validators`.
  An **empty** resulting list means *no* input validation runs — which is the correct
  behavior when neither the package nor the group defines a validator.
- If `entry is None`: behavior is unchanged — fall back to `package.get_all_validators()`.
- When `entry` is provided and `group_entry` is not, derive
  `group_entry = entry.group_entry` (used for the validator `--group` hint passed to
  `validators.validate_one_off()` and for the error-header text).
- The validator compilation loop and the `validators_digests` cache plumbing are unchanged
  — only the source list of validators changes.

### 2. `solutions._generate_testcase_interactively()`

In the `testcase_entry is not None` branch (the `-t` path), pass `entry=interactive_entry`
to `generate_standalone()`. The other two branches keep passing nothing:

- the `-g`/generator-call branch (`GenerationTestcaseEntry.make_interactive()` with a
  generator call) — not tied to any group → package-level fallback;
- the typed-at-prompt branch — likewise package-level fallback.

### 3. Other callers — untouched

- `generators.py` main generation visitor: calls with `validate=False`; validation is done
  separately by `validators.validate_testcases()` which already honors per-entry validators.
- `testcases/main.py`: calls with `validate=False`.
- `stresses.py`: synthesizes a `GenerationMetadata` with no entry → package-level fallback,
  same as today.

## Testing

- Unit test on `generate_standalone(entry=...)` directly:
  - entry whose `validator` is stricter than the package validator → input that the package
    validator accepts but the group validator rejects raises `ValidationError`;
  - entry with no validators (and a package that has none) → no `ValidationError` even for
    "bad" input.
- `irun -t` behavior test: a package with a group-level `validator` stricter than (or in
  addition to) the package validator. `irun -t <strict-group>/0` on input that violates the
  group validator fails; the same input under a group *without* that validator passes.
- Existing `tests/rbx/box/generators_test.py` standalone tests must stay green (they pass no
  `entry`, so they exercise the package-level fallback unchanged).

## Risk

Low. The new parameter is additive and optional; the only behavior change is on the
`rbx irun -t` path, which is precisely what #405 asks for.
