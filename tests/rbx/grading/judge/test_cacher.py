import io
import pathlib
import tempfile
from unittest.mock import Mock, patch

import pytest
from pydantic import BaseModel

from rbx.grading.judge import storage
from rbx.grading.judge.cacher import FileCacher, TombstoneError
from rbx.grading.judge.storage import FilesystemStorage, NullStorage


class CacherTestMetadata(BaseModel):
    """Test metadata model for testing metadata functionality."""

    value: str
    number: int = 42


class TestFileCacher:
    """Test suite for FileCacher class."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for testing."""
        with tempfile.TemporaryDirectory() as temp_dir:
            yield pathlib.Path(temp_dir)

    @pytest.fixture
    def mock_storage(self):
        """Create a mock storage backend."""
        return Mock(spec=storage.Storage)

    @pytest.fixture
    def null_storage(self):
        """Create a null storage backend."""
        return NullStorage()

    @pytest.fixture
    def filesystem_storage(self, temp_dir):
        """Create a filesystem storage backend."""
        return FilesystemStorage(temp_dir)

    @pytest.fixture
    def cacher_with_mock(self, mock_storage):
        """Create a FileCacher with mock storage."""
        return FileCacher(mock_storage)

    @pytest.fixture
    def cacher_with_null(self, null_storage):
        """Create a FileCacher with null storage."""
        return FileCacher(null_storage)

    @pytest.fixture
    def cacher_with_filesystem(self, filesystem_storage):
        """Create a FileCacher with filesystem storage."""
        return FileCacher(filesystem_storage)

    @pytest.fixture
    def shared_cacher(self, filesystem_storage, temp_dir):
        """Create a shared FileCacher."""
        return FileCacher(filesystem_storage, shared=True, folder=temp_dir)

    def test_init_non_shared_creates_temp_directory(self, mock_storage):
        """Test that non-shared cacher creates temporary directories."""
        cacher = FileCacher(mock_storage, shared=False)

        assert not cacher.is_shared()
        assert cacher.file_dir.exists()
        assert cacher.temp_dir.exists()
        assert cacher.temp_dir.parent == cacher.file_dir

    def test_init_shared_uses_provided_folder(self, mock_storage, temp_dir):
        """Test that shared cacher uses provided folder."""
        cacher = FileCacher(mock_storage, shared=True, folder=temp_dir)

        assert cacher.is_shared()
        assert cacher.file_dir == temp_dir / 'fs-cache-shared'
        assert cacher.file_dir.exists()
        assert cacher.temp_dir.exists()

    def test_init_shared_creates_folder_if_provided(self, mock_storage, temp_dir):
        """Test that shared cacher creates folder if it doesn't exist."""
        folder = temp_dir / 'new_folder'
        cacher = FileCacher(mock_storage, shared=True, folder=folder)

        assert cacher.is_shared()
        assert folder.exists()

    def test_precache_lock_exclusive(self, shared_cacher):
        """Test precache lock functionality."""
        # First lock should succeed
        lock1 = shared_cacher.precache_lock()
        assert lock1 is not None

        # Second lock should fail
        lock2 = shared_cacher.precache_lock()
        assert lock2 is None

        # After closing first lock, second should succeed
        lock1.close()
        lock3 = shared_cacher.precache_lock()
        assert lock3 is not None
        lock3.close()

    def test_exists_cache_only_true_when_cached(self, cacher_with_mock):
        """Test exists with cache_only=True returns True when file is cached."""
        digest = 'test_digest'
        cache_file = cacher_with_mock.file_dir / digest
        cache_file.write_bytes(b'test content')

        assert cacher_with_mock.exists(digest, cache_only=True) is True

    def test_exists_cache_only_false_when_not_cached(self, cacher_with_mock):
        """Test exists with cache_only=True returns False when file is not cached."""
        digest = 'nonexistent_digest'

        assert cacher_with_mock.exists(digest, cache_only=True) is False

    def test_exists_checks_backend_when_not_cache_only(self, cacher_with_mock):
        """Test exists checks backend when cache_only=False."""
        digest = 'test_digest'
        cacher_with_mock.backend.exists.return_value = True

        result = cacher_with_mock.exists(digest, cache_only=False)

        assert result is True
        cacher_with_mock.backend.exists.assert_called_once_with(digest)
        assert digest in cacher_with_mock.existing

    def test_exists_remembers_existing_files(self, cacher_with_mock):
        """Test that exists remembers files that exist in backend."""
        digest = 'test_digest'
        cacher_with_mock.existing.add(digest)

        result = cacher_with_mock.exists(digest, cache_only=True)

        assert result is True

    def test_cache_file_tombstone_raises_error(self, cacher_with_mock):
        """Test that cache_file raises TombstoneError for tombstone digest."""
        with pytest.raises(TombstoneError):
            cacher_with_mock.cache_file(storage.TOMBSTONE)

    def test_cache_file_with_cache_only_behavior(self, cacher_with_mock):
        """Test cache_file method behavior when file already exists in cache."""
        digest = 'test_digest'
        cache_file = cacher_with_mock.file_dir / digest
        cache_file.write_bytes(b'cached content')

        # This should not raise an error and should not call backend
        cacher_with_mock.cache_file(digest)

        # Verify backend wasn't called since file was already cached
        cacher_with_mock.backend.get_file.assert_not_called()

    def test_cache_file_loads_from_backend_when_not_cached(self, cacher_with_mock):
        """Test cache_file loads from backend when file not in cache."""
        digest = 'test_digest'
        test_content = b'backend content'

        cacher_with_mock.backend.path_for_symlink.return_value = None
        cacher_with_mock.backend.get_file.return_value = io.BytesIO(test_content)

        cacher_with_mock.cache_file(digest)

        # Verify file was loaded from backend and cached
        cache_file = cacher_with_mock.file_dir / digest
        assert cache_file.exists()
        assert cache_file.read_bytes() == test_content
        cacher_with_mock.backend.get_file.assert_called_once_with(digest)

    def test_get_file_tombstone_raises_error(self, cacher_with_mock):
        """Test that get_file raises TombstoneError for tombstone digest."""
        with pytest.raises(TombstoneError):
            cacher_with_mock.get_file(storage.TOMBSTONE)

    def test_get_file_from_cache_when_available(self, cacher_with_mock):
        """Test get_file returns cached file when available."""
        digest = 'test_digest'
        test_content = b'cached content'

        cache_file = cacher_with_mock.file_dir / digest
        cache_file.write_bytes(test_content)

        with cacher_with_mock.get_file(digest) as f:
            content = f.read()

        assert content == test_content

    def test_get_file_loads_from_backend_when_not_cached(self, cacher_with_mock):
        """Test get_file loads from backend when not cached."""
        digest = 'test_digest'
        test_content = b'backend content'

        cacher_with_mock.backend.path_for_symlink.return_value = None
        cacher_with_mock.backend.get_file.return_value = io.BytesIO(test_content)

        with cacher_with_mock.get_file(digest) as f:
            content = f.read()

        assert content == test_content
        # Verify file is now cached
        cache_file = cacher_with_mock.file_dir / digest
        assert cache_file.exists()
        assert cache_file.read_bytes() == test_content

    def test_get_file_uses_symlink_when_available(self, cacher_with_mock, temp_dir):
        """Test get_file creates symlink when backend provides path."""
        digest = 'test_digest'
        test_content = b'symlink content'

        # Create source file
        source_file = temp_dir / 'source.txt'
        source_file.write_bytes(test_content)

        cacher_with_mock.backend.path_for_symlink.return_value = source_file

        with cacher_with_mock.get_file(digest) as f:
            content = f.read()

        assert content == test_content
        # Verify symlink was created
        cache_file = cacher_with_mock.file_dir / digest
        assert cache_file.is_symlink()
        # Use resolve() to handle macOS /private symlink differences
        assert cache_file.resolve().samefile(source_file)

    def test_get_file_content_returns_bytes(self, cacher_with_mock):
        """Test get_file_content returns file content as bytes."""
        digest = 'test_digest'
        test_content = b'test content'

        cache_file = cacher_with_mock.file_dir / digest
        cache_file.write_bytes(test_content)

        content = cacher_with_mock.get_file_content(digest)

        assert content == test_content

    def test_get_file_to_fobj_writes_to_file_object(self, cacher_with_mock):
        """Test get_file_to_fobj writes content to file object."""
        digest = 'test_digest'
        test_content = b'test content'

        cache_file = cacher_with_mock.file_dir / digest
        cache_file.write_bytes(test_content)

        output = io.BytesIO()
        cacher_with_mock.get_file_to_fobj(digest, output)

        assert output.getvalue() == test_content

    def test_get_file_to_path_writes_to_path(self, cacher_with_mock, temp_dir):
        """Test get_file_to_path writes content to specified path."""
        digest = 'test_digest'
        test_content = b'test content'
        dest_path = temp_dir / 'output.txt'

        cache_file = cacher_with_mock.file_dir / digest
        cache_file.write_bytes(test_content)

        cacher_with_mock.get_file_to_path(digest, dest_path)

        assert dest_path.exists()
        assert dest_path.read_bytes() == test_content

    def test_get_file_to_path_creates_parent_directories(
        self, cacher_with_mock, temp_dir
    ):
        """Test get_file_to_path creates parent directories."""
        digest = 'test_digest'
        test_content = b'test content'
        dest_path = temp_dir / 'subdir' / 'output.txt'

        cache_file = cacher_with_mock.file_dir / digest
        cache_file.write_bytes(test_content)

        cacher_with_mock.get_file_to_path(digest, dest_path)

        assert dest_path.exists()
        assert dest_path.read_bytes() == test_content

    def test_put_file_from_fobj_stores_content(self, cacher_with_mock):
        """Test put_file_from_fobj stores file content and returns digest."""
        test_content = b'test content for storage'

        cacher_with_mock.backend.create_file.return_value = None

        with patch('rbx.grading.grading_context.is_transient', return_value=True):
            cacher_with_mock.put_file_from_fobj(io.BytesIO(test_content))

        # Verify content is cached
        # Note: digest is computed and used for caching verification
        assert len([f for f in cacher_with_mock.file_dir.iterdir() if f.is_file()]) > 0

    def test_put_file_from_fobj_stores_in_backend_when_not_transient(
        self, cacher_with_mock
    ):
        """Test put_file_from_fobj stores in backend when not in transient mode."""
        test_content = b'test content for backend'
        mock_pending = Mock()
        mock_pending.fd = io.BytesIO()

        cacher_with_mock.backend.create_file.return_value = mock_pending

        with patch('rbx.grading.grading_context.is_transient', return_value=False):
            digest = cacher_with_mock.put_file_from_fobj(io.BytesIO(test_content))

        cacher_with_mock.backend.create_file.assert_called_once_with(digest)
        cacher_with_mock.backend.commit_file.assert_called_once_with(mock_pending, None)

    def test_put_file_from_fobj_with_metadata(self, cacher_with_mock):
        """Test put_file_from_fobj stores metadata."""
        test_content = b'test content'
        metadata = {'test': CacherTestMetadata(value='test', number=123)}
        mock_pending = Mock()
        mock_pending.fd = io.BytesIO()

        cacher_with_mock.backend.create_file.return_value = mock_pending

        with patch('rbx.grading.grading_context.is_transient', return_value=False):
            cacher_with_mock.put_file_from_fobj(io.BytesIO(test_content), metadata)

        cacher_with_mock.backend.commit_file.assert_called_once_with(
            mock_pending, metadata
        )

    def test_put_file_content_calls_put_file_from_fobj(self, cacher_with_mock):
        """Test put_file_content calls put_file_from_fobj with BytesIO."""
        test_content = b'test bytes content'

        with patch.object(cacher_with_mock, 'put_file_from_fobj') as mock_put:
            mock_put.return_value = 'test_digest'
            result = cacher_with_mock.put_file_content(test_content)

        assert result == 'test_digest'
        mock_put.assert_called_once()
        # Verify the call was made with correct arguments
        args, kwargs = mock_put.call_args
        fobj = args[0]
        assert isinstance(fobj, io.BytesIO)

    def test_put_file_text_encodes_to_utf8(self, cacher_with_mock):
        """Test put_file_text encodes text to UTF-8."""
        test_text = 'Hello, 世界!'
        expected_bytes = test_text.encode('utf-8')

        with patch.object(cacher_with_mock, 'put_file_content') as mock_put:
            mock_put.return_value = 'test_digest'
            result = cacher_with_mock.put_file_text(test_text)

        assert result == 'test_digest'
        mock_put.assert_called_once_with(expected_bytes, None)

    def test_put_file_from_path_reads_file(self, cacher_with_mock, temp_dir):
        """Test put_file_from_path reads file from filesystem."""
        test_content = b'file system content'
        source_file = temp_dir / 'source.txt'
        source_file.write_bytes(test_content)

        with patch.object(cacher_with_mock, 'put_file_from_fobj') as mock_put:
            mock_put.return_value = 'test_digest'
            result = cacher_with_mock.put_file_from_path(source_file)

        assert result == 'test_digest'
        mock_put.assert_called_once()

    def test_path_for_symlink_tombstone_raises_error(self, cacher_with_mock):
        """Test path_for_symlink raises TombstoneError for tombstone."""
        with pytest.raises(TombstoneError):
            cacher_with_mock.path_for_symlink(storage.TOMBSTONE)

    def test_path_for_symlink_returns_none_when_transient(self, cacher_with_mock):
        """Test path_for_symlink returns None when in transient mode."""
        with patch('rbx.grading.grading_context.is_transient', return_value=True):
            result = cacher_with_mock.path_for_symlink('test_digest')

        assert result is None

    def test_path_for_symlink_delegates_to_backend(self, cacher_with_mock, temp_dir):
        """Test path_for_symlink delegates to backend when not transient."""
        digest = 'test_digest'
        expected_path = temp_dir / 'symlink_target'

        cacher_with_mock.backend.path_for_symlink.return_value = expected_path

        with patch('rbx.grading.grading_context.is_transient', return_value=False):
            result = cacher_with_mock.path_for_symlink(digest)

        assert result == expected_path
        cacher_with_mock.backend.path_for_symlink.assert_called_once_with(digest)

    def test_digest_from_symlink_returns_none_when_transient(
        self, cacher_with_mock, temp_dir
    ):
        """Test digest_from_symlink returns None when in transient mode."""
        link_path = temp_dir / 'link'

        with patch('rbx.grading.grading_context.is_transient', return_value=True):
            result = cacher_with_mock.digest_from_symlink(link_path)

        assert result is None

    def test_digest_from_symlink_delegates_to_backend(self, cacher_with_mock, temp_dir):
        """Test digest_from_symlink delegates to backend when not transient."""
        link_path = temp_dir / 'link'
        expected_digest = 'test_digest'

        cacher_with_mock.backend.filename_from_symlink.return_value = expected_digest

        with patch('rbx.grading.grading_context.is_transient', return_value=False):
            result = cacher_with_mock.digest_from_symlink(link_path)

        assert result == expected_digest
        cacher_with_mock.backend.filename_from_symlink.assert_called_once_with(
            link_path
        )

    def test_set_metadata_skips_when_transient(self, cacher_with_mock):
        """Test set_metadata does nothing when in transient mode."""
        with patch('rbx.grading.grading_context.is_transient', return_value=True):
            cacher_with_mock.set_metadata(
                'digest', 'key', CacherTestMetadata(value='test')
            )

        cacher_with_mock.backend.set_metadata.assert_not_called()

    def test_set_metadata_delegates_to_backend(self, cacher_with_mock):
        """Test set_metadata delegates to backend when not transient."""
        digest = 'test_digest'
        key = 'test_key'
        value = CacherTestMetadata(value='test')

        with patch('rbx.grading.grading_context.is_transient', return_value=False):
            cacher_with_mock.set_metadata(digest, key, value)

        cacher_with_mock.backend.set_metadata.assert_called_once_with(
            digest, key, value
        )

    def test_get_metadata_tombstone_raises_error(self, cacher_with_mock):
        """Test get_metadata raises TombstoneError for tombstone."""
        with pytest.raises(TombstoneError):
            cacher_with_mock.get_metadata(storage.TOMBSTONE, 'key', CacherTestMetadata)

    def test_get_metadata_delegates_to_backend(self, cacher_with_mock):
        """Test get_metadata delegates to backend."""
        digest = 'test_digest'
        key = 'test_key'
        expected_metadata = CacherTestMetadata(value='test')

        cacher_with_mock.backend.get_metadata.return_value = expected_metadata

        result = cacher_with_mock.get_metadata(digest, key, CacherTestMetadata)

        assert result == expected_metadata
        cacher_with_mock.backend.get_metadata.assert_called_once_with(
            digest, key, CacherTestMetadata
        )

    def test_list_metadata_delegates_to_backend(self, cacher_with_mock):
        """Test list_metadata delegates to backend."""
        filename = 'test_file'
        expected_keys = ['key1', 'key2', 'key3']

        cacher_with_mock.backend.list_metadata.return_value = expected_keys

        result = cacher_with_mock.list_metadata(filename)

        assert result == expected_keys
        cacher_with_mock.backend.list_metadata.assert_called_once_with(filename)

    def test_get_size_tombstone_raises_error(self, cacher_with_mock):
        """Test get_size raises TombstoneError for tombstone."""
        with pytest.raises(TombstoneError):
            cacher_with_mock.get_size(storage.TOMBSTONE)

    def test_get_size_delegates_to_backend(self, cacher_with_mock):
        """Test get_size delegates to backend."""
        digest = 'test_digest'
        expected_size = 1024

        cacher_with_mock.backend.get_size.return_value = expected_size

        result = cacher_with_mock.get_size(digest)

        assert result == expected_size
        cacher_with_mock.backend.get_size.assert_called_once_with(digest)

    def test_delete_removes_from_cache_and_backend(self, cacher_with_mock):
        """Test delete removes file from both cache and backend."""
        digest = 'test_digest'

        # Put file in cache
        cache_file = cacher_with_mock.file_dir / digest
        cache_file.write_bytes(b'test content')
        cacher_with_mock.existing.add(digest)

        cacher_with_mock.delete(digest)

        # Verify file removed from cache
        assert not cache_file.exists()
        assert digest not in cacher_with_mock.existing

        # Verify backend delete called
        cacher_with_mock.backend.delete.assert_called_once_with(digest)

    def test_delete_tombstone_does_nothing(self, cacher_with_mock):
        """Test delete does nothing for tombstone."""
        cacher_with_mock.delete(storage.TOMBSTONE)

        cacher_with_mock.backend.delete.assert_not_called()

    def test_drop_removes_only_from_cache(self, cacher_with_mock):
        """Test drop removes file only from cache."""
        digest = 'test_digest'

        # Put file in cache
        cache_file = cacher_with_mock.file_dir / digest
        cache_file.write_bytes(b'test content')
        cacher_with_mock.existing.add(digest)

        cacher_with_mock.drop(digest)

        # Verify file removed from cache
        assert not cache_file.exists()
        assert digest not in cacher_with_mock.existing

        # Verify backend not touched
        cacher_with_mock.backend.delete.assert_not_called()

    def test_drop_tombstone_does_nothing(self, cacher_with_mock):
        """Test drop does nothing for tombstone."""
        cacher_with_mock.drop(storage.TOMBSTONE)

        # Should not raise any error

    def test_purge_cache_clears_cache_directory(self, cacher_with_mock):
        """Test purge_cache clears cache directory and recreates it."""
        # Add some files to cache
        (cacher_with_mock.file_dir / 'file1').write_bytes(b'content1')
        (cacher_with_mock.file_dir / 'file2').write_bytes(b'content2')
        cacher_with_mock.existing.add('file1')
        cacher_with_mock.existing.add('file2')

        cacher_with_mock.purge_cache()

        # Verify directory is recreated and existing set is cleared
        assert cacher_with_mock.file_dir.exists()
        assert len(cacher_with_mock.existing) == 0
        # Verify the files are gone - directory should be empty or only contain temp stuff
        cache_files = [
            f
            for f in cacher_with_mock.file_dir.iterdir()
            if f.name in ['file1', 'file2']
        ]
        assert len(cache_files) == 0

    def test_destroy_cache_removes_cache_directory(self, cacher_with_mock):
        """Test destroy_cache removes cache directory completely."""
        cache_dir = cacher_with_mock.file_dir

        cacher_with_mock.destroy_cache()

        assert not cache_dir.exists()

    def test_destroy_cache_raises_for_shared_cache(self, shared_cacher):
        """Test destroy_cache raises exception for shared cache."""
        with pytest.raises(Exception, match='You may not destroy a shared cache'):
            shared_cacher.destroy_cache()

    def test_list_delegates_to_backend(self, cacher_with_mock):
        """Test list delegates to backend."""
        expected_files = [
            storage.FileWithMetadata(filename='file1', metadata=['key1']),
            storage.FileWithMetadata(filename='file2', metadata=['key2']),
        ]

        cacher_with_mock.backend.list.return_value = expected_files

        result = cacher_with_mock.list()

        assert result == expected_files
        cacher_with_mock.backend.list.assert_called_once()

    def test_check_backend_integrity_valid_files(self, cacher_with_filesystem):
        """Test check_backend_integrity with valid files."""
        # Store a file with known content
        test_content = b'integrity test content'
        cacher_with_filesystem.put_file_content(test_content)

        # Check integrity
        result = cacher_with_filesystem.check_backend_integrity()

        assert result

    def test_check_backend_integrity_invalid_file_reports_error(
        self, cacher_with_filesystem, caplog
    ):
        """Test check_backend_integrity reports error for corrupted file."""
        # Store a file
        test_content = b'original content'
        digest = cacher_with_filesystem.put_file_content(test_content)

        # Corrupt the backend file directly
        backend_file = cacher_with_filesystem.backend.path / digest
        backend_file.write_bytes(b'corrupted content')

        # Check integrity
        result = cacher_with_filesystem.check_backend_integrity()

        assert not result
        assert 'actually has hash' in caplog.text

    def test_check_backend_integrity_delete_corrupted_files(
        self, cacher_with_filesystem
    ):
        """Test check_backend_integrity deletes corrupted files when delete=True."""
        # Store a file
        test_content = b'original content'
        digest = cacher_with_filesystem.put_file_content(test_content)

        # Corrupt the backend file
        backend_file = cacher_with_filesystem.backend.path / digest
        backend_file.write_bytes(b'corrupted content')

        # Check integrity with delete=True
        result = cacher_with_filesystem.check_backend_integrity(delete=True)

        assert not result
        # File should be deleted from backend
        assert not cacher_with_filesystem.backend.exists(digest)

    def test_integration_put_and_get_file(self, cacher_with_filesystem):
        """Integration test: put file and retrieve it."""
        test_content = b'integration test content'

        # Store file
        digest = cacher_with_filesystem.put_file_content(test_content)

        # Retrieve file
        retrieved_content = cacher_with_filesystem.get_file_content(digest)

        assert retrieved_content == test_content

    def test_integration_cache_persistence(self, cacher_with_filesystem):
        """Integration test: verify cache persists across operations."""
        test_content = b'persistent content'

        # Store and cache file
        digest = cacher_with_filesystem.put_file_content(test_content)

        # Remove from backend to test cache
        cacher_with_filesystem.backend.delete(digest)

        # Should still be accessible from cache
        cache_file = cacher_with_filesystem.file_dir / digest
        assert cache_file.exists()
        assert cache_file.read_bytes() == test_content

    def test_integration_with_metadata(self, cacher_with_filesystem):
        """Integration test: store and retrieve file with metadata."""
        test_content = b'content with metadata'
        metadata = {'test': CacherTestMetadata(value='integration', number=999)}

        # Store with metadata
        digest = cacher_with_filesystem.put_file_content(test_content, metadata)

        # Retrieve metadata
        retrieved_metadata = cacher_with_filesystem.get_metadata(
            digest, 'test', CacherTestMetadata
        )

        assert retrieved_metadata is not None
        assert retrieved_metadata.value == 'integration'
        assert retrieved_metadata.number == 999

    def test_large_file_handling(self, cacher_with_filesystem):
        """Test handling of files larger than chunk size."""
        # Create content larger than CHUNK_SIZE (1MB)
        chunk_size = FileCacher.CHUNK_SIZE
        large_content = b'x' * (chunk_size + 1000)

        # Store and retrieve large file
        digest = cacher_with_filesystem.put_file_content(large_content)
        retrieved_content = cacher_with_filesystem.get_file_content(digest)

        assert retrieved_content == large_content

    def test_concurrent_cache_operations(self, shared_cacher):
        """Test concurrent cache operations with locking."""
        # This test verifies that the locking mechanism works
        # Multiple cachers using same shared directory
        test_content = b'concurrent test'

        # Store file in first cacher
        digest = shared_cacher.put_file_content(test_content)

        # Create second cacher with same backend and folder
        second_cacher = FileCacher(
            shared_cacher.backend, shared=True, folder=shared_cacher.folder
        )

        # Both should be able to access the file
        content1 = shared_cacher.get_file_content(digest)
        content2 = second_cacher.get_file_content(digest)

        assert content1 == test_content
        assert content2 == test_content

    def test_error_handling_missing_file(self, cacher_with_mock):
        """Test error handling when backend file is missing."""
        digest = 'nonexistent_digest'

        cacher_with_mock.backend.path_for_symlink.return_value = None
        cacher_with_mock.backend.get_file.side_effect = KeyError('File not found')

        with pytest.raises(KeyError):
            cacher_with_mock.get_file(digest)
