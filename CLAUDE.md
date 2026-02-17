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

## Detailed Module Guides

For complex modules, see the inner CLAUDE.md files:

- [`rbx/box/CLAUDE.md`](rbx/box/CLAUDE.md) -- Schema system, build pipeline, solution running, generators, checkers, code compilation
- [`rbx/grading/CLAUDE.md`](rbx/grading/CLAUDE.md) -- Grading engine: sandbox execution, caching, storage, resource limits
- [`rbx/box/ui/CLAUDE.md`](rbx/box/ui/CLAUDE.md) -- Textual TUI: screens, widgets, terminal emulator, navigation
- [`rbx/box/packaging/CLAUDE.md`](rbx/box/packaging/CLAUDE.md) -- Packaging for judge systems: Polygon (with API upload), BOCA, MOJ, PKG
- [`rbx/box/statements/CLAUDE.md`](rbx/box/statements/CLAUDE.md) -- Statement building: rbxTeX/LaTeX/Jinja pipeline, conversion steps, templates

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
- `contest.rbx.yml`: Contest-level settings
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
