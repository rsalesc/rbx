import pytest
from pydantic import ValidationError

from rbx.box.presets.schema import ReplacementMode, VariableExpansion


class TestVariableExpansionValidation:
    def test_prompt_mode_requires_prompt_field(self):
        with pytest.raises(ValidationError):
            VariableExpansion(
                needle='__NAME__',
                replacement=ReplacementMode.PROMPT,
                prompt=None,
            )

    def test_prompt_mode_accepts_prompt_field(self):
        ve = VariableExpansion(
            needle='__NAME__',
            replacement=ReplacementMode.PROMPT,
            prompt='Enter the problem name:',
        )
        assert ve.prompt == 'Enter the problem name:'

    def test_prompt_mode_is_default(self):
        ve = VariableExpansion(
            needle='__NAME__',
            prompt='Enter name:',
        )
        assert ve.replacement == ReplacementMode.PROMPT
