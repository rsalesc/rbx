"""The MOJ statement settings a problem is packaged with.

`extensions.moj` can be set at three levels, each overriding the one above it
field by field: `env.rbx.yml` (a preset's defaults), `contest.rbx.yml` (every
problem of the contest) and `problem.rbx.yml` (this problem). Only the
statement settings (`MojStatementExtension`) reach the two lower levels; `org`
names where packages are uploaded, which is the environment's to say.
"""

from typing import Optional

from rbx.box.packaging.moj.extension import (
    DEFAULT_FIGURE_SCALE,
    MojExtension,
    MojStatementExtension,
)


def merge(*levels: Optional[MojStatementExtension]) -> MojStatementExtension:
    """The settings the later `levels` set, over the ones the earlier set. A
    field set to `null` counts as unset."""
    merged = MojStatementExtension()
    for level in levels:
        if level is None:
            continue
        merged = merged.model_copy(
            update={
                name: getattr(level, name)
                for name in level.model_fields_set
                if name in MojStatementExtension.model_fields
                and getattr(level, name) is not None
            }
        )
    return merged


def resolve() -> MojStatementExtension:
    """The settings in effect for the problem in the current directory."""
    from rbx.box import environment, package
    from rbx.box.contest import contest_package

    env = environment.get_extension('moj', MojExtension)
    contest = contest_package.find_contest_package()
    contest_moj = (
        contest.extensions.moj
        if contest is not None and contest.extensions is not None
        else None
    )
    pkg = package.find_problem_package_or_die()
    problem_moj = pkg.extensions.moj if pkg.extensions is not None else None
    return merge(env, contest_moj, problem_moj)


def figure_scale() -> float:
    """`figureScale` in effect for the problem in the current directory."""
    scale = resolve().figureScale
    return DEFAULT_FIGURE_SCALE if scale is None else scale
