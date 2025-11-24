import abc
import pathlib
from typing import Iterable, List, Optional, Set

import typer

from rbx import console, utils
from rbx.box import package
from rbx.box.code import compile_item, run_item
from rbx.box.generation_schema import (
    GenerationInput,
    GenerationMetadata,
    GenerationTestcaseEntry,
    GeneratorScriptEntry,
    TestcaseOrScriptEntry,
)
from rbx.box.generator_script_handlers import (
    GeneratorScriptHandlerParams,
    get_generator_script_handler,
)
from rbx.box.schema import (
    CodeItem,
    GeneratorCall,
    GeneratorScript,
    Solution,
    Testcase,
    TestcaseSubgroup,
)
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


async def run_generator_script(testcase: TestcaseSubgroup) -> str:
    assert testcase.generatorScript is not None

    cacher = package.get_file_cacher()

    if not testcase.generatorScript.path.is_file():
        console.console.print(
            f'[error]Generator script not found: [item]{testcase.generatorScript.href()}[/item][/error]'
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


def _resolve_generator_name(generator_name: str, script_entry: GeneratorScript) -> str:
    if generator_name.startswith('@'):
        console.console.print(
            f'[error]Invalid generator name: {generator_name}[/error]'
        )
        raise typer.Exit(1)

    if package.get_generator_or_nil(generator_name) is not None:
        return generator_name
    return str(script_entry.root / generator_name)


def _extract_script_lines(
    script: str, script_entry: GeneratorScript, group: Optional[str] = None
) -> Iterable[GenerationInput]:
    return get_generator_script_handler(
        script, GeneratorScriptHandlerParams(script_entry, group)
    ).parse()


def get_testcase_metadata_markup(entry: GenerationTestcaseEntry) -> str:
    lines = []
    lines.append(
        f'[b bright_white]{entry.group_entry.group}[/b bright_white] / [b bright_white]{entry.group_entry.index}[/b bright_white]'
    )
    lines.append(get_generation_metadata_markup(entry.metadata))
    return '\n'.join(lines)


def get_generation_metadata_markup(metadata: GenerationMetadata) -> str:
    lines = []
    if metadata.copied_from is not None:
        lines.append(
            f'[b bright_white]Copied from:[/b bright_white] {metadata.copied_from.inputPath}'
        )
    if metadata.generator_call is not None:
        lines.append(
            f'[b bright_white]Gen. call:[/b bright_white] {utils.escape_markup(str(metadata.generator_call))}'
        )
    if metadata.generator_script is not None:
        lines.append(
            f'[b bright_white]Gen. script:[/b bright_white] {utils.escape_markup(str(metadata.generator_script))}'
        )
    return '\n'.join(lines)


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
        output_validators: Optional[List[CodeItem]] = None,
        model_solution: Optional[Solution] = None,
    ):
        extra_validators = package.get_globbed_code_items(
            extra_validators or [],
            preexisting_items=[validator] if validator is not None else None,
        )
        output_validators = package.get_globbed_code_items(output_validators or [])

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
                    model_solution=model_solution,
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
                        output_validators=output_validators,
                        model_solution=model_solution,
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
                    output_validators=output_validators,
                    model_solution=model_solution,
                )
            )
            i += 1

        if not visitor.should_visit_generator_scripts(group_path, subgroup_path):
            return

        # Run generator script.
        if subgroup.generatorScript is not None:
            script = await run_generator_script(subgroup)

            # Run each line from generator script.
            for generation_input in _extract_script_lines(
                script, subgroup.generatorScript, group_path
            ):
                if generation_input.copied_from is not None:
                    metadata = GenerationMetadata(
                        copied_from=fill_output_for_defined_testcase(
                            generation_input.copied_from
                        ),
                        copied_to=_copied_to(i),
                        generator_script=generation_input.generator_script,
                    )
                elif generation_input.generator_call is not None:
                    call = GeneratorCall(
                        name=_resolve_generator_name(
                            generation_input.generator_call.name,
                            subgroup.generatorScript,
                        ),
                        args=generation_input.generator_call.args,
                    )
                    metadata = GenerationMetadata(
                        generator_call=call,
                        generator_script=generation_input.generator_script,
                        copied_to=_copied_to(i),
                    )
                elif generation_input.content is not None:
                    metadata = GenerationMetadata(
                        content=generation_input.content,
                        generator_script=generation_input.generator_script,
                        copied_to=_copied_to(i),
                    )
                else:
                    raise ValueError(f'Invalid generation input: {generation_input}')
                await visitor.visit(
                    GenerationTestcaseEntry(
                        group_entry=_entry(i),
                        subgroup_entry=_sub_entry(i),
                        metadata=metadata,
                        validator=validator,
                        extra_validators=extra_validators,
                        output_validators=output_validators,
                        model_solution=model_solution,
                    )
                )
                i += 1

    for group in pkg.testcases:
        if not visitor.should_visit_group(group.name):
            continue

        group_validator = pkg.validator
        if group.validator is not None:
            group_validator = group.validator

        extra_validators = pkg.extraValidators + group.extraValidators
        output_validators = pkg.outputValidators + group.outputValidators
        await _explore_subgroup(
            group,
            0 if group.subgroups else None,
            [group.name],
            validator=group_validator,
            extra_validators=extra_validators,
            output_validators=output_validators,
            model_solution=group.model_solution,
        )

        for i, subgroup in enumerate(group.subgroups):
            await _explore_subgroup(
                subgroup,
                i + 1,
                [group.name, subgroup.name],
                validator=group_validator,
                extra_validators=extra_validators + subgroup.extraValidators,
                output_validators=output_validators + subgroup.outputValidators,
                model_solution=group.model_solution,
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


async def extract_generation_testcases_from_generic_entries(
    entries: List[TestcaseOrScriptEntry],
) -> List[GenerationTestcaseEntry]:
    res: List[GenerationTestcaseEntry] = []
    entry_keys = set(
        entry.key() for entry in entries if isinstance(entry, TestcaseEntry)
    )
    script_entry_keys = set(
        entry for entry in entries if isinstance(entry, GeneratorScriptEntry)
    )

    class ExtractGenerationTestcasesVisitor(TestcaseVisitor):
        async def visit(self, entry: GenerationTestcaseEntry):
            if entry.group_entry.key() in entry_keys:
                res.append(entry)
                return
            script_entry = entry.metadata.generator_script
            if script_entry is not None and script_entry in script_entry_keys:
                res.append(entry)
                return

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
