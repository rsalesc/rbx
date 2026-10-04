# Packaging the whole contest

This walkthrough covers the last thing a chief setter does: packaging a whole contest and
uploading it to the judge in one go. It also shows how to re-ship one problem that changed
without touching the rest.

!!! note "Prerequisite"
    This page closes the `summer-cup` contest we've been building -- problems `A`, `B` and
    `C` in `problems/chocolate`, `problems/gardens` and `problems/sum-of-n`, each carrying
    the `.limits/boca.yml` that
    [Profiling time limits](/setters/contest-profiling-walkthrough) measured. We'll use
    {{boca}} as the target judge, as
    [Packaging a problem](/setters/packaging-walkthrough) did.

## Packaging every problem

From the contest root:

```bash
rbx each package boca
```

`rbx each` runs the command once per problem, in the problem's own folder, in the command
app you already met in [Profiling time limits](/setters/contest-profiling-walkthrough#the-rest-of-the-contest).
A failure doesn't stop the others: a problem whose solutions disagree with their expected
outcomes goes red in the sidebar, and the other problems keep packaging.

When it's done, each problem folder has its own package:

```
problems/chocolate/build/A_chocolate.zip
problems/gardens/build/B_gardens.zip
problems/sum-of-n/build/C_sum_of_n.zip
```

Notice the letter in each filename: {{rbx}} reads it from the contest's `problems` list.

!!! info
    {{rbx}} verifies each problem at the highest
    [verification level](/setters/packaging-walkthrough#verification-levels), which is slow.
    For a faster build, pass `-v1`: it still validates the tests, but doesn't run the
    solutions.

## Packaging a subset

To re-package only some problems, use `rbx on` with a selector:

```bash
rbx on B package boca          # one problem, straight in your terminal
rbx on A,C package boca        # two of them, in the command app
rbx on A..C package boca       # a range, in contest order
rbx on '*,!B' package boca     # everything but B
```

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
{{rbx}} looks for a `.env` (or `.env.local`) walking **up** from wherever it's running, so
every problem underneath the contest root finds the file you put there.

```bash title=".env"
BOCA_BASE_URL="https://your.boca.com/boca"
BOCA_USERNAME="admin_username"
BOCA_PASSWORD="admin_password"
```

!!! warning
    That user has to be an admin of the contest, and the contest has to be the one
    **activated** on the BOCA server. The command doesn't specify a contest: the upload
    goes to whatever contest is currently active on the server. If yesterday's contest is
    still active, the set goes into it, and the command still reports success.

### What the contest decides, and what the problem decides

The zip contains the tests, the limits and the statement. Everything the judge shows *around*
the problem comes from `contest.rbx.yml` instead:

- the **letter** the problem is filed under (`short_name`);
- its **position** in BOCA's problem list, which is its position in the `problems` list;
- its **balloon color**, from that entry's `color`.

Inserting a new problem in the middle of the list shifts every problem after it one
position down, and BOCA files problems by position. The next upload then **overwrites**
problems that were already fine. Re-package the whole set after any reordering, and read
[the BOCA guide](/setters/packaging/boca#i-removed-a-problem-from-the-contest-but-it-still-appears-in-boca)
on why removing a problem is still a manual job.

### When part of the set fails

Every problem is its own upload, so part of the set can fail while the rest goes up. The
upside is that you can re-ship only the failed ones, with `rbx on`:

```bash
rbx on A,C package boca -u
```

Before you re-run, though, know what "it failed" means here. {{rbx}} posts the zip to BOCA's
upload form, then looks for it in BOCA's admin log. If it can't find it, it logs in and
uploads again, up to three times. Once it finds it, it prints:

```
Problem sent to BOCA. rbx cannot determine the upload succeeded, check the website to be sure.
```

{{rbx}} can only confirm that the upload *arrived*. It can't tell whether BOCA accepted the
package inside, but the problem list in the web interface can. **Look at it** before you
call the contest ready.

!!! tip
    When an upload fails on every retry, {{rbx}} points at a likely cause: PHP's 2 MB
    default cap on uploaded files. That one has a fix, on the server side -- see
    [BOCA troubleshooting](/setters/packaging/boca#upload-is-taking-too-long-or-an-error-is-being-reported).

## Shipping a contest to Polygon

With {{polygon}}, you upload the problems over the API and **assemble the contest in the web
interface**, so you package and upload each problem:

```bash
rbx each package polygon -u
```

The [Polygon guide](/setters/packaging/polygon) covers the rest, up to the Gym import.

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

    Polygon, MOJ and DOMjudge, and what each format does and doesn't support.

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
