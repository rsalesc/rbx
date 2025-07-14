import io
import pathlib
import stat
import tempfile

import pytest

from rbx.grading.judge.cacher import FileCacher
from rbx.grading.judge.sandbox import SandboxParams, Truncator
from rbx.grading.judge.sandboxes.stupid_sandbox import StupidSandbox


@pytest.fixture
def sandbox_test_data(testdata_path):
    """Path to sandbox test data directory."""
    return testdata_path / 'sandbox_test'


@pytest.fixture
def test_file_content():
    """Sample file content for testing."""
    return b'Hello, World!\nThis is a test file.\n'


@pytest.fixture
def test_string_content():
    """Sample string content for testing."""
    return 'Hello, World!\nThis is a test string.\n'


class TestSandboxParams:
    """Test SandboxParams model."""

    def test_set_stdio(self):
        """Test setting standard input/output files."""
        params = SandboxParams()
        stdin_path = pathlib.Path('/tmp/input.txt')
        stdout_path = pathlib.Path('/tmp/output.txt')

        params.set_stdio(stdin=stdin_path, stdout=stdout_path)

        assert params.stdin_file == stdin_path
        assert params.stdout_file == stdout_path

    def test_set_stdall(self):
        """Test setting standard input/output/error files."""
        params = SandboxParams()
        stdin_path = pathlib.Path('/tmp/input.txt')
        stdout_path = pathlib.Path('/tmp/output.txt')
        stderr_path = pathlib.Path('/tmp/error.txt')

        params.set_stdall(stdin=stdin_path, stdout=stdout_path, stderr=stderr_path)

        assert params.stdin_file == stdin_path
        assert params.stdout_file == stdout_path
        assert params.stderr_file == stderr_path

    def test_add_mapped_directory(self):
        """Test adding mapped directories."""
        params = SandboxParams()
        src_path = pathlib.Path('/tmp/src')
        dest_path = pathlib.Path('/sandbox/dest')

        params.add_mapped_directory(src_path, dest_path, options='rw')

        assert len(params.dirs) == 1
        assert params.dirs[0].src == src_path
        assert params.dirs[0].dst == dest_path
        assert params.dirs[0].options == 'rw'

    def test_add_mapped_directory_ignore_nonexistent(self, tmp_path):
        """Test ignoring nonexistent directories when flag is set."""
        params = SandboxParams()
        nonexistent_path = tmp_path / 'nonexistent'

        # Should not add when ignore_if_not_existing=True
        params.add_mapped_directory(nonexistent_path, ignore_if_not_existing=True)
        assert len(params.dirs) == 0

    def test_get_cacheable_params(self):
        """Test getting cacheable parameters."""
        params = SandboxParams(fsize=1024, timeout=5000, set_env={'TEST': 'value'})

        cacheable = params.get_cacheable_params()

        assert cacheable['fsize'] == 1024
        assert cacheable['timeout'] == 5000
        assert cacheable['set_env'] == {'TEST': 'value'}
        assert 'cgroup' not in cacheable  # Should exclude default values


