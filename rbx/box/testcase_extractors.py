import abc
import pathlib
import shlex
from typing import Iterable, List, Optional, Set, Tuple

import typer
from pydantic import BaseModel

from rbx import console
from rbx.box import package
from rbx.box.code import compile_item, run_item
from rbx.box.schema import CodeItem, GeneratorCall, Testcase, TestcaseSubgroup
from rbx.box.testcase_utils import (
    TestcaseEntry,
    TestcasePattern,
    fill_output_for_defined_testcase,
)
from rbx.grading.steps import DigestHolder, DigestOrDest, DigestOrSource


def _get_group_input(
    group_path: pathlib.Path, subgroup_prefix: str, i: int
) -> pathlib.Path:
    return group_path / f'{subgroup_prefix}{i:03d}.in'


def _get_group_output(
    group_path: pathlib.Path, subgroup_prefix: str, i: int
) -> pathlib.Path:
    return group_path / f'{subgroup_prefix}{i:03d}.out'


async def _run_generator_script(testcase: TestcaseSubgroup) -> str:
    assert testcase.generatorScript is not None

    cacher = package.get_file_cacher()

    if not testcase.generatorScript.path.is_file():
        console.console.print(
            f'[error]Generator script not found: [item]{testcase.generatorScript.path}[/item][/error]'
        )
        raise typer.Exit(1)

    script_digest = DigestHolder()
    if testcase.generatorScript.path.suffix == '.txt':
        script_digest.value = cacher.put_file_from_path(testcase.generatorScript.path)
    else:
        try:
            compiled_digest = compile_item(testcase.generatorScript)
        except:
            console.console.print(
                f'[error]Failed compiling generator script for group [item]{testcase.name}[/item].[/error]'
            )
            raise

        run_stderr = DigestHolder()
        run_log = await run_item(
            testcase.generatorScript,
            DigestOrSource.create(compiled_digest),
            stdout=DigestOrDest.create(script_digest),
            stderr=DigestOrDest.create(run_stderr),
        )

        if run_log is None or run_log.exitcode != 0:
            console.console.print(
                f'Could not run generator script for group {testcase.name}'
            )
            if run_log is not None:
                console.console.print(
                    f'[error]Summary:[/error] {run_log.get_summary()}'
                )
            if run_stderr.value is not None:
                console.console.print('[error]Stderr:[/error]')
                console.console.print(
                    package.get_digest_as_string(run_stderr.value) or ''
                )
            raise typer.Exit(1)

    assert script_digest.value
    script = cacher.get_file_content(script_digest.value).decode()
    return script


def _extract_script_lines(script: str) -> Iterable[Tuple[str, str, int]]:
    lines = script.splitlines()
    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        if line.startswith('#'):
            continue
        yield shlex.split(line)[0], shlex.join(shlex.split(line)[1:]), i + 1


class GeneratorScriptEntry(BaseModel):
    path: pathlib.Path
    line: int

    def __str__(self) -> str:
        return f'{self.path}:{self.line}'


class GenerationMetadata(BaseModel):
    copied_to: Testcase

    copied_from: Optional[Testcase] = None
    generator_call: Optional[GeneratorCall] = None
    generator_script: Optional[GeneratorScriptEntry] = None


class GenerationTestcaseEntry(BaseModel):
    group_entry: TestcaseEntry
    subgroup_entry: TestcaseEntry

    metadata: GenerationMetadata
    validator: Optional[CodeItem] = None
    extra_validators: List[CodeItem] = []


class TestcaseVisitor(abc.ABC):
    @abc.abstractmethod
    async def visit(self, entry: GenerationTestcaseEntry):
        pass

    def should_visit_group(self, group_name: str) -> bool:
        return True

    def should_visit_subgroup(self, subgroup_path: str) -> bool:
        return True

    def should_visit_generator_scripts(
        self, group_name: str, subgroup_path: str
    ) -> bool:
        return True


class TestcaseGroupVisitor(TestcaseVisitor):
    def __init__(self, groups: Optional[Set[str]] = None):
        self.groups = groups

    def should_visit_group(self, group_name: str) -> bool:
        return self.groups is None or group_name in self.groups


