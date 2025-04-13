import abc
import collections
import dataclasses
import io
import logging
import os
import pathlib
import select
import signal
import stat
import subprocess
import sys
import typing
from typing import IO, Any, Dict, List, Optional

import pydantic

from rbx.grading import processing_context
from rbx.grading.judge import cacher, storage

logger = logging.getLogger(__name__)

MERGE_STDERR = pathlib.PosixPath('/dev/stdout')


def wait_without_std(
    procs: List[subprocess.Popen], actually_pipe_to_stdout: bool = False
) -> List[int]:
    """Wait for the conclusion of the processes in the list, avoiding
    starving for input and output.

    procs (list): a list of processes as returned by Popen.

    return (list): a list of return codes.

    """

    def get_to_consume():
        """Amongst stdout and stderr of list of processes, find the
        ones that are alive and not closed (i.e., that may still want
        to write to).

        return (list): a list of open streams.

        """
        to_consume = []
        for process in procs:
            if process.poll() is None:  # If the process is alive.
                if process.stdout and not process.stdout.closed:
                    to_consume.append(process.stdout)
                if process.stderr and not process.stderr.closed:
                    to_consume.append(process.stderr)
        return to_consume

    # Close stdin; just saying stdin=None isn't ok, because the
    # standard input would be obtained from the application stdin,
    # that could interfere with the child process behaviour
    for process in procs:
        if process.stdin:
            process.stdin.close()

    # Read stdout and stderr to the end without having to block
    # because of insufficient buffering (and without allocating too
    # much memory). Unix specific.
    to_consume = get_to_consume()

    while len(to_consume) > 0:
        to_read = select.select(to_consume, [], [], 1.0)[0]
        for file_ in to_read:
            consumed = file_.read(8 * 1024)
            if actually_pipe_to_stdout:
                sys.stdout.buffer.write(consumed)
                sys.stdout.buffer.flush()
        to_consume = get_to_consume()

    return [process.wait() for process in procs]


@dataclasses.dataclass
class DirectoryMount:
    src: pathlib.Path
    dst: pathlib.Path
    options: Optional[str] = None


class SandboxParams(pydantic.BaseModel):
    """Parameters for the sandbox.

    box_id (int): the id of the sandbox.
    fsize (int|None): maximum file size.
    cgroup (bool): whether to use cgroups.
    dirs ([string]): directories to mount.
    preserve_env (bool): whether to preserve the environment.
    inherit_env ([string]): environment variables to inherit.
    set_env (Dict[string, string]): environment variables to set.
    verbosity (int): verbosity level.
    max_processes (int): maximum number of processes.

    """

    fsize: Optional[int] = None  # KiB
    cgroup: bool = False
    dirs: List[DirectoryMount] = []
    preserve_env: bool = False
    inherit_env: List[str] = []
    set_env: Dict[str, str] = {}
    verbosity: int = 0
    max_processes: Optional[int] = 1

    stdin_file: Optional[pathlib.Path] = None
    stdout_file: Optional[pathlib.Path] = None
    stderr_file: Optional[pathlib.Path] = None
    stack_space: Optional[int] = None  # MiB
    address_space: Optional[int] = None  # MiB
    timeout: Optional[int] = None  # ms
    wallclock_timeout: Optional[int] = None  # ms
    extra_timeout: Optional[int] = None  # ms
    reverse_io: bool = False

    # For timeit
    timeit_dups: Dict[str, List[pathlib.Path]] = dataclasses.field(
        default_factory=lambda: collections.defaultdict(list)
    )
    timeit_prefix: Optional[str] = None

    def get_cacheable_params(self) -> Dict[str, Any]:
        return self.model_dump(mode='json', exclude_unset=True, exclude_none=True)

    def set_stdio(
        self,
        stdin: Optional[pathlib.Path] = None,
        stdout: Optional[pathlib.Path] = None,
    ):
        """Set the standard input/output files.

        stdin (Path): standard input file.
        stdout (Path): standard output file.

        """
        self.stdin_file = stdin
        self.stdout_file = stdout

    def set_stdall(
        self,
        stdin: Optional[pathlib.Path] = None,
        stdout: Optional[pathlib.Path] = None,
        stderr: Optional[pathlib.Path] = None,
    ):
        """Set the standard input/output/error files.

        stdin (Path): standard input file.
        stdout (Path): standard output file.
        stderr (Path): standard error file.

        """
        self.stdin_file = stdin
        self.stdout_file = stdout
        self.stderr_file = stderr

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
        if dest is None:
            dest = src
        if ignore_if_not_existing and not src.exists():
            return
        self.dirs.append(DirectoryMount(src, dest, options))