class TestSandboxBase:
    """Test SandboxBase filesystem methods."""

    def test_sandbox_initialization(self, sandbox):
        """Test sandbox initialization."""
        assert sandbox.name == 'unnamed'
        assert isinstance(sandbox.file_cacher, FileCacher)
        assert sandbox.get_root_path().exists()

    def test_sandbox_with_custom_name(self):
        """Test sandbox with custom name."""
        sandbox = StupidSandbox(name='test_sandbox')
        assert sandbox.name == 'test_sandbox'
        sandbox.cleanup(delete=True)

    def test_relative_path(self, sandbox):
        """Test relative path conversion."""
        rel_path = pathlib.Path('test/file.txt')
        abs_path = sandbox.relative_path(rel_path)

        expected = sandbox.get_root_path() / rel_path
        assert abs_path == expected

    def test_create_file_plain(self, sandbox):
        """Test creating a plain file."""
        file_path = pathlib.Path('test_file.txt')

        with sandbox.create_file(file_path) as f:
            f.write(b'Hello, World!')

        # Check file exists and has correct permissions
        real_path = sandbox.relative_path(file_path)
        assert real_path.exists()
        assert real_path.is_file()

        # Check permissions (readable by all, writable by owner)
        file_stat = real_path.stat()
        expected_mode = stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH | stat.S_IWUSR
        assert file_stat.st_mode & 0o777 == expected_mode

    def test_create_file_executable(self, sandbox):
        """Test creating an executable file."""
        file_path = pathlib.Path('test_executable.sh')

        with sandbox.create_file(file_path, executable=True) as f:
            f.write(b'#!/bin/bash\necho "Hello"')

        # Check file exists and has correct permissions
        real_path = sandbox.relative_path(file_path)
        assert real_path.exists()

        # Check permissions (executable by all)
        file_stat = real_path.stat()
        expected_mode = (
            stat.S_IRUSR
            | stat.S_IRGRP
            | stat.S_IROTH
            | stat.S_IWUSR
            | stat.S_IXUSR
            | stat.S_IXGRP
            | stat.S_IXOTH
        )
        assert file_stat.st_mode & 0o777 == expected_mode

    def test_create_file_with_nested_directory(self, sandbox):
        """Test creating a file in a nested directory."""
        file_path = pathlib.Path('nested/dir/test_file.txt')

        with sandbox.create_file(file_path) as f:
            f.write(b'Nested file content')

        real_path = sandbox.relative_path(file_path)
        assert real_path.exists()
        assert real_path.parent.exists()
        assert real_path.parent.is_dir()

    def test_create_file_override(self, sandbox):
        """Test overriding an existing file."""
        file_path = pathlib.Path('test_override.txt')

        # Create initial file
        with sandbox.create_file(file_path) as f:
            f.write(b'Initial content')

        # Override with new content
        with sandbox.create_file(file_path, override=True) as f:
            f.write(b'New content')

        # Check content was overridden
        content = sandbox.get_file_to_bytes(file_path)
        assert content == b'New content'

    def test_create_file_duplicate_without_override(self, sandbox):
        """Test creating duplicate file without override flag raises error."""
        file_path = pathlib.Path('test_duplicate.txt')

        # Create initial file
        with sandbox.create_file(file_path) as f:
            f.write(b'Initial content')

        # Attempt to create duplicate should raise OSError
        with pytest.raises(OSError):
            with sandbox.create_file(file_path) as f:
                f.write(b'Duplicate content')

    def test_create_symlink(self, sandbox, tmp_path):
        """Test creating a symlink."""
        # Create a target file outside sandbox
        target_file = tmp_path / 'target.txt'
        target_file.write_text('Target content')

        link_path = pathlib.Path('test_link.txt')

        result = sandbox.create_symlink(link_path, target_file)

        if result is not None:  # Symlinks supported
            real_path = sandbox.relative_path(link_path)
            assert real_path.is_symlink()
            assert real_path.resolve() == target_file.resolve()

    def test_create_symlink_override(self, sandbox, tmp_path):
        """Test overriding an existing symlink."""
        target_file1 = tmp_path / 'target1.txt'
        target_file1.write_text('Target 1')
        target_file2 = tmp_path / 'target2.txt'
        target_file2.write_text('Target 2')

        link_path = pathlib.Path('test_link_override.txt')

        # Create initial symlink
        result1 = sandbox.create_symlink(link_path, target_file1)
        if result1 is None:
            pytest.skip('Symlinks not supported on this platform')

        # Override with new target
        sandbox.create_symlink(link_path, target_file2, override=True)

        real_path = sandbox.relative_path(link_path)
        assert real_path.resolve() == target_file2.resolve()

    def test_create_fifo(self, sandbox):
        """Test creating a FIFO."""
        fifo_path = pathlib.Path('test_fifo')

        result = sandbox.create_fifo(fifo_path)

        assert result == sandbox.relative_path(fifo_path)
        assert result.exists()
        assert stat.S_ISFIFO(result.stat().st_mode)

    def test_create_file_from_bytes(self, sandbox, test_file_content):
        """Test creating a file from bytes."""
        file_path = pathlib.Path('test_from_bytes.txt')

        sandbox.create_file_from_bytes(file_path, test_file_content)

        # Verify content
        content = sandbox.get_file_to_bytes(file_path)
        assert content == test_file_content

    def test_create_file_from_string(self, sandbox, test_string_content):
        """Test creating a file from string."""
        file_path = pathlib.Path('test_from_string.txt')

        sandbox.create_file_from_string(file_path, test_string_content)

        # Verify content
        content = sandbox.get_file_to_string(file_path)
        assert content == test_string_content

    def test_create_file_from_other_file(self, sandbox, tmp_path):
        """Test creating a file from another file."""
        # Create source file
        source_file = tmp_path / 'source.txt'
        source_content = b'Source file content'
        source_file.write_bytes(source_content)

        dest_path = pathlib.Path('test_from_file.txt')

        sandbox.create_file_from_other_file(dest_path, source_file)

        # Verify content
        content = sandbox.get_file_to_bytes(dest_path)
        assert content == source_content

    def test_create_file_from_storage(self, sandbox):
        """Test creating a file from storage."""
        file_path = pathlib.Path('test_from_storage.txt')
        test_content = b'Storage file content'

        # Put content in storage first
        with tempfile.NamedTemporaryFile() as tmp:
            tmp.write(test_content)
            tmp.flush()
            digest = sandbox.file_cacher.put_file_from_path(pathlib.Path(tmp.name))

        # Create file from storage
        sandbox.create_file_from_storage(file_path, digest)

        # Verify content
        content = sandbox.get_file_to_bytes(file_path)
        assert content == test_content

    def test_get_file(self, sandbox, test_file_content):
        """Test getting a file handle."""
        file_path = pathlib.Path('test_get_file.txt')
        sandbox.create_file_from_bytes(file_path, test_file_content)

        with sandbox.get_file(file_path) as f:
            content = f.read()

        assert content == test_file_content

    def test_get_file_text(self, sandbox, test_string_content):
        """Test getting a file handle in text mode."""
        file_path = pathlib.Path('test_get_text.txt')
        sandbox.create_file_from_string(file_path, test_string_content)

        with sandbox.get_file_text(file_path) as f:
            content = f.read()

        assert content == test_string_content

    def test_get_file_with_truncation(self, sandbox):
        """Test getting a file with truncation."""
        file_path = pathlib.Path('test_truncate.txt')
        long_content = b'A' * 1000
        sandbox.create_file_from_bytes(file_path, long_content)

        with sandbox.get_file(file_path, trunc_len=100) as f:
            content = f.read()

        assert len(content) == 100
        assert content == b'A' * 100

    def test_get_file_to_bytes(self, sandbox, test_file_content):
        """Test getting file content as bytes."""
        file_path = pathlib.Path('test_to_bytes.txt')
        sandbox.create_file_from_bytes(file_path, test_file_content)

        content = sandbox.get_file_to_bytes(file_path)
        assert content == test_file_content

    def test_get_file_to_bytes_with_limit(self, sandbox):
        """Test getting file content with size limit."""
        file_path = pathlib.Path('test_limit.txt')
        long_content = b'B' * 1000
        sandbox.create_file_from_bytes(file_path, long_content)

        content = sandbox.get_file_to_bytes(file_path, maxlen=50)
        assert len(content) == 50
        assert content == b'B' * 50

    def test_get_file_to_string(self, sandbox, test_string_content):
        """Test getting file content as string."""
        file_path = pathlib.Path('test_to_string.txt')
        sandbox.create_file_from_string(file_path, test_string_content)

        content = sandbox.get_file_to_string(file_path)
        assert content == test_string_content

    def test_get_file_to_storage(self, sandbox, test_file_content):
        """Test putting a file into storage."""
        file_path = pathlib.Path('test_to_storage.txt')
        sandbox.create_file_from_bytes(file_path, test_file_content)

        digest = sandbox.get_file_to_storage(file_path)

        # Verify we can retrieve the same content
        with tempfile.NamedTemporaryFile() as tmp:
            sandbox.file_cacher.get_file_to_path(digest, pathlib.Path(tmp.name))
            retrieved_content = pathlib.Path(tmp.name).read_bytes()

        assert retrieved_content == test_file_content

    def test_stat_file(self, sandbox, test_file_content):
        """Test getting file statistics."""
        file_path = pathlib.Path('test_stat.txt')
        sandbox.create_file_from_bytes(file_path, test_file_content)

        file_stat = sandbox.stat_file(file_path)

        assert file_stat.st_size == len(test_file_content)
        assert stat.S_ISREG(file_stat.st_mode)

    def test_file_exists(self, sandbox):
        """Test checking if file exists."""
        existing_path = pathlib.Path('existing.txt')
        nonexistent_path = pathlib.Path('nonexistent.txt')

        sandbox.create_file_from_bytes(existing_path, b'content')

        assert sandbox.file_exists(existing_path) is True
        assert sandbox.file_exists(nonexistent_path) is False

    def test_remove_file(self, sandbox):
        """Test removing a file."""
        file_path = pathlib.Path('test_remove.txt')
        sandbox.create_file_from_bytes(file_path, b'content')

        assert sandbox.file_exists(file_path) is True

        sandbox.remove_file(file_path)

        assert sandbox.file_exists(file_path) is False

    def test_remove_nonexistent_file(self, sandbox):
        """Test removing a nonexistent file doesn't raise error."""
        nonexistent_path = pathlib.Path('nonexistent.txt')

        # Should not raise an error
        sandbox.remove_file(nonexistent_path)

    def test_glob(self, sandbox):
        """Test globbing files."""
        # Create test files
        sandbox.create_file_from_bytes(pathlib.Path('test1.txt'), b'content1')
        sandbox.create_file_from_bytes(pathlib.Path('test2.txt'), b'content2')
        sandbox.create_file_from_bytes(pathlib.Path('other.py'), b'python code')
        sandbox.create_file_from_bytes(pathlib.Path('subdir/test3.txt'), b'content3')

        # Test various glob patterns
        txt_files = sandbox.glob('*.txt')
        assert len(txt_files) == 2
        assert pathlib.Path('test1.txt') in txt_files
        assert pathlib.Path('test2.txt') in txt_files

        all_files = sandbox.glob('**/*')
        assert len(all_files) >= 4  # At least our test files

        subdir_files = sandbox.glob('subdir/*.txt')
        assert len(subdir_files) == 1
        assert pathlib.Path('subdir/test3.txt') in subdir_files

    def test_reset_sandbox(self, sandbox):
        """Test resetting the sandbox."""
        # Create a file
        file_path = pathlib.Path('test_reset.txt')
        sandbox.create_file_from_bytes(file_path, b'content')

        assert sandbox.file_exists(file_path) is True

        # Reset sandbox
        sandbox.reset()

        # File should be gone
        assert sandbox.file_exists(file_path) is False

    def test_cleanup_sandbox(self, sandbox):
        """Test cleaning up the sandbox."""
        root_path = sandbox.get_root_path()
        assert root_path.exists()

        # Create a file
        file_path = pathlib.Path('test_cleanup.txt')
        sandbox.create_file_from_bytes(file_path, b'content')

        # Cleanup without delete
        sandbox.cleanup(delete=False)
        assert root_path.exists()

        # Cleanup with delete
        sandbox.cleanup(delete=True)
        assert not root_path.exists()


