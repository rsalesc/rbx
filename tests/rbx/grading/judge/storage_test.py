import io
import pathlib
import tempfile
from typing import Dict, cast
from unittest.mock import Mock, patch

import pytest
from pydantic import BaseModel

from rbx.grading.judge.storage import (
    CompressionMetadata,
    FilesystemStorage,
    NullStorage,
    PendingFile,
    copyfileobj,
)


class SampleMetadata(BaseModel):
    """Sample metadata model for testing purposes."""

    value: str
    number: int = 42


class ExtraMetadata(BaseModel):
    """Extra metadata model for testing purposes."""

    flag: bool = True


class TestCopyFileObj:
    """Test the copyfileobj utility function."""

    def test_copy_full_content(self):
        """Test copying full content from source to destination."""
        source_data = b'Hello, world! This is test data.'
        source = io.BytesIO(source_data)
        destination = io.BytesIO()

        copyfileobj(source, destination)

        assert destination.getvalue() == source_data

    def test_copy_with_buffer_size(self):
        """Test copying with custom buffer size."""
        source_data = b'A' * 1000  # 1000 bytes
        source = io.BytesIO(source_data)
        destination = io.BytesIO()

        copyfileobj(source, destination, buffer_size=100)

        assert destination.getvalue() == source_data

    def test_copy_with_maxlen_smaller_than_source(self):
        """Test copying with maxlen smaller than source data."""
        source_data = b'Hello, world!'
        source = io.BytesIO(source_data)
        destination = io.BytesIO()

        copyfileobj(source, destination, maxlen=5)

        assert destination.getvalue() == b'Hello'

    def test_copy_with_maxlen_larger_than_source(self):
        """Test copying with maxlen larger than source data."""
        source_data = b'Hello'
        source = io.BytesIO(source_data)
        destination = io.BytesIO()

        copyfileobj(source, destination, maxlen=100)

        assert destination.getvalue() == source_data

    def test_copy_empty_source(self):
        """Test copying from empty source."""
        source = io.BytesIO(b'')
        destination = io.BytesIO()

        copyfileobj(source, destination)

        assert destination.getvalue() == b''

    def test_copy_with_zero_maxlen(self):
        """Test copying with zero maxlen."""
        source_data = b'Hello, world!'
        source = io.BytesIO(source_data)
        destination = io.BytesIO()

        copyfileobj(source, destination, maxlen=0)

        assert destination.getvalue() == b''

    def test_copy_text_mode(self):
        """Test copying in text mode."""
        source_data = 'Hello, world! This is text data.'
        source = io.StringIO(source_data)
        destination = io.StringIO()

        copyfileobj(source, destination)

        assert destination.getvalue() == source_data


class TestNullStorage:
    """Test the NullStorage implementation."""

    def setup_method(self):
        """Set up test fixtures."""
        self.storage = NullStorage()

    def test_get_file_raises_key_error(self):
        """Test that get_file always raises KeyError."""
        with pytest.raises(KeyError, match='File not found'):
            self.storage.get_file('any_filename')

    def test_create_file_returns_none(self):
        """Test that create_file always returns None."""
        result = self.storage.create_file('any_filename')
        assert result is None

    def test_commit_file_returns_false(self):
        """Test that commit_file always returns False."""
        mock_pending_file = Mock(spec=PendingFile)
        result = self.storage.commit_file(mock_pending_file)
        assert result is False

    def test_commit_file_with_metadata_returns_false(self):
        """Test that commit_file with metadata always returns False."""
        mock_pending_file = Mock(spec=PendingFile)
        metadata = cast(Dict[str, BaseModel], {'test': SampleMetadata(value='test')})
        result = self.storage.commit_file(mock_pending_file, metadata)
        assert result is False

    def test_set_metadata_does_nothing(self):
        """Test that set_metadata does nothing (no exception)."""
        test_metadata = SampleMetadata(value='test')
        self.storage.set_metadata('filename', 'key', test_metadata)
        # No assertion needed - just ensure no exception is raised

    def test_set_metadata_with_none_does_nothing(self):
        """Test that set_metadata with None value does nothing."""
        self.storage.set_metadata('filename', 'key', None)
        # No assertion needed - just ensure no exception is raised

    def test_get_metadata_raises_key_error(self):
        """Test that get_metadata always raises KeyError."""
        with pytest.raises(KeyError, match='File not found'):
            self.storage.get_metadata('filename', 'key', SampleMetadata)

    def test_list_metadata_returns_empty_list(self):
        """Test that list_metadata always returns empty list."""
        result = self.storage.list_metadata('any_filename')
        assert result == []

    def test_exists_returns_false(self):
        """Test that exists always returns False."""
        assert self.storage.exists('any_filename') is False

    def test_get_size_raises_key_error(self):
        """Test that get_size always raises KeyError."""
        with pytest.raises(KeyError, match='File not found'):
            self.storage.get_size('any_filename')

    def test_delete_does_nothing(self):
        """Test that delete does nothing (no exception)."""
        self.storage.delete('any_filename')
        # No assertion needed - just ensure no exception is raised

    def test_list_returns_empty_list(self):
        """Test that list always returns empty list."""
        result = self.storage.list()
        assert result == []

    def test_path_for_symlink_returns_none(self):
        """Test that path_for_symlink always returns None."""
        result = self.storage.path_for_symlink('any_filename')
        assert result is None

    def test_filename_from_symlink_returns_none(self):
        """Test that filename_from_symlink always returns None."""
        mock_path = Mock(spec=pathlib.Path)
        result = self.storage.filename_from_symlink(mock_path)
        assert result is None


