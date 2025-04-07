import pathlib
import shlex
from typing import Dict, Iterable, List, Optional, Set, Tuple

import typer
from pydantic import BaseModel

from rbx import console
from rbx.box import package
from rbx.box.code import SanitizationLevel, compile_item, run_item
from rbx.box.schema import CodeItem, Primitive
from rbx.box.testcase_extractors import (
    GenerationTestcaseEntry,
    extract_generation_testcases_from_groups,
)
from rbx.grading.judge.sandbox import SandboxBase
from rbx.grading.steps import (
    DigestHolder,
    DigestOrDest,
    DigestOrSource,
    GradingFileOutput,
)
from rbx.utils import StatusProgress

HitBounds = Dict[str, Tuple[bool, bool]]


class TestcaseValidationInfo(BaseModel):
    validator: CodeItem
    group: str
    path: pathlib.Path
    ok: bool
    hit_bounds: HitBounds
    message: Optional[str] = None


def _compile_validator(validator: CodeItem) -> str:
    try:
        digest = compile_item(validator, sanitized=SanitizationLevel.PREFER)
    except:
        console.console.print(
            f'[error]Failed compiling validator [item]{validator.path}[/item][/error]'
        )
        raise
    return digest


def _bounds_or(lhs: Tuple[bool, bool], rhs: Tuple[bool, bool]) -> Tuple[bool, bool]:
    return (lhs[0] or rhs[0], lhs[1] or rhs[1])


def _process_bounds(log: str) -> HitBounds:
    bounds: HitBounds = {}
    for line in log.splitlines():
        items = line.split(':')
        if len(items) != 2:
            continue
        k, v = items
        v = v.strip()

        if 'constant-bounds' in k:
            continue

        hit = ('min-value-hit' in v, 'max-value-hit' in v)
        if k not in bounds:
            bounds[k] = hit
            continue
        bounds[k] = _bounds_or(bounds[k], hit)
    return bounds


def _merge_hit_bounds(hit_bounds: Iterable[HitBounds]) -> HitBounds:
    res: HitBounds = {}
    for hb in hit_bounds:
        for k, hit in hb.items():
            if k not in res:
                res[k] = hit
                continue
            res[k] = _bounds_or(res[k], hit)
    return res


def _has_group_specific_validator() -> bool:
    pkg = package.find_problem_package_or_die()

    return any(group.validator is not None for group in pkg.testcases)


async def _validate_testcase(
    testcase: pathlib.Path,
    validator: CodeItem,
    validator_digest: str,
    vars: Optional[Dict[str, Primitive]] = None,
) -> Tuple[bool, Optional[str], HitBounds]:
    vars = vars or {}
    for var in vars:
        assert (
            var.isidentifier()
        ), f'Variable {var} should be a valid Python identifier.'
    # TODO: check if needs to do some escaping
    var_args = [f'--{k}={v}' for k, v in vars.items()]
    var_args.extend(['--testOverviewLogFileName', 'validator.log'])

    message_digest = DigestHolder()
    log_digest = DigestHolder()
    run_log = await run_item(
        validator,
        DigestOrSource.create(validator_digest),
        stdin=DigestOrSource.create(testcase),
        stderr=DigestOrDest.create(message_digest),
        outputs=[
            GradingFileOutput(
                src=pathlib.Path('validator.log'),
                digest=log_digest,
                optional=True,
            )
        ],
        extra_args=shlex.join(var_args) if var_args else None,
    )

    if (
        run_log is not None
        and run_log.exitcode != 0
        and run_log.exitstatus != SandboxBase.EXIT_NONZERO_RETURN
    ):
        console.console.print(
            f'[error]Validator [item]{validator.path}[/item] failed unexpectedly.[/error]'
        )
        console.console.print(f'[error]Summary:[/error] {run_log.get_summary()}')
        raise typer.Exit(1)

    log_overview = ''
    if log_digest.value is not None:
        log_overview = package.get_digest_as_string(log_digest.value or '')
    message = package.get_digest_as_string(message_digest.value or '')
    return (
        run_log is not None and run_log.exitcode == 0,
        message,
        _process_bounds(log_overview or ''),
    )


async def _validate_test(
    testcase: pathlib.Path,
    validator: CodeItem,
    validator_digest: str,
) -> Tuple[bool, Optional[str], HitBounds]:
    pkg = package.find_problem_package_or_die()
    return await _validate_testcase(
        testcase, validator, validator_digest, vars=pkg.expanded_vars
    )


def compile_main_validator() -> Optional[Tuple[CodeItem, str]]:
    pkg = package.find_problem_package_or_die()
    if pkg.validator is None:
        return None

    return pkg.validator, _compile_validator(pkg.validator)


async def validate_one_off(
    testcase: pathlib.Path,
    validator: CodeItem,
    validator_digest: str,
) -> TestcaseValidationInfo:
    ok, message, _ = await _validate_test(testcase, validator, validator_digest)
    info = TestcaseValidationInfo(
        validator=validator,
        group='interactive',
        path=testcase,
        ok=ok,
        hit_bounds={},
        message=message,
    )
    return info


