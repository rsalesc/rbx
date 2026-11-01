# Running in a Docker container

If you have Docker installed, {{rbx}} can compile and run every program inside a container instead
of directly on your machine: solutions, generators, validators, checkers, and interactors alike.

You'd want this for:

- **Limits your machine can't apply.** On macOS, {{rbx}} can't raise the stack limit past a small
  ceiling, and it enforces memory differently than a judge does (see [Stack limit](../../stack-limit.md)
  and [Memory limit](../../memory-limit.md)). Inside the container, programs run on Linux, under the same
  kind of limits most online judges use.
- **Safety.** Programs in the container have no network access, can't modify your files, and can't
  fork without bound.

The container runs Linux on your own CPU architecture, so there is no emulation and no noticeable
slowdown, even on Apple Silicon.

## Turning it on

Let's enable it once, for every command from now on:

```bash
rbx docker enable
```

It first checks that Docker is running and turns the feature on in your setter config. Then it
builds the image your programs run in, which takes a few minutes. That only happens again when
you upgrade {{rbx}} or change what goes into the image.

From then on, nothing else changes in how you use {{rbx}}: `rbx run`, `rbx build`, `rbx stress` and
the rest work exactly as before, with programs running in the container. The container starts on
its own when a command needs it, and stops by itself after a while without use.

!!! tip "Trying it for one command"
    You can always override the setting for one command with the `RBX_DOCKER` environment variable,
    without touching your config:

    ```bash
    RBX_DOCKER=1 rbx run   # in the container, even if it is disabled
    RBX_DOCKER=0 rbx run   # on your machine, even if it is enabled
    ```

## What changes

**Verdicts follow Linux.** A solution that allocates more than the memory limit fails its
allocation and gets `RTE` rather than `MLE`, as on most judges. Declare such solutions with
`outcome: mle+rte`, and read [Memory limit](../../memory-limit.md) for why.

**Your problems must live under a mounted folder, your home directory by default.** Programs see
your files read-only, and only what's under those folders. A problem elsewhere fails with a
message saying so: add its folder to `mounts`, described below.

**Time limits are machine-specific.** A time limit estimated with `rbx time` on your machine isn't
necessarily right for runs in the container, and the other way around. Estimate it again after
switching.

!!! note
    On macOS, Docker Desktop runs containers in a virtual machine with its own share of CPUs and
    memory, which can be smaller than your machine's. `rbx docker status` shows them, and warns when
    {{rbx}} would run more programs in parallel than the VM has CPUs. Raise them in Docker Desktop's
    settings if your runs time out unexpectedly.

## Customizing the container

These settings go under `docker` in your setter config, which you can open with `rbx config edit`:

```yaml title="setter_config.yml"
docker:
  enabled: true
  packages: [g++, gcc, python3, pypy3, default-jdk-headless, clang]
```

The image comes with C, C++, Python, PyPy, Java, and Kotlin. This snippet is the default package
list plus `clang`: setting `packages` replaces the whole list, so keep the defaults you still need.
Below, the settings you are most likely to change:

| Setting | What it does |
| --- | --- |
| `packages` | `apt` packages installed in the image: the compilers and interpreters your problems use. |
| `kotlin_version` | Kotlin compiler release to install, or `null` to leave Kotlin out. |
| `base_image` | Image the toolchains come from, `ubuntu:24.04` by default. Must be Debian-based to use `packages` or `kotlin_version`. Point it at an image matching your judge's compiler versions to get closer to its verdicts. |
| `dockerfile` | A Dockerfile to build the base image from, for anything `packages` can't express. |
| `mounts` | Folders programs can see, read-only. Defaults to `[~]`. |
| `command_substitutions` | Replaces the top-level `command_substitutions` while Docker is on, since those name tools on your machine, like a Homebrew `g++-15`. |
| `max_parallel` | Programs that may run in the container at once, across every {{rbx}} command using it. Defaults to 1. |
| `memory` | Optional memory cap for the whole container, in Docker syntax, like `8g`. Per-program memory limits apply either way. |
| `idle_timeout` | Seconds the container stays up with no command using it. |
| `pids_limit` | Most processes the container may hold at once. |

Changing `packages`, `kotlin_version`, `base_image` or `dockerfile` changes what goes into the
image: the next command builds a new one.

!!! warning "Running programs in parallel"
    By default, the container runs one program at a time, even when several commands use it at
    once, such as `rbx each --parallel`. On macOS, Docker Desktop can hand a program a truncated
    file when several programs read at once, which shows up as random runtime errors.
    Raise `max_parallel` only on a Linux host, or if you accept that risk.

!!! note "Which problem goes first"
    When `rbx each --parallel` or `rbx on --parallel` has programs from several problems waiting
    for the container, the problem that comes earliest in the contest goes first. That way the
    first problems finish their work in the container early and move on to their next command
    while later ones are still running.

    A command you start on its own meanwhile, like `rbx run` in another terminal, waits behind
    those problems.

!!! info
    If a compiler or interpreter is missing from the image, the compile or run that needs it fails,
    saying which one is missing and which setting to change.

## Managing the container

You rarely need these, but they're there:

| Command | What it does |
| --- | --- |
| `rbx docker status` | Whether Docker is on, the image, the container and what it can see. |
| `rbx docker up` | Builds the image if needed and starts the container now. |
| `rbx docker down` | Stops the container. |
| `rbx docker rebuild` | Rebuilds the image from scratch, picking up updates to the base image. |
| `rbx docker shell` | Opens a shell in the container, to inspect a toolchain. |

## Turning it off

To go back to running programs on your machine, run:

```bash
rbx docker disable
```

This keeps your other `docker` settings, so `rbx docker enable` restores them as they were.
