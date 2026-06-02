# Environment

An environment file is a YAML configuration file that describes the environment in which {{rbx}} will execute
your code.

The [`Environment`][rbx.box.environment.Environment] class is used to describe the environment in which the code will be executed. You can follow the schema of this class to figure out everything you can
configure in the environment file, but here we'll describe the most common fields.

## Compilation configuration

You can define a few default settings for compilation by using the `defaultCompilation` field.

You can look at the [`CompilationConfig`][rbx.box.environment.CompilationConfig] class for more details of
what you can do, but here's an example with a few useful settings:

```yaml
defaultCompilation:
  # Defines a few default limits when compiling in the sandbox.
  sandbox:
    timeLimit: 10000 # 10 seconds
    wallTimeLimit: 10000 # 20 seconds
    memoryLimit: 1024 # 1gb
```

Usually, the default values here are enough, but you can customize this for your needs. For instance,
if you have a very slow computer at hand, you might want to increase the limits to ensure the compilers
have the time to do their job.

## Default execution configuration

You can establish similar limits for code execution by using the `defaultExecution` field, by using the
[`ExecutionConfig`][rbx.box.environment.ExecutionConfig] class.

```yaml
defaultExecution:
  # Defines a few default limits when running programs in the sandbox.
  sandbox:
    timeLimit: 10000 # 10 seconds
    wallTimeLimit: 10000 # 20 seconds
    memoryLimit: 1024 # 1gb
```

Notice these limits are language agnostic, and problem agnostic. This means you should set this to a
value larger than any limit you expect for any problem. This is mostly used to ensure programs that
eat too much memory or take too long to finish, but don't have limits applied to them, don't hang forever
or crash your system. Examples are checkers, validators, etc.

## Languages

The `languages` field is used to define the languages supported by the environment. This is
a list of [`EnvironmentLanguage`][rbx.box.environment.EnvironmentLanguage] objects, which you can
look at the schema for more details.

Here's an example of a language definition:

```yaml
languages:
  - name: "cpp" # (1)!
    readableName: "C++17" # (2)!
    extension: "cpp" # (3)!
    compilation: # (4)!
      commands:
        - "g++ -std=c++20 -O2 -o {executable} {compilable}"
    execution: # (5)!
      command: "./{executable}"
    fileMapping: # (6)!
      compilable: "compilable.cpp"
```

1. The `name` field is the name of the language, which will be used to identify the language when
   explicitly specifying the language of a solution or other code item in your packages.
2. The `readableName` field is the name of the language as it will be displayed to you.
3. The `extension` field identifies the extension of files that will be automatically inferred
   to have been written in this language.
4. The `compilation` field is a [`CompilationConfig`][rbx.box.environment.CompilationConfig] object where
   you can specify how code in this language should be compiled. Notice the use of the `{executable}` and `{compilable}` placeholders.
5. The `execution` field is an [`ExecutionConfig`][rbx.box.environment.ExecutionConfig] object where
   you can specify how code in this language should be executed.
6. The `fileMapping` field is a [`FileMapping`][rbx.box.environment.FileMapping] object where
   you can specify how files should be named when copied into the sandbox. Notice you can refer to these
   files by using the `{file}` placeholder in the `compilation` and `execution` fields.

## Linters

Each language can configure built-in linters that {{rbx}} runs during the
compilation phase. Linters analyze the raw source of your code items
(generators, validators, solutions, checkers, etc.) and surface warnings or
errors. Warnings are routed to the warning stack; errors abort the build.

Add linters to a language with the `linters` field. There are two forms:

```yaml
languages:
  - name: "cpp"
    extension: "cpp"
    execution:
      command: "./{executable}"
    linters:
      - testlib                                       # shorthand form
      - name: testlib                                 # full form
        applies_to: [generators]                      # restrict to asset kinds
```

- The **shorthand form** is just the linter name; it applies to every asset
  kind the linter supports.
- The **full form** is an object with `name` and an optional `applies_to`
  list. `applies_to` restricts the linter to specific asset kinds. When it is
  omitted (or `null`), the linter applies to all kinds.

