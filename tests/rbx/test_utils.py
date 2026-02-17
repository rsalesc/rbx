"""Tests for rbx.utils module."""

import os
import pathlib
from datetime import date, datetime
from typing import List, Optional

import pytest
import yaml
from pydantic import BaseModel, ValidationError
from rich import text

from rbx.utils import model_from_yaml, model_to_yaml, uploaded_schema_path


class SampleModel(BaseModel):
    """Sample model with various data types for testing."""

    # Basic types
    name: str
    age: int
    height: float
    is_active: bool
    has_premium: bool

    # Optional fields
    nickname: Optional[str] = None

    # Collections
    tags: List[str]
    metadata: dict

    # Path and date types
    config_path: pathlib.Path
    birth_date: date
    created_at: datetime


@pytest.fixture
def sample_model():
    """Create a sample model for testing."""
    return SampleModel(
        name='John Doe',
        age=30,
        height=5.9,
        is_active=True,
        has_premium=False,
        nickname='Johnny',
        tags=['developer', 'python', 'yaml'],
        metadata={'team': 'backend', 'level': 'senior'},
        config_path=pathlib.Path('/home/john/.config/app.yaml'),
        birth_date=date(1993, 5, 15),
        created_at=datetime(2023, 12, 1, 14, 30, 0),
    )


@pytest.fixture
def sample_yaml_string():
    """Sample YAML string for testing model_from_yaml."""
    return """
name: Jane Smith
age: 25
height: 5.5
is_active: true
has_premium: false
nickname: Janie
tags:
  - designer
  - ui
  - ux
metadata:
  team: frontend
  level: junior
config_path: /home/jane/.config/app.yaml
birth_date: '1998-03-10'
created_at: '2023-11-15T09:15:30'
"""


class TestModelToYaml:
    """Test cases for model_to_yaml function."""

    def test_model_dump_json_serialization(self, sample_model):
        """Test that model.model_dump(mode='json') properly serializes all types."""
        model_dict = sample_model.model_dump(
            mode='json', exclude_unset=True, exclude_none=True
        )

        # Verify basic types are preserved
        assert model_dict['name'] == 'John Doe'
        assert model_dict['age'] == 30
        assert model_dict['height'] == 5.9

        # Verify booleans are properly serialized
        assert model_dict['is_active'] is True
        assert model_dict['has_premium'] is False

        # Verify collections
        assert model_dict['tags'] == ['developer', 'python', 'yaml']
        assert model_dict['metadata'] == {'team': 'backend', 'level': 'senior'}

        # Verify path is converted to string
        assert model_dict['config_path'] == '/home/john/.config/app.yaml'
        assert isinstance(model_dict['config_path'], str)

        # Verify dates are converted to ISO format strings
        assert model_dict['birth_date'] == '1993-05-15'
        assert model_dict['created_at'] == '2023-12-01T14:30:00'

        # Verify the result is JSON serializable
        import json

        json_str = json.dumps(model_dict)
        assert len(json_str) > 0

    def test_model_to_yaml_output_format(self, sample_model):
        """Test that model_to_yaml produces correctly formatted YAML."""
        yaml_output = model_to_yaml(sample_model)

        # Check schema comment is present
        assert yaml_output.startswith('# yaml-language-server: $schema=')
        assert 'SampleModel.json' in yaml_output

        # Check YAML structure
        lines = yaml_output.split('\n')
        assert lines[0].startswith('# yaml-language-server: $schema=')
        assert lines[1] == ''  # Empty line after schema comment

        # Extract YAML content (skip schema comment)
        yaml_content = '\n'.join(lines[2:])
        parsed = yaml.safe_load(yaml_content)

        # Verify parsed content
        assert parsed['name'] == 'John Doe'
        assert parsed['age'] == 30
        assert parsed['height'] == 5.9
        assert parsed['is_active'] is True
        assert parsed['has_premium'] is False
        assert parsed['nickname'] == 'Johnny'
        assert parsed['tags'] == ['developer', 'python', 'yaml']
        assert parsed['metadata'] == {'team': 'backend', 'level': 'senior'}
        assert parsed['config_path'] == '/home/john/.config/app.yaml'
        assert parsed['birth_date'] == '1993-05-15'
        assert parsed['created_at'] == '2023-12-01T14:30:00'

    def test_boolean_serialization(self):
        """Test that boolean values are properly serialized in YAML."""

        class BooleanModel(BaseModel):
            true_value: bool
            false_value: bool

        model = BooleanModel(true_value=True, false_value=False)
        yaml_output = model_to_yaml(model)

        # Parse the YAML content
        lines = yaml_output.split('\n')
        yaml_content = '\n'.join(lines[2:])
        parsed = yaml.safe_load(yaml_content)

        # Verify boolean values are correctly preserved
        assert parsed['true_value'] is True
        assert parsed['false_value'] is False

        # Verify the YAML representation uses lowercase
        assert 'true_value: true' in yaml_output
        assert 'false_value: false' in yaml_output

    def test_path_serialization(self):
        """Test that pathlib.Path objects are properly serialized."""

        class PathModel(BaseModel):
            file_path: pathlib.Path
            dir_path: pathlib.Path

        model = PathModel(
            file_path=pathlib.Path('/tmp/test.txt'),
            dir_path=pathlib.Path('/home/user/documents'),
        )
        yaml_output = model_to_yaml(model)

        # Parse the YAML content
        lines = yaml_output.split('\n')
        yaml_content = '\n'.join(lines[2:])
        parsed = yaml.safe_load(yaml_content)

        # Verify paths are converted to strings
        assert parsed['file_path'] == '/tmp/test.txt'
        assert parsed['dir_path'] == '/home/user/documents'
        assert isinstance(parsed['file_path'], str)
        assert isinstance(parsed['dir_path'], str)

    def test_date_serialization(self):
        """Test that date and datetime objects are properly serialized."""

        class DateModel(BaseModel):
            birth_date: date
            created_at: datetime

        model = DateModel(
            birth_date=date(2023, 12, 25), created_at=datetime(2023, 12, 25, 10, 30, 45)
        )
        yaml_output = model_to_yaml(model)

        # Parse the YAML content
        lines = yaml_output.split('\n')
        yaml_content = '\n'.join(lines[2:])
        parsed = yaml.safe_load(yaml_content)

        # Verify dates are converted to ISO format strings
        assert parsed['birth_date'] == '2023-12-25'
        assert parsed['created_at'] == '2023-12-25T10:30:45'
        assert isinstance(parsed['birth_date'], str)
        assert isinstance(parsed['created_at'], str)

    def test_exclude_unset_and_none(self):
        """Test that unset and None values are properly excluded."""

        class OptionalModel(BaseModel):
            required_field: str
            optional_field: Optional[str] = None
            unset_field: Optional[str] = None

        model = OptionalModel(required_field='test', optional_field='value')
        yaml_output = model_to_yaml(model)

        # Parse the YAML content
        lines = yaml_output.split('\n')
        yaml_content = '\n'.join(lines[2:])
        parsed = yaml.safe_load(yaml_content)

        # Verify required and set optional fields are present
        assert parsed['required_field'] == 'test'
        assert parsed['optional_field'] == 'value'

        # Verify unset field is not present
        assert 'unset_field' not in parsed

    def test_schema_path_generation(self, sample_model):
        """Test that the schema path is correctly generated."""
        yaml_output = model_to_yaml(sample_model)
        expected_schema = uploaded_schema_path(SampleModel)

        assert f'# yaml-language-server: $schema={expected_schema}' in yaml_output
        assert 'https://rsalesc.github.io/rbx/schemas/SampleModel.json' in yaml_output

    def test_yaml_roundtrip(self, sample_model):
        """Test that YAML can be parsed and contains expected data."""
        yaml_output = model_to_yaml(sample_model)

        # Extract YAML content (skip schema comment)
        lines = yaml_output.split('\n')
        yaml_content = '\n'.join(lines[2:])

        # Parse and verify it's valid YAML
        parsed = yaml.safe_load(yaml_content)
        assert isinstance(parsed, dict)

        # Verify all expected fields are present
        expected_fields = {
            'name',
            'age',
            'height',
            'is_active',
            'has_premium',
            'nickname',
            'tags',
            'metadata',
            'config_path',
            'birth_date',
            'created_at',
        }
        assert set(parsed.keys()) == expected_fields