class TestTruncator:
    """Test the Truncator class."""

    def test_truncator_basic(self, tmp_path):
        """Test basic truncation functionality."""
        test_file = tmp_path / 'test.txt'
        content = b'Hello, World! This is a longer message.'
        test_file.write_bytes(content)

        with test_file.open('rb') as f:
            truncator = Truncator(f, 13)  # "Hello, World!"
            truncated_content = truncator.read()

        assert truncated_content == b'Hello, World!'

    def test_truncator_seek_and_tell(self, tmp_path):
        """Test seek and tell operations with truncator."""
        test_file = tmp_path / 'test.txt'
        content = b'0123456789'
        test_file.write_bytes(content)

        with test_file.open('rb') as f:
            truncator = Truncator(f, 5)  # First 5 bytes

            # Test tell
            assert truncator.tell() == 0

            # Test read and tell
            data = truncator.read(3)
            assert data == b'012'
            assert truncator.tell() == 3

            # Test seek
            truncator.seek(1)
            assert truncator.tell() == 1
            data = truncator.read(2)
            assert data == b'12'

    def test_truncator_seek_end(self, tmp_path):
        """Test seeking to end with truncator."""
        test_file = tmp_path / 'test.txt'
        content = b'0123456789'
        test_file.write_bytes(content)

        with test_file.open('rb') as f:
            truncator = Truncator(f, 5)  # First 5 bytes

            # Seek to end should respect truncation
            truncator.seek(0, 2)  # SEEK_END
            assert truncator.tell() == 5

            # Reading should return empty
            data = truncator.read()
            assert data == b''

    def test_truncator_readinto(self, tmp_path):
        """Test readinto method with truncator."""
        test_file = tmp_path / 'test.txt'
        content = b'Hello, World!'
        test_file.write_bytes(content)

        with test_file.open('rb') as f:
            truncator = Truncator(f, 5)  # First 5 bytes

            buffer = bytearray(10)
            bytes_read = truncator.readinto(buffer)

            assert bytes_read == 5
            assert buffer[:5] == b'Hello'

    def test_truncator_properties(self, tmp_path):
        """Test truncator properties."""
        test_file = tmp_path / 'test.txt'
        test_file.write_bytes(b'test content')

        with test_file.open('rb') as f:
            truncator = Truncator(f, 5)

            assert truncator.readable() is True
            assert truncator.seekable() is True
            assert truncator.closed is False

            # Test write raises UnsupportedOperation
            with pytest.raises(io.UnsupportedOperation):
                truncator.write(b'data')

    def test_truncator_close(self, tmp_path):
        """Test closing truncator."""
        test_file = tmp_path / 'test.txt'
        test_file.write_bytes(b'test content')

        f = test_file.open('rb')
        truncator = Truncator(f, 5)

        assert truncator.closed is False
        truncator.close()
        assert truncator.closed is True


