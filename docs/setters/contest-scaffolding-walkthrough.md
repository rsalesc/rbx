# Scaffolding a contest

This walkthrough covers how a contest package comes together: creating it, filling it with
problems -- new ones and ones you already have -- and checking that everything is wired up
before the real work starts.

!!! note "Prerequisite"
    This page opens the **Delivering a contest** track, written for the person assembling
    the whole event rather than a single problem. You don't need to have finished
    [First steps](/setters/first-steps), but we'll reuse the problem it builds near the
    end, so it helps to have it around.

Until now, every command in these docs has run inside a single problem. A contest is the
folder that sits one level above: it remembers which problems take part, in which order,
under which letter, and it owns the statement chrome they all share.

## Creating the contest

Let's create one:

```bash
rbx contest create --path contests/summer-cup
```

If you leave `--path` out, {{rbx}} asks for it. The last component of the path is the
folder it creates, and everything from here on happens inside it.

There's a second way in. `rbx contest init` scaffolds a contest **into the directory
you're already standing in**, instead of creating a new one:

```bash
mkdir summer-cup && cd summer-cup
rbx contest init
```

Use `create` when you're starting from nothing, and `init` when the folder already exists
-- a repository you've just cloned, or a directory your organization's layout obliges you
to keep. Running `create` on a directory that already exists works too, but it asks you to
confirm first, since it's about to write into someone else's folder.

!!! info
    Both commands take `--preset`, and `create` also takes `--variant`. Omit them and
    {{rbx}} uses the active preset, falling back to the default one. Presets are how you
    make every contest you scaffold look like *your* contests -- see the
    [Presets](/setters/presets) guide.

## Reading the contest folder

Here's what the default preset just laid down:

{{ contest_preset_tree() }}

Notice what *isn't* there: any problem. A fresh contest is a configuration file plus a
pile of {{latex}}, and the problems become sibling folders as you add them.

Notice, too, where the statement chrome lives. In a problem package you'll find the
problem's own text and nothing else -- the templates, the style file and the cover page
are all up here, decided once for the whole contest. That's what step 3 of this track is
about; today we only need to know the folder exists.

## Reading `contest.rbx.yml`

`contest.rbx.yml` is to a contest what `problem.rbx.yml` is to a problem. The only field
it truly requires is `name`, and the preset gives you a little more than that:

```yaml title="contest.rbx.yml"
name: "new-contest"  # (1)!
titles:
  en: "New contest"  # (2)!
statements:
  - name: "statement-en"  # (3)!
    language: "en"
    file: "statements/problem-sheet.rbx.tex"
    standaloneProblemTemplate: "statements/problem.rbx.tex"
    contestProblemTemplate: "statements/problem-fragment.rbx.tex"
tutorials:
  - name: "editorial-en"  # (4)!
    # ...
documents:
  - name: "info-en"  # (5)!
    # ...
vars:
  year: 2025  # (6)!
  date: "2025-06-21"
```

1.  An identifier, not a title. Keep it short and filename-friendly -- packagers reach for
    it when they name what they build.

2.  The human-readable title, one per language. The task sheet prints this one.

3.  The task sheet: the document that joins every problem together. Statements are the
    subject of [Building contest statements](/setters/statements/contest), and we won't
    touch them here.

4.  Editorials, built separately from the statements.

5.  Contest-level documents that *never* join on problems -- the preset ships an
    information sheet listing each problem's limits.

6.  Variables shared by the whole contest. They reach the statement templates, so the year
    and the date are written once rather than once per document.

Let's give it a name of our own:

```yaml title="contest.rbx.yml"
name: "summer-cup"
titles:
  en: "Summer Cup 2026"
```

!!! tip
    `rbx contest edit` opens this file in your `$EDITOR`, from anywhere inside the contest.

## Adding problems

Now the interesting part. `rbx contest add` creates a problem **and** registers it, in one
step:

```bash
rbx contest add --path problems/chocolate --short-name A
```

Two things identify a problem, and the command asks for both:

- `--path`, where the problem folder goes, relative to the contest root. Its last component
  becomes the problem's `name` -- `problems/chocolate` creates a problem named `chocolate`.
- `--short-name`, the letter contestants will see: `A`.

The problem itself is scaffolded exactly as `rbx create` would do it, so `--preset` and
`--variant` work here too. Let's add a second one:

```bash
rbx contest add --path problems/gardens --short-name B
```

And `contest.rbx.yml` has grown a `problems` list:

```yaml title="contest.rbx.yml"
problems:
  - short_name: "A"
    path: "problems/chocolate"
  - short_name: "B"
    path: "problems/gardens"
```

