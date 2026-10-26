"""Graders: function-call problems (IOI style).

A grader is compiled together with every solution. In a batch problem it owns
`main()`, reads the test and prints what the checker reads; in a communication
problem it is the stub that talks to the interactor on the contestant's behalf.

Judges see each test behind a hidden header (see `judge_input`), and a batch
grader frames its output with secrets (see `rbx_grader_judge.h`). Both are
generated here, from the required `grader.secret`. Design: docs/plans/2026-10-25-graders-design.md.
"""

import functools
import hashlib
import importlib.resources
import pathlib
import re
from typing import NamedTuple, Optional

import typer

from rbx import console
from rbx.box import package
from rbx.box.schema import CodeItem, Grader, Package, TaskType, Testcase

JUDGE_INPUT_SUFFIX = '.in.judge'
STATEMENT_OUTPUT_SUFFIX = '.out.statement'

# What a grader problem's public run is compiled with: every rbx.h grader
# helper becomes a no-op, so the grader reads the raw input and prints the raw
# answer, as the contestant's copy does.
PUBLIC_DEFINE = '-DRBX_PUBLIC'

_SECRET_BLOCK_RE = re.compile(
    r'^[ \t]*//[ \t]*BEGIN SECRET[ \t]*\n.*?^[ \t]*//[ \t]*END SECRET[ \t]*(?:\n|\Z)',
    re.MULTILINE | re.DOTALL,
)
_RBX_INCLUDE_RE = re.compile(r'^[ \t]*#[ \t]*include[ \t]*["<]rbx\.h[">][^\n]*$', re.M)


class Secrets(NamedTuple):
    input: str
    output: str
    output_end: str


def get_grader() -> Optional[Grader]:
    return package.find_problem_package_or_die().grader


def has_grader(pkg: Optional[Package] = None) -> bool:
    if pkg is None:
        pkg = package.find_problem_package()
    return pkg is not None and pkg.grader is not None


def derive_secret(secret: str, label: str) -> str:
    return hashlib.sha256(f'rbx-grader:{secret}:{label}'.encode()).hexdigest()[:32]


@functools.cache
def get_secrets() -> Secrets:
    """The package's grader secrets, derived from `grader.secret`."""
    grader = package.find_problem_package_or_die().grader
    assert grader is not None
    return Secrets(
        input=derive_secret(grader.secret, 'input'),
        output=derive_secret(grader.secret, 'output'),
        output_end=derive_secret(grader.secret, 'output-end'),
    )


def _read_template(name: str) -> str:
    with importlib.resources.as_file(
        importlib.resources.files('rbx') / 'resources' / 'templates' / name
    ) as file:
        return file.read_text()


def public_helpers() -> str:
    return _read_template('rbx_grader_public.h')


def judge_helpers(secrets: Secrets) -> str:
    return (
        _read_template('rbx_grader_judge.h')
        .replace('{{INPUT_SECRET}}', secrets.input)
        .replace('{{OUTPUT_SECRET}}', secrets.output)
        .replace('{{OUTPUT_END_SECRET}}', secrets.output_end)
    )


def header_block() -> str:
    """What replaces rbx.h's `//<rbx::grader>` sentinel.

    Empty for a problem without a grader. Otherwise the judge helpers, with the
    public ones taking their place under `RBX_PUBLIC`.
    """
    if not has_grader():
        return ''
    return (
        '#ifdef RBX_PUBLIC\n'
        + public_helpers()
        + '#else\n'
        + judge_helpers(get_secrets())
        + '#endif\n'
    )


def public_shim() -> str:
    """The grader-friendly rbx.h, inlined into a public grader in place of rbx.h.

    The public flavour of the grader helpers, the same API as the judge's, plus
    `getGroup()`: no secrets, no vars. Guarded, so a source including rbx.h
    twice still compiles.
    """
    return (
        '// rbx.h, public grader flavour (inlined by rbx).\n'
        '#ifndef RBX_PUBLIC_GRADER_H\n'
        '#define RBX_PUBLIC_GRADER_H\n'
        '#include <cstdio>\n'
        '#include <cstdlib>\n'
        '#include <string>\n'
        '#include <type_traits>\n'
        '#include <utility>\n'
        'namespace rbx {\n'
        'inline const std::string &getGroup() {\n'
        '  static const std::string group;\n'
        '  return group;\n'
        '}\n'
        '} // namespace rbx\n' + public_helpers() + '#endif // RBX_PUBLIC_GRADER_H\n'
    )


_SECRET_MARKER_RE = re.compile(r'//[ \t]*(BEGIN|END)[ \t]+SECRET\b')


class SecretBlockError(ValueError):
    pass


def strip_secret_blocks(source: str) -> str:
    """Remove every `// BEGIN SECRET` ... `// END SECRET` block, markers included.

    A marker left behind (an unmatched BEGIN or END, or one not alone on its
    line) would ship the code it was meant to hide, so it is an error.
    """
    stripped = _SECRET_BLOCK_RE.sub('', source)
    leftover = _SECRET_MARKER_RE.search(stripped)
    if leftover is not None:
        line = stripped.count('\n', 0, leftover.start()) + 1
        raise SecretBlockError(
            f'unmatched `// {leftover.group(1)} SECRET` marker (line {line} after '
            'stripping): every BEGIN needs an END, each alone on its own line'
        )
    return stripped


def make_public_source(source: str) -> str:
    """The contestant version of a grader-side source.

    SECRET blocks are dropped, and `#include "rbx.h"` becomes the public shim,
    so the result is a single file that leaks neither secrets nor vars.
    """
    stripped = strip_secret_blocks(source)
    return _RBX_INCLUDE_RE.sub(lambda _: public_shim().rstrip('\n'), stripped)


