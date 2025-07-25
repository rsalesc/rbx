"""End-to-end tests for BOCA packaging functionality."""

import datetime
import os
import pathlib
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Generator, Iterator

import pytest
from throttlex import Throttler
from typer.testing import CliRunner

from rbx.box import code, package
from rbx.box.cli import app
from rbx.box.packaging.boca.boca_language_utils import (
    get_boca_language_from_rbx_language,
)
from rbx.box.testing import testing_package
from rbx.box.tooling.boca import scraper
from rbx.box.tooling.boca.scraper import BocaScraper


@pytest.fixture(scope='session')
def docker_compose_project_name() -> str:
    """Return a unique project name for docker-compose."""
    return f'rbx-boca-e2e-{int(time.time())}'


@pytest.fixture(scope='session')
def docker_utils_path() -> pathlib.Path:
    """Return the path to the docker-compose file."""
    return Path(__file__).parent / 'docker'


@pytest.fixture(scope='session')
def boca_throttler() -> Throttler:
    """Return a throttler for the BOCA scraper."""
    return Throttler(max_req=1, period=1)


@pytest.fixture(scope='session')
def boca_docker_repo(
    tmp_path_factory, monkeysession, docker_utils_path
) -> Iterator[pathlib.Path]:
    """Return the path to the BOCA docker repository."""
    repo_path = tmp_path_factory.mktemp('boca-docker')
    subprocess.run(
        ['git', 'clone', 'https://github.com/rsalesc/boca-docker.git', '.'],
        cwd=repo_path,
        check=True,
    )

    with monkeysession.context() as m:
        m.chdir(repo_path)
        yield repo_path


