import pathlib
from typing import Awaitable, Callable, Dict, List, Tuple

from rbx.box.retries import Retrier
from rbx.box.setter_config import RepeatsConfig
from rbx.box.testing import testing_package
from rbx.grading import steps


def _attempts(
    out_dir: pathlib.Path, attempts: List[Tuple[float, List[str]]]
) -> Callable[[int], Awaitable[steps.Evaluation]]:
    """A run function whose attempt `k` takes `attempts[k][0]` seconds and
    writes a file per suffix in `attempts[k][1]`, each holding `attempt k`."""

    async def run(retry_index: int) -> steps.Evaluation:
        time, suffixes = attempts[retry_index - 1]
        out = out_dir / '000.out'
        for suffix in suffixes:
            out.with_suffix(suffix).write_text(f'attempt {retry_index}')
        return steps.Evaluation(
            result=steps.CheckerResult(outcome=steps.Outcome.ACCEPTED),
            testcase=steps.TestcaseIO(index=0),
            log=steps.TestcaseLog(
                time=time,
                stdout_absolute_path=out,
                log_absolute_path=out.with_suffix('.log'),
                eval_absolute_path=out.with_suffix('.eval'),
            ),
        )

    return run


def _files(out_dir: pathlib.Path) -> Dict[str, str]:
    return {path.name: path.read_text() for path in sorted(out_dir.iterdir())}


async def test_the_earlier_attempt_wins_with_every_file_and_nothing_of_the_later(
    testing_pkg: testing_package.TestingPackage,
):
    out_dir = testing_pkg.path('runs')
    out_dir.mkdir()
    run = _attempts(
        out_dir,
        [
            # Faster, and a fanout-style run with its capture and logs.
            (0.1, ['.out', '.log', '.eval', '.pio', '.int.log']),
            # Slower, with a file the first lacks.
            (0.5, ['.out', '.log', '.eval', '.sol.log']),
        ],
    )

    evaluation = await Retrier(RepeatsConfig(reps=2)).repeat(run)

    assert evaluation.log.time == 0.1
    assert _files(out_dir) == {
        '000.eval': 'attempt 1',
        '000.int.log': 'attempt 1',
        '000.log': 'attempt 1',
        '000.out': 'attempt 1',
        '000.pio': 'attempt 1',
    }


async def test_the_later_attempt_wins_with_nothing_of_the_earlier(
    testing_pkg: testing_package.TestingPackage,
):
    out_dir = testing_pkg.path('runs')
    out_dir.mkdir()
    run = _attempts(
        out_dir,
        [
            (0.5, ['.out', '.log', '.eval', '.pio', '.int.log']),
            (0.1, ['.out', '.log', '.eval', '.sol.log']),
        ],
    )

    evaluation = await Retrier(RepeatsConfig(reps=2)).repeat(run)

    assert evaluation.log.time == 0.1
    assert _files(out_dir) == {
        '000.eval': 'attempt 2',
        '000.log': 'attempt 2',
        '000.out': 'attempt 2',
        '000.sol.log': 'attempt 2',
    }