class TestFilesystemStorage:
    """Test the FilesystemStorage implementation."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for testing."""
        with tempfile.TemporaryDirectory() as temp_dir:
            yield pathlib.Path(temp_dir)

    @pytest.fixture
    def storage(self, temp_dir):
        """Create a FilesystemStorage instance for testing."""
        return FilesystemStorage(temp_dir)

    @pytest.fixture
    def compressed_storage(self, temp_dir):
        """Create a compressed FilesystemStorage instance for testing."""
        return FilesystemStorage(temp_dir, compress=True)

    def test_init_creates_metadata_directory(self, temp_dir):
        """Test that __init__ creates the metadata directory."""
        FilesystemStorage(temp_dir)
        metadata_dir = temp_dir / '.metadata'
        assert metadata_dir.exists()
        assert metadata_dir.is_dir()

    def test_get_file_nonexistent_raises_key_error(self, storage):
        """Test that get_file raises KeyError for nonexistent files."""
        with pytest.raises(KeyError, match='File not found'):
            storage.get_file('nonexistent.txt')

    def test_create_and_commit_file_basic(self, storage):
        """Test basic file creation and commit workflow."""
        filename = 'test.txt'
        test_data = b'Hello, world!'

        # Create file
        pending_file = storage.create_file(filename)
        assert pending_file is not None
        assert pending_file.filename == filename
        assert pending_file.fd is not None

        # Write data
        pending_file.fd.write(test_data)

        # Commit file
        result = storage.commit_file(pending_file)
        assert result is True

        # Verify file exists
        assert storage.exists(filename)

        # Read file back
        with storage.get_file(filename) as f:
            content = f.read()
        assert content == test_data

    def test_create_file_already_exists_returns_none(self, storage):
        """Test that create_file returns None if file already exists."""
        filename = 'test.txt'
        test_data = b'Hello, world!'

        # Create and commit first file
        pending_file = storage.create_file(filename)
        pending_file.fd.write(test_data)
        storage.commit_file(pending_file)

        # Try to create again
        pending_file2 = storage.create_file(filename)
        assert pending_file2 is None

    def test_commit_file_already_exists_returns_false(self, storage, temp_dir):
        """Test that commit_file returns False if file already exists."""
        filename = 'test.txt'

        # Create file directly
        file_path = temp_dir / filename
        file_path.write_bytes(b'existing content')

        # Create pending file
        pending_file = storage.create_file('other.txt')
        pending_file.fd.write(b'new content')
        # Manually set filename to conflict
        pending_file.filename = filename

        result = storage.commit_file(pending_file)
        assert result is False

    def test_metadata_operations(self, storage):
        """Test metadata setting, getting, and listing."""
        filename = 'test.txt'
        test_data = b'Hello, world!'

        # Create and commit file
        pending_file = storage.create_file(filename)
        pending_file.fd.write(test_data)
        storage.commit_file(pending_file)

        # Set metadata
        test_metadata = SampleMetadata(value='test_value', number=123)
        storage.set_metadata(filename, 'test_key', test_metadata)

        # Get metadata
        retrieved_metadata = storage.get_metadata(filename, 'test_key', SampleMetadata)
        assert retrieved_metadata.value == 'test_value'
        assert retrieved_metadata.number == 123

        # List metadata
        metadata_keys = storage.list_metadata(filename)
        assert 'test_key' in metadata_keys

    def test_metadata_operations_multiple_keys(self, storage):
        """Test metadata operations with multiple keys."""
        filename = 'test.txt'
        test_data = b'Hello, world!'

        # Create and commit file
        pending_file = storage.create_file(filename)
        pending_file.fd.write(test_data)
        storage.commit_file(pending_file)

        # Set multiple metadata
        test_metadata1 = SampleMetadata(value='value1', number=1)
        test_metadata2 = ExtraMetadata(flag=False)

        storage.set_metadata(filename, 'key1', test_metadata1)
        storage.set_metadata(filename, 'key2', test_metadata2)

        # List metadata
        metadata_keys = storage.list_metadata(filename)
        assert set(metadata_keys) == {'key1', 'key2'}

        # Get both metadata
        retrieved1 = storage.get_metadata(filename, 'key1', SampleMetadata)
        retrieved2 = storage.get_metadata(filename, 'key2', ExtraMetadata)

        assert retrieved1.value == 'value1'
        assert retrieved2.flag is False

    def test_set_metadata_nonexistent_file_raises_key_error(self, storage):
        """Test that set_metadata raises KeyError for nonexistent files."""
        test_metadata = SampleMetadata(value='test')
        with pytest.raises(KeyError, match='File not found'):
            storage.set_metadata('nonexistent.txt', 'key', test_metadata)

    def test_get_metadata_nonexistent_key_returns_none(self, storage):
        """Test that get_metadata returns None for nonexistent keys."""
        filename = 'test.txt'
        test_data = b'Hello, world!'

        # Create and commit file
        pending_file = storage.create_file(filename)
        pending_file.fd.write(test_data)
        storage.commit_file(pending_file)

        # Try to get nonexistent metadata
        result = storage.get_metadata(filename, 'nonexistent_key', SampleMetadata)
        assert result is None

    def test_set_metadata_none_removes_metadata(self, storage):
        """Test that setting metadata to None removes it."""
        filename = 'test.txt'
        test_data = b'Hello, world!'

        # Create and commit file
        pending_file = storage.create_file(filename)
        pending_file.fd.write(test_data)
        storage.commit_file(pending_file)

        # Set metadata
        test_metadata = SampleMetadata(value='test')
        storage.set_metadata(filename, 'test_key', test_metadata)

        # Verify it exists
        assert storage.get_metadata(filename, 'test_key', SampleMetadata) is not None
        assert 'test_key' in storage.list_metadata(filename)

        # Remove metadata
        storage.set_metadata(filename, 'test_key', None)

        # Verify it's gone
        assert storage.get_metadata(filename, 'test_key', SampleMetadata) is None
        assert 'test_key' not in storage.list_metadata(filename)

    def test_get_size(self, storage):
        """Test get_size method."""
        filename = 'test.txt'
        test_data = b'Hello, world! This is a test.'

        # Create and commit file
        pending_file = storage.create_file(filename)
        pending_file.fd.write(test_data)
        storage.commit_file(pending_file)

        size = storage.get_size(filename)
        assert size == len(test_data)

    def test_get_size_nonexistent_raises_key_error(self, storage):
        """Test that get_size raises KeyError for nonexistent files."""
        with pytest.raises(KeyError, match='File not found'):
            storage.get_size('nonexistent.txt')

    def test_delete_file(self, storage):
        """Test file deletion."""
        filename = 'test.txt'
        test_data = b'Hello, world!'

        # Create and commit file with metadata
        pending_file = storage.create_file(filename)
        pending_file.fd.write(test_data)
        storage.commit_file(pending_file)

        test_metadata = SampleMetadata(value='test')
        storage.set_metadata(filename, 'test_key', test_metadata)

        # Verify file and metadata exist
        assert storage.exists(filename)
        assert storage.get_metadata(filename, 'test_key', SampleMetadata) is not None

        # Delete file
        storage.delete(filename)

        # Verify file and metadata are gone
        assert not storage.exists(filename)
        assert storage.get_metadata(filename, 'test_key', SampleMetadata) is None

    def test_delete_nonexistent_file_no_error(self, storage):
        """Test that deleting nonexistent file doesn't raise error."""
        storage.delete('nonexistent.txt')  # Should not raise

    def test_list_files(self, storage):
        """Test listing files in storage."""
        # Initially empty
        files = storage.list()
        assert files == []

        # Create some files
        for i in range(3):
            filename = f'test{i}.txt'
            pending_file = storage.create_file(filename)
            pending_file.fd.write(f'content{i}'.encode())
            storage.commit_file(pending_file)

            # Add metadata to some files
            if i < 2:
                test_metadata = SampleMetadata(value=f'value{i}')
                storage.set_metadata(filename, f'key{i}', test_metadata)

        # List files
        files = storage.list()
        assert len(files) == 3

        filenames = [f.filename for f in files]
        assert 'test0.txt' in filenames
        assert 'test1.txt' in filenames
        assert 'test2.txt' in filenames

        # Check metadata
        for file_info in files:
            if file_info.filename in ['test0.txt', 'test1.txt']:
                assert len(file_info.metadata) > 0
            else:
                assert len(file_info.metadata) == 0

    @patch('rbx.grading.grading_context.should_compress')
    @patch('rbx.grading.grading_context.get_compression_level')
    def test_compression_with_context(
        self, mock_get_level, mock_should_compress, storage
    ):
        """Test compression when grading context indicates compression should be used."""
        mock_should_compress.return_value = True
        mock_get_level.return_value = 3

        filename = 'test.txt'
        test_data = b'Hello, world! This should be compressed.'

        # Create file (should be compressed due to context)
        pending_file = storage.create_file(filename)
        assert pending_file is not None
        assert pending_file.metadata['compression'] is not None
        assert pending_file.metadata['compression'].compression_level == 3

        # Write and commit
        pending_file.fd.write(test_data)
        storage.commit_file(pending_file)

        # Verify compression metadata was stored
        compression_meta = storage.get_metadata(
            filename, 'compression', CompressionMetadata
        )
        assert compression_meta is not None
        assert compression_meta.compression_level == 3

    def test_compression_with_flag(self, compressed_storage):
        """Test compression when storage is created with compress=True."""
        filename = 'test.txt'
        test_data = b'Hello, world! This should be compressed.'

        # Create file (should be compressed due to flag)
        with patch('rbx.grading.grading_context.get_compression_level', return_value=5):
            pending_file = compressed_storage.create_file(filename)

        assert pending_file is not None
        assert pending_file.metadata['compression'] is not None
        assert pending_file.metadata['compression'].compression_level == 5

        # Write and commit
        pending_file.fd.write(test_data)
        compressed_storage.commit_file(pending_file)

        # Verify compression metadata was stored
        compression_meta = compressed_storage.get_metadata(
            filename, 'compression', CompressionMetadata
        )
        assert compression_meta is not None
        assert compression_meta.compression_level == 5

    @patch('rbx.grading.grading_context.should_compress')
    @patch('rbx.grading.grading_context.get_compression_level')
    def test_compression_round_trip_data_integrity(
        self, mock_get_level, mock_should_compress, storage
    ):
        """Test that compressed files can be read back and match original data."""
        mock_should_compress.return_value = True
        mock_get_level.return_value = 7

        filename = 'test_compression_roundtrip.txt'
        # Use varied test data to ensure compression is actually working
        test_data = b''.join(
            [
                b'This is a test file with repeated content. ' * 50,
                b'Some different content here. ' * 30,
                b'And yet more varied text to compress effectively. ' * 25,
                b'Final section with unique data: ',
                b''.join(
                    [
                        f'Line {i}: Lorem ipsum dolor sit amet. '.encode()
                        for i in range(100)
                    ]
                ),
            ]
        )

        # Create, write, and commit compressed file
        pending_file = storage.create_file(filename)
        assert pending_file is not None
        assert pending_file.metadata['compression'] is not None
        assert pending_file.metadata['compression'].compression_level == 7

        pending_file.fd.write(test_data)
        storage.commit_file(pending_file)

        # Read the file back and verify it matches exactly
        with storage.get_file(filename) as file_handle:
            read_data = file_handle.read()

        assert read_data == test_data
        assert len(read_data) == len(test_data)

        # Verify it's actually compressed by checking metadata
        compression_meta = storage.get_metadata(
            filename, 'compression', CompressionMetadata
        )
        assert compression_meta is not None
        assert compression_meta.compression_level == 7

    def test_compression_round_trip_with_flag(self, compressed_storage):
        """Test round-trip data integrity when compression is enabled via flag."""
        filename = 'test_flag_roundtrip.bin'
        # Test with binary data including null bytes and various patterns
        test_data = bytes(range(256)) * 100  # 25.6KB of varied binary data

        # Create file with compression flag
        with patch('rbx.grading.grading_context.get_compression_level', return_value=3):
            pending_file = compressed_storage.create_file(filename)

        assert pending_file is not None
        assert pending_file.metadata['compression'] is not None

        # Write and commit
        pending_file.fd.write(test_data)
        compressed_storage.commit_file(pending_file)

        # Read back and verify exact match
        with compressed_storage.get_file(filename) as file_handle:
            read_data = file_handle.read()

        assert read_data == test_data
        assert len(read_data) == len(test_data)

        # Verify the file exists and has correct size
        assert compressed_storage.exists(filename)
        # Note: get_size() returns compressed size, not original size
        assert compressed_storage.get_size(filename) > 0

    def test_commit_file_with_additional_metadata(self, storage):
        """Test commit_file with additional metadata parameter."""
        filename = 'test.txt'
        test_data = b'Hello, world!'

        # Create file
        pending_file = storage.create_file(filename)
        pending_file.fd.write(test_data)

        # Commit with additional metadata
        additional_metadata = cast(
            Dict[str, BaseModel],
            {
                'custom': SampleMetadata(value='custom_value'),
                'another': ExtraMetadata(flag=True),
            },
        )
        storage.commit_file(pending_file, additional_metadata)

        # Verify all metadata was stored
        custom_meta = storage.get_metadata(filename, 'custom', SampleMetadata)
        another_meta = storage.get_metadata(filename, 'another', ExtraMetadata)

        assert custom_meta.value == 'custom_value'
        assert another_meta.flag is True

    def test_commit_file_creates_parent_directories(self, storage, temp_dir):
        """Test that commit_file creates parent directories as needed."""
        filename = 'subdir/nested/test.txt'
        test_data = b'Hello, world!'

        # Create file
        pending_file = storage.create_file(filename)
        pending_file.fd.write(test_data)

        # Commit file
        storage.commit_file(pending_file)

        # Verify file exists with proper directory structure
        file_path = temp_dir / filename
        assert file_path.exists()
        assert file_path.read_bytes() == test_data

    def test_path_for_symlink_uncompressed(self, storage):
        """Test path_for_symlink for uncompressed files."""
        filename = 'test.txt'
        test_data = b'Hello, world!'

        # Create and commit uncompressed file
        pending_file = storage.create_file(filename)
        pending_file.fd.write(test_data)
        storage.commit_file(pending_file)

        # Get symlink path
        symlink_path = storage.path_for_symlink(filename)
        assert symlink_path is not None
        assert symlink_path.exists()
        assert symlink_path.read_bytes() == test_data

    def test_path_for_symlink_compressed_returns_none(self, storage):
        """Test that path_for_symlink returns None for compressed files."""
        filename = 'test.txt'
        test_data = b'Hello, world!'

        # Create and commit file
        pending_file = storage.create_file(filename)
        pending_file.fd.write(test_data)
        storage.commit_file(pending_file)

        # Manually set compression metadata
        compression_meta = CompressionMetadata(compression_level=5)
        storage.set_metadata(filename, 'compression', compression_meta)

        # Should return None for compressed files
        symlink_path = storage.path_for_symlink(filename)
        assert symlink_path is None

    def test_path_for_symlink_nonexistent_raises_key_error(self, storage):
        """Test that path_for_symlink raises KeyError for nonexistent files."""
        with pytest.raises(KeyError, match='File not found'):
            storage.path_for_symlink('nonexistent.txt')

    def test_filename_from_symlink_valid(self, storage, temp_dir):
        """Test filename_from_symlink with valid symlink."""
        filename = 'test.txt'
        test_data = b'Hello, world!'

        # Create and commit file
        pending_file = storage.create_file(filename)
        pending_file.fd.write(test_data)
        storage.commit_file(pending_file)

        # Create a symlink
        target_path = temp_dir / filename
        symlink_path = temp_dir / 'symlink.txt'
        symlink_path.symlink_to(target_path)

        # Test filename extraction
        result_filename = storage.filename_from_symlink(symlink_path)
        assert result_filename == filename

    def test_filename_from_symlink_not_symlink_returns_none(self, storage, temp_dir):
        """Test that filename_from_symlink returns None for non-symlinks."""
        # Create regular file
        regular_file = temp_dir / 'regular.txt'
        regular_file.write_text('content')

        result = storage.filename_from_symlink(regular_file)
        assert result is None

    def test_filename_from_symlink_broken_link_returns_none(self, storage, temp_dir):
        """Test that filename_from_symlink returns None for broken symlinks."""
        # Create symlink to nonexistent file
        symlink_path = temp_dir / 'broken_symlink.txt'
        symlink_path.symlink_to(temp_dir / 'nonexistent.txt')

        result = storage.filename_from_symlink(symlink_path)
        assert result is None

    def test_large_file_operations(self, storage):
        """Test operations with larger files."""
        filename = 'large_test.txt'
        # Create 1MB of test data
        test_data = b'A' * (1024 * 1024)

        # Create and commit file
        pending_file = storage.create_file(filename)
        pending_file.fd.write(test_data)
        storage.commit_file(pending_file)

        # Verify size
        assert storage.get_size(filename) == len(test_data)

        # Read back and verify
        with storage.get_file(filename) as f:
            content = f.read()
        assert content == test_data

    def test_empty_file_operations(self, storage):
        """Test operations with empty files."""
        filename = 'empty.txt'

        # Create and commit empty file
        pending_file = storage.create_file(filename)
        storage.commit_file(pending_file)

        # Verify size
        assert storage.get_size(filename) == 0

        # Verify exists
        assert storage.exists(filename)

        # Read back
        with storage.get_file(filename) as f:
            content = f.read()
        assert content == b''

    def test_unicode_filename_handling(self, storage):
        """Test handling of unicode filenames."""
        filename = 'test_ñáéíóú_中文_🚀.txt'
        test_data = b'Unicode filename test'

        # Create and commit file
        pending_file = storage.create_file(filename)
        pending_file.fd.write(test_data)
        storage.commit_file(pending_file)

        # Verify operations work with unicode filename
        assert storage.exists(filename)
        assert storage.get_size(filename) == len(test_data)

        with storage.get_file(filename) as f:
            content = f.read()
        assert content == test_data

    def test_concurrent_file_creation_race_condition(self, storage, temp_dir):
        """Test handling of race condition in file creation."""
        filename = 'race_test.txt'

        # Create file directly on filesystem to simulate race condition
        file_path = temp_dir / filename
        file_path.write_bytes(b'existing content')

        # Now try to create through storage
        pending_file = storage.create_file(filename)
        assert pending_file is None  # Should return None since file exists

    def test_metadata_directory_structure(self, storage, temp_dir):
        """Test that metadata files are stored in correct directory structure."""
        filename = 'subdir/test.txt'
        test_data = b'Hello, world!'

        # Create and commit file
        pending_file = storage.create_file(filename)
        pending_file.fd.write(test_data)
        storage.commit_file(pending_file)

        # Set metadata
        test_metadata = SampleMetadata(value='test')
        storage.set_metadata(filename, 'test_key', test_metadata)

        # Verify metadata file exists in correct location
        metadata_file = temp_dir / '.metadata' / f'{filename}__test_key.json'
        assert metadata_file.exists()

        # Verify metadata content
        import json

        metadata_content = json.loads(metadata_file.read_text())
        assert metadata_content['value'] == 'test'
        assert metadata_content['number'] == 42

    def test_filename_from_symlink_chain_resolution(self, storage, temp_dir):
        """Test filename_from_symlink with a chain of symlinks."""
        filename = 'target.txt'
        test_data = b'Target file content'

        # Create and commit target file in storage
        pending_file = storage.create_file(filename)
        pending_file.fd.write(test_data)
        storage.commit_file(pending_file)

        # Create a chain of symlinks: symlink1 -> symlink2 -> target
        target_path = temp_dir / filename
        symlink2_path = temp_dir / 'symlink2.txt'
        symlink1_path = temp_dir / 'symlink1.txt'

        symlink2_path.symlink_to(target_path)
        symlink1_path.symlink_to(symlink2_path)

        # Test that the chain is resolved correctly
        result_filename = storage.filename_from_symlink(symlink1_path)
        assert result_filename == filename

    def test_filename_from_symlink_outside_storage_returns_none(
        self, storage, temp_dir
    ):
        """Test that filename_from_symlink returns None when target is outside storage path."""
        # Create a file outside the storage directory
        external_dir = temp_dir.parent / 'external'
        external_dir.mkdir(exist_ok=True)
        external_file = external_dir / 'external.txt'
        external_file.write_text('external content')

        # Create symlink pointing to external file
        symlink_path = temp_dir / 'external_symlink.txt'
        symlink_path.symlink_to(external_file)

        result = storage.filename_from_symlink(symlink_path)
        assert result is None

    def test_filename_from_symlink_points_to_directory_returns_none(
        self, storage, temp_dir
    ):
        """Test that filename_from_symlink returns None when symlink points to directory."""
        # Create a directory in storage
        target_dir = temp_dir / 'target_directory'
        target_dir.mkdir()

        # Create symlink pointing to directory
        symlink_path = temp_dir / 'dir_symlink'
        symlink_path.symlink_to(target_dir)

        result = storage.filename_from_symlink(symlink_path)
        assert result is None

    def test_filename_from_symlink_broken_chain_returns_none(self, storage, temp_dir):
        """Test that filename_from_symlink returns None when symlink chain has broken link."""
        # Create symlink chain with a broken link in the middle
        broken_target = temp_dir / 'nonexistent.txt'
        symlink2_path = temp_dir / 'symlink2.txt'
        symlink1_path = temp_dir / 'symlink1.txt'

        symlink2_path.symlink_to(broken_target)  # Points to nonexistent file
        symlink1_path.symlink_to(symlink2_path)

        result = storage.filename_from_symlink(symlink1_path)
        assert result is None

    def test_filename_from_symlink_circular_reference_handling(self, storage, temp_dir):
        """Test filename_from_symlink behavior with circular symlink references."""
        symlink1_path = temp_dir / 'symlink1.txt'
        symlink2_path = temp_dir / 'symlink2.txt'

        # Create circular symlinks
        symlink1_path.symlink_to(symlink2_path)
        symlink2_path.symlink_to(symlink1_path)

        # The implementation should detect circular references and return None
        result = storage.filename_from_symlink(symlink1_path)
        assert result is None

    def test_filename_from_symlink_subdirectory_file(self, storage, temp_dir):
        """Test filename_from_symlink with files in subdirectories."""
        filename = 'subdir/nested.txt'
        test_data = b'Nested file content'

        # Create subdirectory and file
        subdir = temp_dir / 'subdir'
        subdir.mkdir()

        pending_file = storage.create_file(filename)
        pending_file.fd.write(test_data)
        storage.commit_file(pending_file)

        # Create symlink to nested file
        target_path = temp_dir / filename
        symlink_path = temp_dir / 'nested_symlink.txt'
        symlink_path.symlink_to(target_path)

        result_filename = storage.filename_from_symlink(symlink_path)
        assert result_filename == filename

    def test_filename_from_symlink_relative_vs_absolute_paths(self, storage, temp_dir):
        """Test filename_from_symlink with both relative and absolute symlink targets."""
        filename = 'relative_test.txt'
        test_data = b'Relative path test'

        # Create and commit file
        pending_file = storage.create_file(filename)
        pending_file.fd.write(test_data)
        storage.commit_file(pending_file)

        target_path = temp_dir / filename

        # Test with relative symlink
        rel_symlink_path = temp_dir / 'rel_symlink.txt'
        rel_symlink_path.symlink_to(filename)  # Relative path
        result = storage.filename_from_symlink(rel_symlink_path)
        assert result == filename

        # Test with absolute symlink
        abs_symlink_path = temp_dir / 'abs_symlink.txt'
        abs_symlink_path.symlink_to(target_path.absolute())  # Absolute path
        result = storage.filename_from_symlink(abs_symlink_path)
        assert result == filename

    def test_filename_from_symlink_special_characters_in_path(self, storage, temp_dir):
        """Test filename_from_symlink with special characters in file paths."""
        filename = 'special-chars_file!@#$%^&()_test.txt'
        test_data = b'Special characters test'

        # Create and commit file with special characters
        pending_file = storage.create_file(filename)
        pending_file.fd.write(test_data)
        storage.commit_file(pending_file)

        # Create symlink
        target_path = temp_dir / filename
        symlink_path = temp_dir / 'special_symlink.txt'
        symlink_path.symlink_to(target_path)

        result_filename = storage.filename_from_symlink(symlink_path)
        assert result_filename == filename

    def test_filename_from_symlink_with_spaces_in_path(self, storage, temp_dir):
        """Test filename_from_symlink with spaces in file paths."""
        filename = 'file with spaces.txt'
        test_data = b'Spaces in filename test'

        # Create and commit file with spaces
        pending_file = storage.create_file(filename)
        pending_file.fd.write(test_data)
        storage.commit_file(pending_file)

        # Create symlink
        target_path = temp_dir / filename
        symlink_path = temp_dir / 'spaces_symlink.txt'
        symlink_path.symlink_to(target_path)

        result_filename = storage.filename_from_symlink(symlink_path)
        assert result_filename == filename

    def test_filename_from_symlink_mixed_chain_types(self, storage, temp_dir):
        """Test filename_from_symlink with a chain mixing relative and absolute symlinks."""
        filename = 'mixed_chain_target.txt'
        test_data = b'Mixed chain test'

        # Create and commit target file
        pending_file = storage.create_file(filename)
        pending_file.fd.write(test_data)
        storage.commit_file(pending_file)

        # Create chain: symlink1 (absolute) -> symlink2 (relative) -> target
        symlink2_path = temp_dir / 'symlink2.txt'
        symlink1_path = temp_dir / 'symlink1.txt'

        symlink2_path.symlink_to(filename)  # Relative
        symlink1_path.symlink_to(symlink2_path.absolute())  # Absolute

        result_filename = storage.filename_from_symlink(symlink1_path)
        assert result_filename == filename

    def test_filename_from_symlink_edge_case_empty_storage(self, temp_dir):
        """Test filename_from_symlink with empty storage directory."""
        # Create storage with empty directory
        empty_storage = FilesystemStorage(temp_dir)

        # Create symlink to nonexistent file
        symlink_path = temp_dir / 'empty_symlink.txt'
        symlink_path.symlink_to(temp_dir / 'nonexistent.txt')

        result = empty_storage.filename_from_symlink(symlink_path)
        assert result is None

    def test_filename_from_symlink_case_sensitivity(self, storage, temp_dir):
        """Test filename_from_symlink case sensitivity behavior."""
        filename = 'CaseTest.txt'
        test_data = b'Case sensitivity test'

        # Create and commit file
        pending_file = storage.create_file(filename)
        pending_file.fd.write(test_data)
        storage.commit_file(pending_file)

        # Create symlink
        target_path = temp_dir / filename
        symlink_path = temp_dir / 'case_symlink.txt'
        symlink_path.symlink_to(target_path)

        result_filename = storage.filename_from_symlink(symlink_path)
        assert result_filename == filename
        # Verify exact case is preserved
        assert result_filename == 'CaseTest.txt'

    def test_filename_from_symlink_max_depth_protection(self, storage, temp_dir):
        """Test filename_from_symlink respects maximum depth limit."""
        filename = 'deep_target.txt'
        test_data = b'Deep chain target'

        # Create and commit target file
        pending_file = storage.create_file(filename)
        pending_file.fd.write(test_data)
        storage.commit_file(pending_file)

        # Create a very deep chain of symlinks (more than the max_depth limit)
        current_path = temp_dir / filename
        for i in range(105):  # More than the max_depth of 100
            next_path = temp_dir / f'link_{i}.txt'
            next_path.symlink_to(current_path)
            current_path = next_path

        # The function should return None due to depth limit
        result = storage.filename_from_symlink(current_path)
        assert result is None