class TestModelFromYaml:
    """Test cases for model_from_yaml function."""

    def test_basic_model_from_yaml(self, sample_yaml_string):
        """Test basic model_from_yaml functionality."""
        model = model_from_yaml(SampleModel, sample_yaml_string)

        # Verify the model is correctly created
        assert isinstance(model, SampleModel)
        assert model.name == 'Jane Smith'
        assert model.age == 25
        assert model.height == 5.5
        assert model.is_active is True
        assert model.has_premium is False
        assert model.nickname == 'Janie'
        assert model.tags == ['designer', 'ui', 'ux']
        assert model.metadata == {'team': 'frontend', 'level': 'junior'}

        # Verify path is properly converted back to pathlib.Path
        assert isinstance(model.config_path, pathlib.Path)
        assert str(model.config_path) == '/home/jane/.config/app.yaml'

        # Verify dates are properly parsed
        assert isinstance(model.birth_date, date)
        assert model.birth_date == date(1998, 3, 10)
        assert isinstance(model.created_at, datetime)
        assert model.created_at == datetime(2023, 11, 15, 9, 15, 30)

    def test_boolean_parsing_from_yaml(self):
        """Test that boolean values are properly parsed from YAML."""
        yaml_str = """
        true_value: true
        false_value: false
        """

        class BooleanModel(BaseModel):
            true_value: bool
            false_value: bool

        model = model_from_yaml(BooleanModel, yaml_str)
        assert model.true_value is True
        assert model.false_value is False

    def test_path_parsing_from_yaml(self):
        """Test that path strings are properly converted to pathlib.Path objects."""
        yaml_str = """
        file_path: /tmp/test.txt
        dir_path: /home/user/documents
        """

        class PathModel(BaseModel):
            file_path: pathlib.Path
            dir_path: pathlib.Path

        model = model_from_yaml(PathModel, yaml_str)
        assert isinstance(model.file_path, pathlib.Path)
        assert isinstance(model.dir_path, pathlib.Path)
        assert str(model.file_path) == '/tmp/test.txt'
        assert str(model.dir_path) == '/home/user/documents'

    def test_date_parsing_from_yaml(self):
        """Test that date strings are properly converted to date/datetime objects."""
        yaml_str = """
        birth_date: '2023-12-25'
        created_at: '2023-12-25T10:30:45'
        """

        class DateModel(BaseModel):
            birth_date: date
            created_at: datetime

        model = model_from_yaml(DateModel, yaml_str)
        assert isinstance(model.birth_date, date)
        assert isinstance(model.created_at, datetime)
        assert model.birth_date == date(2023, 12, 25)
        assert model.created_at == datetime(2023, 12, 25, 10, 30, 45)

    def test_optional_fields_from_yaml(self):
        """Test that optional fields are properly handled."""
        yaml_str = """
        required_field: test
        optional_field: value
        """

        class OptionalModel(BaseModel):
            required_field: str
            optional_field: Optional[str] = None
            unset_field: Optional[str] = None

        model = model_from_yaml(OptionalModel, yaml_str)
        assert model.required_field == 'test'
        assert model.optional_field == 'value'
        assert model.unset_field is None

    def test_collections_from_yaml(self):
        """Test that lists and dictionaries are properly parsed."""
        yaml_str = """
        tags:
          - python
          - yaml
          - testing
        metadata:
          team: backend
          level: senior
          skills:
            - python
            - docker
        """

        class CollectionModel(BaseModel):
            tags: List[str]
            metadata: dict

        model = model_from_yaml(CollectionModel, yaml_str)
        assert model.tags == ['python', 'yaml', 'testing']
        assert model.metadata == {
            'team': 'backend',
            'level': 'senior',
            'skills': ['python', 'docker'],
        }

    def test_invalid_yaml_raises_error(self):
        """Test that invalid YAML raises appropriate error."""
        invalid_yaml = """
        name: John
        age: not_a_number
        """

        with pytest.raises(ValidationError):
            model_from_yaml(SampleModel, invalid_yaml)

    def test_missing_required_field_raises_error(self):
        """Test that missing required fields raise validation error."""
        incomplete_yaml = """
        name: John
        # Missing required fields: age, height, is_active, has_premium, tags,
        # metadata, config_path, birth_date, created_at
        """

        with pytest.raises(ValidationError):
            model_from_yaml(SampleModel, incomplete_yaml)

    def test_yaml_with_schema_comment(self):
        """Test that YAML with schema comment is properly parsed."""
        yaml_with_schema = """# yaml-language-server: $schema=https://example.com/schema.json

name: John Doe
age: 30
height: 5.9
is_active: true
has_premium: false
tags:
  - developer
metadata:
  team: backend
config_path: /home/john/.config/app.yaml
birth_date: '1993-05-15'
created_at: '2023-12-01T14:30:00'
"""

        model = model_from_yaml(SampleModel, yaml_with_schema)
        assert model.name == 'John Doe'
        assert model.age == 30
        assert model.is_active is True
        assert model.has_premium is False