class TestSandboxEdgeCases:
    """Test edge cases and error conditions."""

    def test_get_file_to_storage_with_truncation(self, sandbox, tmp_path_factory):
        """Test putting truncated file to storage."""
        file_path = pathlib.Path('test_trunc_storage.txt')
        long_content = b'A' * 1000
        sandbox.create_file_from_bytes(file_path, long_content)

        # Put truncated version to storage
        digest = sandbox.get_file_to_storage(file_path, trunc_len=100)

        # Verify truncated content in storage
        tmp_path = tmp_path_factory.mktemp('test_trunc')
        tmp_file = tmp_path / 'truncated.txt'
        sandbox.file_cacher.get_file_to_path(digest, tmp_file)
        retrieved_content = tmp_file.read_bytes()

        assert len(retrieved_content) == 100
        assert retrieved_content == b'A' * 100

    def test_empty_file_operations(self, sandbox):
        """Test operations on empty files."""
        file_path = pathlib.Path('empty.txt')
        sandbox.create_file_from_bytes(file_path, b'')

        # Test various operations on empty file
        assert sandbox.file_exists(file_path) is True
        assert sandbox.get_file_to_bytes(file_path) == b''
        assert sandbox.get_file_to_string(file_path) == ''

        file_stat = sandbox.stat_file(file_path)
        assert file_stat.st_size == 0

    def test_unicode_file_operations(self, sandbox):
        """Test operations with unicode content."""
        file_path = pathlib.Path('unicode.txt')
        unicode_content = 'Hello, 世界! 🌍'

        sandbox.create_file_from_string(file_path, unicode_content)

        # Test retrieval
        content = sandbox.get_file_to_string(file_path)
        assert content == unicode_content

        # Test bytes representation
        expected_bytes = unicode_content.encode('utf-8')
        bytes_content = sandbox.get_file_to_bytes(file_path)
        assert bytes_content == expected_bytes

    def test_large_file_operations(self, sandbox):
        """Test operations with larger files."""
        file_path = pathlib.Path('large.txt')
        # Create a moderately large file (1MB)
        large_content = b'X' * (1024 * 1024)

        sandbox.create_file_from_bytes(file_path, large_content)

        # Test stat
        file_stat = sandbox.stat_file(file_path)
        assert file_stat.st_size == len(large_content)

        # Test partial read
        partial_content = sandbox.get_file_to_bytes(file_path, maxlen=1024)
        assert len(partial_content) == 1024
        assert partial_content == b'X' * 1024
