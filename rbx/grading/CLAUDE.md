# Grading Engine (`rbx/grading/`)

Low-level sandboxed execution layer for compiling and running programs with resource limits.

## Architecture Overview

```
box/code.py (compile/run interface)
  |
  v
grading/steps.py (high-level execution steps: compile, run, check)
  |
  v
grading/steps_with_caching.py (caching wrapper)
  |
  v
grading/judge/sandbox.py -> sandboxes/stupid_sandbox.py (process execution)
  |
  v
grading/judge/cacher.py + storage.py (file storage and caching)
```

## Core Types (`steps.py`)

### `Outcome` (Enum)
Verdict values ordered from best to worst:
`ACCEPTED` > `WRONG_ANSWER` > `MEMORY_LIMIT_EXCEEDED` > `TIME_LIMIT_EXCEEDED` > `IDLENESS_LIMIT_EXCEEDED` > `RUNTIME_ERROR` > `OUTPUT_LIMIT_EXCEEDED` > `JUDGE_FAILED` > `INTERNAL_ERROR` > `COMPILATION_ERROR`

Key methods: `worst_outcome(outcomes)`, `is_slow()`, `is_limit_exceeded()`, `short_name()`.

### Data Models (Pydantic)

- **`RunLog`** -- Sandbox execution result: `exitcode`, `exitstatus`, `time` (ms), `memory` (bytes), `warnings`, `metadata`
- **`SandboxLog`** -- Extension of RunLog with `stdout_absolute_path`, `stderr_absolute_path`
- **`TestcaseLog`** -- Extension with paths to log/eval files
- **`TestcaseIO`** -- Input/output/answer paths
- **`CheckerResult`** -- `outcome`, `message`, `no_tle_outcome`, `sanitizer_warnings`
- **`Evaluation`** -- Top-level result combining `CheckerResult`, `TestcaseIO`, `TestcaseLog`
- **`Limits`** (in `limits.py`) -- `time` (ms), `memory` (MB), `output` (KB), `isDoubleTL`, `profile`

### Execution Functions

- **`compile_item()`** -- Compiles source code, returns digest (content hash). Uses `DependencyCache` for cache invalidation.
- **`run_item()`** -- Executes a compiled program against input, returns `SandboxLog`.
- **`run_checker()`** -- Runs checker binary with `(input, output, answer)` args.
- **`run_communication_item()`** -- Sets up piped execution between solution and interactor.

## Sandbox (`judge/sandbox.py`, `judge/sandboxes/stupid_sandbox.py`)

### `SandboxBase` (ABC)
Abstract interface defining `execute()` and `execute_communication()`.

### `StupidSandbox`
Main implementation. "Stupid" because it doesn't use OS-level sandboxing (unlike CMS's isolate).

**Process execution:**
1. Creates temporary working directory
2. Symlinks cached files into working dir (avoids copying for performance)
3. Spawns process via `asyncio.create_subprocess_exec`
4. Monitors resource usage via `psutil` (time, memory, child processes)
5. Enforces limits: kills on TLE, MLE, OLE, ILE (idleness)
6. Returns `SandboxLog` with timing, memory, exit status

**Communication execution (`execute_communication()`):**
- Sets up bidirectional pipes between solution and interactor using `tee.py`/`line_tee.py`
- Captures interaction data for debugging (`.pio` files)
- Monitors both processes simultaneously

**Key parameters:**
- `SandboxParams` -- `stdin`, `stdout_file`, `stderr_file`, `extra_files`, `address_space_limit`, `time_limit`, `wall_time_limit`, `memory_limit`, `stack_limit`, `max_processes`, `set_hostname`, `allow_network`
- `CommunicationParams` -- Solution and interactor params, `capture_pipes` flag

## File Caching (`judge/cacher.py`, `judge/storage.py`)

### `Storage` (ABC) -> `FilesystemStorage`
File storage abstraction. `FilesystemStorage` stores files in a directory:
- Files identified by content digest (SHA-1 hash)
- Optional LZ4 compression (controlled by `grading_context`)
- Metadata stored as JSON sidecar files in `.metadata/` subdirectory
- **Symlink support**: `path_for_symlink()` returns path for creating symlinks to cached files (avoids copies)

### `FileCacher`
High-level caching API wrapping `Storage`:
- `put_file_from_path()` / `get_file_to_path()` -- Store/retrieve files by digest
- `put_file_content()` / `get_file_content()` -- Store/retrieve raw bytes
- Uses symlinks when possible for zero-copy access

### `NullStorage`
No-op storage backend (like `/dev/null`) for when caching is disabled.

## Dependency Cache (`caching.py`)

`DependencyCache` provides content-addressed caching with dependency tracking:
- A compilation result is cached keyed by a hash of (source content + compiler flags + dependencies)
- `get_compilation()` / `put_compilation()` -- Check/store compilation results
- Uses `sqlitedict` for persistent key-value mapping
- Digest invalidation: if any dependency changes, the cached result is invalidated

## Context Variables (`grading_context.py`)

Uses Python `contextvars` to manage execution context:

- **`CacheLevel`** enum: `NO_CACHE`, `CACHE_TRANSIENTLY`, `CACHE_COMPILATION`, `CACHE_ALL`
- **`cache_level(level)`** -- Context manager to set cache level
- **`should_compress()`** / **`get_compression_level()`** -- LZ4 compression control
- **`should_check_integrity()`** -- Hash verification for cached files

## Profiling (`profiling.py`)

Performance profiling for sandbox execution. Tracks compilation and execution times. `print_summary()` registered via `atexit` when profiling is enabled.

## Output Handling (`judge/sandboxes/tee.py`, `line_tee.py`)

Helper scripts for interactive problem communication:
- **`tee.py`** -- Character-level tee: reads stdin char-by-char, writes to stdout + stderr (with prefix) + extra file
- **`line_tee.py`** -- Line-level tee: same but operates line-by-line (more efficient for non-interactive output)

Both are forked from BAPCtools and used to capture interaction data between solution and interactor.

## Key Design Decisions

- **Symlinks over copies**: Compiled artifacts are symlinked from cache rather than copied, critical for performance. Symlink support is checked at startup (`main.py`).
- **Content-addressed storage**: Files are identified by SHA-1 digest, enabling automatic deduplication.
- **No OS-level sandboxing**: `StupidSandbox` uses `psutil` for monitoring rather than cgroups/namespaces. This is intentional for portability (works on macOS).
- **LZ4 compression**: Optional compression for storage, controlled per-context via `grading_context`.
