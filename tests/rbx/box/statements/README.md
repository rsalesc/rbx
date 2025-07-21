# Statement Builders Tests

This directory contains comprehensive tests for the statement builders module (`rbx.box.statements.builders`).

## Test Structure

The test suite follows the testing principles defined in `testing.mdc`:

- **Behavior-focused**: Tests focus on the behavior and output of functions rather than implementation details
- **Minimal mocking**: Only mocks `pypandoc` and `latex` functions as specified, avoiding excessive mocking of private functions
- **Reusable fixtures**: Uses existing pytest fixtures and creates reusable ones for common test scenarios
- **Testdata usage**: Leverages the existing testdata infrastructure for assets

## Test Classes

### Core Components
- `TestStatementCodeLanguage`: Tests for language configuration dataclass
- `TestStatementBuilderContext`: Tests for builder context and jinja variable building
- `TestStatementSample`: Tests for sample creation from testcases, including interaction handling
- `TestStatementBuilderProblem`: Tests for problem builder item
- `TestStatementBuilderContest`: Tests for contest builder item

### Utility Functions
- `TestPrepareAssets`: Tests for asset preparation and copying
- `TestRenderJinja`: Tests for jinja template rendering
- `TestRenderJinjaBlocks`: Tests for block-based jinja rendering with explanations

### Builder Classes
- `TestJinjaTeXBuilder`: Tests for JinjaTeX to TeX conversion
- `TestrbxTeXBuilder`: Tests for rbxTeX to TeX conversion with templates
- `TestrbxMarkdownToTeXBuilder`: Tests for rbxMarkdown to rbxTeX conversion (mocks pypandoc)
- `TestTeX2PDFBuilder`: Tests for TeX to PDF conversion (uses existing latex mocks)

### Builder Lists
- `TestBuilderLists`: Tests for builder list constants and filtering

### Sample Types
- `TestExplainedStatementSample`: Tests for enhanced samples with explanations

### Integration Tests
- `TestIntegration`: End-to-end tests combining multiple builders in pipelines

## Key Testing Features

1. **Proper Mocking**: Only mocks external dependencies (`pypandoc.convert_text` and latex components)
2. **Realistic Data**: Uses proper Package and Statement objects with required fields
3. **Asset Testing**: Verifies asset copying and template injection work correctly
4. **Error Handling**: Tests failure scenarios like missing files and compilation errors
5. **Integration**: Tests complete pipelines from source formats to final outputs

## Running Tests

```bash
# Run all statement builder tests
python -m pytest tests/rbx/box/statements/test_builders.py

# Run specific test class
python -m pytest tests/rbx/box/statements/test_builders.py::TestJinjaTeXBuilder -v

# Run with coverage
python -m pytest tests/rbx/box/statements/test_builders.py --cov=rbx.box.statements.builders
```

All tests are designed to be fast and reliable, with appropriate use of temporary directories and proper cleanup. 