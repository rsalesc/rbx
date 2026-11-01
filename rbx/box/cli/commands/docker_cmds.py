"""`rbx docker`: inspect and control the container programs run in.

Registered lazily from `rbx.box.cli._GROUPS`. Normal commands bring the
container up on their own when `docker.enabled` is set; these are for looking at
it and for forcing its hand.
"""

import os
import subprocess

import typer

from rbx import annotations, console
from rbx.box import docker_runtime
from rbx.box.setter_config import get_setter_config

app = typer.Typer(
    cls=annotations.AliasGroup,
    no_args_is_help=True,
    help='Manage the Docker container rbx runs programs in (sub-command).',
)


def _runtime() -> docker_runtime.DockerRuntime:
    return docker_runtime.DockerRuntime(get_setter_config().docker)


@app.command('status', help='Show the Docker configuration and container state.')
def status():
    cfg = get_setter_config().docker
    runtime = _runtime()
    enabled = '[success]yes[/success]' if cfg.enabled else '[error]no[/error]'
    console.console.print(f'Enabled:   {enabled}')
    console.console.print(f'Image:     [item]{runtime.image_tag}[/item]', end='')
    console.console.print(' (built)' if runtime.image_exists() else ' (not built)')
    running = runtime.container_running()
    console.console.print(
        f'Container: [item]{runtime.container_name}[/item]',
        '(running)' if running else '(stopped)',
    )
    console.console.print(f'Boxes:     [item]{runtime.box_root()}[/item] (read-write)')
    for mount in runtime.mounts():
        console.console.print(f'Mount:     [item]{mount}[/item] (read-only)')
    info = subprocess.run(
        ['docker', 'info', '--format', '{{.NCPU}} {{.MemTotal}}'],
        capture_output=True,
        text=True,
    )
    if info.returncode == 0 and info.stdout.split():
        ncpu, mem = info.stdout.split()
        console.console.print(
            f'Docker VM: {ncpu} CPUs, {int(mem) / 2**30:.1f} GiB memory'
        )
        workers = get_setter_config().parallel.max_workers
        if workers > int(ncpu):
            console.console.print(
                f'[warning]parallel.max_workers is {workers}, more than the {ncpu} CPUs '
                'Docker has; parallel runs will contend and time unreliably.[/warning]'
            )


@app.command('up', help='Build the image if needed and start the container.')
def up():
    runtime = _runtime()
    runtime.up()
    console.console.print(
        f'[success]Container [item]{runtime.container_name}[/item] is running.[/success]'
    )


@app.command('down', help='Stop and remove the container.')
def down():
    runtime = _runtime()
    runtime.down()
    console.console.print(
        f'[success]Container [item]{runtime.container_name}[/item] stopped.[/success]'
    )


@app.command(
    'rebuild', help='Rebuild the image from scratch, pulling a fresh base image.'
)
def rebuild():
    runtime = _runtime()
    runtime.down()
    runtime.build_image(force=True)
    console.console.print(
        f'[success]Image [item]{runtime.image_tag}[/item] rebuilt.[/success]'
    )


@app.command('shell', help='Open a shell in the container, as you.')
def shell():
    runtime = _runtime()
    runtime.up()
    os.execvp(
        'docker',
        [
            'docker',
            'exec',
            '-it',
            '-w',
            os.getcwd(),
            runtime.container_name,
            'bash',
        ],
    )