class SandboxBase(abc.ABC):
    """A base class for all sandboxes, meant to contain common
    resources.

    """

    EXIT_SANDBOX_ERROR = 'sandbox error'
    EXIT_OK = 'ok'
    EXIT_TERMINATED = 'terminated'
    EXIT_SIGNAL = 'signal'
    EXIT_TIMEOUT = 'timeout'
    EXIT_TIMEOUT_WALL = 'wall timeout'
    EXIT_NONZERO_RETURN = 'nonzero return'
    EXIT_MEMORY_LIMIT_EXCEEDED = 'memory limit exceeded'
    EXIT_OUTPUT_LIMIT_EXCEEDED = 'output limit exceeded'

    file_cacher: cacher.FileCacher
    name: str
    temp_dir: Optional[pathlib.Path]
    cmd_file: pathlib.Path

    params: SandboxParams

    def __init__(
        self,
        file_cacher: Optional[cacher.FileCacher] = None,
        name: Optional[str] = None,
        temp_dir: Optional[pathlib.Path] = None,
        params: Optional[SandboxParams] = None,
    ):
        """Initialization.

        file_cacher (FileCacher): an instance of the FileCacher class
            (to interact with FS), if the sandbox needs it.
        name (string|None): name of the sandbox, which might appear in the
            path and in system logs.
        temp_dir (Path|None): temporary directory to use; if None, use the
            default temporary directory.

        """
        self.file_cacher = file_cacher or cacher.FileCacher(storage.NullStorage())
        self.name = name if name is not None else 'unnamed'
        self.temp_dir = temp_dir

        self.cmd_file = pathlib.PosixPath('commands.log')

        self.params = params or SandboxParams()
        self.pid = None

        # Set common environment variables.
        # Specifically needed by Python, that searches the home for
        # packages.
        self.params.set_env['HOME'] = './'

    def set_params(self, params: SandboxParams):
        """Set the parameters of the sandbox.

        params (SandboxParams): the parameters to set.

        """
        self.params = params

    def set_multiprocess(self, multiprocess: bool):
        """Set the sandbox to (dis-)allow multiple threads and processes.

        multiprocess (bool): whether to allow multiple thread/processes or not.

        """
        if multiprocess:
            # Max processes is set to 1000 to limit the effect of fork bombs.
            self.params.max_processes = 1000
        else:
            self.params.max_processes = 1

    def get_stats(self) -> str:
        """Return a human-readable string representing execution time
        and memory usage.

        return (string): human-readable stats.

        """
        execution_time = self.get_execution_time()
        if execution_time is not None:
            time_str = f'{execution_time:.3f} sec'
        else:
            time_str = '(time unknown)'
        memory_used = self.get_memory_used()
        if memory_used is not None:
            mem_str = f'{memory_used / (1024 * 1024):.2f} MB'
        else:
            mem_str = '(memory usage unknown)'
        return f'[{time_str} - {mem_str}]'

    @abc.abstractmethod
    def get_root_path(self) -> pathlib.Path:
        """Return the toplevel path of the sandbox.

        return (Path): the root path.

        """
        pass

    @abc.abstractmethod
    def get_execution_time(self) -> Optional[float]:
        """Return the time spent in the sandbox.

        return (float): time spent in the sandbox.

        """
        pass

    @abc.abstractmethod
    def get_memory_used(self) -> Optional[int]:
        """Return the memory used by the sandbox.

        return (int): memory used by the sandbox (in bytes).

        """
        pass

    @abc.abstractmethod
    def get_killing_signal(self) -> int:
        """Return the signal that killed the sandboxed process.

        return (int): offending signal, or 0.

        """
        pass

    @abc.abstractmethod
    def get_exit_status(self) -> str:
        """Get information about how the sandbox terminated.

        return (string): the main reason why the sandbox terminated.

        """
        pass

    @abc.abstractmethod
    def get_exit_code(self) -> int:
        """Return the exit code of the sandboxed process.

        return (int): exitcode, or 0.

        """
        pass

    def set_pid(self, pid: int):
        processing_context.add_to_processing_context(pid)
        self.pid = pid

    def get_pid(self) -> Optional[int]:
        """Return the PID of the sandboxed process.

        return (int|None): the PID of the sandboxed process, or None if
            the sandboxed process is not running.

        """
        return self.pid

    @abc.abstractmethod
    def get_detailed_logs(self) -> str:
        """Return the detailed logs of the sandbox.

        return (string): the detailed logs of the sandbox.

        """
        pass

    @abc.abstractmethod
    def get_human_exit_description(self) -> str:
        """Get the status of the sandbox and return a human-readable
        string describing it.

        return (string): human-readable explaination of why the
                         sandbox terminated.

        """
        pass

    def use_soft_timeout(self) -> bool:
        return False

    def relative_path(self, path: pathlib.Path) -> pathlib.Path:
        """Translate from a relative path inside the sandbox to a
        system path.

        path (Path): relative path of the file inside the sandbox.

        return (string): the absolute path.

        """
        return self.get_root_path() / path

    def create_file(
        self, path: pathlib.Path, executable: bool = False, override: bool = False
    ) -> IO[bytes]:
        """Create an empty file in the sandbox and open it in write
        binary mode.

        path (Path): relative path of the file inside the sandbox.
        executable (bool): to set permissions.

        return (file): the file opened in write binary mode.

        """
        if executable:
            logger.debug('Creating executable file %s in sandbox.', path)
        else:
            logger.debug('Creating plain file %s in sandbox.', path)
        real_path = self.relative_path(path)
        if override:
            real_path.unlink(missing_ok=True)
        # Ensure directory exists.
        real_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            file_fd = os.open(str(real_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            file_ = open(file_fd, 'wb')
        except OSError as e:
            logger.error(
                'Failed create file %s in sandbox. Unable to '
                'evalulate this submission. This may be due to '
                'cheating. %s',
                real_path,
                e,
                exc_info=True,
            )
            raise
        mod = stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH | stat.S_IWUSR
        if executable:
            mod |= stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
        os.chmod(str(real_path), mod)
        return file_

    def create_symlink(
        self, path: pathlib.Path, from_path: pathlib.Path, override: bool = False
    ) -> Optional[pathlib.Path]:
        real_path = self.relative_path(path)
        if override:
            real_path.unlink(missing_ok=True)
        try:
            real_path.symlink_to(from_path.resolve())
        except NotImplementedError:
            return None
        return real_path

    def create_fifo(self, path: pathlib.Path, override: bool = False):
        real_path = self.relative_path(path)
        if override:
            real_path.unlink(missing_ok=True)
        os.mkfifo(str(real_path))
        return real_path

    def create_file_from_storage(
        self,
        path: pathlib.Path,
        digest: str,
        executable: bool = False,
        override: bool = False,
        try_symlink: bool = False,
    ):
        """Write a file taken from FS in the sandbox.

        path (Path): relative path of the file inside the sandbox.
        digest (string): digest of the file in FS.
        executable (bool): to set permissions.

        """
        if try_symlink and executable:
            symlink_path = self.file_cacher.path_for_symlink(digest)
            if symlink_path is not None:
                created = self.create_symlink(
                    path,
                    from_path=symlink_path,
                    override=override,
                )
                if created is not None:
                    created.chmod(0o755)
                    return
        with self.create_file(path, executable, override=override) as dest_fobj:
            self.file_cacher.get_file_to_fobj(digest, dest_fobj)

    def create_file_from_bytes(
        self,
        path: pathlib.Path,
        content: bytes,
        executable: bool = False,
        override: bool = False,
    ):
        """Write some data to a file in the sandbox.

        path (Path): relative path of the file inside the sandbox.
        content (bytes): what to write in the file.
        executable (bool): to set permissions.

        """
        with self.create_file(path, executable, override=override) as dest_fobj:
            dest_fobj.write(content)

    def create_file_from_other_file(
        self,
        path: pathlib.Path,
        from_path: pathlib.Path,
        executable: bool = False,
        override: bool = False,
        try_symlink: bool = False,
    ):
        """Write a file taken from FS in the sandbox.

        path (Path): relative path of the file inside the sandbox.
        digest (string): digest of the file in FS.
        executable (bool): to set permissions.

        """
        if try_symlink and executable:
            created = self.create_symlink(
                path,
                from_path,
                override=override,
            )
            if created is not None:
                created.chmod(0o755)
                return
        with self.create_file(path, executable, override=override) as dest_fobj:
            with from_path.open('rb') as src_fobj:
                storage.copyfileobj(src_fobj, dest_fobj)

    def create_file_from_string(
        self,
        path: pathlib.Path,
        content: str,
        executable: bool = False,
        override: bool = False,
    ):
        """Write some data to a file in the sandbox.

        path (Path): relative path of the file inside the sandbox.
        content (str): what to write in the file.
        executable (bool): to set permissions.

        """
        return self.create_file_from_bytes(
            path, content.encode('utf-8'), executable, override=override
        )

    def get_file(
        self, path: pathlib.Path, trunc_len: Optional[int] = None
    ) -> IO[bytes]:
        """Open a file in the sandbox given its relative path.

        path (Path): relative path of the file inside the sandbox.
        trunc_len (int|None): if None, does nothing; otherwise, before
            returning truncate it at the specified length.

        return (file): the file opened in read binary mode.

        """
        logger.debug(f'Retrieving file {path} from sandbox.')
        real_path = self.relative_path(path)
        file_ = real_path.open('rb')
        if trunc_len is not None:
            file_ = Truncator(file_, trunc_len)
        return typing.cast(IO[bytes], file_)

    def get_file_text(
        self, path: pathlib.Path, trunc_len: Optional[int] = None
    ) -> IO[str]:
        """Open a file in the sandbox given its relative path, in text mode.

        Assumes encoding is UTF-8. The caller must handle decoding errors.

        path (Path): relative path of the file inside the sandbox.
        trunc_len (int|None): if None, does nothing; otherwise, before
            returning truncate it at the specified length.

        return (file): the file opened in read binary mode.

        """
        logger.debug('Retrieving text file %s from sandbox.', path)
        real_path = self.relative_path(path)
        file_ = real_path.open('rt', encoding='utf-8')
        if trunc_len is not None:
            file_ = Truncator(file_, trunc_len)
        return typing.cast(IO[str], file_)

    def get_file_to_bytes(
        self, path: pathlib.Path, maxlen: Optional[int] = 1024
    ) -> bytes:
        """Return the content of a file in the sandbox given its
        relative path.

        path (Path): relative path of the file inside the sandbox.
        maxlen (int): maximum number of bytes to read, or None if no
            limit.

        return (bytes): the content of the file up to maxlen bytes.

        """
        with self.get_file(path) as file_:
            if maxlen is None:
                return file_.read()
            else:
                return file_.read(maxlen)

    def get_file_to_string(
        self, path: pathlib.Path, maxlen: Optional[int] = 1024
    ) -> str:
        """Return the content of a file in the sandbox given its
        relative path.

        path (Path): relative path of the file inside the sandbox.
        maxlen (int): maximum number of bytes to read, or None if no
            limit.

        return (string): the content of the file up to maxlen bytes.

        """
        return self.get_file_to_bytes(path, maxlen).decode('utf-8')

    def get_file_to_storage(
        self, path: pathlib.Path, description: str = '', trunc_len: Optional[int] = None
    ) -> str:
        """Put a sandbox file in FS and return its digest.

        path (Path): relative path of the file inside the sandbox.
        description (str): the description for FS.
        trunc_len (int|None): if None, does nothing; otherwise, before
            returning truncate it at the specified length.

        return (str): the digest of the file.

        """
        with self.get_file(path, trunc_len=trunc_len) as file_:
            return self.file_cacher.put_file_from_fobj(file_, description)

    def stat_file(self, path: pathlib.Path) -> os.stat_result:
        """Return the stats of a file in the sandbox.

        path (Path): relative path of the file inside the sandbox.

        return (stat_result): the stat results.

        """
        return self.relative_path(path).stat()

    def file_exists(self, path: pathlib.Path) -> bool:
        """Return if a file exists in the sandbox.

        path (Path): relative path of the file inside the sandbox.

        return (bool): if the file exists.

        """
        return self.relative_path(path).exists()

    def remove_file(self, path: pathlib.Path):
        """Delete a file in the sandbox.

        path (Path): relative path of the file inside the sandbox.

        """
        self.relative_path(path).unlink(missing_ok=True)

    def glob(self, glob_expr: str) -> List[pathlib.Path]:
        return [
            path.relative_to(self.get_root_path())
            for path in self.get_root_path().glob(glob_expr)
        ]

    @abc.abstractmethod
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
        wait (bool): True if this call is blocking, False otherwise

        return (bool|Popen): if the call is blocking, then return True
            if the sandbox didn't report errors (caused by the sandbox
            itself), False otherwise; if the call is not blocking,
            return the Popen object from subprocess.

        """
        pass

    @abc.abstractmethod
    def hydrate_logs(self):
        """Fetch the results of the execution and hydrate logs.

        This method should be called after the execution has
        terminated, to hydrate logs and stuff.
        """
        pass

    def translate_box_exitcode(self, exitcode: int) -> bool:
        """Translate the sandbox exit code to a boolean sandbox success.

        _ (int): the exit code of the sandbox.

        return (bool): False if the sandbox had an error, True if it
            terminated correctly (regardless of what the internal process
            did).

        """
        # SIGTERM can be safely ignored, just in case it leaks away from
        # the sandbox.
        return exitcode == 0 or exitcode == -signal.SIGTERM

    @abc.abstractmethod
    def initialize(self):
        """Initialize the sandbox.

        To be called at the beginning of the execution.

        """
        pass

    @abc.abstractmethod
    def cleanup(self, delete: bool = False):
        """Cleanup the sandbox.

        To be called at the end of the execution, regardless of
        whether the sandbox should be deleted or not.

        delete (bool): if True, also delete get_root_path() and everything it
            contains.

        """
        pass

    def debug_message(self) -> Any:
        return 'N/A'


class Truncator(io.RawIOBase):
    """Wrap a file-like object to simulate truncation.

    This file-like object provides read-only access to a limited prefix
    of a wrapped file-like object. It provides a truncated version of
    the file without ever touching the object on the filesystem.

    This class is only able to wrap binary streams as it relies on the
    readinto method which isn't provided by text (unicode) streams.

    """

    def __init__(self, fobj, size):
        """Wrap fobj and give access to its first size bytes.

        fobj (fileobj): a file-like object to wrap.
        size (int): the number of bytes that will be accessible.

        """
        self.fobj = fobj
        self.size = size

    def close(self):
        """See io.IOBase.close."""
        self.fobj.close()

    @property
    def closed(self):
        """See io.IOBase.closed."""
        return self.fobj.closed

    def readable(self):
        """See io.IOBase.readable."""
        return True

    def seekable(self):
        """See io.IOBase.seekable."""
        return True

    def readinto(self, b):
        """See io.RawIOBase.readinto."""
        # This is the main "trick": we clip (i.e. mask, reduce, slice)
        # the given buffer so that it doesn't overflow into the area we
        # want to hide (that is, out of the prefix) and then we forward
        # it to the wrapped file-like object.
        b = memoryview(b)[: max(0, self.size - self.fobj.tell())]
        return self.fobj.readinto(b)

    def seek(self, offset, whence=io.SEEK_SET):
        """See io.IOBase.seek."""
        # We have to catch seeks relative to the end of the file and
        # adjust them to the new "imposed" size.
        if whence == io.SEEK_END:
            if self.fobj.seek(0, io.SEEK_END) > self.size:
                self.fobj.seek(self.size, io.SEEK_SET)
            return self.fobj.seek(offset, io.SEEK_CUR)
        else:
            return self.fobj.seek(offset, whence)

    def tell(self):
        """See io.IOBase.tell."""
        return self.fobj.tell()

    def write(self, _):
        """See io.RawIOBase.write."""
        raise io.UnsupportedOperation('write')
