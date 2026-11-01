"""Bring up, and keep, the container `DockerSandbox` runs programs in.

Opt-in through the setter config (`docker.enabled`). The design is in
`docs/plans/2026-11-01-docker-sandbox-design.md`; in short:

- **One image per configuration.** rbx builds it locally: the toolchains come
  from `base_image` (or `dockerfile`) plus `packages`, and rbx adds a layer with
  itself installed under `/opt/rbx`, off `PATH`, so its Python never shadows the
  one solutions run with. The tag hashes everything that went into it, so a
  config change or another rbx version builds a new image instead of reusing a
  stale one.
- **One long-lived container per image and mount set.** Started on first use,
  shared by every rbx process, stopped by its own keeper after `idle_timeout`
  seconds with nobody connected.
- **One agent per rbx process**, reached over `docker exec -i` stdio.

Boxes live under the system temp directory, mounted read-write at the same path,
while `mounts` are read-only. A box must sit outside every mount: Docker Desktop
silently drops a bind mount nested under another one, which would leave the box
read-only (found while prototyping this).

Every failure is fatal and says which setter config key to look at. There is no
fallback to running natively: a setter who asked for the container must not get
the host's limits without noticing.
"""

from __future__ import annotations

import functools
import hashlib
import importlib.metadata
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import threading
from typing import List, Optional, Type
from urllib.parse import unquote, urlparse

from rbx import config, console, utils
from rbx.box.exception import RbxException
from rbx.box.setter_config import DockerConfig, get_setter_config
from rbx.grading.judge.sandboxes.docker_agent import AgentClient, AgentError
from rbx.grading.judge.sandboxes.docker_sandbox import DockerSandbox

AGENT_PYTHON = '/opt/rbx/venv/bin/python'
AGENT_MODULE = 'rbx.grading.judge.sandboxes.docker_agent'
UV_IMAGE = 'ghcr.io/astral-sh/uv:0.8.14'
AGENT_PYTHON_VERSION = '3.12'
IMAGE_REPO = 'rbx-box'
KOTLIN_URL = (
    'https://github.com/JetBrains/kotlin/releases/download/'
    'v{version}/kotlin-compiler-{version}.zip'
)
KOTLIN_DOWNLOAD_PACKAGES = {'ca-certificates', 'curl', 'unzip'}
LABEL = 'dev.rbx.box'

CONFIG_HINT = (
    'Check the [item]docker[/item] section of your setter config '
    '([item]rbx config edit[/item]).'
)


class DockerUnavailableError(RbxException):
    pass


def _fail(*lines: str) -> DockerUnavailableError:
    err = DockerUnavailableError()
    for line in lines:
        err.print(line)
    err.print(CONFIG_HINT)
    return err


def _short_hash(*parts: str) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part.encode())
        digest.update(b'\0')
    return digest.hexdigest()[:12]


def _docker(*args: str, input: Optional[str] = None, check: bool = True):
    try:
        result = subprocess.run(
            ['docker', *args],
            capture_output=True,
            text=True,
            input=input,
        )
    except FileNotFoundError:
        raise _fail(
            '[error]Docker is enabled for rbx, but the [item]docker[/item] command '
            'was not found.[/error]',
            'Install Docker, or set [item]docker.enabled: false[/item].',
        ) from None
    if check and result.returncode != 0:
        raise _fail(
            f'[error]Docker command failed: [item]docker {" ".join(args)}[/item][/error]',
            utils.escape_markup(result.stderr.strip()),
        )
    return result


# --------------------------------------------------------------------------
# What gets installed: rbx itself
# --------------------------------------------------------------------------


def _source_checkout() -> Optional[pathlib.Path]:
    """The source tree rbx runs from, when it is not a released install."""
    try:
        raw = importlib.metadata.distribution('rbx-cp').read_text('direct_url.json')
    except importlib.metadata.PackageNotFoundError:
        raw = None
    if raw:
        info = json.loads(raw)
        url = urlparse(info.get('url', ''))
        if url.scheme == 'file' and info.get('dir_info', {}).get('editable'):
            path = pathlib.Path(unquote(url.path))
            if (path / 'pyproject.toml').is_file():
                return path
    return None