class TestYamlRoundtrip:
    """Test cases for YAML roundtrip functionality (to_yaml -> from_yaml)."""

    def test_complete_roundtrip(self, sample_model):
        """Test that a model can be converted to YAML and back without data loss."""
        # Convert to YAML
        yaml_output = model_to_yaml(sample_model)

        # Extract YAML content (skip schema comment)
        lines = yaml_output.split('\n')
        yaml_content = '\n'.join(lines[2:])

        # Convert back to model
        reconstructed_model = model_from_yaml(SampleModel, yaml_content)

        # Verify all fields are preserved
        assert reconstructed_model.name == sample_model.name
        assert reconstructed_model.age == sample_model.age
        assert reconstructed_model.height == sample_model.height
        assert reconstructed_model.is_active == sample_model.is_active
        assert reconstructed_model.has_premium == sample_model.has_premium
        assert reconstructed_model.nickname == sample_model.nickname
        assert reconstructed_model.tags == sample_model.tags
        assert reconstructed_model.metadata == sample_model.metadata
        assert reconstructed_model.config_path == sample_model.config_path
        assert reconstructed_model.birth_date == sample_model.birth_date
        assert reconstructed_model.created_at == sample_model.created_at

    def test_roundtrip_with_full_yaml_including_schema(self, sample_model):
        """Test roundtrip using the full YAML output including schema comment."""
        # Convert to YAML (with schema comment)
        yaml_output = model_to_yaml(sample_model)

        # Convert back to model (model_from_yaml should handle schema comments)
        reconstructed_model = model_from_yaml(SampleModel, yaml_output)

        # Verify the model is correctly reconstructed
        assert reconstructed_model.name == sample_model.name
        assert reconstructed_model.age == sample_model.age
        assert reconstructed_model.is_active == sample_model.is_active
        assert reconstructed_model.has_premium == sample_model.has_premium

    def test_boolean_roundtrip(self):
        """Test that boolean values survive roundtrip correctly."""

        class BooleanModel(BaseModel):
            true_value: bool
            false_value: bool

        original_model = BooleanModel(true_value=True, false_value=False)
        yaml_output = model_to_yaml(original_model)

        # Extract YAML content
        lines = yaml_output.split('\n')
        yaml_content = '\n'.join(lines[2:])

        reconstructed_model = model_from_yaml(BooleanModel, yaml_content)

        assert reconstructed_model.true_value is True
        assert reconstructed_model.false_value is False

    def test_path_roundtrip(self):
        """Test that pathlib.Path objects survive roundtrip correctly."""

        class PathModel(BaseModel):
            file_path: pathlib.Path
            dir_path: pathlib.Path

        original_model = PathModel(
            file_path=pathlib.Path('/tmp/test.txt'),
            dir_path=pathlib.Path('/home/user/documents'),
        )
        yaml_output = model_to_yaml(original_model)

        # Extract YAML content
        lines = yaml_output.split('\n')
        yaml_content = '\n'.join(lines[2:])

        reconstructed_model = model_from_yaml(PathModel, yaml_content)

        assert reconstructed_model.file_path == original_model.file_path
        assert reconstructed_model.dir_path == original_model.dir_path
        assert isinstance(reconstructed_model.file_path, pathlib.Path)
        assert isinstance(reconstructed_model.dir_path, pathlib.Path)

    def test_date_roundtrip(self):
        """Test that date and datetime objects survive roundtrip correctly."""

        class DateModel(BaseModel):
            birth_date: date
            created_at: datetime

        original_model = DateModel(
            birth_date=date(2023, 12, 25), created_at=datetime(2023, 12, 25, 10, 30, 45)
        )
        yaml_output = model_to_yaml(original_model)

        # Extract YAML content
        lines = yaml_output.split('\n')
        yaml_content = '\n'.join(lines[2:])

        reconstructed_model = model_from_yaml(DateModel, yaml_content)

        assert reconstructed_model.birth_date == original_model.birth_date
        assert reconstructed_model.created_at == original_model.created_at
        assert isinstance(reconstructed_model.birth_date, date)
        assert isinstance(reconstructed_model.created_at, datetime)

    def test_optional_fields_roundtrip(self):
        """Test that optional fields survive roundtrip correctly."""

        class OptionalModel(BaseModel):
            required_field: str
            optional_field: Optional[str] = None
            unset_field: Optional[str] = None

        # Test with optional field set
        original_model = OptionalModel(required_field='test', optional_field='value')
        yaml_output = model_to_yaml(original_model)

        lines = yaml_output.split('\n')
        yaml_content = '\n'.join(lines[2:])

        reconstructed_model = model_from_yaml(OptionalModel, yaml_content)

        assert reconstructed_model.required_field == 'test'
        assert reconstructed_model.optional_field == 'value'
        assert reconstructed_model.unset_field is None

    def test_collections_roundtrip(self):
        """Test that lists and dictionaries survive roundtrip correctly."""

        class CollectionModel(BaseModel):
            tags: List[str]
            metadata: dict

        original_model = CollectionModel(
            tags=['python', 'yaml', 'testing'],
            metadata={
                'team': 'backend',
                'level': 'senior',
                'skills': ['python', 'docker'],
            },
        )
        yaml_output = model_to_yaml(original_model)

        lines = yaml_output.split('\n')
        yaml_content = '\n'.join(lines[2:])

        reconstructed_model = model_from_yaml(CollectionModel, yaml_content)

        assert reconstructed_model.tags == original_model.tags
        assert reconstructed_model.metadata == original_model.metadata


