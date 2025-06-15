# Installation

You can install {{rbx}} with a single command, either using `pip` or `pipx`. Prefer using `pipx` to have a better isolation between the dependencies. Read more about `pipx` [here](https://pipx.pypa.io/stable/installation/).

## Requirements

- Python 3.9.1 or above (stable with Python 3.10).
- A C++ toolchain to compile {{testlib}} libraries (usually `g++`).
- (Optional):
    - Compilers/interpreters that you need to run your solutions on (e.g. `g++`, `java`).
    - pdfLaTeX and other additional packages to convert TeX files into PDF (see https://www.latex-project.org/get/)

## From PyPI

```bash
$ pipx install rbx.cp
```

## From the repository

```bash
$ git clone https://github.com/rsalesc/rbx
$ cd rbx
$ pipx install .
```

## Verify installation

<!-- termynal -->
```bash
$ rbx --help
# rbx help string should show up here
```

---

Proceed to the [Configuration](configuration.md) section.
