import pathlib
import tarfile
import zipfile

import pytest

from scripts import check_dist_size

MB = check_dist_size.MB


def _wheel(path: pathlib.Path, files: dict) -> pathlib.Path:
    target = path / 'pkg-1.0.0-py3-none-any.whl'
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as zf:
        for name, size in files.items():
            zf.writestr(name, b'\0' * size)
    return target


def _sdist(path: pathlib.Path, files: dict) -> pathlib.Path:
    target = path / 'pkg-1.0.0.tar.gz'
    src = path / 'src'
    src.mkdir(exist_ok=True)
    with tarfile.open(target, 'w:gz') as tf:
        for name, size in files.items():
            blob = src / 'blob'
            blob.write_bytes(b'\0' * size)
            tf.add(blob, arcname=f'pkg-1.0.0/{name}')
    return target


def test_load_limits_reads_the_pyproject_table(tmp_path):
    (tmp_path / 'pyproject.toml').write_text(
        '[tool.rbx.dist]\nmax-wheel-mb = 12.5\nmax-sdist-mb = 30\n'
    )

    assert check_dist_size.load_limits(tmp_path / 'pyproject.toml') == {
        'wheel': 12.5,
        'sdist': 30.0,
    }


def test_load_limits_falls_back_when_the_table_is_absent(tmp_path):
    (tmp_path / 'pyproject.toml').write_text('[tool.ruff]\n')

    assert (
        check_dist_size.load_limits(tmp_path / 'pyproject.toml')
        == check_dist_size.DEFAULT_LIMITS
    )


@pytest.mark.parametrize('value', ['"big"', '0', '-3'])
def test_load_limits_ignores_unusable_values(tmp_path, value):
    (tmp_path / 'pyproject.toml').write_text(
        f'[tool.rbx.dist]\nmax-wheel-mb = {value}\n'
    )

    limits = check_dist_size.load_limits(tmp_path / 'pyproject.toml')

    assert limits['wheel'] == check_dist_size.DEFAULT_LIMITS['wheel']


def test_the_real_pyproject_declares_both_limits():
    limits = check_dist_size.load_limits(check_dist_size.REPO_ROOT / 'pyproject.toml')

    assert limits == {'wheel': 5.0, 'sdist': 5.0}


def test_kind_of_recognizes_wheels_and_sdists():
    assert check_dist_size.kind_of(pathlib.Path('a-1.0-py3-none-any.whl')) == 'wheel'
    assert check_dist_size.kind_of(pathlib.Path('a-1.0.tar.gz')) == 'sdist'
    assert check_dist_size.kind_of(pathlib.Path('a-1.0.zip')) is None


def test_entries_strips_the_sdist_prefix(tmp_path):
    sdist = _sdist(tmp_path, {'rbx/box/cli.py': 10, 'README.md': 4})

    assert dict(check_dist_size.entries(sdist)) == {
        'rbx/box/cli.py': 10,
        'README.md': 4,
    }


def test_entries_reports_uncompressed_wheel_sizes(tmp_path):
    wheel = _wheel(tmp_path, {'rbx/big.bin': 5000, 'rbx/small.py': 12})

    assert dict(check_dist_size.entries(wheel)) == {
        'rbx/big.bin': 5000,
        'rbx/small.py': 12,
    }


def test_top_offenders_aggregates_by_directory_largest_first():
    files = [
        ('vscode/node_modules/a', 800),
        ('vscode/node_modules/b', 700),
        ('vscode/src/main.ts', 50),
        ('rbx/box/cli.py', 300),
    ]

    assert check_dist_size.top_offenders(files) == [
        ('vscode/node_modules', 1500),
        ('rbx/box', 300),
        ('vscode/src', 50),
    ]


def test_top_offenders_keeps_shallow_paths_whole():
    assert check_dist_size.top_offenders([('uv.lock', 9)]) == [('uv.lock', 9)]


def test_an_artifact_under_its_limit_is_not_a_violation(tmp_path):
    wheel = _wheel(tmp_path, {'rbx/cli.py': 1024})

    assert check_dist_size.check_artifact(wheel, {'wheel': 5.0, 'sdist': 5.0}) is None


def test_an_oversized_artifact_reports_its_biggest_directories(tmp_path):
    # Stored, not deflated, so the archive on disk really does exceed the limit.
    wheel = tmp_path / 'pkg-1.0.0-py3-none-any.whl'
    with zipfile.ZipFile(wheel, 'w', zipfile.ZIP_STORED) as zf:
        zf.writestr('vscode/node_modules/blob.bin', b'\0' * (3 * MB))
        zf.writestr('rbx/box/cli.py', b'\0' * 1024)

    violation = check_dist_size.check_artifact(wheel, {'wheel': 1.0, 'sdist': 5.0})

    assert violation is not None
    assert violation.kind == 'wheel'
    assert violation.limit_mb == 1.0
    assert violation.size > MB
    assert violation.offenders[0][0] == 'vscode/node_modules'


def test_the_failure_report_names_the_offender_and_the_escape_hatch(tmp_path):
    wheel = tmp_path / 'pkg-1.0.0-py3-none-any.whl'
    with zipfile.ZipFile(wheel, 'w', zipfile.ZIP_STORED) as zf:
        zf.writestr('vscode/node_modules/blob.bin', b'\0' * (3 * MB))

    violation = check_dist_size.check_artifact(wheel, {'wheel': 1.0, 'sdist': 5.0})
    report = check_dist_size.format_violation(violation)

    assert 'RELEASE BLOCKED' in report
    assert 'vscode/node_modules' in report
    assert 'max-wheel-mb' in report


def test_main_passes_on_artifacts_within_limits(tmp_path, capsys):
    _wheel(tmp_path, {'rbx/cli.py': 1024})
    _sdist(tmp_path, {'rbx/cli.py': 1024})

    assert check_dist_size.main([str(tmp_path)]) == 0
    assert 'OK' in capsys.readouterr().out


def test_main_fails_loudly_on_an_oversized_artifact(tmp_path, capsys):
    wheel = tmp_path / 'pkg-1.0.0-py3-none-any.whl'
    with zipfile.ZipFile(wheel, 'w', zipfile.ZIP_STORED) as zf:
        zf.writestr('vscode/node_modules/blob.bin', b'\0' * (6 * MB))

    assert check_dist_size.main([str(tmp_path)]) == 1
    assert 'RELEASE BLOCKED' in capsys.readouterr().err


def test_main_fails_when_there_is_nothing_to_check(tmp_path, capsys):
    assert check_dist_size.main([str(tmp_path)]) == 1
    assert 'nothing to check' in capsys.readouterr().err
