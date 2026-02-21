"""LLM endpoints router for the wizard service."""

from __future__ import annotations

from typing import Optional

from agents import Runner
from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from rbx.box.lang import code_to_lang
from rbx.box.wizard.agent_factories import (
    create_icpc_problem_reviewer,
    create_icpc_statement_language_reviewer,
)
from rbx.box.wizard.supported_models import DEFAULT_MODEL_NAME, SUPPORTED_MODELS

router = APIRouter(prefix='/llm', tags=['llm'])


class ModelsResponse(BaseModel):
    """Response for the models endpoint."""

    models: list[str] = Field(..., description='List of supported models')


@router.get('/models')
async def get_models() -> ModelsResponse:
    """Get the list of supported models."""

    return ModelsResponse(models=list(SUPPORTED_MODELS.keys()))


class ReviewRequest(BaseModel):
    """Input for the ICPC problem review endpoint."""

    statement: str = Field(..., description='Problem statement content')
    language: str = Field(..., description='Language of the statement, e.g., en, pt-br')
    validator: Optional[str] = Field(default=None, description='Validator source code')
    checker: Optional[str] = Field(default=None, description='Checker source code')
    interactor: Optional[str] = Field(
        default=None, description='Interactor source code'
    )
    model: Optional[str] = Field(
        default=None, description='Model to use for the review'
    )


## Removed structured ReviewResponse in favor of plain Markdown output


def _build_review_prompt(payload: ReviewRequest) -> str:
    """Create a concise, instruction-focused prompt for a Markdown review."""

    return (
        'You are an expert programming contest statement reviewer.\n\n'
        'Task: Review the problem statement (language: {language}), the checker (or interactor), and the validator.\n'
        'Identify whether constraints, limits, input/output formatting, and properties are consistent across the '
        'statement, checker, validator, and interactor.\n\n'
        'The statement is given in LaTeX. Pay attention to math expressions to identify constraints, and to the '
        'text itself to identify other issues.\n'
        'Example issues (non-exhaustive):\n'
        '- Constraints (bounds, ranges, etc.) not reflected equally in the statement and in testlib components.\n'
        '- Variables (vars.XXX) not used accordingly.\n\n'
        'Output format (Markdown):\n'
        '## ICPC Problem Review\n'
        '### Inconsistencies\n'
        '- List issues as bullet points. If none, write "None".\n'
        '### Validator issues\n'
        '- List issues as bullet points. If none, write "None".\n'
        '### Checker issues\n'
        '- List issues as bullet points. If none, write "None".\n'
        '### Interactor issues\n'
        '- List issues as bullet points. If none, write "None".\n'
        '- Include small code snippets when relevant.\n'
        '- When referring to code, explicitly mention file (checker/validator/interactor) and exact line numbers like `L12-L18`.\n\n'
        'Materials:\n'
        '[Statement]\n{statement}\n\n'
        '[Checker]\n{checker}\n\n'
        '[Interactor]\n{interactor}\n\n'
        '[Validator]\n{validator}\n'
    ).format(
        language=payload.language,
        statement=payload.statement,
        checker=payload.checker or 'N/A',
        validator=payload.validator or 'N/A',
        interactor=payload.interactor or 'N/A',
    )


@router.post('/review', response_class=PlainTextResponse)
async def review_endpoint(payload: ReviewRequest) -> PlainTextResponse:
    """Review an ICPC problem and return a Markdown report."""

    prompt = _build_review_prompt(payload)

    try:
        agent = create_icpc_problem_reviewer(payload.model or DEFAULT_MODEL_NAME)
        run_result = await Runner.run(agent, prompt)

        output = getattr(run_result, 'final_output', None)
        if isinstance(output, str):
            return PlainTextResponse(output, media_type='text/markdown')

        # Fallbacks
        if isinstance(run_result, str):
            return PlainTextResponse(run_result, media_type='text/markdown')

        text = str(output) if output is not None else str(run_result)
        return PlainTextResponse(text, media_type='text/markdown')
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from None


# ------------------------------
# Language-only statement review
# ------------------------------


class StatementLanguageReviewRequest(BaseModel):
    """Input for language-focused statement review.

    Only the statement text and its language code are required.
    """

    statement: str = Field(..., description='Problem statement content')
    language: str = Field(..., description='Language code, e.g., en, pt-br, es')
    model: Optional[str] = Field(
        default=None, description='Model to use for the review'
    )


def _build_language_review_prompt(payload: StatementLanguageReviewRequest) -> str:
    """Create a prompt that focuses purely on language quality.

    The assistant must analyze grammar, spelling/typos, orthography, clarity/style,
    terminology consistency, and major inconsistencies within the statement text.
    Output must be a Markdown string organized by categories with concise bullets
    and small snippet blocks for context.
    """

    return (
        'Review the following statement in the language "{language}". The lines of the statement are numbered from 1 to N '
        'starting from the next line, and the statement is given in LaTeX format.\n'
        '{statement}\n'
    ).format(language=code_to_lang(payload.language), statement=payload.statement)


@router.post('/review/statement', response_class=PlainTextResponse)
async def review_statement_language(
    payload: StatementLanguageReviewRequest,
) -> PlainTextResponse:
    """Review the statement's language and return a Markdown report."""

    prompt = _build_language_review_prompt(payload)

    try:
        agent = create_icpc_statement_language_reviewer(
            payload.model or DEFAULT_MODEL_NAME
        )
        run_result = await Runner.run(agent, prompt)

        output = getattr(run_result, 'final_output', None)
        if isinstance(output, str):
            return PlainTextResponse(output, media_type='text/markdown')

        # Fallbacks
        if isinstance(run_result, str):
            return PlainTextResponse(run_result, media_type='text/markdown')

        # If the model returns a structured object, convert to string
        text = str(output) if output is not None else str(run_result)
        return PlainTextResponse(text, media_type='text/markdown')
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from None
