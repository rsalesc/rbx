<!-- rbx documentation writing-style guide. -->
<!-- Reverse-engineered from the maintainer's own docs; follow this voice when writing or restyling any rbx documentation. -->
<!-- Wrapped in {% raw %} so mkdocs-macros leaves the {{...}} macro examples literal. -->

{% raw %}
# Author Style Guide — the rbx maintainer's voice

A reverse-engineered, prescriptive guide for writing rbx documentation prose that is indistinguishable from the maintainer's own. Every rule below is grounded in a quoted example from a page the maintainer wrote (excludes `statements/`, `reference/`, and `plans/`, which are AI-written or generated).

There are two registers to master. Both share the same voice; they differ in structure:

- **Feature-guide register** (concept pages like `variables.md`, `testset/generators.md`, `grading/checkers.md`): opens with a definition, motivates with a pain point, teaches the happy path then edge cases.
- **Walkthrough register** (narrative tutorials like `custom-checker-walkthrough.md`, `packaging-walkthrough.md`): continues a running story, moves step by step, ends with "Next steps" grid cards.

---

## 1. Voice & person

**Use "we"/"let's" for the shared journey, "you" for the reader's actions.** The maintainer writes as a guide walking *beside* the reader, constantly switching between "we'll do this together" and "you can do this."

- Shared-journey "we": *"We'll focus on how to create a problem from a pre-initialized preset, how to write its main components and how to test it."* (`first-steps.md`)
- *"In the sections below, we'll go through each of them."* (`running/index.md`)
- Reader-action "you": *"You can start creating a new problem from a pre-initialized preset by running `rbx create`."* (`first-steps.md`)

**"Let's" is the signature section-opener** — it invites the reader into the next action.

- *"Let's skip the configuration of the problem for a second, and just build and run it."* (`first-steps.md`)
- *"Let's write a validator to verify that our testset does not violate these constraints."* (`verification/validators.md`)
- *"Let's mutate our problem into one that doesn't, and see why we need a **checker**."* (`custom-checker-walkthrough.md`)

**Formality: low-to-medium, warm, conversational.** Contractions everywhere (`we'll`, `let's`, `you've`, `it's`, `don't`). Occasional formal "one" for generic statements: *"One can also set the verification level to be used when running the solutions."* (`running/index.md`)

**Strongly opinionated — the maintainer makes judgments and says so, sometimes bluntly.**

- *"We **strongly** recommend using {{testlib}} checkers for your problems, as they are battle-tested"* (`grading/checkers.md`)
- *"**Please**, use {{testlib}} checkers. {{rbx}} is seriously opinionated about this, and although it will most of the times work with non-{{testlib}} checkers, no guarantees are given."* (`grading/checkers.md`)
- *"This is the optional part that we **highly recommend** following."* (`packaging/polygon.md`)
- The word "recommend"/"recommended" recurs as the maintainer's way of steering: *"the two most recommended approaches"* (`testset/index.md`), *"Setting a larger value is usually the recommended approach"* (`verification/index.md`).

**Warmth and light dryness/humor — present but rationed.** It shows up in empathy for the reader's past pain and in the occasional playful phrase, never as jokey filler.

- Empathy: *"Think of all the frustration you had in your life with presentation errors and problems that asked you to print the 'minimum lexicographically path in a graph' just to force the solution to be unique. {{testlib}} checkers are here to solve that."* (`grading/checkers.md`)
- Playful section titles: *"Jngen, the jack of all trades"* and *"Tgen, the modern alternative"* (`testset/generators.md`)
- Playful coinages: *"{{rbx}} will make sure to create a symlink ... automagically for you."* (`presets/index.md`); *"In the LLM era, visualizers are particularly easy to be generated."* (`testset/visualizers.md`)
- Rhetorical "right?" to bond with the reader: *"That is exactly what our model solution already does, right?"* and *"it's hard to get that wrong, right?"* (`grading/checkers.md`)

---

## 2. Sentence & paragraph rhythm

**Sentences are medium-length and flowing**, frequently multi-clause with commas, but broken up by short punchy ones for emphasis. Not terse, not academic.

- Flowing: *"The command will run all selected solutions (or all declared solutions if none are selected) on all testcases, providing for each of them the solution outcome, and for the whole testset the timing and memory usage."* (`running/index.md`)
- Punchy follow-up: *"(2) is the way to go here, as it ensures that the participant's solution is at least as good as the jury's solution."* (`grading/checkers.md`)