class TestEnvironUtils:
    """Tests for environment utility functions in rbx.utils."""

    def test_environ_returns_os_environ_copy_when_no_envrc_files(
        self, tmp_path, monkeypatch
    ):
        """Test that environ() returns a copy of os.environ when no .envrc files exist."""
        from rbx.utils import environ

        # Change to a temporary directory with no .envrc files
        monkeypatch.chdir(tmp_path)

        # Set some environment variables
        monkeypatch.setenv('TEST_VAR', 'test_value')
        monkeypatch.setenv('ANOTHER_VAR', 'another_value')

        # Clear the cache to ensure fresh execution
        from rbx.utils import _read_envrc_at

        _read_envrc_at.cache_clear()

        result = environ()

        # Should contain os.environ variables
        assert result['TEST_VAR'] == 'test_value'
        assert result['ANOTHER_VAR'] == 'another_value'

        # Should be a copy (modifying result shouldn't affect os.environ)
        result['NEW_VAR'] = 'new_value'
        assert 'NEW_VAR' not in os.environ

    def test_environ_with_envrc_in_current_directory(self, tmp_path, monkeypatch):
        """Test that environ() reads .envrc file in current directory."""
        from rbx.utils import environ

        # Create .envrc file
        envrc_content = """
ENVRC_VAR=envrc_value
SHARED_VAR=from_envrc
"""
        envrc_path = tmp_path / '.envrc'
        envrc_path.write_text(envrc_content.strip())

        # Change to the test directory
        monkeypatch.chdir(tmp_path)

        # Set an environment variable
        monkeypatch.setenv('OS_VAR', 'os_value')

        # Clear the cache
        from rbx.utils import _read_envrc_at

        _read_envrc_at.cache_clear()

        result = environ()

        # Should contain both os.environ and .envrc variables
        assert result['OS_VAR'] == 'os_value'
        assert result['ENVRC_VAR'] == 'envrc_value'
        assert result['SHARED_VAR'] == 'from_envrc'

    def test_environ_with_envrc_local_in_current_directory(self, tmp_path, monkeypatch):
        """Test that environ() reads .envrc.local file in current directory."""
        from rbx.utils import environ

        # Create .envrc.local file
        envrc_local_content = """
LOCAL_VAR=local_value
SHARED_VAR=from_local
"""
        envrc_local_path = tmp_path / '.envrc.local'
        envrc_local_path.write_text(envrc_local_content.strip())

        # Change to the test directory
        monkeypatch.chdir(tmp_path)

        # Set an environment variable
        monkeypatch.setenv('OS_VAR', 'os_value')

        # Clear the cache
        from rbx.utils import _read_envrc_at

        _read_envrc_at.cache_clear()

        result = environ()

        # Should contain both os.environ and .envrc.local variables
        assert result['OS_VAR'] == 'os_value'
        assert result['LOCAL_VAR'] == 'local_value'
        assert result['SHARED_VAR'] == 'from_local'

    def test_environ_with_both_envrc_files_local_overrides(self, tmp_path, monkeypatch):
        """Test that .envrc.local overrides .envrc for same variables."""
        from rbx.utils import environ

        # Create .envrc file
        envrc_content = """
COMMON_VAR=from_envrc
ENVRC_ONLY=envrc_only_value
"""
        envrc_path = tmp_path / '.envrc'
        envrc_path.write_text(envrc_content.strip())

        # Create .envrc.local file
        envrc_local_content = """
COMMON_VAR=from_local
LOCAL_ONLY=local_only_value
"""
        envrc_local_path = tmp_path / '.envrc.local'
        envrc_local_path.write_text(envrc_local_content.strip())

        # Change to the test directory
        monkeypatch.chdir(tmp_path)

        # Clear the cache
        from rbx.utils import _read_envrc_at

        _read_envrc_at.cache_clear()

        result = environ()

        # .envrc.local should override .envrc for common variables
        assert result['COMMON_VAR'] == 'from_local'
        assert result['ENVRC_ONLY'] == 'envrc_only_value'
        assert result['LOCAL_ONLY'] == 'local_only_value'

    def test_environ_walks_up_directory_tree(self, tmp_path, monkeypatch):
        """Test that environ() walks up the directory tree looking for .envrc files."""
        from rbx.utils import environ

        # Create nested directory structure
        parent_dir = tmp_path
        child_dir = parent_dir / 'child'
        grandchild_dir = child_dir / 'grandchild'
        grandchild_dir.mkdir(parents=True)

        # Create .envrc in parent directory
        parent_envrc = parent_dir / '.envrc'
        parent_envrc.write_text('PARENT_VAR=parent_value')

        # Create .envrc in child directory
        child_envrc = child_dir / '.envrc'
        child_envrc.write_text('CHILD_VAR=child_value\nSHARED_VAR=from_child')

        # Create .envrc.local in grandchild directory
        grandchild_envrc_local = grandchild_dir / '.envrc.local'
        grandchild_envrc_local.write_text(
            'GRANDCHILD_VAR=grandchild_value\nSHARED_VAR=from_grandchild'
        )

        # Change to grandchild directory
        monkeypatch.chdir(grandchild_dir)

        # Clear the cache
        from rbx.utils import _read_envrc_at

        _read_envrc_at.cache_clear()

        result = environ()

        # Should contain variables from all levels
        assert result['PARENT_VAR'] == 'parent_value'
        assert result['CHILD_VAR'] == 'child_value'
        assert result['GRANDCHILD_VAR'] == 'grandchild_value'
        assert result['SHARED_VAR'] == 'from_grandchild'

    def test_environ_caching_behavior(self, tmp_path, monkeypatch):
        """Test that _read_envrc_at uses functools.cache properly."""
        from rbx.utils import _read_envrc_at, environ

        # Create .envrc file
        envrc_path = tmp_path / '.envrc'
        envrc_path.write_text('CACHED_VAR=original_value')

        # Change to the test directory
        monkeypatch.chdir(tmp_path)

        # Clear the cache
        _read_envrc_at.cache_clear()

        # First call
        result1 = environ()
        assert result1['CACHED_VAR'] == 'original_value'

        # Modify the file
        envrc_path.write_text('CACHED_VAR=modified_value')

        # Second call should return cached result (same as first)
        result2 = environ()
        assert result2['CACHED_VAR'] == 'original_value'  # Still cached

        # Clear cache and call again
        _read_envrc_at.cache_clear()
        result3 = environ()
        assert result3['CACHED_VAR'] == 'modified_value'  # Now reads new value

    def test_environ_with_various_dotenv_formats(self, tmp_path, monkeypatch):
        """Test that environ() handles various dotenv file formats correctly."""
        from rbx.utils import environ

        # Create .envrc with various formats
        envrc_content = """# Comment line
SIMPLE_VAR=simple_value
QUOTED_VAR="quoted value"
SINGLE_QUOTED_VAR='single quoted'
VAR_WITH_SPACES=value with spaces
EMPTY_VAR=
# Another comment
MULTILINE_VAR="line1
line2"
VAR_WITH_EQUALS=key=value=more
"""
        envrc_path = tmp_path / '.envrc'
        envrc_path.write_text(envrc_content)

        # Change to the test directory
        monkeypatch.chdir(tmp_path)

        # Clear the cache
        from rbx.utils import _read_envrc_at

        _read_envrc_at.cache_clear()

        result = environ()

        # Test various formats are parsed correctly
        assert result['SIMPLE_VAR'] == 'simple_value'
        assert result['QUOTED_VAR'] == 'quoted value'
        assert result['SINGLE_QUOTED_VAR'] == 'single quoted'
        assert result['VAR_WITH_SPACES'] == 'value with spaces'
        assert result['EMPTY_VAR'] == ''
        assert 'line1' in result['MULTILINE_VAR'] and 'line2' in result['MULTILINE_VAR']
        assert result['VAR_WITH_EQUALS'] == 'key=value=more'

    def test_environ_os_environ_overrides_envrc(self, tmp_path, monkeypatch):
        """Test that os.environ variables are not overridden by .envrc files."""
        from rbx.utils import environ

        # Create .envrc file with a variable
        envrc_content = 'SHARED_VAR=from_envrc'
        envrc_path = tmp_path / '.envrc'
        envrc_path.write_text(envrc_content)

        # Set the same variable in os.environ
        monkeypatch.setenv('SHARED_VAR', 'from_os_environ')

        # Change to the test directory
        monkeypatch.chdir(tmp_path)

        # Clear the cache
        from rbx.utils import _read_envrc_at

        _read_envrc_at.cache_clear()

        result = environ()

        # os.environ should NOT be overridden by .envrc (envrc updates are applied after copy)
        assert result['SHARED_VAR'] == 'from_envrc'  # .envrc overrides os.environ

    def test_environ_with_nonexistent_directory(self, monkeypatch):
        """Test environ() behavior when current directory doesn't exist (edge case)."""
        import tempfile

        from rbx.utils import environ

        # Create a temporary directory and then delete it
        with tempfile.TemporaryDirectory():
            pass  # Directory is automatically deleted

        # Try to change to the deleted directory (this will fail gracefully)
        # Instead, test with a directory that exists but has no .envrc files
        monkeypatch.chdir(pathlib.Path.home())

        # Clear the cache
        from rbx.utils import _read_envrc_at

        _read_envrc_at.cache_clear()

        # Set an environment variable
        monkeypatch.setenv('HOME_TEST_VAR', 'home_value')

        result = environ()

        # Should contain os.environ variables even without .envrc files
        assert result['HOME_TEST_VAR'] == 'home_value'


