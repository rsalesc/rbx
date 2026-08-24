# Packaging the whole contest

This walkthrough covers the last thing a chief setter does: turning a whole contest into
packages, getting all of them into the judge in one go, and re-shipping the one problem
that changed without touching the rest.

!!! note "Prerequisite"
    This page closes the `summer-cup` contest we've been building -- problems `A`, `B` and
    `C` in `problems/chocolate`, `problems/gardens` and `problems/sum-of-n`, each carrying
    the `.limits/boca.yml` that
    [Profiling time limits](/setters/contest-profiling-walkthrough) measured. We'll use
    {{boca}} as the target judge, as
    [Packaging a problem](/setters/packaging-walkthrough) did.

Step 4 took one problem all the way to the judge. A contest is that, `N` times, on the
morning of the event -- and the interesting part is not the repetition. It's that the set
has to go up as a set: the same limits profile everywhere, the letters matching the
statement, and no problem quietly left at yesterday's version.

## One command per problem, or one for the contest

There are two commands here, and they are *not* two ways of doing the same thing:

| Command | Produces | What it's for |
| :--- | :--- | :--- |
| `rbx each package boca` | one package per problem, in each problem's own `build/` | shipping to the judge |
| `rbx contest package boca` | a single archive at the contest root's `build/` | handing the set over as one file |

