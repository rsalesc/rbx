"""FastAPI application for robox.io webserver."""

from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel

from rbx import console
from rbx.box import package
from rbx.box.environment import VerificationLevel
from rbx.box.schema import CodeItem
from rbx.box.statements import build_statements
from rbx.box.statements.schema import Statement, StatementType
from rbx.box.wizard.llm_router import router as llm_router

origins = [
    'http://localhost',
    'http://localhost:3000',  # Replace with your client-side port
    'http://localhost:3001',  # Replace with your client-side port
]

# Create FastAPI instance
app = FastAPI(title='Robox.io Wizard', version='0.1.0')
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)


app.include_router(llm_router)


@app.get('/api/')
async def hello_world():
    """Return a Hello World JSON response."""
    return {'message': 'Hello World', 'status': 'success'}


class CodeResponse(BaseModel):
    path: str
    code: str
    language: Optional[str]


class CodeUpdateRequest(BaseModel):
    code: str


def _serve_code(code: CodeItem):
    if not code.path.is_file():
        raise HTTPException(status_code=404, detail='Code file not found')
    return CodeResponse(
        path=str(code.path), code=code.path.read_text(), language=code.language
    )


@app.get('/checker')
async def serve_checker():
    """Serve the checker file."""
    pkg = package.find_problem_package_or_die()
    if pkg.checker is None:
        raise HTTPException(status_code=404, detail='Checker not found')
    return _serve_code(pkg.checker)


@app.put('/checker')
async def update_checker(payload: CodeUpdateRequest):
    """Update the checker file."""
    pkg = package.find_problem_package_or_die()
    if pkg.checker is None:
        raise HTTPException(status_code=404, detail='Checker not found')
    pkg.checker.path.write_text(payload.code)
    return _serve_code(pkg.checker)


@app.get('/interactor')
async def serve_interactor():
    """Serve the checker file."""
    pkg = package.find_problem_package_or_die()
    if pkg.interactor is None:
        raise HTTPException(status_code=404, detail='Interactor not found')
    return _serve_code(pkg.interactor)


@app.put('/interactor')
async def update_interactor(payload: CodeUpdateRequest):
    """Update the interactor file."""
    pkg = package.find_problem_package_or_die()
    if pkg.interactor is None:
        raise HTTPException(status_code=404, detail='Interactor not found')
    pkg.interactor.path.write_text(payload.code)
    return _serve_code(pkg.interactor)


@app.get('/validator')
async def serve_validator():
    """Serve the validator file."""
    pkg = package.find_problem_package_or_die()
    if pkg.validator is None:
        raise HTTPException(status_code=404, detail='Validator not found')
    return _serve_code(pkg.validator)


@app.put('/validator')
async def update_validator(payload: CodeUpdateRequest):
    """Update the validator file."""
    pkg = package.find_problem_package_or_die()
    if pkg.validator is None:
        raise HTTPException(status_code=404, detail='Validator not found')
    pkg.validator.path.write_text(payload.code)
    return _serve_code(pkg.validator)


@app.get('/statement/{statement_name}')
async def serve_statement(statement_name: str):
    """Serve the statement file."""
    statement = package.get_statement_or_nil(statement_name)
    if statement is None:
        raise HTTPException(status_code=404, detail='Statement not found')
    build_path = build_statements.get_statement_build_path(statement, StatementType.PDF)
    return RedirectResponse(f'/package/{build_path}')


@app.get('/statement')
async def serve_main_statement():
    """Serve the main statement file."""
    pkg = package.find_problem_package_or_die()
    if not pkg.expanded_statements:
        raise HTTPException(status_code=404, detail='Statement not found')
    statement = pkg.expanded_statements[0]
    return RedirectResponse(f'/statement/{statement.name}')


@app.post('/statement/{statement_name}/build')
async def build_statement(statement_name: str):
    """Build the statement file."""
    statement = package.get_statement_or_nil(statement_name)
    if statement is None:
        raise HTTPException(status_code=404, detail='Statement not found')
    try:
        with console.console.capture() as capture:
            await build_statements.execute_build(
                verification=VerificationLevel.VALIDATE.value, names=[statement_name]
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=capture.get() + str(e)) from None


@app.get('/statement/{statement_name}/code')
async def serve_statement_code(statement_name: str):
    """Serve the statement code file."""
    statement = package.get_statement_or_nil(statement_name)
    if statement is None:
        raise HTTPException(status_code=404, detail='Statement not found')
    if statement.type != StatementType.rbxTeX:
        raise HTTPException(
            status_code=400, detail='Statement is not a rbxTeX statement'
        )
    return _serve_code(CodeItem(path=statement.path, language='latex'))


@app.put('/statement/{statement_name}/code')
async def update_statement_code(statement_name: str, payload: CodeUpdateRequest):
    """Update the statement code file."""
    statement = package.get_statement_or_nil(statement_name)
    if statement is None:
        raise HTTPException(status_code=404, detail='Statement not found')
    if statement.type != StatementType.rbxTeX:
        raise HTTPException(
            status_code=400, detail='Statement is not a rbxTeX statement'
        )
    statement.path.write_text(payload.code)
    return _serve_code(CodeItem(path=statement.path, language='latex'))


class StatementListResponse(BaseModel):
    statements: List[Statement]


@app.get('/statements')
async def serve_statements():
    """Serve the statements file."""
    pkg = package.find_problem_package_or_die()
    return StatementListResponse(statements=pkg.expanded_statements)


@app.get('/package/{path:path}')
async def serve_package_file(path: str):
    """Serve files from the current working directory.

    Args:
        path: The file path relative to the current working directory.

    Returns:
        FileResponse: The requested file.

    Raises:
        HTTPException: If the file doesn't exist or is outside the working directory.
    """
    # Get the current working directory
    cwd = Path.cwd()

    # Resolve the full path
    file_path = cwd / path

    # Resolve to absolute path to handle .. and symbolic links
    try:
        file_path = file_path.resolve()
    except Exception:
        raise HTTPException(status_code=404, detail='Invalid file path') from None

    # Security check: ensure the resolved path is within the current working directory
    try:
        file_path.relative_to(cwd)
    except ValueError:
        raise HTTPException(
            status_code=403,
            detail='Access denied: Path is outside the working directory',
        ) from None

    # Check if the file exists and is a file (not a directory)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail='File not found')

    if not file_path.is_file():
        raise HTTPException(status_code=404, detail='Path is not a file')

    # Serve the file
    return FileResponse(file_path)
