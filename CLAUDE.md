# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**rbx** (`rbx-cp` on PyPI) is a CLI tool for competitive programming problem setters. It manages the full lifecycle of problems and contests: test generation, solution judging, statement building (PDF/HTML/Markdown), and packaging for judge systems (Polygon, BOCA, MOJ, PKG).

## Commands

### Dependencies
```bash
uv sync
```

### Testing
```bash
# Run all tests (exclude CLI tests which are slow)
uv run pytest --ignore=tests/rbx/box/cli

# Run a single test file
uv run pytest tests/path/to/test_file.py

# Run a specific test
uv run pytest tests/path/to/test_file.py::test_function_name

# Run tests in parallel
uv run pytest -n auto

# Run with coverage
uv run pytest --ignore=tests/rbx/box/cli --cov=rbx --cov-branch --cov-report=xml -n auto
```

Test markers: `e2e`, `slow`, `docker` (these are excluded from default CI runs via `mise run test`).

Docker-backed suites live under `tests/docker/` (currently only the BOCA upload e2e test) and are **disabled by default**: `tests/docker/conftest.py` skips collection of that subtree unless `RBX_DOCKER_TESTS=1` is set, and the test modules carry a matching module-level `skipif`. Do not run or re-enable them as part of ordinary work -- they need a docker daemon, docker-compose and network access. `mise run test-docker` is the only supported entry point.

End-to-end CLI scenarios live under `tests/e2e/` and are written in a YAML DSL (one `e2e.rbx.yml` per fixture package). Run them with `mise run test-e2e`. See [`tests/e2e/README.md`](tests/e2e/README.md) for the schema and authoring guide.

### Linting and Formatting
```bash
uv run ruff check .        # Lint
uv run ruff check --fix .  # Lint with auto-fix
uv run ruff format .       # Format
```

### Running the CLI
```bash
uv run rbx
```

## Code Style

- **Single quotes** for strings (enforced by ruff)
- **Absolute imports only** — relative imports are banned (`TID` rule)
- Ruff rules enabled: `E4`, `E7`, `E9`, `F`, `B`, `I`, `TID`, `SLF`
- Pre-commit hooks run ruff check/format and commitizen (conventional commits)

## Git Commits

