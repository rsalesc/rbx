# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Testing
```bash
# Run all tests
poetry run pytest --ignore=tests/rbx/box/cli

# Run all tests with coverage
poetry run pytest --ignore=tests/rbx/box/cli --cov=rbx --cov-branch --cov-report=xml --junitxml=junit.xml -o junit_family=legacy -n auto

# Run a single test file
poetry run pytest tests/path/to/test_file.py

# Run a specific test
poetry run pytest tests/path/to/test_file.py::test_function_name

# Run tests in parallel
poetry run pytest -n auto
```

### Linting and Formatting
```bash
# Run linter
poetry run ruff check .

# Run linter with auto-fix
poetry run ruff check --fix .

# Format code
poetry run ruff format .

# Run pre-commit hooks
poetry run pre-commit run --all-files
```

### Building
```bash
# Install dependencies
poetry install

# Build the package
poetry build

# Run the CLI tools
poetry run rbc  # Main CLI
poetry run rbx  # Box CLI
```

## Architecture Overview

robox.io (rbx) is a CLI tool for competitive programming problem setters, designed to manage the entire lifecycle of competitive programming problems and contests.

### Core Concepts

1. **Package System**: Problems and contests are organized as self-contained packages
   - Problem Package: Contains solutions, validators, checkers, test cases, and statements
   - Contest Package: A collection of problem packages with contest-level settings

2. **Configuration Files**:
   - `problem.rbx.yml`: Defines problem structure, test cases, solutions, validators
   - `contest.rbx.yml`: Defines contest-level settings
   - `env.rbx.yml`: Language settings, compilation flags, sandbox configuration

3. **Key Components**:
   - **Solutions**: Code files with expected outcomes (AC, WA, TLE, etc.)
   - **Validators**: Ensure test inputs meet problem constraints
   - **Checkers**: Verify if outputs are correct (custom or standard)
   - **Generators**: Create test cases programmatically
   - **Interactors**: For interactive problems

4. **Grading System** (`rbx/grading/judge/`):
   - Sandboxed execution environment for untrusted code
   - Resource limit enforcement (time, memory, output size)
   - Caching system for compilation and execution
   - Multiple outcome types: AC, WA, TLE, RTE, MLE, OLE

5. **Build System**:
   - Test generation from scripts or programs
   - Input validation against constraints
   - Output generation using AC solution
   - Solution verification against expected outcomes

6. **Statement System**:
   - Supports rbxTeX, Markdown, HTML, Jinja templates
   - Multi-language support
   - Variable substitution system
   - Outputs to PDF, HTML, Markdown

### Directory Structure

```
rbx/
├── box/           # Main application logic
│   ├── contest/   # Contest management
│   ├── packaging/ # Package builders for different platforms
│   ├── presets/   # Preset management
│   ├── statements/# Statement building
│   ├── stressing/ # Stress testing
│   ├── testing/   # Testing utilities
│   └── ui/        # Terminal UI components
├── grading/       # Grading and judging logic
│   └── judge/     # Sandbox and execution environment
└── resources/     # Checkers, presets, templates
```

### Key CLI Commands

- `rbx create <name>`: Create new problem
- `rbx edit`: Edit problem configuration
- `rbx build`: Build all tests
- `rbx run`: Run solutions against tests
- `rbx stress`: Stress test to find edge cases
- `rbx statements build`: Build problem statements
- `rbx package build`: Create deployment package

### Development Notes

- Python 3.9.1+ required
- Uses Poetry for dependency management
- Async operations throughout the codebase
- Rich terminal output using Rich library
- Sandboxing uses `StupidSandbox` implementation
- Caching is implemented for compilation and execution

### Testing Best Practices

- Re-use existing pyfixtures, or create one if the testing logic can be reused in various places
- Test behavior, not implementation details. Avoid mocking private functions unless strictly necessary, and use API mocking sparingly. Assert over entire objects and strings where possible (preferrably in a single line assert call)
- Avoid change detector tests.
- Re-use files in the `testdata` folder, or create new ones when necessary, encapsulated inside a folder related to the current test.