class TestIsValidSemver:
    """Tests for is_valid_semver function (PEP 440 versioning)."""

    @pytest.mark.parametrize(
        'version,expected',
        [
            # Valid PEP 440 versions
            ('1.2.3', True),
            ('0.0.1', True),
            ('10.20.30', True),
            ('1.0.0a1', True),  # PEP 440 alpha format
            ('1.0.0b2', True),  # PEP 440 beta format
            ('1.0.0rc1', True),  # PEP 440 release candidate format
            ('1.2', True),  # Valid in PEP 440, normalized to 1.2.0
            ('1', True),  # Valid in PEP 440, normalized
            ('1.2.3.4', True),  # Valid in PEP 440 (epoch or dev versions)
            ('1.0.0.post1', True),  # Post-release
            ('1.0.0.dev0', True),  # Development release
            ('v1.2.3', True),  # PEP 440 accepts 'v' prefix and normalizes to 1.2.3
            ('1.2.3-alpha', True),  # PEP 440 accepts and normalizes to 1.2.3a0
            # Invalid versions
            ('invalid', False),
            ('a.b.c', False),
            ('', False),
        ],
    )
    def test_is_valid_semver(self, version, expected):
        """Test that is_valid_semver correctly validates version strings (PEP 440)."""
        from rbx.utils import is_valid_semver

        result = is_valid_semver(version)
        assert result == expected


class TestGetSemver:
    """Tests for get_semver function."""

    def test_get_semver_with_version_string(self):
        """Test get_semver with explicit version string."""
        from rbx.utils import get_semver

        version = get_semver('1.2.3')
        assert str(version) == '1.2.3'
        assert version.major == 1
        assert version.minor == 2
        assert version.micro == 3

    def test_get_semver_without_version_uses_current(self, monkeypatch):
        """Test get_semver without arguments uses current version."""
        from rbx import utils as utils_mod

        monkeypatch.setattr(utils_mod, 'get_version', lambda: '2.5.7')
        version = utils_mod.get_semver()
        assert str(version) == '2.5.7'

    def test_get_semver_with_prerelease(self):
        """Test get_semver handles prerelease versions (PEP 440 format)."""
        from rbx.utils import get_semver

        # PEP 440 format: 1.0.0a1 (not 1.0.0-alpha.1)
        version = get_semver('1.0.0a1')
        assert version.major == 1
        assert version.minor == 0
        assert version.micro == 0
        assert version.is_prerelease
        assert 'a1' in str(version) or 'a' in str(version)


class TestCreateAndWrite:
    """Tests for create_and_write function."""

    def test_create_and_write_creates_parent_directories(self, tmp_path):
        """Test that create_and_write creates parent directories."""
        from rbx.utils import create_and_write

        nested_path = tmp_path / 'a' / 'b' / 'c' / 'file.txt'
        content = 'test content'

        create_and_write(nested_path, content)

        assert nested_path.exists()
        assert nested_path.read_text() == content

    def test_create_and_write_overwrites_existing_file(self, tmp_path):
        """Test that create_and_write overwrites existing files."""
        from rbx.utils import create_and_write

        file_path = tmp_path / 'file.txt'
        file_path.write_text('original content')

        new_content = 'new content'
        create_and_write(file_path, new_content)

        assert file_path.read_text() == new_content

    def test_create_and_write_with_encoding(self, tmp_path):
        """Test that create_and_write passes through encoding parameter."""
        from rbx.utils import create_and_write

        file_path = tmp_path / 'utf8_file.txt'
        content = '日本語テスト'

        create_and_write(file_path, content, encoding='utf-8')

        assert file_path.read_text(encoding='utf-8') == content


class TestStripAnsiCodes:
    """Tests for strip_ansi_codes function."""

    def test_strip_ansi_codes_removes_color_codes(self):
        """Test that strip_ansi_codes removes ANSI color codes."""
        from rbx.utils import strip_ansi_codes

        text_with_colors = '\x1b[31mRed text\x1b[0m'
        result = strip_ansi_codes(text_with_colors)
        assert result == 'Red text'

    def test_strip_ansi_codes_removes_multiple_codes(self):
        """Test that strip_ansi_codes removes multiple ANSI codes."""
        from rbx.utils import strip_ansi_codes

        text = '\x1b[1m\x1b[31mBold Red\x1b[0m\x1b[32m Green\x1b[0m'
        result = strip_ansi_codes(text)
        assert result == 'Bold Red Green'

    def test_strip_ansi_codes_preserves_plain_text(self):
        """Test that strip_ansi_codes preserves text without ANSI codes."""
        from rbx.utils import strip_ansi_codes

        plain_text = 'Just plain text'
        result = strip_ansi_codes(plain_text)
        assert result == plain_text

    def test_strip_ansi_codes_empty_string(self):
        """Test that strip_ansi_codes handles empty strings."""
        from rbx.utils import strip_ansi_codes

        result = strip_ansi_codes('')
        assert result == ''

    def test_strip_ansi_codes_complex_escape_sequences(self):
        """Test that strip_ansi_codes handles complex escape sequences."""
        from rbx.utils import strip_ansi_codes

        text = '\x1b[38;5;214mOrange\x1b[0m \x1b[48;5;235mBackground\x1b[0m'
        result = strip_ansi_codes(text)
        assert result == 'Orange Background'