**Paragraphs are short — typically 1–3 sentences.** One-sentence paragraphs are common, used as transitions or emphasis beats.

- *"Of course, we have to add tests to these groups. The rest of this section will be devoted to this topic."* (`testset/index.md`)
- *"Now, let's finally check that the graph is connected."* (`verification/validators.md`) — a lone one-sentence paragraph that pivots the narrative.

**Rhythm pattern:** a lead-in sentence → a code block or table → a short explanatory sentence or two after. Prose and code alternate in small beats; the maintainer rarely writes more than a few sentences without a snippet, list, or admonition.

---

## 3. How to open a page and a section

**Concept pages open definition-first, in a recognizable parallel formula**, then immediately motivate with a pain point.

- The recurring "X is a concept introduced by testlib to ..." template:
  - *"Validator is a concept introduced by {{testlib}} to verify whether the tests you generate for a problem are in the format you really expect."* (`verification/validators.md`)
  - *"Checker is a concept introduced by {{testlib}} to verify whether the participant's solution is correct for a given testcase."* (`grading/checkers.md`)
  - *"Interactor is a concept introduced by {{testlib}} to play the role of an agent that communicates with the participant's solution..."* (`grading/interactors.md`)
- Other definition-first openers: *"Variables are a way to define the constraints of your problem in a single place and reference them everywhere else."* (`variables.md`); *"Stress testing is a technique used to verify the correctness of a solution by generating random inputs..."* (`stress-testing.md`); *"Generators are a {{testlib}} concept. They are programs that produce a testcase for a problem."* (`testset/generators.md`)

**The definition is followed by a "why should you care" motivation**, often invoking a concrete frustration.

- *"The motivation for having variables are simple: imagine you've decided to change the constraints of your problem. Without variables, you'd have to change this constraint in the validator ... It's super easy to forget about these changes, increasing the likelihood of introducing a disastrous bug in your problem."* (`variables.md`)
- *"Think of the frustrating scenarios where you've written in the statement that the graph should be connected ... but there was a test in your testset that contradicted this. Even experienced setters make these mistakes..."* (`verification/validators.md`)

**Concept pages frequently establish a persistent "Motivational problem"** that the whole page then teaches against. This is a named `## Motivational problem` section.

- *"For the next sections, let's assume we have a problem that asks you to find a path between two vertices 1 and `N` in a **connected** graph..."* (`verification/validators.md`, reused verbatim as the through-line in `grading/checkers.md`)

**Walkthrough pages open with a one-line scope statement + a prerequisite pointer.**

- *"This walkthrough covers the full process of packaging a problem for a judge system, from profiling time limits all the way to uploading the final package."* (`packaging-walkthrough.md`)
- *"!!! note "Prerequisite" — This page continues the story from [First steps](first-steps.md). If you haven't gone through it yet, start there — we pick up right where it left off."* (`custom-checker-walkthrough.md`)

**Sections (`##`/`###`) usually open with either a "Let's" invitation or a plain declarative definition of the thing the section covers**, then get to a command or snippet fast.

- *"Testcase globbing is the simplest way of adding manually defined tests to a group."* (`testset/index.md`)

---

## 4. Heading conventions

**Sentence case, always.** Never Title Case for normal section headings.

- *"Defining variables"*, *"Using variables"* (`variables.md`); *"Writing a generator"*, *"Idempotency"* (`testset/generators.md`); *"Building the testset"*, *"Visualizing the testset"* (`testset/index.md`); *"Running solutions"*, *"Sharing a report"* (`running/index.md`).

**Gerund/noun-phrase headings dominate** ("Defining …", "Using …", "Writing …", "Running …", "Building …").

**Questions are used deliberately as headings** when the section answers a reader's likely question. They also appear as `### What about …?` mid-page pivots.

- *"## Do I need to write a checker?"* (`grading/interactors.md`)
- *"### What about the outputs?"* and *"#### What about interactive problems?"* (`testset/index.md`)
- *"## Why a preset?"* (`presets/index.md`)

**Walkthrough step headings are imperative and numbered**, and may carry an explicit anchor.

