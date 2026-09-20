# Multi-language presets and language management

**Date:** 2026-09-20
**Status:** approved

## Problem

A preset written for three languages is a literal directory tree: the template
`problem.rbx.yml` hardcodes three `statements`/`tutorials` entries and three
`titles`, `statement/` ships three skeletons, and `contest.rbx.yml` hardcodes
3× (`statements` + `tutorials` + `documents`). Two workflows suffer:

- **Initialization.** Creating a problem or contest in only one or two of those
  languages means deleting the rest by hand.
- **Late additions.** A last-minute request to support a new language means
  copying files and yml entries into every problem and the contest by hand.

Nothing in rbx knows which files belong to which language; that is the gap.

## Design

### 1. Schema (additive, non-breaking)

**Language list.** `contest.rbx.yml` gains `languages: [en, pt]`.
`problem.rbx.yml` gains the same field. When absent, a problem inside a contest
inherits the contest's list; a standalone problem derives it from its concrete
statement entries, which is today's behaviour.

**Wildcard entries.** A statement, tutorial or document entry may declare
`language: "*"`, and `{lang}` may appear in its `name`, `file`,
`standaloneProblemTemplate`, `contestProblemTemplate`, `assets` globs and
`params` values. At load time each wildcard expands into one concrete entry per
language in the effective list. A concrete entry for the same `(language,
variant)` (or `name`, on the contest) wins over the expansion, so a single
language can still be special-cased.

```yaml
# contest.rbx.yml (chrome is shared and switches on language internally)
languages: [en, pt]
statements:
  - name: "statement-{lang}"
    language: "*"
    file: "statements/problem-sheet.rbx.tex"
    standaloneProblemTemplate: "statements/problem.rbx.tex"
    contestProblemTemplate: "statements/problem-fragment.rbx.tex"
documents:
  - name: "info-{lang}"
    language: "*"
    file: "statements/info.jinja.tex"
    type: "JinjaTeX"

# problem.rbx.yml
statements:
  - language: "*"
    file: "statement/statement-{lang}.rbx.tex"
tutorials:
  - language: "*"
    file: "statement/editorial-{lang}.rbx.tex"
```

`titles` stays a plain dict: it is authored content, one line per language.

**Where expansion happens.** Not in a Pydantic validator, because a problem
cannot see the contest's list from inside its own model. The package and
contest loaders expand wildcards right after parsing, before uniqueness
validation and before the resolver or the contest join see any entry. Errors
raised on an expanded entry name the wildcard it came from and the language.

**Guarantee.** A package with neither `languages:` nor `"*"` loads identically
to today. Both forms mix freely in one file.

### 2. Presets

No new preset schema. The template packages are real packages, so the
template's own `languages:` list is the declaration of what the preset ships,
and its wildcard entries are the source of truth for which files are
language-scoped: expanding `{lang}` over the template's list yields each
language's *language pack* (e.g. `statement/statement-pt.rbx.tex`,
`statement/editorial-pt.rbx.tex`). Everything else in the template is
language-neutral. The first entry of the list is the default language.

A preset whose problem and contest templates list different languages is a
preset bug and is warned about, not modelled.

### 3. Commands

**Initialization.** `rbx create` and `rbx contest create` gain
`--languages en,pt` (`-l`). When the flag is absent and the template lists more
than one language, a multi-select picker is shown; a single-language template
asks nothing. On the copied package: `languages:` is rewritten to the
selection, files belonging to unselected languages' expansions are deleted,
and `titles` is pruned to the selection. `rbx contest add` takes no flag: a
problem created inside a contest inherits the contest's list (no `languages:`
is written into it) and its language files are pruned to match.

**Management.** A new lazily-registered `rbx lang` group (alias `languages`):

- `rbx lang ls` lists the effective languages and, for each, the resolved
  statement/tutorial files and whether they exist. Inside a contest, one block
  per problem.
- `rbx lang add <lang>` in a standalone problem appends to `languages:`, copies
  the preset's language pack files that do not already exist and adds a
  placeholder `titles.<lang>`. Inside a contest it must be run at the contest
  root: it appends to the contest list and does the problem step for every
  problem. Idempotent: re-running fills in what is missing and touches nothing
  else. If the preset does not ship the language it errors listing what it does
  ship; `--from <lang>` clones that language's files instead of the skeleton.
- `rbx lang rm <lang>` removes from the list(s). Files are kept and reported as
  orphaned unless `--delete-files` is given.

### 4. Build-time behaviour

Nothing new in the engine. After expansion the resolver and the contest join
see plain concrete entries. A listed language whose file is missing fails the
way a missing `file` fails today, with the error naming the wildcard and the
language and suggesting `rbx lang add`. `--languages` on `rbx contest st b`
keeps its meaning (filter what to build).

### 5. Compatibility and v2

Non-breaking. JSON schemas pick the new fields up automatically.

The bundled default preset keeps its concrete `language: en` entries for now.
Converting it to wildcards means renaming `statement/statement.rbx.tex` to
`statement-en.rbx.tex`, which every getting-started page, a recorded cast, the
vscode demo and the cast fixtures refer to; that churn is a follow-up of its
own. Until then `rbx lang add` on a package with no wildcard statements errors
out explaining what to declare, rather than listing a language nothing renders.

For v2 the natural follow-up is to make the wildcard form the only form:
`statements:` becomes a single recipe and the language list the sole
per-language knob, possibly with skeletons rendered through Jinja. Nothing here
blocks that; it is a deletion, not a migration.

### 6. Testing

- Loader: wildcard expansion, `{lang}` substitution in each field,
  concrete-overrides-wildcard, contest-list inheritance, and the identity case.
- Creation: a multi-language testdata preset; `--languages` pruning for problem
  and contest; `rbx contest add` inheritance.
- `rbx lang`: add/rm/ls over a contest fixture with two problems, idempotency,
  the unsupported-language error and `--from`.
- One e2e scenario: create a contest with `en`, build statements, `lang add
  pt`, build again and assert the `pt` PDFs appear.

## Alternatives considered

- **Tooling only over literal trees** (convention-based prune/add, no schema
  change): the preset author still writes everything N times and the yml
  surgery is fiddly and implicit.
- **Parametric presets** (Jinja-rendered template files, language packs in the
  manifest): the cleanest end state but breaks every existing preset and the
  tracking/sync machinery; deferred to v2.