async def run_testcase_visitor(visitor: TestcaseVisitor):
    pkg = package.find_problem_package_or_die()

    async def _explore_subgroup(
        subgroup: TestcaseSubgroup,
        subgroup_index: Optional[int],
        prefix: List[str],
        validator: Optional[CodeItem] = None,
        extra_validators: Optional[List[CodeItem]] = None,
    ):
        extra_validators = extra_validators or []

        assert prefix and len(prefix) >= 1 and len(prefix) <= 2
        group_path = prefix[0]
        subgroup_path = '/'.join(prefix)
        if not visitor.should_visit_subgroup(subgroup_path):
            return

        def _entry(i: int) -> TestcaseEntry:
            return TestcaseEntry(group=group_path, index=i)

        def _sub_entry(i: int) -> TestcaseEntry:
            return TestcaseEntry(group=subgroup_path, index=i)

        def _copied_to(i: int) -> Testcase:
            group_fs_path = package.get_build_testgroup_path(group_path)
            group_prefix = ''
            if subgroup_index is not None:
                group_prefix = f'{subgroup_index}-'
            if len(prefix) == 2:
                group_prefix += f'{prefix[1]}-'
            return Testcase(
                inputPath=_get_group_input(group_fs_path, group_prefix, i),
                outputPath=_get_group_output(group_fs_path, group_prefix, i),
            )

        # Go through testcases.
        i = 0
        # Individual testcases.
        for tc in subgroup.testcases or []:
            await visitor.visit(
                GenerationTestcaseEntry(
                    group_entry=_entry(i),
                    subgroup_entry=_sub_entry(i),
                    metadata=GenerationMetadata(
                        copied_from=fill_output_for_defined_testcase(tc),
                        copied_to=_copied_to(i),
                    ),
                    validator=validator,
                    extra_validators=extra_validators,
                )
            )
            i += 1

        # Glob testcases.
        if subgroup.testcaseGlob:
            matched_inputs = sorted(pathlib.PosixPath().glob(subgroup.testcaseGlob))

            for input_path in matched_inputs:
                if not input_path.is_file() or input_path.suffix != '.in':
                    continue

                tc = Testcase(inputPath=input_path)
                await visitor.visit(
                    GenerationTestcaseEntry(
                        group_entry=_entry(i),
                        subgroup_entry=_sub_entry(i),
                        metadata=GenerationMetadata(
                            copied_from=fill_output_for_defined_testcase(tc),
                            copied_to=_copied_to(i),
                        ),
                        validator=validator,
                        extra_validators=extra_validators,
                    )
                )
                i += 1

        # Single generators.
        for generator_call in subgroup.generators:
            await visitor.visit(
                GenerationTestcaseEntry(
                    group_entry=_entry(i),
                    subgroup_entry=_sub_entry(i),
                    metadata=GenerationMetadata(
                        generator_call=generator_call,
                        copied_to=_copied_to(i),
                    ),
                    validator=validator,
                    extra_validators=extra_validators,
                )
            )
            i += 1

        if not visitor.should_visit_generator_scripts(group_path, subgroup_path):
            return

        # Run generator script.
        if subgroup.generatorScript is not None:
            script = await _run_generator_script(subgroup)

            # Run each line from generator script.
            for generator_name, args, line_number in _extract_script_lines(script):
                call = GeneratorCall(name=generator_name, args=args)
                await visitor.visit(
                    GenerationTestcaseEntry(
                        group_entry=_entry(i),
                        subgroup_entry=_sub_entry(i),
                        metadata=GenerationMetadata(
                            generator_call=call,
                            generator_script=GeneratorScriptEntry(
                                path=subgroup.generatorScript.path,
                                line=line_number,
                            ),
                            copied_to=_copied_to(i),
                        ),
                        validator=validator,
                        extra_validators=extra_validators,
                    )
                )
                i += 1

    for group in pkg.testcases:
        if not visitor.should_visit_group(group.name):
            continue

        group_validator = pkg.validator
        if group.validator is not None:
            group_validator = group.validator

        extra_validators = group.extraValidators
        await _explore_subgroup(
            group,
            0 if group.subgroups else None,
            [group.name],
            validator=group_validator,
            extra_validators=extra_validators,
        )

        for i, subgroup in enumerate(group.subgroups):
            await _explore_subgroup(
                subgroup,
                i + 1,
                [group.name, subgroup.name],
                validator=group_validator,
                extra_validators=extra_validators + subgroup.extraValidators,
            )


async def extract_generation_testcases(
    entries: List[TestcaseEntry],
) -> List[GenerationTestcaseEntry]:
    # TODO: support subgroups.
    groups = set(entry.group for entry in entries)
    entry_keys = set(entry.key() for entry in entries)

    res: List[GenerationTestcaseEntry] = []

    class ExtractGenerationTestcasesVisitor(TestcaseVisitor):
        def should_visit_group(self, group_name: str) -> bool:
            return group_name in groups

        async def visit(self, entry: GenerationTestcaseEntry):
            # TODO: support subgroups.
            if entry.group_entry.key() not in entry_keys:
                return
            res.append(entry)

    await run_testcase_visitor(ExtractGenerationTestcasesVisitor())
    return res


async def extract_generation_testcases_from_groups(
    groups: Optional[Set[str]] = None,
) -> List[GenerationTestcaseEntry]:
    res: List[GenerationTestcaseEntry] = []

    class ExtractGenerationTestcasesVisitor(TestcaseGroupVisitor):
        async def visit(self, entry: GenerationTestcaseEntry):
            res.append(entry)

    await run_testcase_visitor(ExtractGenerationTestcasesVisitor(groups))
    return res


async def extract_generation_testcases_from_patterns(
    patterns: List[TestcasePattern],
) -> List[GenerationTestcaseEntry]:
    res: List[GenerationTestcaseEntry] = []

    class ExtractGenerationTestcasesVisitor(TestcaseVisitor):
        def should_visit_group(self, group_name: str) -> bool:
            return any(pattern.intersecting_group(group_name) for pattern in patterns)

        def should_visit_subgroup(self, subgroup_path: str) -> bool:
            return any(
                pattern.intersecting_group(subgroup_path) for pattern in patterns
            )

        async def visit(self, entry: GenerationTestcaseEntry):
            if not any(
                pattern.match(entry.group_entry) for pattern in patterns
            ) and not any(pattern.match(entry.subgroup_entry) for pattern in patterns):
                return
            res.append(entry)

    await run_testcase_visitor(ExtractGenerationTestcasesVisitor())
    return res