BOCA ingests problems one at a time, and so does its upload form, so the command you'll
actually run on contest morning is the first one. The second is covered
[at the end of this page](#the-contest-bundle) -- it's an archive, not a shipping route.

## Packaging every problem

From the contest root:

```bash
rbx each package boca
```

`rbx each` runs the command once per problem, in the problem's own folder, in the command
app you already met in [step 2](/setters/contest-profiling-walkthrough#the-rest-of-the-contest)
-- a sidebar of problems on the left, the selected problem's output on the right. Two of
its habits matter more here than they did during profiling:

- **A failure doesn't stop the sweep.** A problem whose solutions disagree with their
  expected outcomes fails, goes red in the sidebar, and the other problems keep packaging.
  You end up with a partial set, which is exactly what you want to be told about.
- **The report you need is the red one.** Arrow-key over to it; each tab keeps its own
  scrollback.

Three packages exist when it's done, one per problem folder:

```
problems/chocolate/build/A_chocolate.zip
problems/gardens/build/B_gardens.zip
problems/sum-of-n/build/C_sum_of_n.zip
```

Notice the letter in each filename. It isn't in the problem's `problem.rbx.yml` anywhere --
{{rbx}} reads it from the contest's `problems` list, which is the first of several places
where the contest, not the problem, decides what the judge sees.

!!! info
    Every problem here is built and verified from scratch, at verification level 4. That's
    three full builds, and it's the slowest command in this track. The `-v` flags that
    trade verification for speed are the same ones as in
    [step 4](/setters/packaging-walkthrough#verification-levels) -- and `rbx each package boca -v0`
    on the morning of the contest is a bad trade.

## Packaging a subset

You will rarely re-package all of it. A test changes in `B` an hour before the contest, and
what you want is `B` and nothing else, so `rbx on` takes the same command with a selector in
front of it:

```bash
rbx on B package boca          # one problem, straight in your terminal
rbx on A,C package boca        # two of them, in the command app
rbx on A..C package boca       # a range, in contest order
rbx on '*,!D' package boca     # everything but D
```

A single problem is a single command, so {{rbx}} skips the app and runs it in place.

!!! info
    The selector understands names, aliases and folders as well as letters, and quoting is
    on you whenever it contains `*` or `!`. It's documented in full in
    [Selecting problems](/setters/reference/contest#selecting-problems).

## Uploading the set

Add `-u` and each package goes up as soon as it's built:

```bash
rbx each package boca -u
```

<!-- Still hosted on asciinema.org: reproducing an upload needs a live BOCA
     server, which the recording pipeline has no way to stand up. -->
{{ asciinema("onJXQDVPELqn2kITmCrbkJeCX", speed=3) }}

The credentials come from the environment, and you can set them once for the whole contest:
{{rbx}} looks for a `.env` (or `.env.local`) walking **up** from wherever it's running, so a
single file at the contest root is found by every problem underneath it.

```bash title=".env"
BOCA_BASE_URL="https://your.boca.com/boca"
BOCA_USERNAME="admin_username"
BOCA_PASSWORD="admin_password"
```

!!! warning
    That user has to be an admin of the contest, and the contest has to be the one
    **activated** on the BOCA server. Nothing in the command names a contest: the upload
    lands wherever the server's active contest currently points, so a set uploaded against
    yesterday's activation goes into yesterday's contest and reports success doing it.

### What the contest decides, and what the problem decides

The zip carries the tests, the limits and the statement. Everything the judge shows *around*
the problem comes from `contest.rbx.yml` instead:

- the **letter** the problem is filed under (`short_name`);
- its **position** in BOCA's problem list, which is its position in the `problems` list;
- its **balloon color**, from that entry's `color`.

Which explains a failure mode worth knowing before it happens: insert a new problem in the
middle of the list and everything after it shifts one letter down, so the next upload
**overwrites** problems that were already fine. Re-package the whole set after any
reordering, and read
[the BOCA guide](/setters/packaging/boca#i-removed-a-problem-from-the-contest-but-it-still-appears-in-boca)
on why removing a problem is still a manual job.

### When part of the set fails

Every problem is its own upload, so a set can be half-shipped. That's the good news: the
failures are re-shippable on their own, and `rbx on` is how you do it.

```bash
rbx on A,C package boca -u
```

Before you re-run, though, know what "it failed" means here. {{rbx}} posts the zip to BOCA's
upload form, goes looking for the upload in BOCA's own admin log, and retries up to three
times when it can't find it. Then it tells you this:

```
Problem sent to BOCA. rbx cannot determine the upload succeeded, check the website to be sure.
```

That is not modesty. What was confirmed is that the upload *arrived*; whether BOCA liked the
package inside is a separate question, and nothing in that exchange answers it. The problem
list in the web interface does. **Look at it** before you call the contest ready.

!!! tip
    An upload that fails on every retry is, more often than not, PHP's 2 MB default cap on
    uploaded files rather than anything about your package. That one has a fix, on the
    server side -- see
    [BOCA troubleshooting](/setters/packaging/boca#upload-is-taking-too-long-or-an-error-is-being-reported).

## The contest bundle {: #the-contest-bundle }

The other command packages the contest as a unit:

```bash
rbx contest package boca
```

{{ asciinema("contest-package-bundle") }}

It builds every problem's package first -- the same three zips as above, in the same places
-- and then collects them into one archive at the contest root:

```
build/boca-contest.zip
└── problems/
    ├── A.zip
    ├── B.zip
    └── C.zip
```

There's no `-u` here, and that's deliberate rather than missing: BOCA has no notion of
importing a contest, only problems. Reach for the bundle when the set has to travel as one
file -- handing it to whoever runs the judge, or archiving what the contest actually
shipped.

Three formats have a contest-level command, and they don't all mean the same thing by it:

| Command | The archive it writes |
| :--- | :--- |
| `rbx contest package boca` | the problem packages, unchanged, side by side |
| `rbx contest package polygon` | the problem packages plus the `contest.xml` and `contest.dat` descriptors Polygon reads |
| `rbx contest package pkg` | the problem packages plus the contest's own statement |

MOJ has no contest-level command at all -- `rbx each package moj` is the whole story there.

## Shipping a contest to Polygon

{{polygon}} works the other way around, and it's worth saying explicitly because the shape
of the workflow inverts. There, the *problems* are uploaded over the API and the **contest
is assembled in the web interface** -- so the bulk command you want is the per-problem one
again, pointed at Polygon:

```bash
rbx each package polygon -u
```

`rbx contest package polygon` is the offline counterpart, and it's a different job: the
descriptors above describe the set to Polygon without any of it having gone through the API.
The API route, all the way to the Gym import at the end of it, is laid out step by step in
the [Polygon guide](/setters/packaging/polygon).

## Next steps

The contest is on the judge. What's left is the part you can only do once it's there.

<div class="grid cards" markdown>

-   :fontawesome-solid-flask-vial: **Submit your own solutions to it**

    ---

    `rbx each tooling boca submit` sends every declared solution to the judge and compares
    the verdict BOCA returns against the one the problem expects. It's the closest thing to
    a dry run of the contest, and it needs the judge credentials rather than the admin ones.

    [:octicons-arrow-right-24: CLI reference](/setters/reference/cli)

-   :fontawesome-solid-box-open: **Package for another judge**

    ---

    Polygon, MOJ and PKG, and what each format does and doesn't support.

    [:octicons-arrow-right-24: Packaging](/setters/packaging)

-   :fontawesome-solid-file-lines: **The task sheet that goes with it**

    ---

    One PDF joining every problem, and the editorial alongside it.

    [:octicons-arrow-right-24: Contest statements](/setters/statements/contest)

-   :fontawesome-solid-seedling: **Make the next contest easier**

    ---

    Everything you just configured -- chrome, environment, layout -- can be a preset that
    the next contest starts from.

    [:octicons-arrow-right-24: Presets](/setters/presets)

</div>
