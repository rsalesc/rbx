---
name: docs-style
description: Use when writing, editing, restyling or reviewing any user-facing documentation in this repository -- pages under docs/ (setters guides, walkthroughs, intro, packaging, statements), shared partials, or admonitions and annotations inside them -- and before committing or opening a PR that touches docs/*.md.
---

# Docs style: Vale + adversarial review

Docs in this repository answer to two layers. Both run on every docs change:

1. **Vale** (`.vale.ini`) -- mechanical checks: the upstream **Google developer
   documentation style guide**; two AI-prose detectors, **Slop**
   (`vale-llm-slop`) and **ai-tells** (`vale-ai-tells`); and `rbx`, the
   checkable subset of the house voice (`.vale/styles/rbx/`).
2. **The `docs-style-reviewer` agent** -- an adversarial reviewer for what a
   linter cannot see: accuracy against the code, introduce-before-use, page
   architecture, and the Google and house rules that need judgment.

The house guide is
[`docs/plans/docs-writing-style-guide.md`](../../../docs/plans/docs-writing-style-guide.md).
Read it before writing. **Where it conflicts with Google, the house guide wins**;
everywhere else, Google applies.

| Topic | Google says | This repo does |
| --- | --- | --- |
| Person | second person, avoid "we" | "you" for the reader's actions, "we"/"let's" for the shared walkthrough |
| Task headings | bare infinitive ("Create a ...") | gerunds ("Creating a ..."); imperative only for numbered walkthrough steps |
| Capital after a colon in a heading | lowercase | capital ("Step 1: Profile the time limit") |
| Em dashes | no surrounding spaces | spaced `—` or `--`, rationed; prefer rewriting the sentence |
| Tense | present | present, but walkthroughs may narrate ahead ("we'll build") |
| Opinions and a bold **Please** | avoid | allowed and rationed: "we **strongly** recommend" is the house steering device |

## Setup (once per machine)

```bash
mise install          # Vale is pinned in mise.toml's [tools]; needs mise >= 2025.8.0
vale sync             # fetches the packages in .vale.ini into the gitignored .vale/styles/
```

`mise run docs:lint` runs `vale sync` itself, so a package bump in `.vale.ini`
reaches you on the next lint.

If the Vale Claude Code plugin is installed, its `PostToolUse` hook lints every
`.md` you `Edit`/`Write` and hands **errors** back automatically. That hook is
a floor, not the review. Warnings and suggestions only appear when you run Vale
yourself.

## Workflow

1. **Write** in the house voice. Use the macros (`{{rbx}}`, `{{testlib}}`),
   never the bare names.
2. **Lint the files you touched**, at every level:
   `mise run docs:lint docs/path/page.md` (or `vale docs/path/page.md`).
   - **Errors:** fix all of them in lines you wrote or edited.
   - **Warnings:** fix them, or be ready to justify each one to the reviewer.
     Most `ai-tells.*` warnings are AI-prose heuristics that also fire on
     human prose here. Treat a cluster of them in one paragraph as a sign to
     rewrite it, and a lone hit as a judgment call. Slop and ai-tells overlap,
     so one phrase often draws a pair of alerts. Fix the phrase once.
   - **Suggestions:** read them; `Google.Passive`, `Google.Will`, `rbx.Filler`
     and `rbx.EmDash` are judgment calls, not orders.
3. **Dispatch the `docs-style-reviewer` agent** (Agent tool,
   `subagent_type: docs-style-reviewer`) with the changed file paths and one
   line on what the change is for. Do this for every docs change, however small.
   Agent types load at session start, so if `docs-style-reviewer` is not
   listed, dispatch `general-purpose` instead and tell it to read
   `.claude/agents/docs-style-reviewer.md` and act as that agent.
4. **Address every BLOCKER and MAJOR finding**, then re-run step 2. Re-dispatch
   the reviewer if you changed more than wording.
5. Report the final Vale counts for the touched files, and the reviewer's
   verdict, in your summary or PR body.

When the ask is **only a review**, run steps 2-3 on the target files and relay
the findings. Don't fix anything you weren't asked to.

## Tuning Vale

- A correct project term flagged by `Vale.Spelling`: add it to
  `.vale/styles/config/vocabularies/rbx/accept.txt` (regex; use `(?i)` when
  it can start a sentence). **Never** add `rbx` or `testlib`: vocabulary terms
  are exempt from every rule, which would switch off `rbx.Macros`.
- A rule that is wrong for this project: change `.vale.ini` with a comment
  citing the house-guide section that overrides it. Never edit a synced style
  (`Google`, `Slop`, `STE`, `ai-tells` under `.vale/styles/`).
- Packages are pinned by release URL in `.vale.ini`. When you bump
  `vale-ai-tells`, regenerate its override block. Every ai-tells rule that
  fires on the current `docs/` is set to `warning`, and the rest stay
  `error`. Keep the `NO` list as is unless the house guide changed.
- Never raise `MinAlertLevel`, and never disable a rule to clear an alert you
  produced.

## Known blind spots

Vale does **not** read these, so the reviewer must:

- Admonitions with a **blank line** after `!!! type` (they parse as indented
  code). Prefer starting the body on the next line, which Vale does lint.
- Generated pages (`docs/setters/reference/cli.md`, `docs/schemas/`) -- fix
  the command help or the model docstring instead.
- `docs/plans/` -- the contributor archive is excluded from linting.

## Common mistakes

| Mistake | Fix |
| --- | --- |
| Treating a clean hook as a clean page | The hook reports errors only; run `vale` for warnings |
| Skipping the reviewer for a "one-line" docs fix | One-liners still forward-reference undefined concepts; always dispatch it |
| Rewriting a whole page to clear pre-existing alerts | Fix what you touched; mention the backlog, don't expand scope |
| "Fixing" `we`/`let's` because Google says so | House voice wins; see the table above |