Notice that {{rbx}} keeps the list sorted by short name as it inserts. That ordering is
load-bearing: it's the order problems appear in the task sheet, and the order that ranges
like `A..C` walk.

!!! warning "Letters are letters"
    `short_name` has to match `^[A-Z]+[0-9]*$` and be at most four characters. `A`, `B1`
    and `AA` are fine; `a`, `1` and `chocolate` are not. If you want to call a problem
    `chocolate` on the command line, give it an **alias** -- see
    [Selecting problems](/setters/reference/contest#selecting-problems).

Adding a letter that's already taken -- as a `short_name` *or* as someone's alias -- is
refused, so you can't quietly end up with two problem `B`s.

## Bringing in a problem you already have

Quite often the problem exists before the contest does. Someone wrote it standalone, or
you're pulling last year's spare into this year's set. Say we want the sum-of-N problem
from [First steps](/setters/first-steps) to be problem `C`.

There's no single command for this today. It's two steps, and both are easy:

```bash
mv ~/sum-of-n contests/summer-cup/problems/sum-of-n
```

Then add it to the `problems` list by hand:

```yaml title="contest.rbx.yml" hl_lines="6-7"
problems:
  - short_name: "A"
    path: "problems/chocolate"
  - short_name: "B"
    path: "problems/gardens"
  - short_name: "C"
    path: "problems/sum-of-n"
```

That's all a registered problem is: a letter and a path. In fact `path` is optional -- drop
it and {{rbx}} looks for a folder named after the short name, so a problem living in `C/`
needs nothing but its `short_name`.

!!! tip
    The imported problem keeps its own `problem.rbx.yml`, untouched. Nothing about being
    in a contest changes how a problem is built, which is why a problem can be developed
    standalone and adopted later.

## Reordering and removing problems

Letters aren't stored anywhere except `contest.rbx.yml`, so relettering a contest is
editing that file. Swap two `short_name` values and the problems swap places; there's no
command for it, and none is needed.

Two things don't follow along automatically, and both bite:

- The **folder name** stays what it was. A problem in `problems/chocolate` can perfectly
  well be problem `D`, and usually is by the time the set settles.
- The **order of the list** is what the task sheet and `A..C` ranges read, so keep the
  list sorted when you reletter.

Removing is a command:

```bash
rbx contest remove B
```

It takes a short name, an alias or a path, and drops the problem from `contest.rbx.yml`.

!!! danger "It deletes the folder"
    `rbx contest remove` doesn't only unregister the problem -- it **deletes the problem
    directory from disk**, and it doesn't ask first. If the problem isn't committed
    anywhere, its tests, solutions and statement go with it. Commit before you prune.

## Checking the contest

Let's make sure the contest is in the state we think it is:

```bash
rbx contest summary
```

You'll get one row per problem: its letter and name, its time and memory limits, how many
samples and hidden tests it has, and how many solutions it declares, bucketed by the
outcome each is expected to get.

Below, the whole walkthrough at once -- creating the contest, adding both problems, and
the summary they add up to:

{{ asciinema("contest-scaffold") }}

Read the table as an answer to "is everything wired up?". A letter you don't recognize, a
suspiciously empty test count, a problem with no {{tags.accepted}} solution -- they all
show up here, at a glance, before you've spent an afternoon packaging. A problem that
can't be summarized at all prints an error of its own and the rest of the table carries on,
which is usually the fastest way to find the one folder you moved and forgot to re-point.

!!! tip
    From here on, most commands you already know work across the contest.
    `rbx contest each run` runs every problem's solutions, and `rbx contest on A,C run`
    runs just two of them. The selector syntax is documented in
    [Selecting problems](/setters/reference/contest#selecting-problems).

## Next steps

The contest exists and the problems are in it. What's left is turning that into something
a judge can serve.

<div class="grid cards" markdown>

-   :fontawesome-solid-clock: **Measure the limits for real**

    ---

    Continue the track: replace every guessed time limit in that summary table with one
    measured for the judge, across the whole contest.

    [:octicons-arrow-right-24: Profiling time limits](/setters/contest-profiling-walkthrough)

-   :fontawesome-solid-file-lines: **Build the task sheet**

    ---

    Put the `statements/` folder to work: one PDF joining every problem, and the editorial
    alongside it.

    [:octicons-arrow-right-24: Contest statements](/setters/statements/contest)

-   :fontawesome-solid-gear: **Configure further**

    ---

    Want to know every field `contest.rbx.yml` accepts, from problem colors to aliases?

    [:octicons-arrow-right-24: `contest.rbx.yml`](/setters/reference/contest)

</div>