The valid `applies_to` tokens are the asset kinds: `generator`, `validator`,
`solution`, `checker`, `interactor`, and `visualizer`. Plural spellings
(`generators`, `solutions`, ...) are also accepted.

The effective scope for a linter on a given asset is the intersection of the
linter's own supported kinds and the `applies_to` you configure.

### Available linters

- `testlib` (C++, generators): lints testlib/tgen/jngen-based generators. Its
  current check warns when a function call passes two or more arguments that
  each contain a side-effecting call (e.g. `f(rnd.next(), rnd.next())`). C++
  leaves argument evaluation order unspecified, so such calls can produce
  different results across compilers.

### Suppressing a linter in a file

If a linter flags something you intend to keep, you can disable it for an entire
file with a comment directive of the form `<linter-name>-linter: disable`. For
the `testlib` linter:

```cpp
// testlib-linter: disable
```

The directive must appear in a comment (a `//` or `#` comment marker). It
disables only that linter; other linters configured for the language still run.

## File mapping

The `fileMapping` field is a [`FileMapping`][rbx.box.environment.FileMapping] object where
you can specify how files should be named when copied into the sandbox.

Notice you can refer to these files by using the `{file}` placeholder in the `compilation` and `execution` fields when configuring new
languages.

Here's an example of a file mapping for the Java language, and how you would
consume them in the `compilation` and `execution` fields:

```yaml
languages:
  - name: "java"
    readableName: "Java"
    extension: "java"
    compilation:
      commands:
        - "javac -Xlint -encoding UTF-8 {compilable}"
        - "jar cvf {executable} @glob:*.class"
    execution:
      command:
        "java -Xss100m -Xmx{{memory}}m -Xms{{initialMemory}}m -cp {executable}
        Main"
    fileMapping:
      compilable: "Main.java"
      executable: "Main.jar"
```

Notice how we use the `{compilable}` and `{executable}` placeholders in the `compilation` and `execution` fields,
and name them appropriately in the `fileMapping` field.

## Command variables

Also, notice you have a few variables that are available to you in the `compilation` and `execution` fields.

- `{compilable}`: The path to the file that should be compiled.
- `{executable}`: The path to the file that should be executed.
- `{stdin}`: The path to the file that should be used as standard input.
- `{stdout}`: The path to the file that should be used as standard output.
- `{stderr}`: The path to the file that should be used as standard error.
- `{memory}`: The memory limit for the sandbox.
- `{initialMemory}`: The initial memory for the sandbox.
- `{javaClass}`: The name of the Java class to be executed.

And you also have available to you a `@glob:...` command that is expanded into a list of files that match the glob pattern. This is particularly useful for languages that need multiple files to be compiled or executed (such as Java in the example above).

## Timing estimation

Last but not least, you can configure a timing formula to be used when estimating time limits after running
`rbx time` or `rbx run -t`.

By default, the formula is `step_up(max(fastest * 3, slowest * 1.5), 100)`. The following variables/functions are available to you:

- `fastest`: The time of the fastest solution among all AC solutions.
- `slowest`: The time of the slowest solution among all AC solutions.
- `step_up(value, step)`: Returns the value rounded up to the nearest multiple of `step`.
- `step_down(value, step)`: Returns the value rounded down to the nearest multiple of `step`.
- `max(a, b)`: Returns the maximum of `a` and `b`.
- `min(a, b)`: Returns the minimum of `a` and `b`.

You might specify a different formula by using the `timing` field:

```yaml
timing:
  formula: "step_up(max(fastest * 2, slowest * 1.5), 100)"
```

### Language groups

By default, the time limit is estimated once from the pooled timings of all accepted
solutions and applied to every language. With `timing.groups` you can instead estimate a
separate time limit per group of languages, which is useful when languages with very
different performance characteristics (e.g. compiled vs. interpreted) should not share a
single limit.

```yaml
timing:
  formula: "step_up(max(fastest * 3, slowest * 1.5), 100)"
  groups:
    - languages: [c, cpp]
    - languages: [java, kotlin]
      whenEmpty:          # used only when this group has no solutions
        relativeTo: cpp   # any language; resolves to the group containing it
        multiplier: 2.0   # omit relativeTo to multiply the base estimate
    - languages: [python]
```

