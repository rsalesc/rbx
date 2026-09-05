import pathlib
from typing import Any, Dict, Optional
from unittest import mock

import pytest
import yaml

from rbx import crash
from rbx.config import CACHE_DIR_NAME


def raise_and_catch(exc: BaseException) -> BaseException:
    """Give `exc` a real traceback, the way a crash would have."""
    try:
        raise exc
    except BaseException as caught:
        return caught


def frontmatter_of(report: str) -> Dict[str, Any]:
    assert report.startswith('---\n')
    block = report.split('---\n', 2)[1]
    return yaml.safe_load(block)


def body_of(report: str) -> str:
    return report.split('---\n', 2)[2]


@pytest.fixture
def cwd(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    work_dir = tmp_path / 'work'
    work_dir.mkdir()
    monkeypatch.chdir(work_dir)
    return work_dir


@pytest.fixture
def crashes_dir(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    app_path = tmp_path / 'app'
    monkeypatch.setattr('rbx.utils.get_app_path', lambda: app_path)
    return app_path / crash.CRASHES_DIR_NAME


def test_report_carries_the_command_and_cwd(
    cwd: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr('sys.argv', ['rbx', 'run', '-s', 'my sol.cpp'])

    report = crash.render_report(raise_and_catch(KeyError('foo')), cwd)

    fm = frontmatter_of(report)
    assert fm['command'] == "rbx run -s 'my sol.cpp'"
    assert fm['cwd'] == str(cwd)
    assert fm['argv'] == ['rbx', 'run', '-s', 'my sol.cpp']
    assert fm['exception'] == 'KeyError'


def test_report_body_carries_the_traceback(cwd: pathlib.Path):
    report = crash.render_report(raise_and_catch(ValueError('boom')), cwd)

    body = body_of(report)
    assert 'Traceback (most recent call last)' in body
    assert 'ValueError: boom' in body
    assert 'raise exc' in body


def test_frontmatter_survives_a_hostile_message(cwd: pathlib.Path):
    message = 'a: b\n---\nnot: frontmatter'

    report = crash.render_report(raise_and_catch(ValueError(message)), cwd)

    assert frontmatter_of(report)['message'] == message


def test_package_is_the_innermost_marked_ancestor(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    contest = tmp_path / 'contest'
    problem = contest / 'problem'
    problem.mkdir(parents=True)
    (contest / 'contest.rbx.yml').write_text('')
    (problem / 'problem.rbx.yml').write_text('')
    monkeypatch.setattr('sys.argv', ['rbx', 'build'])

    report = crash.render_report(raise_and_catch(ValueError('boom')), problem)

    assert frontmatter_of(report)['package'] == str(problem)


def test_package_is_null_outside_one(cwd: pathlib.Path):
    report = crash.render_report(raise_and_catch(ValueError('boom')), cwd)

    assert frontmatter_of(report)['package'] is None


def test_report_crash_writes_the_file_and_the_latest_link(
    cwd: pathlib.Path, crashes_dir: pathlib.Path
):
    path = crash.report_crash(raise_and_catch(ValueError('boom')))

    assert path is not None
    assert path.parent == crashes_dir
    assert 'ValueError: boom' in path.read_text()

    latest = crashes_dir / crash.LATEST_NAME
    assert latest.resolve() == path.resolve()


def test_report_crash_prunes_old_reports(cwd: pathlib.Path, crashes_dir: pathlib.Path):
    crashes_dir.mkdir(parents=True)
    stale = [
        crashes_dir / f'2020{i:04d}T000000Z-1.md' for i in range(crash.MAX_REPORTS + 5)
    ]
    for path in stale:
        path.write_text('stale')

    path = crash.report_crash(raise_and_catch(ValueError('boom')))

    assert path is not None
    reports = sorted(p.name for p in crashes_dir.glob('*.md') if not p.is_symlink())
    assert len(reports) == crash.MAX_REPORTS
    # The oldest ones went, the newest stale ones and the new report stayed.
    assert stale[0].name not in reports
    assert path.name in reports


def test_report_crash_links_into_an_existing_package_cache(
    cwd: pathlib.Path, crashes_dir: pathlib.Path
):
    (cwd / 'problem.rbx.yml').write_text('')
    (cwd / CACHE_DIR_NAME).mkdir()

    path = crash.report_crash(raise_and_catch(ValueError('boom')))

    assert path is not None
    link = cwd / CACHE_DIR_NAME / crash.PACKAGE_LINK_NAME
    assert link.resolve() == path.resolve()


def test_report_crash_does_not_create_a_package_cache(
    cwd: pathlib.Path, crashes_dir: pathlib.Path
):
    (cwd / 'problem.rbx.yml').write_text('')

    assert crash.report_crash(raise_and_catch(ValueError('boom'))) is not None
    assert not (cwd / CACHE_DIR_NAME).exists()


def test_report_crash_swallows_its_own_failures(
    cwd: pathlib.Path, crashes_dir: pathlib.Path
):
    with mock.patch.object(
        crash, 'render_report', side_effect=RuntimeError('reporter is broken')
    ):
        result: Optional[pathlib.Path] = crash.report_crash(
            raise_and_catch(ValueError('boom'))
        )

    assert result is None
