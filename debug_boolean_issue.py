#!/usr/bin/env python3
"""Debug script to trace boolean values through the entire pipeline."""

import pathlib
from datetime import date, datetime
from typing import Dict, List, Optional

import yaml
from pydantic import BaseModel

from rbx.box.fields import Primitive
from rbx.box.schema import Package
from rbx.utils import model_from_yaml, model_to_yaml


def test_yaml_loading():
    """Test how YAML loading works with boolean values."""
    print('=== Testing YAML Loading ===\n')

    # Test 1: Direct YAML loading
    yaml_content = """
name: test-problem
timeLimit: 1000
memoryLimit: 256
vars:
  bool_true: true
  bool_false: false
  int_val: 42
  float_val: 3.14
  str_val: "hello"
"""

    print('1. Raw YAML content:')
    print(yaml_content)

    # Test yaml.safe_load directly
    print('\n2. Direct yaml.safe_load result:')
    raw_yaml = yaml.safe_load(yaml_content)
    print(f'   Raw vars: {raw_yaml["vars"]}')
    for name, value in raw_yaml['vars'].items():
        print(f'   {name}: {value} (type: {type(value).__name__})')

    # Test model_from_yaml
    print('\n3. model_from_yaml result:')
    package = model_from_yaml(Package, yaml_content)
    print(f'   Package vars: {package.vars}')
    for name, value in package.vars.items():
        print(f'   {name}: {value} (type: {type(value).__name__})')

    # Test expanded_vars
    print('\n4. expanded_vars result:')
    expanded = package.expanded_vars
    print(f'   Expanded vars: {expanded}')
    for name, value in expanded.items():
        print(f'   {name}: {value} (type: {type(value).__name__})')

    # Test model_dump with different modes
    print('\n5. model_dump results:')

    # Without mode
    dump_regular = package.model_dump()
    print(f'   Regular dump vars: {dump_regular["vars"]}')
    for name, value in dump_regular['vars'].items():
        print(f'   {name}: {value} (type: {type(value).__name__})')

    # With mode='json'
    dump_json = package.model_dump(mode='json')
    print(f'   JSON dump vars: {dump_json["vars"]}')
    for name, value in dump_json['vars'].items():
        print(f'   {name}: {value} (type: {type(value).__name__})')

    # With mode='python'
    dump_python = package.model_dump(mode='python')
    print(f'   Python dump vars: {dump_python["vars"]}')
    for name, value in dump_python['vars'].items():
        print(f'   {name}: {value} (type: {type(value).__name__})')

    # Test model_to_yaml
    print('\n6. model_to_yaml result:')
    yaml_output = model_to_yaml(package)
    print('   YAML output (first 10 lines):')
    lines = yaml_output.split('\n')
    for i, line in enumerate(lines[:10]):
        print(f'   {i+1:2d}: {line}')

    # Parse the YAML output back
    yaml_content_from_output = '\n'.join(lines[2:])  # Skip schema comment
    parsed_back = yaml.safe_load(yaml_content_from_output)
    print(f'\n   Parsed back vars: {parsed_back["vars"]}')
    for name, value in parsed_back['vars'].items():
        print(f'   {name}: {value} (type: {type(value).__name__})')