- *"## Step 1: Profile the time limit {: #profiling }"*, *"### Create a profile for BOCA"*, *"### Choose a strategy"* (`packaging-walkthrough.md`)

**Spell out "and" — do not use "&"** in headings or prose (no `&` observed anywhere in body text).

**Depth: mostly `##` and `###`.** `####` and even `#####` appear only in dense reference-heavy sections (`presets/index.md` uses `##### Flag-based symlink tracking`; `testset/index.md` uses `##### Manual tests (@input)`). Keep nesting shallow unless the material genuinely demands it.

**Packaging pages use a "Category: Target" title form:** *"# Packaging: Polygon"*, *"# Packaging: BOCA"* (`packaging/polygon.md`, `packaging/boca.md`).

**Recurring named sections to reuse:** `## Motivational problem`, `## Writing a <thing>`, `## Running <thing>`, `## Next steps` (the closing grid-card block on walkthroughs).

---

## 5. Admonitions

Admonitions are used **heavily and purposefully** — expect one every few paragraphs on a dense page. All five types appear: `tip`, `note`, `warning`, `danger`, `info`.

**Map of when each is used:**

- **`!!! tip`** — the "you can always take this shortcut" aside, and reassurances. *"!!! tip — You can always manually call a validator on a custom input with `rbx validate`."* (`verification/validators.md`); *"!!! info — You can always call your generator manually with: ..."* (`testset/generators.md`, note `info` used for the same purpose).
- **`!!! note`** — clarifications and caveats that aren't dangerous. *"!!! note — A problem can have multiple generators. This one is just an example."* (`first-steps.md`)
- **`!!! warning`** — gotchas that will bite you. *"!!! warning "Test ordering" — The order of the tests will be the lexicographical order of the files. Be careful to not define tests as `1.in`, `2.in`, ..."* (`testset/index.md`)
- **`!!! danger`** — strong opinions, security, and "this will break" territory. *"!!! danger "Non-{{testlib}} checkers" — **Please**, use {{testlib}} checkers."* (`grading/checkers.md`); *"!!! danger "Security" — ... only run code written by authors you trust!"* (`grading/index.md`)
- **`!!! info`** — pointers to fuller references. *"!!! info — For a complete reference on profiling, formulas, and profiles, see the [Profiling](/setters/profiling) guide."* (`packaging-walkthrough.md`)

**Title them when the title adds signal** — a short quoted title is common and idiomatic: `"Introducing randomness"` (`testset/generators.md`), `"Test ordering"` (`testset/index.md`), `"Prerequisite"` (`custom-checker-walkthrough.md`), `"Under development"` (`testset/generators.md`), `"When you *do* need the model answer"` (`custom-checker-walkthrough.md`). Untitled admonitions are equally fine for short asides.

**Tone inside admonitions is the same conversational voice**, with the same bold emphasis and contractions — not a stiffer "official warning" tone. Admonitions can nest inside code annotations (see §6).

---

## 6. Code examples

**Introduce a snippet with a lead-in sentence ending in a colon, or a "Below, …" framing.** Rarely a bare code block with no setup.

- *"Let's write a simple validator that checks the input format above."* → block (`verification/validators.md`)
- *"Below, an example of a very simple, ICPC-style test plan: just two groups..."* → block (`testset/index.md`)
- *"The `vars` sections should look like this:"* → block (`first-steps.md`)

**Use `title=` on fences to name the file being shown** — this is pervasive: ` ```yaml title="problem.rbx.yml" `, ` ```cpp title="validator.cpp" ` (`variables.md`, `grading/index.md`, `verification/validators.md`). Also `title=".env"` for env files (`packaging-walkthrough.md`).

**Use code annotations `# (1)!` with a numbered explanation list below the block.** This is the maintainer's primary explanatory device for code — the annotations often carry the real teaching, and can be multi-paragraph with their own nested admonitions and even nested code blocks.

- The `first-steps.md` directory tree uses `# (1)!` through `# (8)!` with rich explanations, one of which contains a nested ` ```` ` block and a `!!! note`.
- The annotation explanations read like the prose: *"`getVar` reads a variable defined in `problem.rbx.yaml` that is accessible in the validator. It allows you to change the constraints of the problem, and instantly replicate the change in validators and statements."* (`first-steps.md`)

