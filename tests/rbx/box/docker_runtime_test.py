"""The parts of Docker mode that need no Docker: configuration to image and
container, the checks that fail before anything starts, and the switches the
rest of rbx reads.
"""

import contextlib
import pathlib
from unittest import mock

import pytest

from rbx.box import docker_runtime, environment, global_package, setter_config
from rbx.box.docker_runtime import DockerRuntime, DockerUnavailableError
from rbx.box.setter_config import DockerConfig, SetterConfig
from rbx.grading.judge.sandboxes.docker_sandbox import DockerSandbox
from rbx.grading.judge.sandboxes.stupid_sandbox import StupidSandbox


def _runtime(released: bool = True, **cfg) -> DockerRuntime:
    with (
        mock.patch.object(
            docker_runtime,
            '_source_checkout',
            return_value=None if released else pathlib.Path('/src/rbx'),
        ),
        mock.patch.object(docker_runtime, '_source_hash', return_value='abc'),
    ):
        return DockerRuntime(DockerConfig(**cfg))


def test_dockerfile_installs_packages_and_a_released_rbx():
    dockerfile = _runtime(
        packages=['python3', 'g++', 'g++'], kotlin_version=None
    ).dockerfile()
    assert dockerfile.splitlines()[0] == 'FROM ubuntu:24.04'
    assert 'apt-get install -y --no-install-recommends g++ python3 ' in dockerfile
    assert f"'rbx-cp=={docker_runtime.utils.get_version()}'" in dockerfile
    assert 'wheel' not in dockerfile
    # rbx lives off PATH, in its own venv, so it never shadows the python3 that
    # solutions run with.
    assert '/opt/rbx/venv' in dockerfile


def test_dockerfile_installs_a_source_checkout_from_its_wheel():
    dockerfile = _runtime(released=False).dockerfile()
    assert 'COPY wheel/ /opt/rbx/wheel/' in dockerfile
    assert 'rbx-cp==' not in dockerfile


def test_no_packages_and_no_kotlin_means_no_apt():
    dockerfile = _runtime(
        base_image='gcc:14', packages=[], kotlin_version=None
    ).dockerfile()
    assert 'apt-get' not in dockerfile
    assert 'kotlin' not in dockerfile


def test_kotlin_and_pypy_are_in_the_default_image():
    dockerfile = _runtime().dockerfile()
    assert ' pypy3 ' in dockerfile
    version = setter_config.DEFAULT_DOCKER_KOTLIN_VERSION
    assert f'v{version}/kotlin-compiler-{version}.zip' in dockerfile
    assert '/usr/local/bin/kotlinc' in dockerfile
    # The download tools come along even when `packages` is emptied.
    no_packages = _runtime(packages=[]).dockerfile()
    assert 'ca-certificates curl unzip' in no_packages
    assert _runtime(kotlin_version='2.0.0').image_tag != _runtime().image_tag


def test_image_tag_follows_everything_that_goes_into_the_image():
    base = _runtime().image_tag
    assert _runtime().image_tag == base
    assert _runtime(packages=['g++']).image_tag != base
    assert _runtime(base_image='gcc:14').image_tag != base
    assert _runtime(released=False).image_tag != base
    # Runtime knobs change the container, not the image.
    assert _runtime(idle_timeout=5).image_tag == base
    assert _runtime(idle_timeout=5).container_name != _runtime().container_name


def test_user_dockerfile_becomes_the_base(tmp_path: pathlib.Path):
    user = tmp_path / 'Dockerfile'
    user.write_text('FROM debian:12\n')
    runtime = _runtime(dockerfile=str(user))
    first = runtime.dockerfile().splitlines()[0]
    assert first.startswith('FROM rbx-box-base:')
    tag = runtime.image_tag
    user.write_text('FROM debian:13\n')
    assert _runtime(dockerfile=str(user)).image_tag != tag


@contextlib.contextmanager
def _raises_unavailable(phrase: str):
    """`pytest.raises(DockerUnavailableError)` whose message contains `phrase`.

    The message is rendered by a rich console, which wraps it at the console
    width -- on CI a long temporary path pushes the phrase across a line break.
    """
    with pytest.raises(DockerUnavailableError) as exc:
        yield
    assert phrase in ' '.join(str(exc.value).split())


