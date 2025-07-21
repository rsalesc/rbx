# Statement Builders Tests

This directory contains comprehensive tests for the statement builders module (`rbx.box.statements.builders`).

## Test Structure

The test suite follows the testing principles defined in `testing.mdc`:

- **Behavior-focused**: Tests focus on the behavior and output of functions rather than implementation details
- **Minimal mocking**: Only mocks `pypandoc` and `latex` functions as specified, avoiding excessive mocking of private functions
- **Reusable fixtures**: Uses existing pytest fixtures and creates reusable ones for common test scenarios
- **Testdata usage**: Leverages the existing testdata infrastructure for assets

## Test Files

### `test_builders.py`
Tests for the statement builders module (`rbx.box.statements.builders`).

#### Test Classes

**Core Components**
- `TestStatementCodeLanguage`: Tests for language configuration dataclass
- `TestStatementBuilderContext`: Tests for builder context and jinja variable building
- `TestStatementSample`: Tests for sample creation from testcases, including interaction handling
- `TestStatementBuilderProblem`: Tests for problem builder item
- `TestStatementBuilderContest`: Tests for contest builder item

**Utility Functions**
- `TestPrepareAssets`: Tests for asset preparation and copying
- `TestRenderJinja`: Tests for jinja template rendering
- `TestRenderJinjaBlocks`: Tests for block-based jinja rendering with explanations

**Builder Classes**
- `TestJinjaTeXBuilder`: Tests for JinjaTeX to TeX conversion
- `TestrbxTeXBuilder`: Tests for rbxTeX to TeX conversion with templates
- `TestrbxMarkdownToTeXBuilder`: Tests for rbxMarkdown to rbxTeX conversion (mocks pypandoc)
- `TestTeX2PDFBuilder`: Tests for TeX to PDF conversion (uses existing latex mocks)

**Builder Lists**
- `TestBuilderLists`: Tests for builder list constants and filtering

**Sample Types**
- `TestExplainedStatementSample`: Tests for enhanced samples with explanations

**Integration Tests**
- `TestIntegration`: End-to-end tests combining multiple builders in pipelines

### `test_build_statements.py`
Tests for the statement building functions (`rbx.box.statements.build_statements`).

#### Test Classes

**Environment Functions**
- `TestGetEnvironmentLanguagesForStatement`: Tests for environment language extraction with different command configurations

**Builder Selection**
- `TestGetBuilder`: Tests for builder retrieval from builder lists
- `TestGetImplicitBuilders`: Tests for automatic builder chain resolution
- `TestGetBuilders`: Tests for builder chain construction with explicit steps and configuration overrides

**Asset Management**
- `TestGetRelativeAssets`: Tests for asset resolution including glob patterns, relative paths, and error handling

**Statement Building**
- `TestBuildStatementBytes`: Tests for the core statement building function with various configurations
- `TestBuildStatement`: Tests for the complete file creation workflow

**Integration Tests**
- `TestBuildStatementsIntegration`: End-to-end tests using testing package fixtures

## Key Testing Features

1. **Proper Mocking**: Only mocks external dependencies (`pypandoc.convert_text` and latex components)
2. **Realistic Data**: Uses proper Package and Statement objects with required fields
3. **Asset Testing**: Verifies asset copying and template injection work correctly
4. **Error Handling**: Tests failure scenarios like missing files and compilation errors
5. **Integration**: Tests complete pipelines from source formats to final outputs
6. **Environment Isolation**: Uses proper mocking to avoid dependencies on system environment

## Running Tests

```bash
# Run all statement tests
python -m pytest tests/rbx/box/statements/ -v

# Run specific test file
python -m pytest tests/rbx/box/statements/test_build_statements.py -v

# Run specific test class
python -m pytest tests/rbx/box/statements/test_build_statements.py::TestGetBuilders -v

# Run with coverage
python -m pytest tests/rbx/box/statements/ --cov=rbx.box.statements
```

All tests are designed to be fast and reliable, with appropriate use of temporary directories and proper cleanup. The test suite provides comprehensive coverage of the statement building functionality while following the established testing principles of focusing on behavior over implementation details. 