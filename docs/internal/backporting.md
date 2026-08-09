# Backporting a fix to an older version

Sometimes a bug is reported against a released version that `main` has long
moved past -- someone is on `0.38.0` while `main` is already at `1.0.0`. The fix
needs to reach **both** lines: a patch release on the old line for the people
stuck there, and `main` so the bug does not come back.

This page is the runbook for that. It is written to be followed literally,
including by an agent that has never done a release here.

## The one rule

**Fix forward first, cherry-pick down, never merge back.**

The fix lands on `main` first, always. Only then is it ported to a maintenance
branch cut from the old tag. The maintenance branch is a one-way destination:
it accumulates `bump:` commits and a truncated `CHANGELOG.md` that must never
flow back into `main`, or commitizen's version derivation gets confused.

If you do it in the other order -- patch the old line first, intending to
forward-port later -- the fix eventually gets forgotten and the bug reappears
in the next major. Do not do it in the other order.

## How releases work here

Read this before touching anything, because the mechanics decide what is safe.

- Versioning is [commitizen](https://commitizen-tools.github.io/commitizen/)
  driven. `cz bump` reads the current version from `pyproject.toml`, derives
  the next one from the conventional-commit types since the last tag, and
  writes it to every entry in `tool.commitizen.version_files` --
  `pyproject.toml`, `rbx/__version__.py`, and the default preset's
  `min_version`. Tags are annotated and unprefixed (`tag_format = "$version"`),
  so the tag is `0.38.1`, not `v0.38.1`.
- **On current `main` there is no release CI.** Releases are cut manually from
  a local checkout with `mise run release` (bump + push tags + PyPI +
  schemas), or its pieces: `mise run bump`, `mise run publish`,
  `mise run publish-schemas`. The tag-push trigger in
  `.github/workflows/release.yml` is deliberately commented out.

That last point is the trap, because **GitHub Actions runs the workflow files
as they existed at the tagged commit**, not as they exist on `main`. Older tags
predate the change, so their `release.yml` still has the tag trigger *active*.
Pushing a `0.38.1` tag built on top of `0.38.0` therefore fires that old
workflow and publishes to PyPI automatically -- the opposite of how `main`
behaves today.

So before releasing an old line, work out which mode it is in, and do not do
both. Double-publishing is not catastrophic (the CI action passes
`skip-existing`), but a local `uv publish` onto a version CI already uploaded
will fail noisily.

## Pre-flight: work out how the old tag releases

Five minutes here saves an afternoon:

```bash
# 1. Is the tag-push trigger live in the release workflow at that tag?
git show 0.38.0:.github/workflows/release.yml | head -30

# 2. Does the test workflow trigger on tag pushes at that tag?
git show 0.38.0:.github/workflows/tests.yml | head -20
```

If the trigger **is** live, the old `release.yml` gates PyPI publishing behind
`lewagon/wait-on-check-action`, which blocks until checks matching
`^ubuntu-latest - Python \d+\.\d+\.x$` report on the tag ref. Two ways that
hangs forever and publishes nothing:

- `tests.yml` at that tag does not trigger on tag pushes; or
- the test matrix job name at that tag does not match that regexp.

If the trigger is **not** live -- anything tagged after `ci: disable release
workflow in favor of mise release`, which landed just after `1.0.0` -- nothing
happens on tag push and you publish by hand.

Also note what the old `release.yml` is *missing*. Anything added to the
release pipeline after that tag simply will not run -- for example, the
schema-publish job did not exist before `1.0.0`, so a `0.38.x` release cannot
publish schemas. That is fine, but know it in advance instead of discovering it
as a missing artifact.

## The procedure

### 1. Fix on `main`

Nothing special -- a normal branch, a normal `fix:` commit, a normal PR. Note
the resulting commit sha on `main`; call it `$SHA`. This is what ships in the
next patch of the current line.

### 2. Cut the maintenance branch from the old tag

One-time per minor version. Name it by minor, so future patches on the same
line reuse it:

```bash
git checkout -b release/0.38.x 0.38.0
git push -u origin release/0.38.x
```

### 3. Port the fix

```bash
git cherry-pick $SHA
```

If the surrounding code was refactored between the two versions, the
cherry-pick may conflict badly. When the conflict is large enough that
resolving it amounts to rewriting the patch anyway, **write the equivalent fix
by hand on the branch instead**, with the same commit message. A backport is
allowed to have a different diff from its origin commit; it is not allowed to
have different behaviour.

Whatever you do, run the tests on the branch. The old line's test suite is the
only thing that knows whether the port is correct in that context.

### 4. Bump on the branch

`cz` reads the current version from the branch's own `pyproject.toml`
(`0.38.0`), so a `fix:` commit already implies `0.38.1`. Force the increment
anyway so a stray `feat:` in the cherry-pick cannot produce `0.39.0`:

```bash
cz bump --increment PATCH
git push && git push --tags
```

The bump also rewrites `min_version` in the default preset to `0.38.1`, which
is correct for that line.

!!! warning "Do not run `mise run release` on a maintenance branch"

    It runs `mise run publish-schemas`, which may not exist -- or may not
    behave -- at that point in history, and it may double up with the old
    tag-triggered CI. Bump and publish as separate, deliberate steps.

### 5. Publish, in whichever mode the pre-flight established

- **Old tag-triggered CI is live** (any line before the trigger was disabled):
  the `git push --tags` above already started it. Do nothing else; watch the
  run.
- **No release CI at that tag**: publish by hand from the branch checkout with
  `mise run publish`.

Either way, confirm PyPI actually received the new version before telling
anyone it shipped.

## What this does *not* break

- **PyPI ordering.** Uploading `0.38.1` after `1.0.0` is fine. `pip install
  rbx-cp` still resolves to the newest overall version; people on the old line
  get the fix with `pip install 'rbx-cp<1.0'`.
- **The published schemas.** `latest/` on the schemas site is computed as the
  greatest version directory present, not as "the last one published", so an
  out-of-order publish cannot regress it. (See [JSON schemas](schemas.md).) In
  practice a pre-`1.0.0` line publishes no schemas at all.

## Afterwards

Keep the maintenance branch. A second fix on the same line is then just another
cherry-pick plus another `cz bump --increment PATCH` -- steps 1, 3, 4, 5, with
step 2 already done.

And once more, because it is the mistake that costs the most to undo: **never
merge `release/0.38.x` into `main`.**