**Use tabbed `=== "..."` blocks to show parallel files side by side** — almost always pairing an asset with its `problem.rbx.yml` wiring, or showing "static vs dynamic" alternatives.

- *`=== "validator.cpp"` / `=== "problem.rbx.yml"`* (`verification/validators.md`)
- *`=== "tests/testplan.txt (static)"` / `=== "tests/testplan.py (dynamic)"`* (`first-steps.md`)

**Use `linenums="1"` and `hl_lines="..."` to focus attention** on the lines that changed between iterations: ` ```cpp title="validator.cpp" hl_lines="4-29 41 50-51 54" linenums="1" ` (`verification/validators.md`).

**CLI demos:**
- Static terminal blocks use `<!--termynal-->` above a bash fence: (`first-steps.md`, `intro/installation.md`).
- Recorded casts use the macro `{{ asciinema("<id>") }}`, sometimes with a speed arg: `{{ asciinema("TOoswpIL4mRKfstnDCkKLw2Xn", speed=1.5) }}` (`stress-testing.md`). Placeholders/TODOs for unrecorded casts are left inline as HTML comments: `<!-- TODO(#437): record the rbx stress run ... -->` (`stress-testing-walkthrough.md`).
- `{.bash .no-copy}` marks non-copyable illustrative shell output (`first-steps.md`).

**Prose after a snippet restates what it does in plain language**, often starting with "Notice" or "The … above …":

- *"The generator above produces a testcase with `N` integers, each one between 1 and `MAX`, separated by spaces."* (`testset/generators.md`)

**Comment inside code the way you'd narrate it**, including inline asides: `int32_t ans = 0; // int32 overflows!!` (`first-steps.md`); `cout << 2 << " " << n - 1 << endl; // bug: 2 + (n - 1) = n + 1` (`custom-checker-walkthrough.md`).

---

## 7. Formatting idioms

**Bold** — for the load-bearing word in a sentence and for imperatives/warnings: *"This command **builds** all testcases and **executes** each solution against them"* (`first-steps.md`); *"add a second, deliberately buggy solution"* (`first-steps.md`); *"**strongly**"*, *"**Please**"*, *"**must**"*, *"the **exact** time limit"* (`packaging/boca.md`).

***Italics*** — three distinct jobs:
1. Introducing/naming a term: *"a `.txt` file (a _testplan_)"* (`first-steps.md`); *"(*aka* a testplan)"* (`testset/index.md`).
2. Emphasizing a concept word: *"verifies the *property*"* (`custom-checker-walkthrough.md`); *"compares the *sequence of words*"* (`grading/checkers.md`).
3. **The signature italic cross-reference line** placed at the top of a section — a recurring move: *"*If you haven't read the [Generators section](generators.md) yet, you should read it before proceeding.*"* (`testset/index.md`); *"*You can read more about {{testlib}} validators in the [Codeforces documentation](...).*"* (`verification/validators.md`).

**Inline `code`** — for absolutely everything technical: commands (`rbx run`), fields (`testcaseGlob`), filenames (`sols/main.cpp`), flags (`-v0`), functions (`getVar<>()`), outcomes (`WRONG_ANSWER`), directories (`build/tests`).

**Project macros — use them, never hardcode the names.** The tool is always `{{rbx}}`, and every named external gets its macro: `{{testlib}}`, `{{polygon}}`, `{{codeforces}}`, `{{boca}}`, `{{jngen}}`, `{{tgen}}`, `{{rbxTeX}}`/`{{rbxtex}}`, `{{icpcformat}}`, `{{YAML}}`, `{{Jinja2}}`, `{{repo}}`. Verdicts in prose use the colored tags: `{{tags.accepted}}` and `{{tags.wrong_answer}}` (`first-steps.md`, `custom-checker-walkthrough.md`).

**Em-dashes and parentheticals are frequent.** The maintainer uses `--` (double hyphen) as an em-dash constantly — *"a `.txt` file -- each of its lines is a generator call"* (`testset/index.md`); newer pages also use a real `—` — *"the solution's `stderr` is shown in its own colored section ... — handy for debugging"* (`running/index.md`). Either is acceptable; be consistent within a page. Parentheticals for quick clarifications: *"a TUI (terminal UI)"* (`first-steps.md`), *"(1-indexed)"* (`testset/generators.md`), *"(potentially)"* (`variables.md`).

**Contractions: always.** *"we'll"*, *"let's"*, *"don't"*, *"it's"*, *"you've"*.

**Emoji: functional only, never decorative in body prose.**
- In comparison tables: `:white_check_mark:`, `:x:`, `:warning:` (`packaging/index.md`).
- As inline good/bad markers when contrasting two approaches: *":warning: We could simply read the answer ..."* vs *":white_check_mark: We could compare the participant's path ..."* (`grading/checkers.md`).
- As fontawesome icons in grid cards (`:fontawesome-solid-rocket:`). Do **not** sprinkle 🎉/🚀-style emoji through sentences.

**Lists vs tables vs prose — deliberate choices:**
- **Grid tables** (`+---+`/`+===+` syntax) for reference comparisons: methods of adding tests (`testset/index.md`), outcomes (`grading/index.md`), built-in checkers (`grading/checkers.md`), supported formats (`packaging/index.md`), operators (`stress-testing.md`).
- **Pipe tables** for simpler enumerations: verification levels (`verification/index.md`), strategies (`packaging-walkthrough.md`), the interaction trace (`grading/interactors.md`).
- **Bulleted lists** for options, arguments, and pros/cons: the three checker files (`grading/checkers.md`), the "A few things to keep in mind" list (`running/index.md`).
- **Numbered lists** for genuine sequences: the "This command performs the following steps automatically" list (`packaging-walkthrough.md`).
- **Prose** for motivation, judgment, and connecting tissue.

**Closing "Next steps" grid cards** on walkthrough/narrative pages, using material's `<div class="grid cards" markdown>` with fontawesome icons and `[:octicons-arrow-right-24: Label](/path)` links (`first-steps.md`, `custom-checker-walkthrough.md`, `packaging-walkthrough.md`, `stress-testing-walkthrough.md`).

---

## 8. Signature phrases & transitions

Reach for these — they are the connective tissue that makes the voice recognizable:

- **"Let's …"** to open a section or step: *"Let's write a simple validator…"*, *"Let's change the problem to:"*, *"Let's first talk about variables."*
- **"Notice …" / "Notice how …" / "You can notice …"** to point at what matters: *"Notice we're super strict about spaces, end-of-lines and end-of-file here."* (`verification/validators.md`); *"Notice that we didn't have to touch `problem.rbx.yml`…"* (`first-steps.md`).
- **"Below, …" / "In the table below" / "the example below"** to hand off to a snippet or table.
- **"Of course, …"** as a conceding transition: *"Of course, we still have to check that the graph is connected, but let's do this in a minute."* (`verification/validators.md`).
- **"Think of …"** to invoke a scenario or analogy: *"Think of a code (in Python, or even in C++) that produces a testplan file as its output."* (`testset/index.md`).
- **"You can always …"** for escape-hatch tips: *"You can always manually call a validator…"* (`verification/validators.md`).
- **"In fact, …"** to add a reinforcing detail: *"In fact, a generator call is a valid generator expression."* (`stress-testing.md`).
- **"Last but not least, …"** for the final item: *"Of course, last but not least, we have to update the statement…"* (`first-steps.md`).
- **"Feel free to …"** for optional exploration: *"Feel free to explore the rest of the documentation on the sidebar…"* (`first-steps.md`).
- **"super"** as an intensifier: *"super easy to forget"*, *"super strict about spaces"*; and **"pretty straightforward"**: *"The syntax is pretty straightforward."* (`stress-testing.md`).
- **Rhetorical "right?"** to check understanding: *"…that our model solution already does, right?"* (`grading/checkers.md`).
- **Cross-reference sign-offs**: *"You can read more about … in the [X] section."*, *"To read more about variables, check the [Variables] section."*, *"see [Wall time limits](...)."* — nearly every section ends by pointing onward.
- **Reassurance**: *"You should not worry about this!"* (`grading/interactors.md`); *"no extra code needed."* (`custom-checker-walkthrough.md`).
- **Question-as-transition inside prose**: *"What about the outputs? Where they come from?"* (`testset/index.md`); *"Why is such a small range enough?"* (`stress-testing-walkthrough.md`) — the maintainer voices the reader's next question, then answers it.

---

## 9. Explanatory strategy

**Why before how.** Nearly every concept page leads with motivation (the pain of not having the feature) before mechanics — see the variables and validators openings in §3. The reader is told why they should care before being shown syntax.

**Introduce a concept before you rely on it.** Never drop a term or mechanism the reader hasn't met yet — not in a table column, an aside, or a code recap. Either define it in a phrase at first use (define *joining* before you show a "Joins?" column; say what a *document* is before listing `documents`), or defer it to the section that owns it with a forward link (*"how a template turns blocks into a rendered page is covered in [Template context]"*). Respect the reading order: an earlier page may *preview* a later concept, but only by naming it and pointing onward — never by dumping its mechanics (`\VAR{problem.blocks.legend}`, `params`, the namespaces) inline where the reader has no way to understand them yet.

**Happy path first, edge cases after.** `testset/index.md` teaches the simple testcase glob, *then* generator scripts, *then* an `#### Advanced testplan features` section (`@input`, `@copy`, `@testgroup`). `grading/checkers.md` does the *"### Output-only case"* first and the harder *"### Output + answer case"* second.

**Build iteratively on one running example, highlighting the delta.** The validator is written in three passes — first a hardcoded version, then *"Let's do the following modifications to our problem to make it safer:"* (switching to variables), then *"Now, let's finally check that the graph is connected."* — each pass shown with `hl_lines` marking exactly what changed (`verification/validators.md`).

**Contrast good vs bad approaches and explain *why*.** *"(1) is very dangerous for obvious reasons: what if the jury's solution is wrong? ... (2) is the way to go here, as it ensures that the participant's solution is at least as good as the jury's solution."* (`grading/checkers.md`) — options are laid out, then judged, with reasoning.

**Anticipate and voice the reader's next question.** *"Until now, we've just generated the inputs of our testcases. What about the outputs? Where they come from?"* (`testset/index.md`).

**Handle pitfalls inline and honestly**, in prose or a `warning`/`danger` admonition, and name the consequence: *"This is a dangerous practice, as it's super easy to forget to do so."* (`verification/validators.md`); *"Be careful when using `stderr` ... If you print too much into the `stderr`, your program might slow down."* (`testset/visualizers.md`).

**Push detail into code annotations, not prose walls.** When explaining a code sample, prefer `# (1)!` annotations that narrate specific lines over a paragraph re-describing the whole block (see §6).

**Be transparent about limitations and flakiness** rather than glossing: *"Quite often the Taskbook FTP will be down. It seems this endpoint is not very reliable anymore."* (`packaging/polygon.md`); *"A `version` of `latest` re-resolves the default-branch HEAD on every `rbx presets sync`, so it can drift over time."* (`presets/index.md`).

---

## 10. Page architecture (feature-guide register)

Every hand-written feature guide is built from the same skeleton. Follow it.

```
# <Feature>

<definition sentence>
<frustration paragraph: the concrete pain this feature removes>
<what we'll cover, in reading order>

## Motivational problem            <- one running example for the whole page
## <the happy path, 2-4 sections>  <- the 80% case, built up incrementally
## <extra feature>                 <- each optional capability, one ## each
## <extra feature>
## <pointer onward>
```

**The running example is the page's spine.** `verification/validators.md` opens
with "Motivational problem" (a connected-graph problem) and every snippet down
the page is that same problem, growing. `grading/checkers.md`,
`custom-checker-walkthrough.md` and `stress-testing.md` do the same. A page that
switches example between sections makes the reader re-orient each time.

Where a page can reuse *another* page's running example, it should. The
statement guide writes the statement for the very graph problem the validator
guide validated, so the reader watches one package come together across the
guide instead of meeting a new toy problem per page.

**Build the happy path up, don't lay it out flat.** The validator page shows a
validator with hard-coded bounds, then the same validator reading `vars`, then
the same validator checking connectivity, using `hl_lines` to point at what
moved. Three passes over one artifact teach more than one finished artifact.

### Extra features get their own `##`, at the end

This is the rule most easily broken and the most valuable. Anything that is not
part of the 80% path is a **dedicated section, below the happy path**, never a
parenthesis inside it.

Look at how the hand-written pages end:

| Page | Happy path | Dedicated extras |
| --- | --- | --- |
| `running/index.md` | running solutions on the testset | *Running on the judge itself*, *Sharing a report*, *Running tests with custom inputs* |
| `stress-testing.md` | defining and running a stress test | *Saving a stress test*, *Fuzzing inputs*, *Finding slowest tests*, *Other applications* |
| `verification/validators.md` | a testlib validator | *Using custom validators*, *Defining additional validators*, *Varying constraints per test group* |
| `presets/index.md` | creating and using a preset | *Libraries*, *The preset registry*, *Sharing a preset publicly*, *Sharing a preset privately* |

A reader on the happy path can stop at the first extra section and still have a
working mental model. A reader who came for one flag finds it in the table of
contents instead of by scanning prose. And when the feature grows a new flag,
there is an obvious place to put it.

Signs you are sprinkling instead of sectioning: a "note that you can also ..."
clause, a flag introduced mid-paragraph, or a second YAML key bolted onto a
snippet that was illustrating something else.

### Naming sections

Sentence case, and name the reader's action rather than the bare noun.
"Printing constraints from vars" over "Variables". "Sharing a report" over
"The share flag". Honest questions are also in register ("Why a preset?", "Why
rbxTeX"). Never Title Case, never "&".

## 11. Recordings

Every feature guide except the statements one had a cast before this guide was
written, and the pattern is consistent:

- **One cast per command worth watching**, placed immediately after the snippet
  that introduces the command, never as decoration.
- The prose says what the command does; the cast shows the output. Don't
  transcribe the terminal output into prose as well.
- A cast inside a `!!! tip` is the idiom for a side command the reader can reach
  for later, as the validators page does with `rbx validate`.
- Casts are generated artifacts. Add a fixture and a spec under `casts/`, and
  read `casts/README.md` first.

## 12. Document the contract, not the implementation

Write down the behaviour a setter can rely on. Reach for a specific number,
field name or internal step only when the reader has to *act* on it; otherwise
describe the guarantee and link to the reference or the schema, which are
generated and cannot drift.

The tell is a page that transcribes something the code owns. A hand-written
copy of a field list is correct on the day it is written and wrong on the day
someone adds a field, and a reader following a stale copy is worse off than one
who was told nothing and followed the link.

The precedent is the default timing formula. The profiling page does not spell
it out:

```markdown
​```text
{{ default_timing_formula() }}
​```
```

The macro reads `DEFAULT_TIMING_FORMULA` out of `rbx/box/environment.py` when
the docs are built, so the page cannot disagree with the tool. A test pins it
there.

Applied elsewhere, this is why the profiles page links to
[`LimitsProfile`](/schemas/LimitsProfile.json) rather than reproducing its
fields, and why it says a profile records where each group's number came from
without listing what that record contains. The same restraint applies to
anything marked *in development*: name it, say it is unstable, and stop.

What this does **not** license is vagueness about things the reader must type —
flags, file names, YAML keys and the values they take are the contract, and
they belong on the page in full.

## 13. Reconciling with the scaffold-docs prose rules

The `scaffold-docs` skill carries a Strunk-and-White prose rubric. It agrees
with this guide about cutting filler (*just*, *simply*, *actually*, *really*),
about banning hype adjectives (*powerful*, *seamless*, *effortless*), and about
never closing a section with a victory lap ("And that's it!", "Now you're ready
to ..."). Apply all of that.

Two of its rules bend to the house voice:

- **Opinions stay.** The rubric says "do not inject opinion"; this project's
  docs are openly opinionated, and "we strongly recommend" is the maintainer's
  main steering device. Keep it.
- **Em dashes are rationed, not banned.** The hand-written pages use them
  sparingly. Agent-written prose reaches for one every other sentence, which is
  the actual tell. When you find one, rewrite the sentence rather than swapping
  in a comma.

---

## 14. DO / DON'T checklist

**DO**
- DO open a concept page with a one-sentence definition, then a "why you should care" motivation grounded in a concrete frustration.
- DO introduce a concept before you use it — define a term at first use, or defer it (with a forward link) to the page that owns it. Never forward-reference a mechanism the reader hasn't met.
- DO reuse the *"X is a concept introduced by testlib to …"* formula for testlib-derived features.
- DO establish a single running "Motivational problem" and teach the whole page against it.
- DO give every optional capability its own `##` section, below the happy path, instead of sprinkling it through the main narrative (see section 10).
- DO add a cast for any command worth watching, right after the snippet that introduces it.
- DO write section headings in **sentence case**, favoring gerunds ("Defining …", "Writing …") and honest questions ("Why a preset?", "What about the outputs?").
- DO address the reader as **"you"** for their actions and use **"let's"/"we'll"** for the shared walkthrough.
- DO be openly opinionated — "we strongly recommend", "we highly recommend", and occasionally a blunt "**Please**".
- DO introduce every snippet with a lead-in sentence (usually ending in a colon) and follow it with a plain-language "The … above …" recap.
- DO put `title="problem.rbx.yml"` on fences, pair assets with their YAML wiring via `=== "..."` tabs, and use `hl_lines`/`linenums` to spotlight changes.
- DO teach code via `# (1)!` annotations, and let those annotations get rich (nested admonitions/snippets are fine).
- DO use admonitions liberally and match the type to intent (`tip` for shortcuts, `danger` for opinions/security, `info` for "see the full reference").
- DO scatter "Notice …", "Below, …", "Of course, …", "In fact, …", "You can always …" as connective tissue.
- DO point onward at the end of every section ("Read more about … in the [X] section.") and close narrative pages with "Next steps" grid cards.
- DO use the project macros (`{{rbx}}`, `{{testlib}}`, `{{tags.accepted}}`, …) instead of hardcoding names.
- DO be candid about limitations, flakiness, and pitfalls, naming the consequence.
- DO document the contract and link to the generated reference or schema for exhaustive field lists (see section 12) — but spell out in full anything the reader has to type.

**DON'T**
- DON'T use Title Case headings, and DON'T write "&" — spell out "and".
- DON'T open cold with mechanics/syntax before motivating the feature.
- DON'T drop a term or mechanism the reader hasn't met — a "Joins?" column before *joining* is defined, `\VAR{problem.blocks.legend}` before templates exist, `params` before it's introduced. Define it first, or defer it to the page that owns it.
- DON'T drop a bare code block with no lead-in and no follow-up.
- DON'T write long academic paragraphs — keep them to 1–3 sentences and let one-sentence paragraphs breathe.
- DON'T sprinkle decorative emoji through sentences (emoji are for tables, good/bad markers, and card icons only).
- DON'T stay neutral when the maintainer would have an opinion — take a side and justify it.
- DON'T over-nest headings; stay at `##`/`###` unless the density truly warrants `####`+.
- DON'T explain a whole code block in prose when annotations can carry it.
- DON'T write "utilize/leverage/in order to"-style corporate register; DO say "use", "to", and use contractions.
- DON'T hide caveats — surface them in a `warning`/`danger` box or an honest sentence.
- DON'T transcribe what the code owns — a hand-copied field list, an internal sequence of steps, or a default value the tool can render. It is correct the day you write it and wrong the day someone changes it.

---

## Three "in their voice" micro-samples (neutral topics)

**Sample A — a concept page opening (feature-guide register):**

> # Snapshots
>
> A snapshot is a frozen copy of your package at a given point in time, that you can restore later.
>
> The motivation is simple: imagine you've spent an afternoon reworking your testset, only to realize the old one was actually better. Without snapshots, you'd be digging through your shell history trying to undo everything by hand. It's super easy to lose work this way. Let's see how {{rbx}} lets you avoid that.

**Sample B — a "shortcut" tip plus a snippet lead-in (feature-guide register):**

> You can save a snapshot at any time by giving it a name:
>
> ```bash
> rbx snapshot save before-rework
> ```
>
> Notice the name is just a label — you can have as many as you like. Below, we restore it just as easily:
>
> ```bash
> rbx snapshot restore before-rework
> ```
>
> !!! tip
>     You can always list every snapshot you've taken with `rbx snapshot ls`, so you don't have to remember the exact name.

**Sample C — a walkthrough step with an honest caveat (walkthrough register):**

> ## Step 2: Restore on another machine
>
> Snapshots live inside your package, so once you've pushed the repository, you can restore from any machine. Clone the contest, and run:
>
> ```bash
> rbx snapshot restore before-rework
> ```
>
> !!! warning
>     Restoring **overwrites** your current working files. If you have uncommitted changes you care about, take a fresh snapshot first — otherwise they're gone. {{rbx}} won't ask twice.

{% endraw %}
