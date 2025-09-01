# Installation

You can install {{rbx}} with a single command, either using `pip`, `pipx` or `uv`. Prefer using `uv` or `pipx` to have a better isolation between the dependencies. Read more about how to install and use `uv` [here](https://docs.astral.sh/uv/getting-started/installation/).

## Requirements

- Python 3.9.1 or above (stable with Python 3.10).
- A C++ toolchain to compile {{testlib}} libraries (usually `g++`).
- (Optional):
    - Compilers/interpreters that you need to run your solutions on (e.g. `g++`, `java`).
    - pdfLaTeX and other additional packages to convert TeX files into PDF (see https://www.latex-project.org/get/)

## From PyPI

```bash
$ uv tool install rbx.cp
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
heavily uses symlinks, which is inherently a POSIX feature, and even though it's been implemented in Windows
recently, it's not yet perfectly supported.

If you want to use {{rbx}} on Windows, you can do so by using the WSL (Windows Subsystem for Linux). Also,
you'll have to make sure your packages are cloned within the WSL instance and filesystem. Cloning on a Windows
folder and mounting it into the WSL instance **will not work** since symlinks will not be preserved.

---

Proceed to the [Configuration](configuration.md) section.