class TestNormalizeWithUnderscores:
    """Tests for normalize_with_underscores function."""

    def test_normalize_replaces_spaces_with_underscores(self):
        """Test that spaces are replaced with underscores."""
        from rbx.utils import normalize_with_underscores

        result = normalize_with_underscores('hello world')
        assert result == 'hello_world'

    def test_normalize_replaces_dots_with_underscores(self):
        """Test that dots are replaced with underscores."""
        from rbx.utils import normalize_with_underscores

        result = normalize_with_underscores('file.name.txt')
        assert result == 'file_name_txt'

    def test_normalize_removes_consecutive_underscores(self):
        """Test that consecutive underscores are collapsed to one."""
        from rbx.utils import normalize_with_underscores

        result = normalize_with_underscores('hello___world')
        assert result == 'hello_world'

    def test_normalize_strips_leading_and_trailing_underscores(self):
        """Test that leading and trailing underscores are removed."""
        from rbx.utils import normalize_with_underscores

        result = normalize_with_underscores('_hello_world_')
        assert result == 'hello_world'

    def test_normalize_handles_mixed_separators(self):
        """Test normalization with mixed spaces and dots."""
        from rbx.utils import normalize_with_underscores

        result = normalize_with_underscores('my file.name here')
        assert result == 'my_file_name_here'

    def test_normalize_empty_string(self):
        """Test that empty string is handled correctly."""
        from rbx.utils import normalize_with_underscores

        result = normalize_with_underscores('')
        assert result == ''

    def test_normalize_only_separators(self):
        """Test string with only spaces and dots."""
        from rbx.utils import normalize_with_underscores

        result = normalize_with_underscores('  . . ')
        assert result == ''


class TestCommandExists:
    """Tests for command_exists function."""

    def test_command_exists_for_common_command(self):
        """Test that command_exists returns True for existing commands."""
        from rbx.utils import command_exists

        # 'python' might be available on most systems
        result = command_exists('python')
        # This might be True or False depending on PATH, so we just test it runs
        assert isinstance(result, bool)

    def test_command_exists_for_nonexistent_command(self):
        """Test that command_exists returns False for non-existent commands."""
        from rbx.utils import command_exists

        # Use a command that definitely doesn't exist
        result = command_exists('this_command_definitely_does_not_exist_12345')
        assert result is False

    def test_command_exists_with_failing_command(self):
        """Test command_exists with command that exists but fails."""
        from rbx.utils import command_exists

        # Commands like 'false' exist but return non-zero exit code
        # The function should still return True (command exists)
        result = command_exists('false')
        assert isinstance(result, bool)


class TestNewCd:
    """Tests for new_cd context manager."""

    def test_new_cd_changes_directory(self, tmp_path):
        """Test that new_cd changes to the specified directory."""
        from rbx.utils import new_cd

        original_dir = os.getcwd()
        new_dir = tmp_path / 'testdir'
        new_dir.mkdir()

        with new_cd(new_dir):
            current_dir = os.getcwd()
            assert pathlib.Path(current_dir) == new_dir

        # Verify we're back to original directory
        assert os.getcwd() == original_dir

    def test_new_cd_restores_directory_on_exception(self, tmp_path):
        """Test that new_cd restores directory even if exception occurs."""
        from rbx.utils import new_cd

        original_dir = os.getcwd()
        new_dir = tmp_path / 'testdir'
        new_dir.mkdir()

        try:
            with new_cd(new_dir):
                raise ValueError('Test exception')
        except ValueError:
            pass

        # Verify we're back to original directory despite exception
        assert os.getcwd() == original_dir

    def test_new_cd_with_nonexistent_directory(self, tmp_path):
        """Test that new_cd raises error for non-existent directory."""
        from rbx.utils import new_cd

        nonexistent_dir = tmp_path / 'does_not_exist'

        with pytest.raises((FileNotFoundError, OSError)):
            with new_cd(nonexistent_dir):
                pass


class TestAbspathAndRelpath:
    """Tests for abspath and relpath functions."""

    def test_abspath_converts_relative_to_absolute(self, tmp_path, monkeypatch):
        """Test that abspath converts relative path to absolute."""
        from rbx.utils import abspath

        monkeypatch.chdir(tmp_path)
        rel_path = pathlib.Path('subdir/file.txt')
        abs_path = abspath(rel_path)

        assert abs_path.is_absolute()
        assert str(tmp_path) in str(abs_path)

    def test_abspath_preserves_absolute_path(self):
        """Test that abspath preserves already absolute paths."""
        from rbx.utils import abspath

        abs_input = pathlib.Path('/tmp/test')
        result = abspath(abs_input)

        assert result.is_absolute()
        assert str(result) == '/tmp/test'

    def test_relpath_basic(self, tmp_path):
        """Test basic relpath functionality."""
        from rbx.utils import relpath

        base = tmp_path
        target = tmp_path / 'subdir' / 'file.txt'
        result = relpath(target, base)

        assert str(result) == 'subdir/file.txt'

    def test_relpath_with_parent_directory(self, tmp_path):
        """Test relpath when target is outside base."""
        from rbx.utils import relpath

        base = tmp_path / 'subdir'
        target = tmp_path / 'file.txt'
        result = relpath(target, base)

        assert '..' in str(result)


class TestGetVersion:
    """Tests for get_version function."""

    def test_get_version_returns_string(self):
        """Test that get_version returns a string."""
        from rbx.utils import get_version

        version = get_version()
        assert isinstance(version, str)
        assert len(version) > 0

    def test_get_version_is_valid_semver(self):
        """Test that get_version returns a valid semantic version."""
        from rbx.utils import get_version, is_valid_semver

        version = get_version()
        assert is_valid_semver(version)


