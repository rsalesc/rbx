#!/usr/bin/env python3
"""Test script to check if Union type order affects boolean serialization."""

from typing import Dict, Union

from pydantic import BaseModel

# Define Union types at module level to avoid linter errors
PrimitiveOriginal = Union[str, int, float, bool]
PrimitiveBoolFirst = Union[bool, str, int, float]
PrimitiveBoolBeforeFloat = Union[str, int, bool, float]


def test_union_order():
    """Test different Union type orders to see their effect on serialization."""

    print('=== Testing Union Type Order Effect ===\n')

    class ModelOriginal(BaseModel):
        vars: Dict[str, PrimitiveOriginal]

    class ModelBoolFirst(BaseModel):
        vars: Dict[str, PrimitiveBoolFirst]

    class ModelBoolBeforeFloat(BaseModel):
        vars: Dict[str, PrimitiveBoolBeforeFloat]

    test_data = {
        'vars': {
            'bool_true': True,
            'bool_false': False,
            'int_val': 42,
            'float_val': 3.14,
            'str_val': 'hello',
        }
    }

    # Test all three models
    models = [
        ('Original (str, int, float, bool)', ModelOriginal),
        ('Bool First (bool, str, int, float)', ModelBoolFirst),
        ('Bool Before Float (str, int, bool, float)', ModelBoolBeforeFloat),
    ]

    for name, ModelClass in models:
        print(f'{name}:')
        model = ModelClass(**test_data)

        # Test regular dump
        regular_dump = model.model_dump()
        print(f"  Regular dump vars: {regular_dump['vars']}")
        for var_name, value in regular_dump['vars'].items():
            print(f'    {var_name}: {value} (type: {type(value).__name__})')

        # Test JSON mode dump
        json_dump = model.model_dump(mode='json')
        print(f"  JSON dump vars: {json_dump['vars']}")
        for var_name, value in json_dump['vars'].items():
            print(f'    {var_name}: {value} (type: {type(value).__name__})')

        print()


def test_direct_union_behavior():
    """Test how Union types behave directly."""
    print('=== Testing Direct Union Behavior ===\n')

    class TestOriginal(BaseModel):
        value: PrimitiveOriginal

    class TestBoolFirst(BaseModel):
        value: PrimitiveBoolFirst

    # Test with boolean values
    test_values = [True, False, 1, 0, 1.0, 0.0, 'true', 'false']

    for test_val in test_values:
        print(f'Testing value: {test_val} (type: {type(test_val).__name__})')

        # Original order
        try:
            model_orig = TestOriginal(value=test_val)
            regular_orig = model_orig.model_dump()
            json_orig = model_orig.model_dump(mode='json')
            print(
                f"  Original - Regular: {regular_orig['value']} ({type(regular_orig['value']).__name__})"
            )
            print(
                f"  Original - JSON: {json_orig['value']} ({type(json_orig['value']).__name__})"
            )
        except Exception as e:
            print(f'  Original - Error: {e}')

        # Bool first order
        try:
            model_bool = TestBoolFirst(value=test_val)
            regular_bool = model_bool.model_dump()
            json_bool = model_bool.model_dump(mode='json')
            print(
                f"  BoolFirst - Regular: {regular_bool['value']} ({type(regular_bool['value']).__name__})"
            )
            print(
                f"  BoolFirst - JSON: {json_bool['value']} ({type(json_bool['value']).__name__})"
            )
        except Exception as e:
            print(f'  BoolFirst - Error: {e}')

        print()


if __name__ == '__main__':
    test_union_order()
    test_direct_union_behavior()