Semantics:

- Groups are **disjoint**. Any language not listed in any group is left **unbucketed**
  and joins a single shared **leftover pool**: the pool's accepted-solution timings are
  estimated together, so an unrepresented language inherits a represented sibling's limit
  instead of silently falling back to the base time limit. If the whole pool has no
  solutions it DEFAULTs to the base limit (with a loud warning), like any other empty group.
- During estimation, the accepted-solution timings are pooled **per group**, and each
  group that has at least one solution gets its own estimated time limit from the formula.
- `whenEmpty` is **optional** and is only used when a group has **no** solutions. It sets
  the group's time limit to `multiplier ×` the time limit of the group containing
  `relativeTo` (or `multiplier ×` the base estimate when `relativeTo` is omitted).
  `multiplier` must be `> 0`.
- A group that is empty and has no `whenEmpty` falls back to the base time limit, with a
  **loud warning** (source `DEFAULTED`).

The resolved per-language limits are written into the existing `.limits/{profile}.yml`
`modifiers`, so nothing else in the pipeline changes; the chosen grouping is also stored as
presentation-only metadata under a `groups:` key in that profile.

`rbx time` is **interactive**: it shows every environment language and lets you place each
one into a numbered group (`1`–`9`), make it a **singleton** `[X]` (its own bucket, via
`space`/`tab`), or leave it **unbucketed** `[ ]` (the default — joins the leftover pool).
The picker is prepopulated from `env.rbx.yml` (languages in an env group keep their group
number; everything else starts unbucketed). Press `Enter` to confirm or `q` to cancel.
Pass `--auto` to skip the prompt and use the env groups as-is. After `rbx time` finishes (and again at the end of
`rbx package boca`), a per-group table is printed showing the **Languages**, **Solutions**,
**Time Limit**, and **Source** (estimated / `×N of <lang>` / `DEFAULTED`) for each group,
with `DEFAULTED` rows highlighted. The **leftover** group is listed **first**, marked with a
leading asterisk (`*`) on its languages and explained in a footer beneath the table.

!!! note
    The shipped default preset groups `python` on its own and `java`/`kotlin` together, while
    leaving `c`/`cpp` ungrouped (the leftover pool). Both groups fall back relative to `cpp`
    when they have no solutions: `python` at `3×` and `java`/`kotlin` at `2×` the C++ limit.

## Wall time limits

Solutions are also bounded by a **wall (real) time** limit, in addition to the
CPU time limit. Slow languages (Java, Kotlin, Python) can spend significant
wall-clock time on JVM/interpreter startup before doing any work, so a wall
limit that is too tight produces spurious time-limit verdicts.

{{rbx}} computes the wall time limit from the CPU time limit with a configurable
`a * x + b` formula, where `x` is the **effective per-language CPU time limit**
(after any per-language modifiers and double-TL expansion):

- `wallTimeMultiplier` (`a`) -- multiplier applied to the CPU time limit. Must be
  `>= 1.0` (the wall limit can never be tighter than the CPU limit). Defaults to `2.0`.
- `wallTimeIncrement` (`b`) -- extra wall time, in **milliseconds**, added on top.
  Must be `>= 0`. Defaults to `0`.

Configure the environment-wide defaults under the `timing` field:

```yaml
timing:
  formula: "step_up(max(fastest * 3, slowest * 1.5), 100)"
  wallTimeMultiplier: 2.0
  wallTimeIncrement: 1000   # +1s of wall headroom for every solution
```

You can override either coefficient for a specific language using that
language's `timing` field. Unspecified coefficients fall back to the
environment-wide defaults:

```yaml
languages:
  - name: "java"
    # ...
    timing:
      wallTimeIncrement: 3000   # JVM startup headroom; multiplier inherited
```

The same formula and coefficients are used both when judging locally and when
packaging for BOCA, so the wall time a solution gets is consistent across both.

!!! note
    The shipped default preset sets `wallTimeMultiplier: 2.0` and
    `wallTimeIncrement: 1000`, with larger increments for slow languages
    (`py: 2000`, `java`/`kt: 3000`).