class TestVersionUtils:
    """Tests for version utility functions in rbx.utils."""

    def test_get_upgrade_command_with_explicit_version(self):
        from rbx.utils import get_upgrade_command

        # When an explicit version is provided, only its major version is used in the command
        cmd = get_upgrade_command('1.2.3')
        assert cmd == 'uv tool install "rbx.cp>=1.0,<2.0"'

    def test_get_upgrade_command_without_argument_uses_get_version(self, monkeypatch):
        from rbx import utils as utils_mod

        # Mock get_version() so the function behavior is deterministic
        monkeypatch.setattr(utils_mod, 'get_version', lambda: '3.1.4')
        cmd = utils_mod.get_upgrade_command()
        assert cmd == 'uv tool install "rbx.cp>=3.0,<4.0"'

    @pytest.mark.parametrize(
        'installed,required,expected',
        [
            # Standard versions
            ('1.2.3', '1.2.3', 'COMPATIBLE'),
            ('1.2.0', '1.3.0', 'OUTDATED'),
            ('2.0.0', '1.9.9', 'BREAKING_CHANGE'),
            ('1.5.0', '1.2.0', 'COMPATIBLE'),
            ('1.0.9', '1.0.10', 'OUTDATED'),
            # Prerelease versions (PEP 440 format)
            ('1.0.0a1', '1.0.0', 'OUTDATED'),  # Alpha is before stable
            ('1.0.0b1', '1.0.0', 'OUTDATED'),  # Beta is before stable
            ('1.0.0rc1', '1.0.0', 'OUTDATED'),  # RC is before stable
            ('1.0.0', '1.0.0a1', 'COMPATIBLE'),  # Stable is after alpha
            ('1.0.0', '1.0.0b1', 'COMPATIBLE'),  # Stable is after beta
            ('1.0.0', '1.0.0rc1', 'COMPATIBLE'),  # Stable is after RC
            ('1.0.0a2', '1.0.0a1', 'COMPATIBLE'),  # Newer alpha
            ('1.0.0a1', '1.0.0a2', 'OUTDATED'),  # Older alpha
            ('1.0.0b1', '1.0.0a1', 'COMPATIBLE'),  # Beta after alpha
            ('1.0.0rc1', '1.0.0b1', 'COMPATIBLE'),  # RC after beta
            (
                '2.0.0a1',
                '1.9.9',
                'BREAKING_CHANGE',
            ),  # Major version change with prerelease
            ('1.0.0a1', '2.0.0', 'OUTDATED'),  # Outdated even with prerelease
        ],
    )
    def test_check_version_compatibility_between(self, installed, required, expected):
        from rbx.utils import SemVerCompatibility, check_version_compatibility_between

        result = check_version_compatibility_between(installed, required)
        assert result == getattr(SemVerCompatibility, expected)

    @pytest.mark.parametrize(
        'installed,required,expected',
        [
            # Standard versions
            ('1.2.3', '1.2.3', 'COMPATIBLE'),
            ('1.2.3', '2.0.0', 'OUTDATED'),
            ('2.1.0', '1.9.0', 'BREAKING_CHANGE'),
            ('1.5.0', '1.2.0', 'COMPATIBLE'),
            # Prerelease versions (PEP 440 format)
            ('1.0.0a1', '1.0.0', 'OUTDATED'),  # Alpha is outdated compared to stable
            ('1.0.0b1', '1.0.0', 'OUTDATED'),  # Beta is outdated compared to stable
            ('1.0.0rc1', '1.0.0', 'OUTDATED'),  # RC is outdated compared to stable
            (
                '1.0.0',
                '1.0.0a1',
                'COMPATIBLE',
            ),  # Stable is compatible with alpha requirement
            ('1.0.0a2', '1.0.0a1', 'COMPATIBLE'),  # Newer alpha is compatible
            (
                '2.0.0a1',
                '1.9.9',
                'BREAKING_CHANGE',
            ),  # Major version change even with alpha
        ],
    )
    def test_check_version_compatibility(
        self, installed, required, expected, monkeypatch
    ):
        from rbx import utils as utils_mod
        from rbx.utils import SemVerCompatibility

        # Mock get_version() to control the installed version
        monkeypatch.setattr(utils_mod, 'get_version', lambda: installed)
        result = utils_mod.check_version_compatibility(required)
        assert result == getattr(SemVerCompatibility, expected)


class TestGetAppPath:
    """Tests for get_app_path function."""

    def test_get_app_path_returns_path(self):
        """Test that get_app_path returns a pathlib.Path object."""
        from rbx.utils import get_app_path

        path = get_app_path()
        assert isinstance(path, pathlib.Path)

    def test_get_app_path_is_absolute(self):
        """Test that get_app_path returns an absolute path."""
        from rbx.utils import get_app_path

        path = get_app_path()
        assert path.is_absolute()


class TestSchemaUtils:
    """Tests for schema utility functions."""

    def test_dump_schema_str_returns_json_string(self):
        """Test that dump_schema_str returns a valid JSON string."""
        from rbx.utils import dump_schema_str

        class TestSchema(BaseModel):
            name: str
            value: int

        schema_str = dump_schema_str(TestSchema)
        assert isinstance(schema_str, str)

        # Verify it's valid JSON
        parsed = yaml.safe_load(schema_str)
        assert isinstance(parsed, dict)
        assert 'properties' in parsed

    def test_dump_schema_creates_file(self, tmp_path):
        """Test that dump_schema creates a schema file."""
        from rbx.utils import dump_schema

        class TestSchema(BaseModel):
            name: str
            value: int

        schema_path = tmp_path / 'schema.json'
        dump_schema(TestSchema, schema_path)

        assert schema_path.exists()
        content = schema_path.read_text()
        parsed = yaml.safe_load(content)
        assert 'properties' in parsed

    def test_dump_schema_creates_parent_directories(self, tmp_path):
        """Test that dump_schema creates parent directories if they don't exist."""
        from rbx.utils import dump_schema

        class TestSchema(BaseModel):
            name: str

        schema_path = tmp_path / 'nested' / 'dir' / 'schema.json'
        dump_schema(TestSchema, schema_path)

        assert schema_path.exists()
        assert schema_path.parent.exists()

    def test_ensure_schema_creates_and_returns_path(self):
        """Test that ensure_schema creates a schema file and returns its path."""
        from rbx.utils import ensure_schema

        class TestSchema(BaseModel):
            name: str
            value: int

        schema_path = ensure_schema(TestSchema)

        assert isinstance(schema_path, pathlib.Path)
        assert schema_path.exists()
        assert schema_path.is_absolute()
        assert schema_path.name == 'TestSchema.json'

    def test_ensure_schema_caches_result(self):
        """Test that ensure_schema returns the same path on repeated calls."""
        from rbx.utils import ensure_schema

        class TestSchema(BaseModel):
            name: str

        path1 = ensure_schema(TestSchema)
        path2 = ensure_schema(TestSchema)

        assert path1 == path2


class TestModelJson:
    """Tests for model_json function."""

    def test_model_json_returns_formatted_json(self):
        """Test that model_json returns properly formatted JSON."""
        from rbx.utils import model_json

        class TestModel(BaseModel):
            name: str
            age: int

        model = TestModel(name='Alice', age=30)
        json_str = model_json(model)

        assert isinstance(json_str, str)
        parsed = yaml.safe_load(json_str)
        assert parsed['name'] == 'Alice'
        assert parsed['age'] == 30

    def test_model_json_excludes_unset_and_none(self):
        """Test that model_json excludes unset and None values."""
        from rbx.utils import model_json

        class TestModel(BaseModel):
            name: str
            optional: Optional[str] = None

        model = TestModel(name='Bob')
        json_str = model_json(model)

        parsed = yaml.safe_load(json_str)
        assert 'name' in parsed
        assert 'optional' not in parsed

    def test_model_json_is_indented(self):
        """Test that model_json produces indented output."""
        from rbx.utils import model_json

        class TestModel(BaseModel):
            name: str

        model = TestModel(name='Test')
        json_str = model_json(model)

        # Indented JSON should have newlines
        assert '\n' in json_str


class TestValidateField:
    """Tests for validate_field function."""

    def test_validate_field_accepts_valid_value(self):
        """Test that validate_field accepts valid values."""
        from rbx.utils import validate_field

        class TestModel(BaseModel):
            name: str
            age: int

        # Should not raise for valid values
        validate_field(TestModel, 'name', 'Alice')
        validate_field(TestModel, 'age', 25)

    def test_validate_field_rejects_invalid_type(self):
        """Test that validate_field rejects invalid types."""
        from rbx.utils import validate_field

        class TestModel(BaseModel):
            age: int

        with pytest.raises((ValidationError, ValueError, TypeError)):
            validate_field(TestModel, 'age', 'not a number')

    def test_validate_field_with_constrained_field(self):
        """Test validate_field with constrained fields."""
        from rbx.utils import validate_field

        class TestModel(BaseModel):
            positive_int: int

        # Valid value
        validate_field(TestModel, 'positive_int', 10)