**You MUST use the `/commit` skill when creating commits.** This project enforces [Conventional Commits](https://www.conventionalcommits.org/) via commitizen (`cz_conventional_commits`). The pre-commit hook will reject non-compliant messages. See [`.claude/skills/commit.md`](.claude/skills/commit.md) for the full workflow and allowed commit types.

## Detailed Module Guides

For complex modules, see the inner CLAUDE.md files:

- [`rbx/box/CLAUDE.md`](rbx/box/CLAUDE.md) -- Schema system, build pipeline, solution running, generators, checkers, code compilation
- [`rbx/grading/CLAUDE.md`](rbx/grading/CLAUDE.md) -- Grading engine: sandbox execution, caching, storage, resource limits
- [`rbx/box/ui/CLAUDE.md`](rbx/box/ui/CLAUDE.md) -- Textual TUI: screens, widgets, terminal emulator, navigation
- [`rbx/box/packaging/CLAUDE.md`](rbx/box/packaging/CLAUDE.md) -- Packaging for judge systems: Polygon (with API upload), BOCA, MOJ, PKG
- [`rbx/box/statements/CLAUDE.md`](rbx/box/statements/CLAUDE.md) -- Statement building: rbxTeX/LaTeX/Jinja pipeline, conversion steps, templates
- [`casts/README.md`](casts/README.md) -- Documentation asciinema recordings: specs, fixtures, `mise run record`

## Releases and Backports

Releases are commitizen-driven and cut manually with `mise run release` (bump + push tags + PyPI + schemas). There is no release CI on `main` -- the tag-push trigger in `.github/workflows/release.yml` is deliberately disabled. Tags cut from older commits still carry the enabled trigger, which matters when backporting.

The bump goes through [`scripts/release.py`](scripts/release.py), which prints `current -> next` and **asks for confirmation** before committing, tagging and pushing; declining aborts the whole release before anything is published. Pass `--minor` (or `--major` / `--patch` / `-i MINOR`) to override the increment commitizen derives from the commit log -- e.g. `mise run release --minor` ships a `feat!` as a minor bump, and the prompt says which version commitizen would have picked instead. `--yes` skips the prompt (required when there is no terminal), `--no-push` bumps locally only, and any other flag is forwarded to `cz bump`.

To ship a fix to an already-released older version (e.g. patch `0.38.0` while `main` is at `1.0.0`), follow [`docs/internal/backporting.md`](docs/internal/backporting.md). The short version: **fix forward on `main` first, cherry-pick down to a `release/<major>.<minor>.x` branch cut from the old tag, never merge that branch back.**

## Architecture

### Entry Point and CLI

Entry point: `rbx/box/main.py:app` → delegates to **Typer** commands in `rbx/box/cli.py`.

Key CLI commands: `rbx build`, `rbx run`, `rbx stress`, `rbx statements build`, `rbx package build`, `rbx create`, `rbx ui`.

### Core Data Flow

1. **Package loading** (`package.py`): Discovers and parses `problem.rbx.yml` via Pydantic models in `schema.py`
2. **Build pipeline** (`builder.py`): Orchestrates generation → validation → output generation → solution running
3. **Generators** (`generators.py`): Run generator programs to create test inputs
4. **Validators** (`validators.py`): Validate inputs against constraints
5. **Solutions** (`solutions.py`): Run solutions in sandboxed environment, collect verdicts
6. **Checkers** (`checkers.py`): Verify outputs via checker programs

### Grading Engine (`rbx/grading/`)

Low-level sandboxed execution layer:
- `steps.py`: Execution steps and `Outcome` enum (AC, WA, TLE, RTE, MLE, OLE, etc.)
- `judge/sandbox.py`: Base sandbox interface; `sandboxes/stupid_sandbox.py`: main implementation
- `caching.py` / `steps_with_caching.py`: Dependency-aware compilation/execution caching

### Configuration Files (user-facing, not project config)

- `problem.rbx.yml`: Problem structure, test cases, solutions, validators
- `contest.rbx.yml`: Contest-level settings. May be a single contest, a dispatcher (`use_variants: true`) with all contests in sibling `contest.<id>.rbx.yml` files, or a real contest WITH sibling variants (canonical is the default, siblings are extra variants). Selected via `-C <id>` or `RBX_CONTEST=<id>`. See `docs/plans/2026-05-06-multi-contest-design.md`.
- `env.rbx.yml`: Language settings, compilation flags, sandbox configuration

### Submodules

- `box/contest/`: Contest management and multi-problem operations
- `box/packaging/`: Export to judge formats (Polygon, BOCA, MOJ, PKG); Polygon has API upload support
- `box/statements/`: Statement building with LaTeX, Jinja, Markdown; multi-language support
- `box/stressing/`: Stress testing with generator/finder parsers
- `box/ui/`: Textual-based TUI (`textual` framework)
- `box/wizard/`: AI-powered problem creation using `openai-agents` SDK

### Key Patterns

- **Async throughout**: Most operations are async; `syncer` bridges sync Typer commands to async code
- **Pydantic v2**: Extensive use for all configuration, schemas, and data validation
- **`@package.within_problem` decorator**: Guards CLI commands to ensure they run inside a valid problem directory
- **Rich output**: Custom Rich console theme in `console.py`
- **Caching via symlinks**: `FileCacher` uses symlinks; symlink support is checked at startup

## Testing Conventions

- Reuse existing pytest fixtures from `tests/rbx/conftest.py` and `tests/rbx/box/conftest.py`
- Key fixtures: `cleandir`, `cleandir_with_testdata` (uses `@pytest.mark.test_pkg`), `pkg_from_testdata`, `testing_pkg`, `mock_pdflatex`
- Test behavior, not implementation details; avoid mocking private functions
- Use `mock.patch` from stdlib; assert over entire objects where possible
- Reuse files in `testdata/` folders or create new ones in a folder related to the test
- Always run written tests to verify they pass