def compile_validators(
    validators: List[CodeItem],
    progress: Optional[StatusProgress] = None,
) -> Dict[str, str]:
    validator_to_compiled_digest = {}

    validator_to_compiled_digest = {}

    for validator in validators:
        if str(validator.path) in validator_to_compiled_digest:
            continue

        if progress:
            progress.update(f'Compiling validator [item]{validator.path}[/item]...')
        validator_to_compiled_digest[str(validator.path)] = _compile_validator(
            validator
        )

    return validator_to_compiled_digest


def compile_validators_for_entries(
    validation_entries: List[GenerationTestcaseEntry],
    progress: Optional[StatusProgress] = None,
) -> Dict[str, str]:
    validators = []

    for entry in validation_entries:
        if entry.validator is not None:
            validators.append(entry.validator)
        validators.extend(entry.extra_validators)

    return compile_validators(validators, progress=progress)


async def validate_testcases(
    progress: Optional[StatusProgress] = None,
    groups: Optional[Set[str]] = None,
) -> List[TestcaseValidationInfo]:
    def step():
        if progress is not None:
            progress.step()

    validation_entries = await extract_generation_testcases_from_groups(groups)
    validator_to_compiled_digest = compile_validators_for_entries(
        validation_entries, progress=progress
    )

    validation_info = []

    for entry in validation_entries:
        input_path = entry.metadata.copied_to.inputPath
        if not input_path.is_file():
            continue

        # Main validation.
        if entry.validator is not None:
            compiled_digest = validator_to_compiled_digest[str(entry.validator.path)]
            ok, message, hit_bounds = await _validate_test(
                input_path, entry.validator, compiled_digest
            )
            validation_info.append(
                TestcaseValidationInfo(
                    validator=entry.validator,
                    group=entry.group_entry.group,
                    path=input_path,
                    ok=ok,
                    hit_bounds=hit_bounds,
                    message=message,
                )
            )

        for extra_validator in entry.extra_validators:
            compiled_digest = validator_to_compiled_digest[str(extra_validator.path)]
            ok, message, hit_bounds = await _validate_test(
                input_path, extra_validator, compiled_digest
            )
            validation_info.append(
                TestcaseValidationInfo(
                    validator=extra_validator,
                    group=entry.group_entry.group,
                    path=input_path,
                    ok=ok,
                    hit_bounds=hit_bounds,
                    message=message,
                )
            )

        step()

    return validation_info


def has_validation_errors(infos: List[TestcaseValidationInfo]) -> bool:
    return any(not info.ok for info in infos)


def print_validation_report(infos: List[TestcaseValidationInfo]):
    console.console.rule('Validation report', style='status')
    hit_bounds_per_group: Dict[Optional[str], HitBounds] = {}
    any_failure = False
    for info in infos:
        if not info.ok:
            console.console.print(
                f'[error]Testcase [item]{info.path}[/item] failed verification on validator [item]{info.validator.path}[/item]:[/error]'
            )
            console.console.print(info.message)
            any_failure = True
            continue

        if info.group not in hit_bounds_per_group:
            hit_bounds_per_group[info.group] = {}
        hit_bounds_per_group[info.group] = _merge_hit_bounds(
            [hit_bounds_per_group[info.group], info.hit_bounds]
        )

    if not hit_bounds_per_group:
        console.console.print()
        return

    if not _has_group_specific_validator():
        hit_bounds_per_group = {None: _merge_hit_bounds(hit_bounds_per_group.values())}

    def _is_hit_bound_good(hit_bounds: HitBounds) -> bool:
        return any(not v[0] or not v[1] for v in hit_bounds.values())

    # Cleanup entries in hit bounds per group that are totally empty.
    # Also skip samples.
    hit_bounds_per_group = {
        k: v
        for k, v in hit_bounds_per_group.items()
        if _is_hit_bound_good(v) and k != 'samples'
    }

    all_groups = set(info.group for info in infos)
    if len(all_groups) == 1 and 'samples' in all_groups:
        # If there's only the samples group, do not check for hit bounds.
        hit_bounds_per_group = {}

    if not hit_bounds_per_group and not any_failure:
        console.console.print('[info]No validation issues found.[/info]')
        return

    for group, hit_bounds in hit_bounds_per_group.items():
        if group is None:
            console.console.print('Hit bounds:')
        else:
            console.console.print(f'Group [item]{group}[/item] hit bounds:')

        for k, v in hit_bounds.items():
            if all(v):
                continue

            if not v[0]:
                console.console.print(
                    f'  - {k}: [warning]min-value not hit[/warning]',
                )
            if not v[1]:
                console.console.print(
                    f'  - {k}: [warning]max-value not hit[/warning]',
                )
        console.console.print()