def _source_hash(root: pathlib.Path) -> str:
    """Hash the code that ends up in a wheel built from `root`."""
    digest = hashlib.sha256()
    files = sorted(
        p
        for p in (root / 'rbx').rglob('*')
        if p.is_file() and '__pycache__' not in p.parts
    )
    for path in [root / 'pyproject.toml', *files]:
        digest.update(str(path.relative_to(root)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


# --------------------------------------------------------------------------
# The runtime
# --------------------------------------------------------------------------


class DockerRuntime:
    """A `DockerBackend` (see `DockerSandbox`) built from the setter config."""

    def __init__(self, cfg: DockerConfig):
        self.cfg = cfg
        self._lock = threading.Lock()
        self._client: Optional[AgentClient] = None
        self._image_id: Optional[str] = None
        self._checkout = _source_checkout()
        self._source_hash = (
            _source_hash(self._checkout) if self._checkout is not None else None
        )

    # -- configuration -----------------------------------------------------

    def box_root(self) -> pathlib.Path:
        return pathlib.Path(tempfile.gettempdir()) / f'rbx-docker-{os.getuid()}'

    def mounts(self) -> List[pathlib.Path]:
        return [utils.abspath(pathlib.Path(m).expanduser()) for m in self.cfg.mounts]

    def _rbx_spec(self) -> str:
        if self._source_hash is not None:
            return f'source:{self._source_hash}'
        return f'rbx-cp=={utils.get_version()}'

    def _user_base_tag(self) -> Optional[str]:
        if self.cfg.dockerfile is None:
            return None
        path = pathlib.Path(self.cfg.dockerfile).expanduser()
        if not path.is_file():
            raise _fail(
                f'[error][item]docker.dockerfile[/item] points at [item]{path}[/item], '
                'which does not exist.[/error]'
            )
        return f'{IMAGE_REPO}-base:{_short_hash(path.read_text())}'

    def dockerfile(self) -> str:
        base = self._user_base_tag() or self.cfg.base_image
        lines = [f'FROM {base}']
        apt = set(self.cfg.packages)
        kotlin = self.cfg.kotlin_version
        if kotlin:
            apt |= KOTLIN_DOWNLOAD_PACKAGES
        if apt:
            lines.append(
                'RUN apt-get update && DEBIAN_FRONTEND=noninteractive '
                f'apt-get install -y --no-install-recommends {" ".join(sorted(apt))} '
                '&& rm -rf /var/lib/apt/lists/*'
            )
        if kotlin:
            # apt has no usable kotlinc, so it comes from JetBrains' release.
            url = KOTLIN_URL.format(version=kotlin)
            lines.append(
                f'RUN curl -fsSL -o /tmp/kotlin.zip {url} '
                '&& unzip -q /tmp/kotlin.zip -d /opt && rm /tmp/kotlin.zip '
                '&& ln -s /opt/kotlinc/bin/kotlinc /usr/local/bin/kotlinc '
                '&& ln -s /opt/kotlinc/bin/kotlin /usr/local/bin/kotlin'
            )
        lines += [
            f'COPY --from={UV_IMAGE} /uv /usr/local/bin/uv',
            'ENV UV_PYTHON_INSTALL_DIR=/opt/rbx/python UV_NO_CACHE=1',
            f'RUN uv venv --managed-python --python {AGENT_PYTHON_VERSION} /opt/rbx/venv',
        ]
        if self._source_hash is not None:
            lines += [
                'COPY wheel/ /opt/rbx/wheel/',
                f'RUN uv pip install --python {AGENT_PYTHON} /opt/rbx/wheel/*.whl',
            ]
        else:
            lines.append(
                f'RUN uv pip install --python {AGENT_PYTHON} '
                f"'rbx-cp=={utils.get_version()}'"
            )
        lines.append(f'LABEL {LABEL}=1')
        return '\n'.join(lines) + '\n'

    @functools.cached_property
    def image_tag(self) -> str:
        user_dockerfile = ''
        if self.cfg.dockerfile is not None:
            user_dockerfile = pathlib.Path(self.cfg.dockerfile).expanduser().read_text()
        return f'{IMAGE_REPO}:{_short_hash(self.dockerfile(), user_dockerfile, self._rbx_spec())}'

    @functools.cached_property
    def container_name(self) -> str:
        return 'rbx-box-' + _short_hash(
            self.image_tag,
            str(self.box_root()),
            *map(str, self.mounts()),
            str(self.cfg.idle_timeout),
            str(self.cfg.pids_limit),
            str(self.cfg.memory),
            str(os.getuid()),
        )

    def validate(self) -> None:
        box_root = utils.abspath(self.box_root())
        for mount in self.mounts():
            if not mount.is_dir():
                raise _fail(
                    f'[error][item]docker.mounts[/item] lists [item]{mount}[/item], '
                    'which is not a directory.[/error]'
                )
            if box_root.is_relative_to(mount):
                raise _fail(
                    f'[error]The rbx sandbox directory [item]{box_root}[/item] is inside '
                    f'the mount [item]{mount}[/item].[/error]',
                    'Docker cannot mount it read-write there; remove that mount or '
                    'narrow it.',
                )
        for needed in (utils.abspath(pathlib.Path.cwd()), config.get_app_path()):
            needed = utils.abspath(needed)
            if not any(needed.is_relative_to(m) for m in self.mounts()):
                raise _fail(
                    f'[error][item]{needed}[/item] is not visible to the rbx Docker '
                    'container.[/error]',
                    'Add a directory containing it to [item]docker.mounts[/item].',
                )

    # -- image -------------------------------------------------------------

    def image_exists(self, tag: Optional[str] = None) -> bool:
        tag = tag or self.image_tag
        return _docker('image', 'inspect', tag, check=False).returncode == 0

    def _build(self, args: List[str], what: str) -> None:
        with console.console.status(
            f'Building {what} (only once per configuration; this takes a few minutes)...'
        ):
            result = subprocess.run(
                ['docker', 'build', *args], capture_output=True, text=True
            )
        if result.returncode != 0:
            output = (result.stdout + result.stderr).strip().splitlines()
            raise _fail(
                f'[error]Failed to build {what}.[/error]',
                utils.escape_markup('\n'.join(output[-40:])),
            )

    def build_image(self, force: bool = False) -> None:
        # Every way into Docker comes through here first (the cache fingerprint
        # included), so this is where an unreachable daemon is reported as such
        # rather than as a failed build.
        ensure_daemon()
        if not force and self.image_exists():
            return
        # `rbx each --parallel` starts one rbx per problem at once, and each would
        # otherwise build the same image. The first builds; the rest wait, then
        # find it built.
        from filelock import FileLock

        self.box_root().mkdir(parents=True, exist_ok=True)
        with FileLock(str(self.box_root() / '.build.lock')):
            self._build_image_locked(force)

    def _build_image_locked(self, force: bool) -> None:
        user_base = self._user_base_tag()
        if user_base is not None and (force or not self.image_exists(user_base)):
            assert self.cfg.dockerfile is not None
            path = pathlib.Path(self.cfg.dockerfile).expanduser()
            self._build(
                ['-t', user_base, '-f', str(path), str(path.parent)],
                f'the base image from [item]{path}[/item]',
            )
        if not force and self.image_exists():
            return
        with tempfile.TemporaryDirectory(prefix='rbx-docker-build-') as tmp:
            context = pathlib.Path(tmp)
            (context / 'Dockerfile').write_text(self.dockerfile())
            if self._checkout is not None:
                with console.console.status('Building an rbx wheel from source...'):
                    result = subprocess.run(
                        [
                            'uv',
                            'build',
                            '--wheel',
                            '--out-dir',
                            str(context / 'wheel'),
                            str(self._checkout),
                        ],
                        capture_output=True,
                        text=True,
                    )
                if result.returncode != 0:
                    raise _fail(
                        '[error]Failed to build an rbx wheel from '
                        f'[item]{self._checkout}[/item].[/error]',
                        utils.escape_markup(result.stderr.strip()[-2000:]),
                    )
            args = ['-t', self.image_tag]
            if force:
                args += ['--pull', '--no-cache']
            self._build(
                [*args, str(context)],
                f'the rbx Docker image [item]{self.image_tag}[/item]',
            )

    def image_id(self) -> str:
        if self._image_id is None:
            self.build_image()
            result = _docker('image', 'inspect', '-f', '{{.Id}}', self.image_tag)
            self._image_id = result.stdout.strip()
        return self._image_id

    # -- container ---------------------------------------------------------

    def container_running(self) -> bool:
        result = _docker(
            'inspect', '-f', '{{.State.Running}}', self.container_name, check=False
        )
        return result.returncode == 0 and result.stdout.strip() == 'true'

    def _run_args(self) -> List[str]:
        box_root = str(self.box_root())
        args = [
            'run',
            '-d',
            '--rm',
            '--init',
            '--name',
            self.container_name,
            '--label',
            f'{LABEL}=1',
            '--user',
            f'{os.getuid()}:{os.getgid()}',
            '--network',
            'none',
            '--cap-drop',
            'ALL',
            '--security-opt',
            'no-new-privileges',
            '--read-only',
            '--tmpfs',
            '/tmp:exec',
            '-e',
            'HOME=/tmp',
            '--ulimit',
            'stack=-1:-1',
            '--ulimit',
            'core=0',
            '--pids-limit',
            str(self.cfg.pids_limit),
        ]
        if self.cfg.memory:
            args += ['--memory', self.cfg.memory]
        args += ['-v', f'{box_root}:{box_root}:rw']
        for mount in self.mounts():
            args += ['-v', f'{mount}:{mount}:ro']
        args += [
            self.image_tag,
            AGENT_PYTHON,
            '-m',
            AGENT_MODULE,
            'keep',
            '--idle-timeout',
            str(self.cfg.idle_timeout),
        ]
        return args

    def up(self) -> None:
        self.validate()
        self.box_root().mkdir(parents=True, exist_ok=True)
        ensure_daemon()
        self.image_id()
        from filelock import FileLock

        with FileLock(str(self.box_root() / '.container.lock')):
            if self.container_running():
                return
            # A container that stopped but was not removed yet would hold the name.
            _docker('rm', '-f', self.container_name, check=False)
            _docker(*self._run_args())

    def down(self) -> None:
        _docker('rm', '-f', self.container_name, check=False)

    # -- DockerBackend -----------------------------------------------------

    def _agent_command(self) -> List[str]:
        return [
            'docker',
            'exec',
            '-i',
            self.container_name,
            AGENT_PYTHON,
            '-m',
            AGENT_MODULE,
            'serve',
            '--slots',
            str(self.cfg.max_parallel),
        ]

    def client(self) -> AgentClient:
        with self._lock:
            if self._client is not None:
                return self._client
            last_error: Optional[Exception] = None
            # Twice: the keeper may stop an idle container between our check that
            # it runs and the agent attaching to it.
            for _ in range(2):
                self.up()
                client = AgentClient(self._agent_command())
                try:
                    client.ping()
                except AgentError as e:
                    last_error = e
                    continue
                self._client = client
                return client
            raise _fail(
                '[error]Could not start the rbx sandbox agent in container '
                f'[item]{self.container_name}[/item].[/error]',
                utils.escape_markup(str(last_error)),
            )

    def fingerprint(self) -> str:
        return f'docker:{self.image_id()}'

    def not_found_hint(self, executable: str) -> str:
        return (
            f"'{executable}' is not installed in the rbx Docker image "
            f'({self.image_tag}). Add the package that provides it to docker.packages, '
            'or change docker.base_image, in your setter config (rbx config edit).'
        )

    def is_visible(self, path: pathlib.Path) -> bool:
        roots = [utils.abspath(self.box_root()), *self.mounts()]
        return any(utils.abspath(path).is_relative_to(root) for root in roots)

    def close(self) -> None:
        with self._lock:
            if self._client is not None:
                self._client.close()
                self._client = None


@functools.cache
def ensure_daemon() -> None:
    if shutil.which('docker') is None:
        raise _fail(
            '[error]Docker is enabled for rbx, but the [item]docker[/item] command '
            'was not found.[/error]',
            'Install Docker, or set [item]docker.enabled: false[/item].',
        )
    result = _docker('info', '--format', '{{.ServerVersion}}', check=False)
    if result.returncode != 0:
        hint = (
            'Start Docker Desktop'
            if sys.platform == 'darwin'
            else 'Start the Docker daemon'
        )
        raise _fail(
            '[error]Docker is enabled for rbx, but the Docker daemon is not '
            'reachable.[/error]',
            f'{hint}, or set [item]docker.enabled: false[/item].',
        )


DOCKER_ENV_VAR = 'RBX_DOCKER'
DOCS_URL = 'https://rbx.rsalesc.dev/setters/running/docker/'


def env_override() -> Optional[bool]:
    """`RBX_DOCKER=1` / `RBX_DOCKER=0` for one command, or None when unset."""
    value = os.environ.get(DOCKER_ENV_VAR, '').strip().lower()
    if value in ('1', 'true', 'yes', 'on'):
        return True
    if value in ('0', 'false', 'no', 'off'):
        return False
    return None


def docker_enabled() -> bool:
    return get_setter_config().docker_enabled()


def set_enabled(enabled: bool) -> pathlib.Path:
    """Flip `docker.enabled` in the setter config file, in place.

    Edited as YAML rather than re-dumped from the model, so the setter's
    comments, ordering and other settings survive (`save_setter_config` would
    rewrite the whole file). A config without a `docker` section gets one.
    """
    from ruamel.yaml import YAML

    from rbx.box import setter_config

    setter_config.get_setter_config()  # Creates the file from the default if missing.
    path = setter_config.get_setter_config_path()
    yaml = YAML()
    yaml.preserve_quotes = True
    data = yaml.load(path.read_text()) or {}
    section = data.get('docker')
    if section is None:
        data['docker'] = {'enabled': enabled}
        if hasattr(data, 'yaml_set_comment_before_after_key'):
            data.yaml_set_comment_before_after_key(
                'docker',
                before=f'\nRun programs inside a Docker container. See {DOCS_URL}',
            )
    else:
        section['enabled'] = enabled
    with path.open('w') as f:
        yaml.dump(data, f)
    setter_config.get_setter_config.cache_clear()
    # Fail here, on a file the user can still fix, rather than on the next run.
    setter_config.get_setter_config()
    get_runtime.cache_clear()
    get_sandbox_type.cache_clear()
    return path


@functools.cache
def get_runtime() -> DockerRuntime:
    return DockerRuntime(get_setter_config().docker)


@functools.cache
def get_sandbox_type() -> Type[DockerSandbox]:
    return DockerSandbox.bind(get_runtime())