@pytest.fixture(scope='session')
def boca_environment(
    docker_compose_project_name: str,
    boca_docker_repo: pathlib.Path,
    docker_utils_path: pathlib.Path,
) -> Generator[dict, None, None]:
    """Start BOCA environment using docker-compose."""
    # Check if docker and docker-compose are available
    try:
        subprocess.run(['docker', '--version'], check=True, capture_output=True)
        subprocess.run(['docker-compose', '--version'], check=True, capture_output=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        pytest.skip('Docker or docker-compose not available')

    # Start the BOCA environment
    env = os.environ.copy()
    env['COMPOSE_PROJECT_NAME'] = docker_compose_project_name

    try:
        # Start docker-compose
        subprocess.run(
            [
                'docker-compose',
                '-f',
                'docker-compose.build.yml',
                'up',
                '-d',
                '--build',
            ],
            check=True,
            env=env,
            cwd=boca_docker_repo,
        )

        # Wait for BOCA to be ready
        wait_script = docker_utils_path / 'wait-for-boca.sh'
        subprocess.run(['bash', str(wait_script)], check=True)

        yield {
            'base_url': 'http://localhost:8000/boca',
            'system_user': 'system',
            'system_pass': 'boca',
            'admin_user': 'admin',
            'admin_pass': 'boca',
            'judge_user': 'judge',
            'judge_pass': 'boca',
        }

    finally:
        # Tear down the environment
        subprocess.run(
            [
                'docker-compose',
                '-f',
                'docker-compose.build.yml',
                'down',
                '-v',
            ],
            env=env,
            cwd=boca_docker_repo,
        )


@pytest.fixture
def boca_system_scraper(
    boca_environment: dict, boca_throttler: Throttler
) -> BocaScraper:
    """Return a BOCA scraper for the system user."""
    return BocaScraper(
        base_url=boca_environment['base_url'],
        username=boca_environment['system_user'],
        password=boca_environment['system_pass'],
        verbose=True,
        throttler=boca_throttler,
    )


@pytest.fixture
def boca_admin_scraper(
    boca_environment: dict, boca_throttler: Throttler
) -> BocaScraper:
    """Return a BOCA scraper for the admin user."""
    return BocaScraper(
        base_url=boca_environment['base_url'],
        username=boca_environment['admin_user'],
        password=boca_environment['admin_pass'],
        verbose=True,
        throttler=boca_throttler,
    )


@pytest.fixture
def boca_judge_scraper(
    boca_environment: dict, boca_throttler: Throttler
) -> BocaScraper:
    """Return a BOCA scraper for the judge user."""
    return BocaScraper(
        base_url=boca_environment['base_url'],
        username=boca_environment['judge_user'],
        password=boca_environment['judge_pass'],
        verbose=True,
        throttler=boca_throttler,
        is_judge=True,
    )


@pytest.fixture
def test_problem_dir() -> Path:
    """Return the path to the test problem directory."""
    return Path(__file__).parent / 'testdata' / 'simple-problem'


@pytest.fixture
def temp_problem_dir(test_problem_dir: Path) -> Generator[Path, None, None]:
    """Create a temporary copy of the test problem."""
    with tempfile.TemporaryDirectory() as tmpdir:
        temp_path = Path(tmpdir) / 'problem'
        shutil.copytree(test_problem_dir, temp_path)
        yield temp_path


@pytest.mark.e2e
@pytest.mark.slow
@pytest.mark.docker
@pytest.mark.preset_path('problem')
@pytest.mark.resource_pkg('presets/default')
def test_boca_package_generation_and_upload(
    preset_testing_pkg_from_resources: testing_package.TestingPackage,
    boca_system_scraper: BocaScraper,
    boca_admin_scraper: BocaScraper,
    boca_judge_scraper: BocaScraper,
):
    """Test that rbx can generate a BOCA package and upload it successfully."""
    runner = CliRunner()

    # Build the package (first we need to build the problem)
    build_result = runner.invoke(app, ['build'])
    assert build_result.exit_code == 0, f'Build failed: {build_result.output}'

    # Generate BOCA package
    package_result = runner.invoke(app, ['package', 'boca'])
    assert (
        package_result.exit_code == 0
    ), f'Package generation failed: {package_result.output}'

    package_path = preset_testing_pkg_from_resources.path('build/new_problem.zip')
    assert package_path.exists(), f'Package file not found: {package_path}'

    # Verify package was created
    assert package_path.stat().st_size > 0, 'Package file is empty'

    # Step 1: Login as system user to create and activate a contest
    print('\n=== STEP 1: Contest Creation ===')
    print('Logging in as system user...')
    boca_system_scraper.login()
    assert boca_system_scraper.loggedIn, 'Failed to login as system user'
    print('System login successful!')

    boca_system_scraper.create_and_activate_contest()

    # Step 2: Login as admin and configure the contest
    print('\n=== STEP 2: Contest Configuration ===')
    print('Logging in as admin user...')
    boca_admin_scraper.login()
    assert boca_admin_scraper.loggedIn, 'Failed to login as admin user'
    print('Admin login successful!')

    start_time = datetime.datetime.now() - datetime.timedelta(minutes=1)
    boca_admin_scraper.configure_contest(start_time=start_time)
    boca_admin_scraper.configure_main_site(autojudge=True, chief='judge')

    print('\n=== STEP 3: Problem Upload ===')
    print(f'Uploading package: {package_path}')
    boca_admin_scraper.upload(package_path, testing=True)

    print('\n=== STEP 3.1: Contest Snapshot ===')
    snapshot = scraper.create_snapshot(boca_admin_scraper)

    print('\n=== STEP 4: Judge Account Creation ===')
    print('Creating judge account...')
    boca_admin_scraper.create_judge_account()

    print('\n=== STEP 5: Judge Submission ===')
    print('Logging in as judge user...')
    boca_judge_scraper.login()
    assert boca_judge_scraper.loggedIn, 'Failed to login as judge user'
    print('Judge login successful!')

    print('Submitting solutions...')
    problem_index = snapshot.get_problem_by_shortname('A').index
    for solution in package.get_solutions():
        solution_path = preset_testing_pkg_from_resources.path(solution.path)
        boca_language = get_boca_language_from_rbx_language(
            code.find_language_name(solution)
        )
        language_index = snapshot.get_language_by_extension(boca_language).index
        boca_judge_scraper.submit_as_judge(
            problem_index, language_index, solution_path, wait=600
        )

    print('\n=== STEP 6: Run Retrieval ===')
    print('Waiting for all runs to be judged...')
    boca_judge_scraper.wait_for_all_judged()
    print('All runs judged!')
    print('Retrieving runs...')
    runs = boca_judge_scraper.retrieve_runs(only_judged=True)
    runs_snapshot = scraper.ContestSnapshot(detailed_runs=runs)

    for solution in package.get_solutions():
        run = runs_snapshot.get_detailed_run_by_path(solution.path)
        assert run.outcome is not None, f'Run {run.run_number} has no outcome'
        assert solution.outcome.match(
            run.outcome
        ), f'Run {run.run_number} for solution {solution.path} has outcome {run.outcome} but expected {solution.outcome}'
        print(
            f'Run {run.run_number} for solution {solution.path} verified (expected {solution.outcome}, found {run.outcome})'
        )

    print('All runs retrieved and verified!')


@pytest.mark.e2e
@pytest.mark.slow
def test_boca_package_structure(temp_problem_dir: Path):
    """Test that the generated BOCA package has the correct structure."""
    import zipfile

    runner = CliRunner()

    # Change to the problem directory
    os.chdir(temp_problem_dir)

    # Build and package
    build_result = runner.invoke(app, ['build'])
    assert build_result.exit_code == 0, f'Build failed: {build_result.output}'

    package_result = runner.invoke(app, ['package', 'boca'])
    assert (
        package_result.exit_code == 0
    ), f'Package generation failed: {package_result.output}'

    # Find and inspect the package
    # Search in multiple possible locations
    possible_locations = [
        temp_problem_dir / '.rbx' / 'build',
        temp_problem_dir / '.box' / 'build',
        temp_problem_dir / 'build',
    ]

    package_files = []
    for location in possible_locations:
        if location.exists():
            package_files = list(location.glob('*.zip'))
            if package_files:
                break

    # If still not found, look recursively
    if not package_files:
        package_files = list(temp_problem_dir.glob('**/*.zip'))

    assert (
        len(package_files) > 0
    ), f'No zip files found. Searched in: {possible_locations}. Output was: {package_result.output}'
    package_path = package_files[0]

    with zipfile.ZipFile(package_path, 'r') as zf:
        file_list = zf.namelist()

        # Check for expected BOCA structure
        assert any('description' in f for f in file_list), 'Missing problem description'
        assert any('input/' in f for f in file_list), 'Missing input directory'
        assert any('output/' in f for f in file_list), 'Missing output directory'
        assert any('limits/' in f for f in file_list), 'Missing limits directory'

        # Check for test cases
        input_files = [f for f in file_list if f.startswith('input/')]
        output_files = [f for f in file_list if f.startswith('output/')]
        assert len(input_files) > 0, 'No input files found'
        assert len(output_files) > 0, 'No output files found'
        assert len(input_files) == len(output_files), 'Input/output file count mismatch'
