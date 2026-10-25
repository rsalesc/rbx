"""The files contestants download for a problem (`attachments` in problem.rbx.yml).

Packed into one archive per problem, `build/attachments/<problem>.zip`. A file
marked `public: true` is the contestant version of a grader-side source (see
`graders.make_public_source`), compile-checked here so a public grader that
still needs something only the judge has never ships.
"""

import pathlib
import shutil
import subprocess
import tempfile
import zipfile
from typing import Dict, List, Optional

import typer

from rbx import console
from rbx.box import graders, package
from rbx.box.schema import FileAttachment, Package, SamplesAttachment
from rbx.grading import steps

_C_FAMILY = {'.c', '.cc', '.cpp', '.cxx', '.h', '.hh', '.hpp', '.hxx'}
_SOURCES = {'.c', '.cc', '.cpp', '.cxx'}


def _fail(message: str):
    console.console.print(f'[error]{message}[/error]')
    raise typer.Exit(1)


def get_attachments_path() -> pathlib.Path:
    pkg = package.find_problem_package_or_die()
    return package.get_build_path() / 'attachments' / f'{pkg.name}.zip'


def _file_content(attachment: FileAttachment) -> bytes:
    if not attachment.path.is_file():
        _fail(f'Attachment [item]{attachment.path}[/item] not found.')
    if not attachment.public:
        return attachment.path.read_bytes()
    if attachment.path.suffix.lower() not in _C_FAMILY:
        _fail(
            f'Attachment [item]{attachment.path}[/item] is marked [item]public[/item], '
            'which only applies to C/C++ sources.'
        )
    try:
        return graders.make_public_source(attachment.path.read_text()).encode()
    except graders.SecretBlockError as e:
        _fail(f'Cannot derive the public [item]{attachment.path}[/item]: {e}.')
        raise


def _compile_check(files: Dict[str, bytes], public: List[str]):
    """Compile every public C/C++ source alone, with only the archive around it.

    That is exactly what a contestant has: no rbx.h, no vars, no secrets. A
    public grader still reaching for one of them fails here, by name.
    """
    compiler = shutil.which('g++') or shutil.which('clang++')
    if compiler is None:
        console.console.print(
            '[warning]No C++ compiler found: the public attachments were not '
            'compile-checked.[/warning]'
        )
        return
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp) / 'archive'
        root.mkdir()
        for name, content in files.items():
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_bytes(content)
        # Like a judge (and like rbx's own compilation), make <bits/stdc++.h>
        # available, which Apple clang does not ship.
        include_dir = pathlib.Path(tmp) / 'include'
        bits = steps.maybe_get_bits_stdcpp_for_commands([f'{compiler} x.cpp'])
        if bits is not None and bits.src is not None:
            (include_dir / 'bits').mkdir(parents=True, exist_ok=True)
            shutil.copyfile(bits.src, include_dir / 'bits' / 'stdc++.h')
        for name in public:
            if pathlib.Path(name).suffix.lower() not in _SOURCES:
                continue
            result = subprocess.run(
                [compiler, '-std=c++20', '-fsyntax-only', '-I', str(root)]
                + ['-I', str(include_dir), name],
                cwd=root,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                _fail(
                    f'The public attachment [item]{name}[/item] does not compile on '
                    'its own, as contestants receive it. Move code that needs rbx.h '
                    '(getVar, secrets) into a `// BEGIN SECRET` ... `// END SECRET` '
                    f'block, or use a literal.\n{result.stderr.strip()}'
                )


async def _sample_files(attachment: SamplesAttachment) -> Dict[str, bytes]:
    from rbx.box import testcase_sample_utils

    files: Dict[str, bytes] = {}
    samples = await testcase_sample_utils.get_statement_samples()
    for i, sample in enumerate(samples):
        stem = f'{attachment.samples.rstrip("/")}/{i + 1:02d}'
        files[f'{stem}.in'] = sample.inputPath.read_bytes()
        if sample.hasOutput and sample.outputPath.is_file():
            files[f'{stem}.out'] = sample.outputPath.read_bytes()
    return files


async def collect(pkg: Optional[Package] = None) -> Dict[str, bytes]:
    """Every attachment, by its name inside the archive."""
    if pkg is None:
        pkg = package.find_problem_package_or_die()
    files: Dict[str, bytes] = {}
    public: List[str] = []
    for attachment in pkg.attachments:
        if isinstance(attachment, SamplesAttachment):
            new_files = await _sample_files(attachment)
        else:
            new_files = {attachment.archive_name: _file_content(attachment)}
            if attachment.public:
                public.append(attachment.archive_name)
        for name, content in new_files.items():
            if name in files:
                _fail(
                    f'Two attachments are both named [item]{name}[/item] in the archive.'
                )
            files[name] = content
    if public:
        _compile_check(files, public)
    return files


async def build() -> Optional[pathlib.Path]:
    """Write `build/attachments/<problem>.zip`; None for a problem without any."""
    pkg = package.find_problem_package_or_die()
    if not pkg.attachments:
        return None
    files = await collect(pkg)
    dest = get_attachments_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, 'w', zipfile.ZIP_DEFLATED) as zf:
        for name in sorted(files):
            zf.writestr(name, files[name])
    console.console.print(f'Attachments written at [item]{dest}[/item]')
    return dest