def judge_input(raw: bytes, group: Optional[str]) -> bytes:
    """A test as judges see it: the hidden header, then the raw input."""
    secrets = get_secrets()
    return f'{secrets.input}\n{group or ""}\n'.encode() + raw


def judge_input_path(input_path: pathlib.Path) -> pathlib.Path:
    """Where the judge view of a built `NNN.in` lives (`NNN.in.judge`)."""
    return input_path.with_suffix(JUDGE_INPUT_SUFFIX)


def write_judge_input(input_path: pathlib.Path, group: Optional[str]) -> pathlib.Path:
    dest = judge_input_path(input_path)
    dest.write_bytes(judge_input(input_path.read_bytes(), group))
    return dest


def statement_output_path(testcase: Testcase) -> pathlib.Path:
    """Where a built test's public answer lives (`NNN.out.statement`)."""
    return testcase.inputPath.with_suffix(STATEMENT_OUTPUT_SUFFIX)


async def compile_public(model_solution: CodeItem) -> str:
    """Build `model_solution` with the grader under `RBX_PUBLIC`, where every
    helper is a no-op, for `generate_public_output`.

    Compile it once per solution, before generating outputs in parallel: one
    compile per sample would build and store the same binary concurrently.
    """
    from rbx.box import code

    return await code.compile_item(model_solution, extra_flags=[PUBLIC_DEFINE])


async def generate_public_output(
    model_solution: CodeItem, public_digest: str, testcase: Testcase
):
    """Write the answer contestants see for a sample of a batch grader problem.

    `public_digest` is the solution built by `compile_public`. It runs on the
    raw input: the result is the plain answer the public grader prints, with
    no secrets in it. The package's `.ans` keeps the judge's version untouched.
    """
    from rbx.box import code
    from rbx.grading.steps import DigestOrDest, DigestOrSource

    digest = public_digest
    dest = statement_output_path(testcase)
    run_log = await code.run_item(
        model_solution,
        DigestOrSource.create(digest),
        stdin=DigestOrSource.create(testcase.inputPath),
        stdout=DigestOrDest.create(dest),
    )
    if run_log is None or run_log.exitcode != 0:
        console.console.print(
            f'[error]The public run of {model_solution.href()} failed on '
            f'[item]{testcase.inputPath}[/item], so its statement answer could '
            'not be generated.[/error]'
        )
        raise typer.Exit(1)


def framed_output(output_path: pathlib.Path) -> pathlib.Path:
    """A raw answer as a batch grader would have printed it, prologue included.

    For checker inputs a setter writes by hand (checker unit tests): they can't
    spell the prologue themselves, since the secrets are derived. Returns the
    path unchanged for a problem without a batch grader.
    """
    pkg = package.find_problem_package()
    if pkg is None or pkg.grader is None or pkg.type != TaskType.BATCH:
        return output_path
    secrets = get_secrets()
    framed = f'{secrets.output}\n{secrets.output_end}\nOK\n'.encode()
    framed += output_path.read_bytes()
    cache_dir = package.get_problem_cache_dir() / 'framed-outputs'
    cache_dir.mkdir(parents=True, exist_ok=True)
    dest = cache_dir / (hashlib.sha256(framed).hexdigest()[:32] + '.out')
    if not dest.is_file():
        dest.write_bytes(framed)
    return dest


def unframed_output(output_path: pathlib.Path) -> pathlib.Path:
    """An answer without a batch grader's prologue, for tools that read its format.

    Returns the path unchanged when there is no batch grader, or when the file
    does not start with the prologue (a grader verdict, a hand-written answer).
    """
    pkg = package.find_problem_package()
    if pkg is None or pkg.grader is None or pkg.type != TaskType.BATCH:
        return output_path
    secrets = get_secrets()
    prologue = f'{secrets.output}\n{secrets.output_end}\nOK\n'.encode()
    content = output_path.read_bytes()
    if not content.startswith(prologue):
        return output_path
    cache_dir = package.get_problem_cache_dir() / 'unframed-outputs'
    cache_dir.mkdir(parents=True, exist_ok=True)
    body = content[len(prologue) :]
    dest = cache_dir / (hashlib.sha256(body).hexdigest()[:32] + '.out')
    if not dest.is_file():
        dest.write_bytes(body)
    return dest


def run_input(input_path: pathlib.Path) -> pathlib.Path:
    """The input a run hands to the solution, the checker or the interactor.

    A test without a grader runs on its raw input. With one, a built test runs
    on the `.in.judge` written next to it during generation; any other input
    (`rbx run` on a custom file, a stress input) is wrapped on the spot with no
    group, into the problem cache rather than beside the setter's file.
    """
    if not has_grader():
        return input_path
    built = judge_input_path(input_path)
    if built.is_file() and built.stat().st_mtime >= input_path.stat().st_mtime:
        return built
    wrapped = judge_input(input_path.read_bytes(), None)
    cache_dir = package.get_problem_cache_dir() / 'judge-inputs'
    cache_dir.mkdir(parents=True, exist_ok=True)
    # Keyed by the input's path, not its content, so a stress run rewriting
    # one input file over and over reuses one wrapped file.
    key = hashlib.sha256(str(input_path.resolve()).encode()).hexdigest()[:32]
    dest = cache_dir / f'{key}.in'
    if not dest.is_file() or dest.read_bytes() != wrapped:
        dest.write_bytes(wrapped)
    return dest
