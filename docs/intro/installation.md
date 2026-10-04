# Installation

You can install {{rbx}} with one command, either using `pip`, `pipx` or `uv`. Prefer using `uv` or `pipx` to have a better isolation between the dependencies. See the [`uv` installation guide](https://docs.astral.sh/uv/getting-started/installation/).

## Requirements

- Python 3.10 or newer.
- A C++ toolchain to compile {{testlib}} libraries (usually `g++`). On macOS, see [C/C++ on macOS](../cpp-on-macos.md).
- (Optional):
    - Compilers/interpreters that you need to run your solutions on (for example, `g++`, `java`).
    - pdfLaTeX and other additional packages to convert TeX files into PDF ([install LaTeX](https://www.latex-project.org/get/)).

## From PyPI

```bash
$ uv tool install rbx.cp
```

To upgrade later, install the latest version over it:

```bash
$ uv tool install rbx.cp@latest
```

## From the repository

```bash
$ git clone https://github.com/rsalesc/rbx
$ cd rbx
$ uv tool install .
```

## Verify installation

<!-- termynal -->
```bash
$ rbx --help
# rbx help string should show up here
```

## A note for Windows users

{{rbx}} **is not** supported on Windows. One of the main reasons (but not the only one) is that {{rbx}}
heavily uses symlinks, which is inherently a POSIX feature. Windows supports symlinks only partially.

If you want to use {{rbx}} on Windows, you can do so by using the WSL (Windows Subsystem for Linux). Also,
you'll have to make sure your packages are cloned within the WSL instance and filesystem. Cloning on a Windows
folder using Git-on-Windows and mounting it into the WSL instance **will not work** by default since symlinks
will not be preserved. See [Windows and symlinks](windows-git.md).

---

Proceed to the [First steps](../setters/first-steps.md) section.