def test_missing_user_dockerfile_fails(tmp_path: pathlib.Path):
    with _raises_unavailable('does not exist'):
        _runtime(dockerfile=str(tmp_path / 'nope')).dockerfile()


def test_box_root_inside_a_mount_is_refused(tmp_path: pathlib.Path):
    runtime = _runtime(mounts=[str(tmp_path)])
    with mock.patch.object(DockerRuntime, 'box_root', return_value=tmp_path / 'b'):
        with _raises_unavailable('inside the mount'):
            runtime.validate()


def test_a_problem_outside_every_mount_is_refused(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    (tmp_path / 'mounted').mkdir()
    (tmp_path / 'problem').mkdir()
    monkeypatch.chdir(tmp_path / 'problem')
    runtime = _runtime(mounts=[str(tmp_path / 'mounted')])
    with _raises_unavailable('not visible'):
        runtime.validate()


def test_visibility_covers_boxes_and_mounts(tmp_path: pathlib.Path):
    runtime = _runtime(mounts=[str(tmp_path / 'mounted')])
    assert runtime.is_visible(tmp_path / 'mounted' / 'x')
    assert runtime.is_visible(runtime.box_root() / 'rbx-abc' / 'f')
    assert not runtime.is_visible(tmp_path / 'elsewhere')


def test_run_args_isolate_the_container():
    args = _runtime(memory='4g', pids_limit=99)._run_args()  # noqa: SLF001
    joined = ' '.join(args)
    for flag in (
        '--network none',
        '--read-only',
        '--cap-drop ALL',
        '--ulimit stack=-1:-1',
        '--pids-limit 99',
        '--memory 4g',
    ):
        assert flag in joined
    box = str(_runtime().box_root())
    assert f'{box}:{box}:rw' in args


def test_agents_run_one_program_at_a_time_unless_configured():
    def slots(runtime: DockerRuntime) -> str:
        command = runtime._agent_command()  # noqa: SLF001
        return command[command.index('--slots') + 1]

    assert slots(_runtime()) == '1'
    assert slots(_runtime(max_parallel=3)) == '3'
    with pytest.raises(ValueError):
        DockerConfig(max_parallel=0)


def test_missing_docker_cli_fails_pointing_at_the_config():
    docker_runtime.ensure_daemon.cache_clear()
    with mock.patch.object(docker_runtime.shutil, 'which', return_value=None):
        with pytest.raises(DockerUnavailableError) as exc:
            docker_runtime.ensure_daemon()
    assert 'docker.enabled' in str(exc.value)
    assert 'rbx config edit' in str(exc.value)


def test_not_found_hint_names_the_config_keys():
    hint = _runtime().not_found_hint('kotlinc')
    assert 'kotlinc' in hint
    assert 'docker.packages' in hint


def test_docker_mode_uses_its_own_command_substitutions():
    cfg = SetterConfig(
        command_substitutions={'g++': 'g++-15'},
        sanitizers=setter_config.SanitizersConfig(
            command_substitutions={'g++': 'clang++'}
        ),
    )
    assert cfg.substitute_command('g++ a.cpp') == 'g++-15 a.cpp'
    cfg.docker = DockerConfig(enabled=True, command_substitutions={'gcc': 'gcc-13'})
    assert cfg.substitute_command('g++ a.cpp') == 'g++ a.cpp'
    assert cfg.substitute_command('g++ a.cpp', sanitized=True) == 'g++ a.cpp'
    assert cfg.substitute_command('gcc a.c') == 'gcc-13 a.c'


def test_sandbox_type_follows_the_setter_config():
    enabled = SetterConfig(docker=DockerConfig(enabled=True))
    with (
        mock.patch.object(docker_runtime, 'get_setter_config', return_value=enabled),
        mock.patch.object(docker_runtime, '_source_checkout', return_value=None),
    ):
        environment.get_sandbox_type.cache_clear()
        docker_runtime.get_runtime.cache_clear()
        docker_runtime.get_sandbox_type.cache_clear()
        global_package.get_global_sandbox_type.cache_clear()
        try:
            sandbox_type = environment.get_sandbox_type()
            assert issubclass(sandbox_type, DockerSandbox)
            assert not sandbox_type.runs_on_host()
            assert global_package.get_global_sandbox_type() is sandbox_type
        finally:
            environment.get_sandbox_type.cache_clear()
            docker_runtime.get_runtime.cache_clear()
            docker_runtime.get_sandbox_type.cache_clear()
            global_package.get_global_sandbox_type.cache_clear()
    assert environment.get_sandbox_type() is StupidSandbox


@pytest.fixture
def setter_config_file(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / 'setter_config.yml'
    monkeypatch.setattr(setter_config, 'get_setter_config_path', lambda: path)
    setter_config.get_setter_config.cache_clear()
    yield path
    setter_config.get_setter_config.cache_clear()


def test_enable_adds_a_docker_section_keeping_comments(setter_config_file):
    setter_config_file.write_text(
        '# my precious comment\nhyperlinks: false  # inline too\n'
    )
    docker_runtime.set_enabled(True)
    text = setter_config_file.read_text()
    assert '# my precious comment' in text
    assert 'hyperlinks: false  # inline too' in text
    assert docker_runtime.DOCS_URL in text
    cfg = setter_config.get_setter_config()
    assert cfg.docker.enabled and not cfg.hyperlinks


def test_disable_keeps_the_other_docker_settings(setter_config_file):
    setter_config_file.write_text(
        'docker:\n  enabled: true\n  packages: [g++]  # only c++\n'
    )
    docker_runtime.set_enabled(False)
    text = setter_config_file.read_text()
    assert 'packages: [g++]  # only c++' in text
    cfg = setter_config.get_setter_config()
    assert not cfg.docker.enabled
    assert cfg.docker.packages == ['g++']


def test_enable_creates_the_config_from_the_default(setter_config_file):
    docker_runtime.set_enabled(True)
    text = setter_config_file.read_text()
    # The default template's comments come along, and its disabled section is
    # flipped rather than duplicated.
    assert 'rbx docker enable' in text
    assert text.count('docker:') == 1
    assert setter_config.get_setter_config().docker.enabled


def test_default_setter_configs_ship_docker_disabled():
    for name in ('default_setter_config.yml', 'default_setter_config.mac.yml'):
        path = pathlib.Path(setter_config.__file__).parent.parent / 'resources' / name
        cfg = docker_runtime.utils.model_from_yaml(SetterConfig, path.read_text())
        assert cfg.docker == DockerConfig(enabled=False)


@pytest.mark.parametrize(
    'value,expected', [('1', True), ('true', True), ('0', False), ('off', False)]
)
def test_rbx_docker_env_var_overrides_the_config(
    value, expected, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv('RBX_DOCKER', value)
    for enabled in (True, False):
        cfg = SetterConfig(docker=DockerConfig(enabled=enabled))
        with mock.patch.object(docker_runtime, 'get_setter_config', return_value=cfg):
            assert docker_runtime.docker_enabled() is expected


def test_unset_or_unknown_env_var_defers_to_the_config(
    monkeypatch: pytest.MonkeyPatch,
):
    cfg = SetterConfig(docker=DockerConfig(enabled=True))
    with mock.patch.object(docker_runtime, 'get_setter_config', return_value=cfg):
        monkeypatch.delenv('RBX_DOCKER', raising=False)
        assert docker_runtime.docker_enabled()
        monkeypatch.setenv('RBX_DOCKER', 'maybe')
        assert docker_runtime.docker_enabled()


def test_rbx_docker_env_var_also_switches_command_substitutions(
    monkeypatch: pytest.MonkeyPatch,
):
    cfg = SetterConfig(
        command_substitutions={'g++': 'g++-15'},
        sanitizers=setter_config.SanitizersConfig(
            command_substitutions={'g++': 'clang++'}
        ),
        docker=DockerConfig(enabled=False, command_substitutions={'g++': 'g++-13'}),
    )
    monkeypatch.setenv('RBX_DOCKER', '1')
    # In the container: the host's clang++ for sanitizers must not leak in.
    assert cfg.substitute_command('g++ a.cpp', sanitized=True) == 'g++-13 a.cpp'
    cfg.docker.enabled = True
    monkeypatch.setenv('RBX_DOCKER', '0')
    assert cfg.substitute_command('g++ a.cpp') == 'g++-15 a.cpp'
    assert cfg.substitute_command('g++ a.cpp', sanitized=True) == 'clang++ a.cpp'
