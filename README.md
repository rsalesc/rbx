<p align="center">
	<img src="docs/rbx_white.png" alt="rbx" width="200">
</p>

<p align="center">
    <em>The go-to CLI tool for programming competitions setters.</em>
</p>
<p align="center">
	<!-- loscal repository, no metadata badges. -->
<p>
<p align="center">
	<img src="https://img.shields.io/badge/Python-3776AB.svg?style=default&logo=Python&logoColor=white" alt="Python">
	<img src="https://img.shields.io/badge/FastAPI-009688.svg?style=default&logo=FastAPI&logoColor=white" alt="FastAPI">
	<img src="https://img.shields.io/badge/JSON-000000.svg?style=default&logo=JSON&logoColor=white" alt="JSON">
</p>

<br><!-- TABLE OF CONTENTS -->
<details>
  <summary>Table of Contents</summary><br>

- [Overview](#overview)
- [Features](#features)
- [Documentation](#documentation)
- [Contributing](#contributing)
- [License](#license)
</details>
<hr>

##  Overview

<!--[![Usage video]](https://github.com/rsalesc/rbx/assets/4999965/111de01e-6cbd-495e-b8c2-4293921e49b3)-->

[![GitHub license](https://img.shields.io/github/license/rsalesc/rbx.svg)](https://github.com/rsalesc/rbx/blob/master/LICENSE)
[![PyPI pyversions](https://img.shields.io/pypi/pyversions/rbx.svg)](https://pypi.python.org/pypi/rbx/)
[![PyPI version shields.io](https://img.shields.io/pypi/v/rbx.svg)](https://pypi.python.org/pypi/rbx/)

**rbx** is a CLI tool that empowers setters from the competitive programming community.

A flexible setting tool, as powerful as [Polygon](https://polygon.codeforces.com/), right on your terminal.

--- 

## Features

- 🧱 Structure: describe your problem or contest structure with the use of YAML configuration files.
- 🤖 Generation: provides a simple way to describe your whole testset, including both manually added and generated testcases.
- 🔨 Testing: provides commands for automatically running correct and incorrect solutions against the testcases of your problem, automatically judging whether the verdict was as expected or not.
- ✅ Verify: checks if your testcases and solutions are strictly conformant with the use of validators and unit tests.
- 📝 Statements: provides tooling for writing and building statements, also ensuring they're easily synchronized with your testset.
- 📤 Package: provides a single command for packaging your problems for use in your preferred judge system.

---

##  Documentation

You can read the docs [here](https://rsalesc.github.io/rbx/).

---

## Contributing

### Prerequisites

- Python 3.9+
- [uv](https://docs.astral.sh/uv/) — package manager
- [mise](https://mise.jdx.dev/) — task runner

### Getting Started

```bash
git clone https://github.com/rsalesc/rbx.git
cd rbx
mise run sync
pre-commit install
```

### Common Tasks

All development commands are run through `mise`:

| Command | Description |
|---|---|
| `mise run sync` | Install/sync all dependencies |
| `mise run lock` | Regenerate `uv.lock` |
| `mise run lint` | Run linter |
| `mise run lint-fix` | Run linter with auto-fix |
| `mise run format` | Format code |
| `mise run format-check` | Check formatting without changes |
| `mise run check` | Run all checks (lint + format) |
| `mise run test` | Run tests (excludes e2e/slow/docker) |
| `mise run test-cov` | Run tests with coverage |
| `mise run test-e2e` | Run e2e tests |
| `mise run build` | Clean build the package |

Run `mise tasks` to see all available tasks.

### Code Style

- **Single quotes** for strings
- **Absolute imports only** — no relative imports
- **Conventional Commits** — enforced by pre-commit hook

All style rules are enforced automatically by pre-commit hooks (ruff check, ruff format, commitizen).

### Submitting Changes

1. Create a branch from `main`
2. Make your changes
3. Run `mise run check` and `mise run test`
4. Commit using [Conventional Commits](https://www.conventionalcommits.org/) format
5. Open a pull request

---

##  License

This project is protected under the [Apache License 2.0](http://www.apache.org/licenses/) License. For more details, refer to the [LICENSE](LICENSE) file.

---

[**Return**](#-overview)

---
