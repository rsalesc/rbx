"""The files contestants download for a problem (`attachments` in problem.rbx.yml).

Packed into one archive per problem, `build/attachments/<problem>.zip`. A file
marked `stripSecret: true` is the contestant version of a grader-side source (see
`graders.make_public_source`), compile-checked here so a public grader that
still needs something only the judge has never ships.
"""

import pathlib
import shutil
import zipfile
from typing import Dict, List, Optional

import typer

from rbx import console
from rbx.box import graders, package
from rbx.box.schema import FileAttachment, Package, SamplesAttachment
from rbx.grading import steps

_SOURCES = {'.c', '.cc', '.cpp', '.cxx'}
_HEADERS = {'.h', '.hh', '.hpp', '.hxx'}
_C_FAMILY = _SOURCES | _HEADERS


def _fail(message: str):
    console.console.print(f'[error]{message}[/error]')
    raise typer.Exit(1)


def get_attachments_path() -> pathlib.Path:
    pkg = package.find_problem_package_or_die()
    return package.get_build_path() / 'attachments' / f'{pkg.name}.zip'


def _file_content(attachment: FileAttachment) -> bytes:
    if not attachment.path.is_file():
        _fail(f'Attachment [item]{attachment.path}[/item] not found.')
    if not attachment.stripSecret:
        return attachment.path.read_bytes()
    if attachment.path.suffix.lower() not in _C_FAMILY:
        _fail(
            f'Attachment [item]{attachment.path}[/item] is marked '
            '[item]stripSecret[/item], which only applies to C/C++ sources.'
        )
    try:
        return graders.make_public_source(attachment.path.read_text()).encode()
    except graders.SecretBlockError as e:
        _fail(f'Cannot derive the public [item]{attachment.path}[/item]: {e}.')
        raise


async def _compile_check(files: Dict[str, bytes], stripped: List[str]):
    """Compile every stripped C/C++ source with only the archive around it.

    That is exactly what a contestant has: no rbx.h, no vars, no secrets. A
    public grader still reaching for one of them fails here, by name. It goes
    through `code.compile_item`, so the language and commands are the ones
    `env.rbx.yml` declares; `-c`, since the contestant's functions are missing.
    """
    from rbx.box import code
    from rbx.box.schema import CodeItem

    check_dir = package.get_build_path() / 'attachments' / '.check'
    shutil.rmtree(check_dir, ignore_errors=True)
    for name, content in files.items():
        (check_dir / name).parent.mkdir(parents=True, exist_ok=True)
        (check_dir / name).write_bytes(content)
    headers = [
        str(check_dir / name)
        for name in files
        if pathlib.Path(name).suffix.lower() in _HEADERS
    ]
    for name in stripped:
        if pathlib.Path(name).suffix.lower() not in _SOURCES:
            continue
        item = CodeItem(path=check_dir / name, compilationFiles=headers)
        try:
            await code.compile_item(item, extra_flags=['-c'])
        except steps.CompilationError:
            _fail(
                f'The attachment [item]{name}[/item] does not compile on its own, '
                'as contestants receive it. Move code that needs rbx.h (getVar, '
                'secrets) into a `// BEGIN SECRET` ... `// END SECRET` block, or '
                'use a literal.'
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
    stripped: List[str] = []
    for attachment in pkg.attachments:
        if isinstance(attachment, SamplesAttachment):
            new_files = await _sample_files(attachment)
        else:
            new_files = {attachment.archive_name: _file_content(attachment)}
            if attachment.stripSecret:
                stripped.append(attachment.archive_name)
        for name, content in new_files.items():
            if name in files:
                _fail(
                    f'Two attachments are both named [item]{name}[/item] in the archive.'
                )
            files[name] = content
    if stripped:
        await _compile_check(files, stripped)
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
