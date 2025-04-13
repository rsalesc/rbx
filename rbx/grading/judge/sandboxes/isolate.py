from __future__ import annotations

import logging
import os
import pathlib
import shutil
import stat
import subprocess
import tempfile
from typing import IO, Any, Dict, List, Optional

from rbx.config import get_app_path
from rbx.grading.judge.cacher import FileCacher
from rbx.grading.judge.sandbox import (
    SandboxBase,
    SandboxParams,
    wait_without_std,
)

logger = logging.getLogger(__name__)


class IsolateSandbox(SandboxBase):
    """This class creates, deletes and manages the interaction with a
    sandbox. The sandbox doesn't support concurrent operation, not
    even for reading.

    The Sandbox offers API for retrieving and storing file, as well as
    executing programs in a controlled environment. There are anyway a
    few files reserved for use by the Sandbox itself:

     * commands.log: a text file with the commands ran into this
       Sandbox, one for each line;

     * run.log.N: for each N, the log produced by the sandbox when running
       command number N.

    """

    next_id = 0

    # If the command line starts with this command name, we are just
    # going to execute it without sandboxing, and with all permissions
    # on the current directory.
    SECURE_COMMANDS = ['/bin/cp', '/bin/mv', '/usr/bin/zip', '/usr/bin/unzip']

    log: Optional[Dict[str, Any]]

    def __init__(
        self,
        file_cacher: Optional[FileCacher] = None,
        name: Optional[str] = None,
        temp_dir: Optional[pathlib.Path] = None,
        params: Optional[SandboxParams] = None,
        debug: bool = False,
    ):
        """Initialization.

        For arguments documentation, see SandboxBase.__init__.

        """
        if not temp_dir:
            temp_dir = pathlib.Path(tempfile.gettempdir())
        SandboxBase.__init__(self, file_cacher, name, temp_dir, params)

        self.box_id = IsolateSandbox.next_id % 10
        IsolateSandbox.next_id += 1

        # We create a directory "home" inside the outer temporary directory,
        # that will be bind-mounted to "/tmp" inside the sandbox (some
        # compilers need "/tmp" to exist, and this is a cheap shortcut to
        # create it). The sandbox also runs code as a different user, and so
        # we need to ensure that they can read and write to the directory.
        # But we don't want everybody on the system to, which is why the
        # outer directory exists with no read permissions.
        self._outer_dir = pathlib.Path(
            tempfile.mkdtemp(dir=str(self.temp_dir), prefix='cms-%s-' % (self.name))
        )
        self._home = self._outer_dir / 'home'
        self._home_dest = pathlib.PosixPath('/tmp')
        self._home.mkdir(parents=True, exist_ok=True)
        self.allow_writing_all()

        self.exec_name = 'isolate'
        self.box_exec = self.detect_box_executable()
        # Used for -M - the meta file ends up in the outer directory. The
        # actual filename will be <info_basename>.<execution_number>.
        self.info_basename = self._outer_dir / 'run.log'
        self.log = None
        self.exec_num = -1
        self.cmd_file = self._outer_dir / 'commands.log'
        self.chdir = self._home_dest
        self.debug = debug
        logger.debug(
            "Sandbox in `%s' created, using box `%s'.", self._home, self.box_exec
        )

        # Ensure we add a few extra things to params.
        self.set_params(params or SandboxParams())

        # Tell isolate to get the sandbox ready. We do our best to cleanup
        # after ourselves, but we might have missed something if a previous
        # worker was interrupted in the middle of an execution, so we issue an
        # idempotent cleanup.
        self.cleanup()
        self.initialize()

    def set_params(self, params: SandboxParams):
        """Set the parameters of the sandbox.

        params (SandboxParams): the parameters to set.

        """
        super().set_params(params)
        self.add_mapped_directory(self._home, dest=self._home_dest, options='rw')

        # Set common environment variables.
        # Specifically needed by Python, that searches the home for
        # packages.
        self.params.set_env['HOME'] = str(self._home_dest)

    def add_mapped_directory(
        self,
        src: pathlib.Path,
        dest: Optional[pathlib.Path] = None,
        options: Optional[str] = None,
        ignore_if_not_existing: bool = False,
    ):
        """Add src to the directory to be mapped inside the sandbox.

        src (Path): directory to make visible.
        dest (Path|None): if not None, the path where to bind src.
        options (str|None): if not None, isolate's directory rule options.
        ignore_if_not_existing (bool): if True, ignore the mapping when src
            does not exist (instead of having isolate terminate with an
            error).

        """
        self.params.add_mapped_directory(
            src, dest, options, ignore_if_not_existing=ignore_if_not_existing
        )

    def maybe_add_mapped_directory(
        self,
        src: pathlib.Path,
        dest: Optional[pathlib.Path] = None,
        options: Optional[str] = None,
    ):
        """Same as add_mapped_directory, with ignore_if_not_existing."""
        return self.add_mapped_directory(
            src, dest, options, ignore_if_not_existing=True
        )

    def allow_writing_all(self):
        """Set permissions in such a way that any operation is allowed."""
        self._home.chmod(0o777)
        for child in self._home.iterdir():
            child.chmod(0o777)

    def allow_writing_none(self):
        """Set permissions in such a way that the user cannot write anything."""
        self._home.chmod(0o755)
        for child in self._home.iterdir():
            child.chmod(0o755)

    def allow_writing_only(self, inner_paths: List[pathlib.Path]):
        """Set permissions in so that the user can write only some paths.

        By default the user can only write to the home directory. This
        method further restricts permissions so that it can only write
        to some files inside the home directory.

        inner_paths ([Path]): the only paths that the user is allowed to
            write to; they should be "inner" paths (from the perspective
            of the sandboxed process, not of the host system); they can
            be absolute or relative (in which case they are interpreted
            relative to the home directory); paths that point to a file
            outside the home directory are ignored.

        """
        outer_paths: List[pathlib.Path] = []
        for inner_path in inner_paths:
            abs_inner_path = (self._home_dest / inner_path).resolve()
            # If an inner path is absolute (e.g., /fifo0/u0_to_m) then
            # it may be outside home and we should ignore it.
            if not abs_inner_path.is_relative_to(self._home_dest.resolve()):
                continue
            rel_inner_path = abs_inner_path.relative_to(self._home_dest)
            outer_path = self._home / rel_inner_path
            outer_paths.append(outer_path)

        # If one of the specified file do not exists, we touch it to
        # assign the correct permissions.
        for path in outer_paths:
            if not path.exists():
                path.touch()

        # Close everything, then open only the specified.
        self.allow_writing_none()
        for path in outer_paths:
            path.chmod(0o722)

    def get_root_path(self) -> pathlib.Path:
        """Return the toplevel path of the sandbox.

        return (Path): the root path.

        """
        return self._outer_dir

    def relative_path(self, path: pathlib.Path) -> pathlib.Path:
        """Translate from a relative path inside the sandbox to a system path.

        path (Path): relative path of the file inside the sandbox.

        return (Path): the absolute path.

        """
        return self._home / path

    def detect_box_executable(self) -> pathlib.Path:
        """Try to find an isolate executable. It first looks in
        ./isolate/, then the local directory, then in a relative path
        from the file that contains the Sandbox module, then in the
        system paths.

        return (Path): the path to a valid (hopefully) isolate.

        """
        paths: List[pathlib.Path] = [
            pathlib.PosixPath('./isolate') / self.exec_name,
            pathlib.PosixPath('.') / self.exec_name,
            get_app_path() / self.exec_name,
            pathlib.PosixPath('/usr/local/bin') / self.exec_name,
            pathlib.PosixPath(self.exec_name),
        ]
        for path in paths:
            # Consider only non-directory, executable files with SUID flag on.
            if path.exists() and not path.is_dir() and os.access(str(path), os.X_OK):
                st = path.stat()
                if st.st_mode & stat.S_ISUID != 0:
                    return path

        # As default, return self.exec_name alone, that means that
        # system path is used.
        return paths[-1]

    def build_box_options(self) -> List[str]:
        """Translate the options defined in the instance to a string
        that can be postponed to isolate as an arguments list.

        return ([string]): the arguments list as strings.

        """
        res = list()
        if self.box_id is not None:
            res += [f'--box-id={self.box_id}']
        if self.params.cgroup:
            res += ['--cg']
        if self.chdir is not None:
            res += [f'--chdir={str(self.chdir)}']
        for dirmount in self.params.dirs:
            s = str(dirmount.dst) + '=' + str(dirmount.src)
            if dirmount.options is not None:
                s += ':' + dirmount.options
            res += [f'--dir={s}']
        if self.params.preserve_env:
            res += ['--full-env']
        for var in self.params.inherit_env:
            res += [f'--env={var}']
        for var, value in self.params.set_env.items():
            res += [f'--env={var}={value}']
        if self.params.fsize is not None:
            # Isolate wants file size as KiB.
            fsize = self.params.fsize
            res += [f'--fsize={fsize}']
        if self.params.stdin_file is not None:
            inner_stdin = self.inner_absolute_path(self.params.stdin_file)
            res += ['--stdin=%s' % str(inner_stdin)]
        if self.params.stack_space is not None:
            # Isolate wants stack size as KiB.
            stack_space = self.params.stack_space * 1024
            res += [f'--stack={stack_space}']
        if self.params.address_space is not None:
            # Isolate wants memory size as KiB.
            address_space = self.params.address_space * 1024
            if self.params.cgroup:
                res += [f'--cg-mem={address_space}']
            else:
                res += [f'--mem={address_space}']
        if self.params.stdout_file is not None:
            inner_stdout = self.inner_absolute_path(self.params.stdout_file)
            res += ['--stdout=%s' % str(inner_stdout)]
        if self.params.max_processes is not None:
            res += [f'--processes={self.params.max_processes}']
        else:
            res += ['--processes']
        if self.params.stderr_file is not None:
            inner_stderr = self.inner_absolute_path(self.params.stderr_file)
            res += ['--stderr=%s' % str(inner_stderr)]
        if self.params.timeout is not None:
            # Isolate wants time in seconds.
            timeout = float(self.params.timeout) / 1000
            res += ['--time=%g' % timeout]
        res += ['--verbose'] * self.params.verbosity
        if self.params.wallclock_timeout is not None:
            wallclock_timeout = float(self.params.wallclock_timeout) / 1000
            res += ['--wall-time=%g' % wallclock_timeout]
        if self.params.extra_timeout is not None:
            extra_timeout = float(self.params.extra_timeout) / 1000
            res += ['--extra-time=%g' % extra_timeout]
        res += ['--meta=%s' % ('%s.%d' % (self.info_basename, self.exec_num))]
        res += ['--run']
        return res

    def hydrate_logs(self):
        """Read the content of the log file of the sandbox (usually
        run.log.N for some integer N), and set self.log as a dict
        containing the info in the log file (time, memory, status,
        ...).

        """
        # self.log is a dictionary of lists (usually lists of length
        # one).
        self.log = {}
        info_file = pathlib.Path('%s.%d' % (self.info_basename, self.exec_num))
        try:
            with self.get_file_text(info_file) as log_file:
                for line in log_file:
                    key, value = line.strip().split(':', 1)
                    if key in self.log:
                        self.log[key].append(value)
                    else:
                        self.log[key] = [value]
        except OSError as error:
            raise OSError(
                'Error while reading execution log file %s. %r' % (info_file, error)
            ) from error

    def get_execution_time(self) -> Optional[float]:
        """Return the time spent in the sandbox, reading the logs if
        necessary.

        return (float): time spent in the sandbox.

        """
        assert self.log is not None
        if 'time' in self.log:
            return float(self.log['time'][0])
        return None

    def get_execution_wall_clock_time(self) -> Optional[float]:
        """Return the total time from the start of the sandbox to the
        conclusion of the task, reading the logs if necessary.

        return (float): total time the sandbox was alive.

        """
        assert self.log is not None
        if 'time-wall' in self.log:
            return float(self.log['time-wall'][0])
        return None

    def use_soft_timeout(self) -> bool:
        return True

    def get_memory_used(self) -> Optional[int]:
        """Return the memory used by the sandbox, reading the logs if
        necessary.

        return (int): memory used by the sandbox (in kbytes).

        """
        assert self.log is not None
        if 'cg-mem' in self.log:
            # Isolate returns memory measurements in KiB.
            return int(self.log['cg-mem'][0])
        return None

    def get_killing_signal(self) -> int:
        """Return the signal that killed the sandboxed process,
        reading the logs if necessary.

        return (int): offending signal, or 0.

        """
        assert self.log is not None
        if 'exitsig' in self.log:
            return int(self.log['exitsig'][0])
        return 0

    def get_exit_code(self) -> int:
        """Return the exit code of the sandboxed process, reading the
        logs if necessary.

        return (int): exitcode, or 0.

        """
        assert self.log is not None
        if 'exitcode' in self.log:
            return int(self.log['exitcode'][0])
        return 0

    def get_status_list(self) -> List[str]:
        """Reads the sandbox log file, and set and return the status
        of the sandbox.

        return (list): list of statuses of the sandbox.

        """
        assert self.log is not None
        if 'status' in self.log:
            return self.log['status']
        return []

    def get_exit_status(self) -> str:
        """Get the list of statuses of the sandbox and return the most
        important one.

        return (string): the main reason why the sandbox terminated.

        """
        # TODO: figure out EXIT_TERMINATED
        assert self.log is not None
        status_list = self.get_status_list()
        if 'XX' in status_list:
            return self.EXIT_SANDBOX_ERROR
        elif 'TO' in status_list:
            if 'message' in self.log and 'wall' in self.log['message'][0]:
                return self.EXIT_TIMEOUT_WALL
            else:
                return self.EXIT_TIMEOUT
        elif 'SG' in status_list:
            return self.EXIT_SIGNAL
        elif 'RE' in status_list:
            return self.EXIT_NONZERO_RETURN
        # OK status is not reported in the log file, it's implicit.
        return self.EXIT_OK

    def get_human_exit_description(self) -> str:
        """Get the status of the sandbox and return a human-readable
        string describing it.

        return (string): human-readable explaination of why the
                         sandbox terminated.

        """
        status = self.get_exit_status()
        if status == self.EXIT_OK:
            return (
                'Execution successfully finished (with exit code %d)'
                % self.get_exit_code()
            )
        elif status == self.EXIT_SANDBOX_ERROR:
            return 'Execution failed because of sandbox error'
        elif status == self.EXIT_TIMEOUT:
            return 'Execution timed out'
        elif status == self.EXIT_TIMEOUT_WALL:
            return 'Execution timed out (wall clock limit exceeded)'
        elif status == self.EXIT_SIGNAL:
            return 'Execution killed with signal %s' % self.get_killing_signal()
        elif status == self.EXIT_NONZERO_RETURN:
            return 'Execution failed because the return code was nonzero'
        return ''

    def get_detailed_logs(self) -> str:
        """Return the detailed logs of the sandbox.

        return (string): the detailed logs of the sandbox.

        """
        return str(self.log)

    def inner_absolute_path(self, path: pathlib.Path) -> pathlib.Path:
        """Translate from a relative path inside the sandbox to an
        absolute path inside the sandbox.

        path (string): relative path of the file inside the sandbox.

        return (string): the absolute path of the file inside the sandbox.

        """
        return self._home_dest / path

    def _popen(
        self,
        command: List[str],
        stdin: Optional[IO[bytes] | int] = None,
        stdout: Optional[IO[bytes] | int] = None,
        stderr: Optional[IO[bytes] | int] = None,
        close_fds: bool = True,
    ) -> subprocess.Popen:
        """Execute the given command in the sandbox using
        subprocess.Popen, assigning the corresponding standard file
        descriptors.

        command ([string]): executable filename and arguments of the
            command.
        stdin (file|None): a file descriptor.
        stdout (file|None): a file descriptor.
        stderr (file|None): a file descriptor.
        close_fds (bool): close all file descriptor before executing.

        return (Popen): popen object.

        """
        self.log = None
        self.exec_num += 1

        # We run a selection of commands without isolate, as they need
        # to create new files. This is safe because these commands do
        # not depend on the user input.
        if command[0] in IsolateSandbox.SECURE_COMMANDS:
            logger.debug(
                'Executing non-securely: %s at %s',
                str(command),
                self._home,
            )
            try:
                prev_permissions = stat.S_IMODE(self._home.stat().st_mode)
                self._home.chmod(0o700)
                with open(self.cmd_file, 'at', encoding='utf-8') as cmds:
                    cmds.write('%s\n' % str(command))
                p = subprocess.Popen(
                    command,
                    cwd=str(self._home),
                    stdin=stdin,
                    stdout=stdout,
                    stderr=stderr,
                    close_fds=close_fds,
                )
                self._home.chmod(prev_permissions)
                # For secure commands, we clear the output so that it
                # is not forwarded to the contestants. Secure commands
                # are "setup" commands, which should not fail or
                # provide information for the contestants.
                if self.params.stdout_file:
                    (self._home / self.params.stdout_file).open('wb').close()
                if self.params.stderr_file:
                    (self._home / self.params.stderr_file).open('wb').close()
                self._write_empty_run_log(self.exec_num)
            except OSError:
                logger.critical(
                    'Failed to execute program in sandbox with command: %s',
                    str(command),
                    exc_info=True,
                )
                raise
            return p

        args = [self.box_exec] + self.build_box_options() + ['--'] + command
        logger.debug(
            "Executing program in sandbox with command: `%s'.",
            str(args),
        )
        # Temporarily allow writing new files.
        prev_permissions = stat.S_IMODE(self._home.stat().st_mode)
        self._home.chmod(0o700)
        with open(self.cmd_file, 'at', encoding='utf-8') as commands:
            commands.write('%s\n' % (str(args)))
        self._home.chmod(prev_permissions)
        try:
            p = subprocess.Popen(
                args, stdin=stdin, stdout=stdout, stderr=stderr, close_fds=close_fds
            )
        except OSError:
            logger.critical(
                'Failed to execute program in sandbox with command: %s',
                str(args),
                exc_info=True,
            )
            raise

        return p

    def _write_empty_run_log(self, index: int):
        """Write a fake run.log file with no information."""
        info_file = pathlib.PosixPath('%s.%d' % (self.info_basename, index))
        with info_file.open('wt', encoding='utf-8') as f:
            f.write('time:0.000\n')
            f.write('time-wall:0.000\n')
            f.write('max-rss:0\n')
            f.write('cg-mem:0\n')

    def execute_without_std(
        self,
        command: List[str],
    ) -> bool:
        """Execute the given command in the sandbox using
        subprocess.Popen and discarding standard input, output and
        error. More specifically, the standard input gets closed just
        after the execution has started; standard output and error are
        read until the end, in a way that prevents the execution from
        being blocked because of insufficient buffering.

        command ([string]): executable filename and arguments of the
            command.

        return (bool|Popen): return True if the sandbox didn't report
            errors (caused by the sandbox itself), False otherwise.
        """
        popen = self._popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            close_fds=True,
        )

        # If the caller wants us to wait for completion, we also avoid
        # std*** to interfere with command. Otherwise we let the
        # caller handle these issues.
        with popen as p:
            self.set_pid(p.pid)
            exitcode = self.translate_box_exitcode(
                wait_without_std([p], actually_pipe_to_stdout=self.debug)[0]
            )
        self.hydrate_logs()
        return exitcode

    def translate_box_exitcode(self, exitcode: int) -> bool:
        """Translate the sandbox exit code to a boolean sandbox success.

        Isolate emits the following exit codes:
        * 0 -> both sandbox and internal process finished successfully (meta
            file will contain "status:OK" -> return True;
        * 1 -> sandbox finished successfully, but internal process was
            terminated, e.g., due to timeout (meta file will contain
            status:x" with x in (TO, SG, RE)) -> return True;
        * 2 -> sandbox terminated with an error (meta file will contain
            "status:XX") -> return False.

        """
        if exitcode == 0 or exitcode == 1:
            return True
        elif exitcode == 2:
            return False
        else:
            raise Exception('Sandbox exit status (%d) unknown' % exitcode)

    def initialize(self):
        """Initialize isolate's box."""
        init_cmd = (
            [self.box_exec]
            + (['--cg'] if self.params.cgroup else [])
            + ['--box-id=%d' % self.box_id, '--init']
        )
        try:
            subprocess.check_call(init_cmd)
        except subprocess.CalledProcessError as e:
            raise Exception('Failed to initialize sandbox') from e

    def cleanup(self, delete: bool = False):
        """See Sandbox.cleanup()."""
        # The user isolate assigns within the sandbox might have created
        # subdirectories and files therein, making the user outside the sandbox
        # unable to delete the whole tree. If the caller asked us to delete the
        # sandbox, we first issue a chmod within isolate to make sure that we
        # will be able to delete everything. If not, we leave the files as they
        # are to avoid masking possible problems the admin wanted to debug.

        exe = (
            [self.box_exec]
            + (['--cg'] if self.params.cgroup else [])
            + ['--box-id=%d' % self.box_id]
        )

        if delete:
            # Ignore exit status as some files may be owned by our user
            subprocess.call(
                exe
                + [
                    '--dir=%s=%s:rw' % (str(self._home_dest), str(self._home)),
                    '--run',
                    '--',
                    '/bin/chmod',
                    '777',
                    '-R',
                    str(self._home_dest),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.STDOUT,
            )

        # Tell isolate to cleanup the sandbox.
        subprocess.check_call(
            exe + ['--cleanup'], stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT
        )

        if delete:
            logger.debug('Deleting sandbox in %s.', self._outer_dir)
            # Delete the working directory.
            shutil.rmtree(str(self._outer_dir), ignore_errors=True)
