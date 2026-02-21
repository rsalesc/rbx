"""Factories to instantiate Agents for wizard tasks."""

from __future__ import annotations

import functools

from agents import Agent

from rbx.box.wizard.supported_models import get_model_settings


@functools.cache
def create_icpc_problem_reviewer(model_name: str) -> Agent:
    """Create an Agent for ICPC problem review."""

    settings = get_model_settings(model_name)
    return Agent(
        name='ICPCProblemReviewer',
        instructions=(
            'You are an expert in reviewing ICPC problem statements and their tooling. '
            'You analyze statements, checkers, and validators to ensure consistency. '
            'Be concise, output Markdown with bullet points and headings, and reference exact code line numbers when needed.'
        ),
        model=model_name,
        model_settings=settings,
    )


@functools.cache
def create_icpc_statement_language_reviewer(model_name: str) -> Agent:
    """Create an Agent focused on statement language review."""

    settings = get_model_settings(model_name)
    return Agent(
        name='ICPCStatementLanguageReviewer',
        instructions=(
            'You are an expert programming contest statement reviewer focusing solely on language quality. '
            'Be concise, focus on the language itself, and include textual snippets to cite the issues you found, '
            'along a suggestion for improvement.'
            'Focus on errors (grammar, spelling, typos, etc.), not on stylistic choices. Consider '
            'the language itself (e.g., use of English, Portuguese, etc.), and categorize the issues '
            'so a human can review them easily and fix them.'
            'Output in Markdown format.'
        ),
        model=model_name,
        model_settings=settings,
    )
