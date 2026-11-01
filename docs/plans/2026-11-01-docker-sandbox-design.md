# Docker sandbox (opt-in)

Status: implemented (branch `worktree-docker-sandbox`).

## Goal

Let a setter who has Docker run every program rbx compiles or executes --
everything that goes through `code.py` -- inside a container instead of directly
on their machine. Two reasons:

1. **Safety.** No network, a read-only view of the host, a cap on processes.
2. **Limits the host cannot apply.** macOS ignores `RLIMIT_STACK` changes (its
   hard stack limit is 64 MiB) and does not impose `RLIMIT_AS`, so a deep
   recursion that a Linux judge accepts cannot pass locally at all.

Non-goals: emulating a judge exactly, cross-architecture emulation, wrapping
statement builds, packaging or the TUI.

## Decisions

- **Opt-in in the setter config** (`docker:` section), never in the package. A
  setter's machine decides how programs run; `env.rbx.yml` is untouched.
- **On macOS, Docker means Linux** on the host's own architecture (arm64 on Apple
  Silicon): native speed, no QEMU. Compilation therefore happens in the
  container too, so binaries always match where they run.
- **Fail outright.** No Docker CLI, no daemon, a failed build, a path the
  container cannot see: each is an error naming the setter config key. There is
  no silent fallback to native execution.
- **Toolchains from a locally built image**: `base_image` (default
  `ubuntu:24.04`) or a user `dockerfile`, plus apt `packages` (default `g++ gcc
  python3 default-jdk-headless`). rbx appends its own layer: a uv-managed Python
  and `rbx-cp==<version>` under `/opt/rbx`, off `PATH`. From a source checkout
  (editable install) it builds and installs a wheel instead, and the source hash
  joins the image tag, so local changes rebuild automatically. No registry, no
  release-process change.
- **No startup toolchain check.** A missing compiler surfaces as the existing
  `ProgramNotFoundError`; in Docker mode its advice names `docker.packages` /
  `docker.base_image` instead of "is it on your PATH?".

## Architecture

```
host                                              container (long-lived)
----                                              ----------------------
DockerSandbox(StupidSandbox)                      keeper: docker_agent keep
  box setup, symlinks, outputs  (inherited)       agent:  docker_agent serve  (one per rbx process)
  run() / run_communication() --JSON lines over-->  StupidSandbox(path=box).run(...)
                                docker exec -i       same rlimits, watchdog, tees
```

- **`DockerSandbox` subclasses `StupidSandbox` and overrides only `run` and
  `run_communication`**, plus `create_symlink` (below). Everything else --
  creating the box, staging files, reading outputs -- is inherited and happens on
  the host. The agent runs the very same `StupidSandbox` code against the box,
  which the container sees at the same absolute path. No execution logic is
  duplicated; the only change to `StupidSandbox` is an optional `path=` to adopt
  an existing box.
- **Transport: one `docker exec -i` per rbx process**, JSON lines with request
  ids, many concurrent requests (a thread each in the agent). ~40 ms to attach
  once, ~0.5 ms per request after. No port, so the container runs with
  `--network none`.
- **Lifecycle**: the first program starts the container (`docker run -d --rm
  --init`, under a file lock so concurrent rbx processes share one). Its main
  process is a keeper that exits once no agent has been connected for
  `idle_timeout` seconds (default 900). A fully cached run starts nothing.
- **Container flags**: `--user <uid>:<gid>`, `--network none`, `--cap-drop ALL`,
  `no-new-privileges`, `--read-only` root with a tmpfs `/tmp`, `--ulimit
  stack=-1:-1` (so rbx can raise the stack as far as asked), `--pids-limit`,
  optional `--memory`.
- **Mounts at identical paths**: the box root read-write, `docker.mounts`
  (default `~`) read-only.

## Seams in the rest of rbx

- `SandboxBase.runs_on_host()` -- False for Docker. Gates every host probe that
  would describe the wrong machine: `which` alias resolution of compilers, the
  `g++ -v` `bits/stdc++.h` injection, the macOS sanitizer and stack checks, and
  the hard-rlimit warnings in `_finalize_limits`.
- `SandboxBase.cache_fingerprint()` -- the image id for Docker, joined to compile
  and run cache keys as `__executor__`. `None` for `StupidSandbox`, so existing
  caches stay valid.
- `SandboxBase.program_not_found_hint()` -- the Docker advice above.
- `SetterConfig.substitute_command` -- in Docker mode the host's substitutions
  (Homebrew `g++-15`, `clang++` for sanitizers) are ignored in favour of
  `docker.command_substitutions`.
- `environment.get_sandbox_type()` and `global_package.get_global_sandbox_type()`
  (precompiled headers) return the bound `DockerSandbox` when enabled.

## Findings from prototyping on Docker Desktop (macOS, arm64)

1. **Nested bind mounts are dropped silently.** A read-write mount under a
   read-only one (the box under `~`) comes up read-only. Boxes therefore live in
   `tempfile.gettempdir()/rbx-docker-<uid>`, outside every mount, and
   `validate()` refuses a mount that would contain them.
2. **Host-created FIFOs work** as pipes when both ends are in the container.
3. **The transient file cache is invisible** (a private `mkdtemp`), so a symlink
   to it would dangle; `DockerSandbox.create_symlink` returns `None` for a
   target outside the visible roots, which makes callers copy instead.
4. **Freshly written host files can read as empty in the guest for ~100 ms.**
   Reproduced with an 89 MB precompiled header (`cannot read PCH file`) and with
   any single `write()` of 48 MiB or more. Every request now carries a manifest
   of the box's file sizes as the host sees them (following symlinks), and the
   agent waits until its view agrees before starting the program, failing loudly
   after 5 s. The wait is outside the measured time.
5. Memory under `RLIMIT_AS` behaves as on any Linux host: an allocation over the
   limit fails up front (RTE), which is why fixtures use `MLE_OR_RTE`.

## Testing

- `tests/rbx/grading/judge/test_docker_sandbox.py` -- the agent run directly on
  the host (its command is a parameter): protocol, error passthrough,
  concurrency, dead agent, copy fallback, file sync, keeper.
- `tests/rbx/box/docker_runtime_test.py` -- config to Dockerfile/tag/container,
  validation, substitutions, sandbox selection.
- `tests/docker/sandbox/` (gated by `RBX_DOCKER_TESTS=1`) -- a real container:
  stack follows `stack_space`, no network, read-only host, large fresh inputs.

## Follow-ups

- A setter-facing docs page.
- Time limits estimated natively (`rbx time`) do not transfer to Docker runs;
  consider tying limits profiles to the sandbox fingerprint.
- `rbx docker status` warns when `parallel.max_workers` exceeds the VM's CPUs;
  Docker Desktop's default VM can be smaller than the host.
