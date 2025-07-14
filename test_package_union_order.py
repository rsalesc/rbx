#!/usr/bin/env python3
"""Test if changing Primitive Union order fixes the Package boolean issue."""

from typing import Dict, Union

from pydantic import BaseModel

# Test with different Primitive definitions
PrimitiveOriginal = Union[str, int, float, bool]
PrimitiveBoolFirst = Union[bool, str, int, float]


class PackageOriginal(BaseModel):
    name: str
    timeLimit: int = 1000
    memoryLimit: int = 256
    vars: Dict[str, PrimitiveOriginal] = {}


class PackageBoolFirst(BaseModel):
    name: str
    timeLimit: int = 1000
    memoryLimit: int = 256
    vars: Dict[str, PrimitiveBoolFirst] = {}


def test_package_union_order():
    """Test Package models with different Union orders."""

    print('=== Testing Package with Different Primitive Union Orders ===\n')

    test_data = {
        'name': 'test-problem',
        'timeLimit': 1000,
        'memoryLimit': 256,
        'vars': {
            'bool_true': True,
            'bool_false': False,
        },
    }

    models = [
        ('Package with Original Union (str, int, float, bool)', PackageOriginal),
        ('Package with Bool-First Union (bool, str, int, float)', PackageBoolFirst),
    ]

    for name, PackageClass in models:
        print(f'{name}:')
        package = PackageClass(**test_data)

        # Test regular dump
        regular_dump = package.model_dump()
        print(f"  Regular dump vars: {regular_dump['vars']}")
        for var_name, value in regular_dump['vars'].items():
            print(f'    {var_name}: {value} (type: {type(value).__name__})')

        # Test JSON mode dump (the problematic one)
        json_dump = package.model_dump(mode='json')
        print(f"  JSON dump vars: {json_dump['vars']}")
        for var_name, value in json_dump['vars'].items():
            print(f'    {var_name}: {value} (type: {type(value).__name__})')

        print()


if __name__ == '__main__':
    test_package_union_order()