def test_pydantic_field_behavior():
    """Test how Pydantic handles the vars field specifically."""
    print('\n\n=== Testing Pydantic Field Behavior ===\n')

    # Create a simple model to test Dict[str, Primitive] behavior
    class TestModel(BaseModel):
        vars: Dict[str, Primitive]

    # Test with direct Python values
    print('1. Direct Python values:')
    test_model = TestModel(
        vars={
            'bool_true': True,
            'bool_false': False,
            'int_val': 42,
            'float_val': 3.14,
            'str_val': 'hello',
        }
    )
    print(f'   vars: {test_model.vars}')
    for name, value in test_model.vars.items():
        print(f'   {name}: {value} (type: {type(value).__name__})')

    # Test with YAML-loaded values
    print('\n2. YAML-loaded values:')
    yaml_data = {
        'vars': {
            'bool_true': True,
            'bool_false': False,
            'int_val': 42,
            'float_val': 3.14,
            'str_val': 'hello',
        }
    }
    test_model2 = TestModel(**yaml_data)
    print(f'   vars: {test_model2.vars}')
    for name, value in test_model2.vars.items():
        print(f'   {name}: {value} (type: {type(value).__name__})')

    # Test model_dump with different modes
    print('\n3. model_dump modes:')

    regular_dump = test_model.model_dump()
    print(f'   Regular: {regular_dump["vars"]}')
    for name, value in regular_dump['vars'].items():
        print(f'   {name}: {value} (type: {type(value).__name__})')

    json_dump = test_model.model_dump(mode='json')
    print(f'   JSON: {json_dump["vars"]}')
    for name, value in json_dump['vars'].items():
        print(f'   {name}: {value} (type: {type(value).__name__})')


def test_specific_package_creation():
    """Test creating a Package specifically like in the failing test."""
    print('\n\n=== Testing Specific Package Creation ===\n')

    # Create package like in the test
    package = Package(
        name='test-problem',
        timeLimit=1000,
        memoryLimit=256,
        vars={
            'bool_true': True,
            'bool_false': False,
        },
    )

    print('1. Direct Package creation:')
    print(f'   vars: {package.vars}')
    for name, value in package.vars.items():
        print(f'   {name}: {value} (type: {type(value).__name__})')

    print('\n2. expanded_vars:')
    expanded = package.expanded_vars
    print(f'   expanded: {expanded}')
    for name, value in expanded.items():
        print(f'   {name}: {value} (type: {type(value).__name__})')


def test_sample_model_vs_package():
    """Compare SampleModel behavior with Package behavior."""
    print('\n\n=== Testing SampleModel vs Package ===\n')

    # Create the same SampleModel as in the test
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

    sample_model = SampleModel(
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

    package_model = Package(
        name='test-problem',
        timeLimit=1000,
        memoryLimit=256,
        vars={
            'bool_true': True,
            'bool_false': False,
        },
    )

    print('1. SampleModel boolean fields:')
    sample_json = sample_model.model_dump(
        mode='json', exclude_unset=True, exclude_none=True
    )
    print(
        f'   is_active: {sample_json["is_active"]} (type: {type(sample_json["is_active"]).__name__})'
    )
    print(
        f'   has_premium: {sample_json["has_premium"]} (type: {type(sample_json["has_premium"]).__name__})'
    )

    print('\n2. Package vars field:')
    package_json = package_model.model_dump(
        mode='json', exclude_unset=True, exclude_none=True
    )
    print(f'   vars: {package_json["vars"]}')
    for name, value in package_json['vars'].items():
        print(f'   {name}: {value} (type: {type(value).__name__})')

    print('\n3. Primitive type annotation:')
    print(f'   Primitive type: {Primitive}')

    # Test a model with Dict[str, bool] vs Dict[str, Primitive]
    print('\n4. Comparing Dict[str, bool] vs Dict[str, Primitive]:')

    class BoolDictModel(BaseModel):
        bools: Dict[str, bool]

    class PrimitiveDictModel(BaseModel):
        prims: Dict[str, Primitive]

    bool_model = BoolDictModel(bools={'bool_true': True, 'bool_false': False})
    prim_model = PrimitiveDictModel(prims={'bool_true': True, 'bool_false': False})

    bool_json = bool_model.model_dump(mode='json')
    prim_json = prim_model.model_dump(mode='json')

    print('   Dict[str, bool]:')
    for name, value in bool_json['bools'].items():
        print(f'     {name}: {value} (type: {type(value).__name__})')

    print('   Dict[str, Primitive]:')
    for name, value in prim_json['prims'].items():
        print(f'     {name}: {value} (type: {type(value).__name__})')


if __name__ == '__main__':
    test_yaml_loading()
    test_pydantic_field_behavior()
    test_specific_package_creation()
    test_sample_model_vs_package()