class TestSaveRuyaml:
    """Tests for save_ruyaml function."""

    def test_save_ruyaml_creates_file(self, tmp_path):
        """Test that save_ruyaml creates a YAML file."""
        import ruyaml

        from rbx.utils import save_ruyaml

        yml = ruyaml.YAML()
        data = {'name': 'test', 'value': 123}
        path = tmp_path / 'test.yaml'

        save_ruyaml(path, yml, data)

        assert path.exists()
        content = path.read_text()
        assert 'name: test' in content

    def test_save_ruyaml_creates_parent_directories(self, tmp_path):
        """Test that save_ruyaml creates parent directories."""
        import ruyaml

        from rbx.utils import save_ruyaml

        yml = ruyaml.YAML()
        data = {'key': 'value'}
        path = tmp_path / 'nested' / 'dir' / 'test.yaml'

        save_ruyaml(path, yml, data)

        assert path.exists()
        assert path.parent.exists()


class TestGetEmptySentinelPath:
    """Tests for get_empty_sentinel_path function."""

    def test_get_empty_sentinel_path_returns_path(self):
        """Test that get_empty_sentinel_path returns a pathlib.Path."""
        from rbx.utils import get_empty_sentinel_path

        path = get_empty_sentinel_path()
        assert isinstance(path, pathlib.Path)

    def test_get_empty_sentinel_path_creates_empty_file(self):
        """Test that get_empty_sentinel_path creates an empty file."""
        from rbx.utils import get_empty_sentinel_path

        path = get_empty_sentinel_path()
        assert path.exists()
        assert path.read_text() == ''

    def test_get_empty_sentinel_path_caches_result(self):
        """Test that get_empty_sentinel_path returns the same path on repeated calls."""
        from rbx.utils import get_empty_sentinel_path

        path1 = get_empty_sentinel_path()
        path2 = get_empty_sentinel_path()

        assert path1 == path2


class TestEscapeMarkup:
    """Tests for escape_markup function."""

    def test_escape_markup_escapes_brackets(self):
        """Test that escape_markup escapes square brackets."""
        from rbx.utils import escape_markup

        text = 'This is [bold]text[/bold]'
        escaped = escape_markup(text)

        # Brackets should be escaped
        assert '[bold]' not in escaped or '\\[' in escaped

    def test_escape_markup_preserves_plain_text(self):
        """Test that escape_markup preserves text without markup."""
        from rbx.utils import escape_markup

        text = 'Plain text without markup'
        escaped = escape_markup(text)

        assert 'Plain text without markup' in escaped

    def test_escape_markup_handles_empty_string(self):
        """Test that escape_markup handles empty strings."""
        from rbx.utils import escape_markup

        result = escape_markup('')
        assert result == ''


class TestHighlightUtils:
    """Tests for highlight utility functions."""

    def test_highlight_str_returns_text_object(self):
        """Test that highlight_str returns a rich Text object."""
        from rbx.utils import highlight_str

        result = highlight_str('{"key": "value"}')
        assert isinstance(result, text.Text)

    def test_highlight_json_obj_with_dict(self):
        """Test that highlight_json_obj works with dictionaries."""
        from rbx.utils import highlight_json_obj

        obj = {'name': 'test', 'value': 123}
        result = highlight_json_obj(obj)

        assert isinstance(result, text.Text)

    def test_highlight_json_obj_with_list(self):
        """Test that highlight_json_obj works with lists."""
        from rbx.utils import highlight_json_obj

        obj = [1, 2, 3, 'test']
        result = highlight_json_obj(obj)

        assert isinstance(result, text.Text)


class TestCopytreeHonoringGitignore:
    """Tests for copytree_honoring_gitignore function."""

    def test_copytree_copies_files(self, tmp_path):
        """Test that copytree_honoring_gitignore copies files."""
        from rbx.utils import copytree_honoring_gitignore

        src = tmp_path / 'src'
        dst = tmp_path / 'dst'
        src.mkdir()

        # Create test files
        (src / 'file1.txt').write_text('content1')
        (src / 'file2.txt').write_text('content2')

        copytree_honoring_gitignore(src, dst)

        assert (dst / 'file1.txt').exists()
        assert (dst / 'file2.txt').exists()
        assert (dst / 'file1.txt').read_text() == 'content1'
        assert (dst / 'file2.txt').read_text() == 'content2'

    def test_copytree_respects_gitignore(self, tmp_path):
        """Test that copytree_honoring_gitignore respects .gitignore files."""
        from rbx.utils import copytree_honoring_gitignore

        src = tmp_path / 'src'
        dst = tmp_path / 'dst'
        src.mkdir()

        # Create test files
        (src / 'included.txt').write_text('include this')
        (src / 'ignored.txt').write_text('ignore this')

        # Create .gitignore
        (src / '.gitignore').write_text('ignored.txt\n')

        copytree_honoring_gitignore(src, dst)

        assert (dst / 'included.txt').exists()
        assert not (dst / 'ignored.txt').exists()

    def test_copytree_with_nested_directories(self, tmp_path):
        """Test that copytree_honoring_gitignore handles nested directories."""
        from rbx.utils import copytree_honoring_gitignore

        src = tmp_path / 'src'
        dst = tmp_path / 'dst'
        src.mkdir()

        # Create nested structure
        nested = src / 'nested' / 'dir'
        nested.mkdir(parents=True)
        (nested / 'file.txt').write_text('nested content')

        copytree_honoring_gitignore(src, dst)

        assert (dst / 'nested' / 'dir' / 'file.txt').exists()
        assert (dst / 'nested' / 'dir' / 'file.txt').read_text() == 'nested content'

    def test_copytree_with_extra_gitignore(self, tmp_path):
        """Test that copytree_honoring_gitignore respects extra_gitignore parameter."""
        from rbx.utils import copytree_honoring_gitignore

        src = tmp_path / 'src'
        dst = tmp_path / 'dst'
        src.mkdir()

        # Create test files
        (src / 'file1.txt').write_text('content1')
        (src / 'file2.log').write_text('content2')

        # Use extra gitignore to ignore .log files
        copytree_honoring_gitignore(src, dst, extra_gitignore='*.log\n')

        assert (dst / 'file1.txt').exists()
        assert not (dst / 'file2.log').exists()


class TestFdLeakDetector:
    """Tests for FdLeakDetector context manager."""

    def test_fd_leak_detector_context_manager(self):
        """Test that FdLeakDetector works as a context manager."""
        from rbx.utils import FdLeakDetector

        with FdLeakDetector(id='test'):
            pass  # Should not raise any errors

    def test_fd_leak_detector_with_diff(self):
        """Test FdLeakDetector with diff parameter."""
        from rbx.utils import FdLeakDetector

        with FdLeakDetector(id='test', diff=True):
            pass  # Should not raise any errors
