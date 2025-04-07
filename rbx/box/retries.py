import dataclasses
import pathlib
import shutil
import tempfile
from contextlib import contextmanager
from typing import Awaitable, Callable, List, Optional

from rbx.box import package
from rbx.box.setter_config import RepeatsConfig, get_setter_config
from rbx.grading.steps import Evaluation, Outcome


def _both_accepted(eval_a: Evaluation, eval_b: Evaluation) -> bool:
    return (
        eval_a.result.outcome == Outcome.ACCEPTED
        and eval_b.result.outcome == Outcome.ACCEPTED
    )


def _any_tle(eval_a: Evaluation, eval_b: Evaluation) -> bool:
    return (
        eval_a.result.outcome == Outcome.TIME_LIMIT_EXCEEDED
        or eval_b.result.outcome == Outcome.TIME_LIMIT_EXCEEDED
    )


def _get_faster(eval_a: Evaluation, eval_b: Evaluation) -> Evaluation:
    if eval_a.log.time is None:
        return eval_b
    if eval_b.log.time is None:
        return eval_a
    if eval_a.log.time < eval_b.log.time:
        return eval_a
    return eval_b


def _merge_evaluations(eval_a: Evaluation, eval_b: Evaluation) -> Evaluation:
    if _both_accepted(eval_a, eval_b) or _any_tle(eval_a, eval_b):
        return _get_faster(eval_a, eval_b)
    if eval_a.result.outcome != Outcome.ACCEPTED:
        return eval_a
    if eval_b.result.outcome != Outcome.ACCEPTED:
        return eval_b
    return _get_faster(eval_a, eval_b)


@contextmanager
def _temp_retry_dir():
    """Create a temporary directory for retry artifacts."""
    temp_dir = tempfile.mkdtemp(prefix='rbx_retry_')
    try:
        yield pathlib.Path(temp_dir)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


@dataclasses.dataclass
class FileToRecover:
    from_path: pathlib.Path
    to_path: pathlib.Path


def _move_to_temp_dir(path: pathlib.Path, temp_dir: pathlib.Path) -> FileToRecover:
    problem_path = package.find_problem()
    path = path.resolve()
    temp_dir = temp_dir.resolve()
    relative = path.relative_to(problem_path)

    temp_path = temp_dir / relative
    temp_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(path, temp_path)
    return FileToRecover(temp_path, path)


def _move_logs_to_temp_dir(
    eval: Evaluation, temp_dir: pathlib.Path
) -> List[FileToRecover]:
    recover = []
    if (
        eval.log.stdout_absolute_path is not None
        and eval.log.stdout_absolute_path.exists()
    ):
        recover.append(_move_to_temp_dir(eval.log.stdout_absolute_path, temp_dir))
    if (
        eval.log.stderr_absolute_path is not None
        and eval.log.stderr_absolute_path.exists()
    ):
        recover.append(_move_to_temp_dir(eval.log.stderr_absolute_path, temp_dir))
    if eval.log.log_absolute_path is not None and eval.log.log_absolute_path.exists():
        recover.append(_move_to_temp_dir(eval.log.log_absolute_path, temp_dir))
    return recover


class Retrier:
    def __init__(self, config: Optional[RepeatsConfig] = None, is_stress: bool = False):
        self.config = config or get_setter_config().repeats
        self.is_stress = is_stress

        self.reset()

    def reset(self):
        self.reps = self.config.reps - 1
        self.retries = self.config.retries
        self.retries_for_stress = self.config.retries_for_stress
        self.retry_index = 0

    async def repeat(
        self,
        func: Callable[[int], Awaitable[Evaluation]],
    ) -> Evaluation:
        self.retry_index += 1
        eval = await func(self.retry_index)
        if self.should_repeat(eval):
            with _temp_retry_dir() as temp_dir:
                # Move files to temp dir to open run for repeat.
                recover = _move_logs_to_temp_dir(eval, temp_dir)
                # Actually repeat and choose the best evaluation.
                next_eval = await self.repeat(func)
                chosen_eval = _merge_evaluations(eval, next_eval)

                if id(chosen_eval) == id(eval):
                    # Must recover originally moved files.
                    for file in recover:
                        file.to_path.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(file.from_path, file.to_path)
                return chosen_eval
        return eval

    def should_repeat(self, eval: Evaluation) -> bool:
        if self.is_stress:
            if (
                eval.result.outcome == Outcome.TIME_LIMIT_EXCEEDED
                and self.retries_for_stress > 0
            ):
                self.retries_for_stress -= 1
                return True
        if eval.result.outcome == Outcome.TIME_LIMIT_EXCEEDED and self.retries > 0:
            self.retries -= 1
            return True
        if self.reps > 0:
            self.reps -= 1
            return True
        return False
