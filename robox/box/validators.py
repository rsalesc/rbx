import pathlib
import shlex
from typing import Dict, List, Optional, Set, Tuple

from pydantic import BaseModel

from robox import console
from robox.box import package
from robox.box.code import compile_item, run_item
from robox.box.schema import CodeItem, Primitive
from robox.box.testcases import find_built_testcase_inputs
from robox.grading.steps import (
    DigestHolder,
    DigestOrDest,
    DigestOrSource,
    GradingFileOutput,
)
from robox.utils import StatusProgress

HitBounds = Dict[str, Tuple[bool, bool]]


class TestcaseValidationInfo(BaseModel):
    group: str
    path: pathlib.Path
    ok: bool
    hit_bounds: HitBounds
    message: Optional[str] = None


def _compile_validator(validator: CodeItem) -> str:
    try:
        digest = compile_item(validator)
    except:
        console.console.print(
            f'[error]Failed compiling validator [item]{validator.path}[/item].[/error]'
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
        k = k[1:-1]
        v = v.strip()

        hit = ('min-value-hit' in v, 'max-value-hit' in v)
        if k not in bounds:
            bounds[k] = hit
            continue
        bounds[k] = _bounds_or(bounds[k], hit)
    return bounds


def _validate_testcase(
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
    run_log = run_item(
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
    log_overview = ''
    if log_digest.value is not None:
        log_overview = package.get_digest_as_string(log_digest.value or '')
    message = package.get_digest_as_string(message_digest.value or '')
    return (
        run_log is not None and run_log.exitcode == 0,
        message,
        _process_bounds(log_overview or ''),
    )


def validate_test(
    testcase: pathlib.Path,
    validator: CodeItem,
    validator_digest: str,
) -> Tuple[bool, Optional[str], HitBounds]:
    pkg = package.find_problem_package_or_die()
    return _validate_testcase(
        testcase, validator, validator_digest, vars=pkg.expanded_vars
    )


def compile_main_validator() -> Optional[Tuple[CodeItem, str]]:
    pkg = package.find_problem_package_or_die()
    if pkg.validator is None:
        return None

    return pkg.validator, _compile_validator(pkg.validator)


def compile_validators(
    progress: Optional[StatusProgress] = None,
) -> Dict[str, str]:
    pkg = package.find_problem_package_or_die()

    group_to_compiled_digest = {}

    for group in pkg.testcases:
        validator = group.validator or pkg.validator
        if validator is None:
            continue
        if progress:
            progress.update(
                f'Compiling validator for group [item]{group.name}[/item]...'
            )
        group_to_compiled_digest[group.name] = _compile_validator(validator)

    return group_to_compiled_digest


def validate_testcases(
    progress: Optional[StatusProgress] = None,
    groups: Optional[Set[str]] = None,
) -> List[TestcaseValidationInfo]:
    def step():
        if progress is not None:
            progress.step()

    pkg = package.find_problem_package_or_die()

    group_to_compiled_digest = compile_validators(progress)

    validation_info = []

    for group in pkg.testcases:
        validator = group.validator or pkg.validator
        if validator is None:
            continue
        if group.name not in group_to_compiled_digest:
            continue
        if groups is not None and group.name not in groups:
            continue
        compiled_digest = group_to_compiled_digest[group.name]

        testcases = find_built_testcase_inputs(group)

        for testcase in testcases:
            ok, message, hit_bounds = validate_test(
                testcase, validator, compiled_digest
            )
            validation_info.append(
                TestcaseValidationInfo(
                    group=group.name,
                    path=testcase,
                    ok=ok,
                    hit_bounds=hit_bounds,
                    message=message,
                )
            )
            step()

    return validation_info


def print_validation_report(infos: List[TestcaseValidationInfo]):
    console.console.rule('Validation report', style='status')
    hit_bounds_per_group: Dict[str, HitBounds] = {}
    for info in infos:
        if not info.ok:
            console.console.print(
                f'[error]Testcase [item]{info.path}[/item] failed verification:[/error]\n{info.message}'
            )
            continue

        if info.group not in hit_bounds_per_group:
            hit_bounds_per_group[info.group] = {}
        hit_bounds = hit_bounds_per_group[info.group]

        for k, v in info.hit_bounds.items():
            if k not in hit_bounds:
                hit_bounds[k] = (False, False)
            hit_bounds[k] = _bounds_or(hit_bounds[k], v)

    for group, hit_bounds in hit_bounds_per_group.items():
        console.console.print(f'Group [item]{group}[/item] hit bounds:')
        for k, v in hit_bounds.items():
            if k == 'samples':
                # Skip samples.
                continue

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
