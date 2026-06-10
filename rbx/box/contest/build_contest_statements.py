"""Contest statement building (statements v2, design §6.2, issue #566).

Assembles the recursive overlay and joins the problems via ``\\subimport``:

- contest chrome is overlaid at the shared root;
- each problem is staged isolated under ``.problems/<SHORT>/`` and rendered with
  the contest's ``contestProblemTemplate`` into a ``statement.tex`` *fragment*;
- the contest ``file`` template is rendered with the ``problems`` list and
  ``\\subimport``s each fragment via its ``import_dir`` / ``import_file`` handles;
- the whole overlay is compiled from the root, so paths stay portable.

``documents`` (infosheets etc.) are emitted with :func:`build_document` — they
never join on problems.
"""

import pathlib
import shutil
import typing
from typing import Any, Dict, List, Optional, Tuple

import typer

from rbx import console
from rbx.box import cd, limits_info, naming, package, package_utils
from rbx.box.contest.contest_package import (
    find_contest,
    get_contest_build_path,
    get_contest_statements_build_path,
)
from rbx.box.contest.schema import Contest, ContestProblem, ContestStatement, Document
from rbx.box.exception import RbxException
from rbx.box.formatting import href
from rbx.box.sanitizers import issue_stack
from rbx.box.sanitizers.issue_stack import Issue
from rbx.box.statements import engine, overlay, render, resolver
from rbx.box.statements.build_statements import (
    get_environment_languages_for_statement,
)
from rbx.box.statements.context import (
    ContestRenderContext,
    ProblemRenderContext,
    contest_jinja_kwargs,
)
from rbx.box.statements.overlay import problem_overlay_dir
from rbx.box.statements.schema import BaseStatement, StatementType
from rbx.box.testcase_sample_utils import get_statement_samples


class StatementBuildIssue(Issue):
    def __init__(self, problem: ContestProblem):
        self.problem = problem

    def get_overview_section(self) -> Optional[Tuple[str, ...]]:
        return ('statement',)

    def get_overview_message(self) -> str:
        return f'Error building statement for problem [item]{self.problem.short_name}[/item].'


def get_statement_build_dir(statement: BaseStatement) -> pathlib.Path:
    return get_contest_statements_build_path() / statement.name  # type: ignore[attr-defined]


def _explanation_suffix(statement_type: StatementType) -> str:
    return '.md' if statement_type == StatementType.rbxMarkdown else '.tex'


def _contest_output_path(name: str, output_type: StatementType) -> pathlib.Path:
    path = (get_contest_build_path() / name).with_suffix(output_type.get_file_suffix())
    active_profile = limits_info.get_active_profile()
    if (
        active_profile is not None
        and limits_info.get_saved_limits_profile(active_profile) is not None
    ):
        path = path.with_stem(f'{path.stem}-{active_profile}')
    return path


def _fresh_dir(path: pathlib.Path) -> pathlib.Path:
    shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _problems_to_build(
    contest: Contest, problems_of_interest: Optional[List[ContestProblem]]
) -> List[ContestProblem]:
    if problems_of_interest is None:
        return list(contest.problems)
    wanted = {p.short_name for p in problems_of_interest}
    return [p for p in contest.problems if p.short_name in wanted]


async def build_statement(
    statement: ContestStatement,
    contest: Contest,
    problems_of_interest: Optional[List[ContestProblem]] = None,
    output_type: Optional[StatementType] = None,
    use_samples: bool = True,
    custom_vars: Optional[Dict[str, Any]] = None,
    install_tex: bool = False,
) -> pathlib.Path:
    output_type = output_type or StatementType.PDF
    custom_vars = custom_vars or {}
    languages = get_environment_languages_for_statement()
    contest_root = find_contest()

    if not statement.type.is_rbx():
        # A non-rbx contest statement is emitted like a document (no join).
        return _emit_simple(statement, contest, output_type, custom_vars)

    assert statement.file is not None
    overlay_root = _fresh_dir(get_statement_build_dir(statement))
    chrome_dir = (contest_root / statement.file).resolve().parent
    overlay.stage_chrome(overlay_root, chrome_dir)

    contest_ctx = ContestRenderContext(
        title=naming.get_contest_title(
            lang=statement.language, statement=statement, contest=contest
        ),
        vars=contest.expanded_vars,
        params=statement.expanded_vars,
        location=statement.location,
        date=statement.date,
    )

    problem_ctxs: List[ProblemRenderContext] = []
    for problem in _problems_to_build(contest, problems_of_interest):
        console.console.print(
            f'Building statement for problem [item]{problem.short_name}[/item]...'
        )
        try:
            problem_ctx = await _render_problem_fragment_async(
                statement,
                contest,
                problem,
                overlay_root,
                chrome_dir,
                contest_root,
                contest_ctx,
                languages,
                use_samples,
                custom_vars,
            )
        except (typer.Exit, RbxException):
            # Hard config/abort errors (e.g. a missing matching statement, or
            # conflicting explanation files) must surface, not be downgraded to a
            # per-problem skip.
            raise
        except Exception as exc:
            console.console.print(
                f'[error]Error building statement for problem '
                f'[item]{problem.short_name}[/item]: {exc}[/error]'
            )
            issue_stack.add_issue(StatementBuildIssue(problem))
            continue
        if problem_ctx is not None:
            problem_ctxs.append(problem_ctx)

    template_rel = (contest_root / statement.file).resolve().name
    contest_doc = render.render_contest_document(
        overlay_root,
        template_rel,
        lang=statement.language,
        languages=languages,
        contest=contest_ctx,
        problems=problem_ctxs,
    )

    if install_tex:
        from rbx.box.statements import latex

        tmp = overlay_root / '__install__.tex'
        tmp.write_bytes(contest_doc)
        latex.install_tex_packages(tmp, overlay_root)

    output_bytes = _finish(overlay_root, contest_doc, output_type)
    out_path = _contest_output_path(statement.name, output_type)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(output_bytes)
    console.console.print(
        f'[success]Contest statement [item]{statement.name}[/item] built for language '
        f'[item]{statement.language}[/item] at {href(out_path)}[/success]'
    )
    return out_path


async def _render_problem_fragment_async(
    contest_statement: ContestStatement,
    contest: Contest,
    problem: ContestProblem,
    overlay_root: pathlib.Path,
    chrome_dir: pathlib.Path,
    contest_root: pathlib.Path,
    contest_ctx: ContestRenderContext,
    languages,
    use_samples: bool,
    custom_vars: Dict[str, Any],
) -> Optional[ProblemRenderContext]:
    with cd.new_package_cd(problem.get_path()):
        package_utils.clear_package_cache()
        pkg = package.find_problem_package_or_die()
        problem_statement = resolver.select_problem_statement(
            contest_statement, pkg.expanded_statements, problem.short_name
        )

        assert problem_statement.file is not None
        problem_dir = (problem_statement.file).resolve().parent

        short = problem.short_name
        problem_root = problem_overlay_dir(overlay_root, short)
        root_prefix = f'.problems/{short}/'
        overlay.stage_join_problem(overlay_root, problem_dir, short)

        assert contest_statement.contestProblemTemplate is not None
        template_rel = engine.relativize_template(
            contest_root,
            chrome_dir,
            contest_statement.contestProblemTemplate,
            overlay_root,
        )

        problem_ctx = ProblemRenderContext(
            title=naming.get_problem_title(
                problem_statement.language, problem_statement, pkg
            ),
            vars={**pkg.expanded_vars, **custom_vars},
            params=problem_statement.expanded_params,
            short_name=short,
            limits=limits_info.get_limits_profile(
                profile=limits_info.get_active_profile()
            ),
            profiles=limits_info.get_available_limits_profiles(),
            groups={g.name: g for g in pkg.testcases},
            import_dir=root_prefix,
            import_file='statement',
        )

        samples = (
            await get_statement_samples(
                explanation_suffix=_explanation_suffix(problem_statement.type)
            )
            if use_samples
            else []
        )

        fragment = engine.render_problem_tex(
            render_root=overlay_root,
            problem_root=problem_root,
            root_prefix=root_prefix,
            template_rel=template_rel,
            content=problem_statement.file.read_bytes(),
            lang=problem_statement.language,
            languages=languages,
            problem=problem_ctx,
            contest=contest_ctx,
            samples=samples,
            use_samples=use_samples,
            statement_type=problem_statement.type,
        )
        (problem_root / 'statement.tex').write_bytes(fragment)
        return problem_ctx


def _finish(
    overlay_root: pathlib.Path, tex: bytes, output_type: StatementType
) -> bytes:
    if output_type == StatementType.PDF:
        return render.compile_pdf(overlay_root, tex)
    if output_type in (StatementType.TeX, StatementType.Markdown):
        return tex
    console.console.print(
        f'[error]statements v2 cannot yet emit contest output type '
        f'[item]{output_type}[/item].[/error]'
    )
    raise typer.Exit(1)


def _emit_simple(
    statement: BaseStatement,
    contest: Contest,
    output_type: StatementType,
    custom_vars: Dict[str, Any],
) -> pathlib.Path:
    """Emit a non-joining contest statement/document (jinja or static)."""
    name: str = statement.name  # type: ignore[attr-defined]
    assert statement.file is not None
    languages = get_environment_languages_for_statement()
    contest_root = find_contest()
    overlay_root = _fresh_dir(get_contest_statements_build_path() / name)
    chrome_dir = (contest_root / statement.file).resolve().parent
    overlay.stage_chrome(overlay_root, chrome_dir)
    source_rel = (contest_root / statement.file).resolve().name

    contest_ctx = ContestRenderContext(
        title=naming.get_contest_title(
            lang=statement.language, statement=None, contest=contest
        ),
        vars=contest.expanded_vars,
        params=statement.expanded_params,
        location=getattr(statement, 'location', None),
        date=getattr(statement, 'date', None),
    )

    if statement.type in (StatementType.JinjaTeX, StatementType.JinjaMarkdown):
        kwargs = contest_jinja_kwargs(
            lang=statement.language,
            languages=languages,
            contest=contest_ctx,
            problems=[],
        )
        content = render.render_jinja_document(overlay_root, source_rel, kwargs)
    else:
        content = (overlay_root / source_rel).read_bytes()

    if statement.type == StatementType.PDF:
        output_bytes = content
    elif output_type == StatementType.PDF:
        if statement.type in (StatementType.Markdown, StatementType.JinjaMarkdown):
            output_bytes = render.md_to_pdf(overlay_root, content)
        else:
            output_bytes = render.compile_pdf(overlay_root, content)
    else:
        output_bytes = content

    out_path = _contest_output_path(name, output_type)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(typing.cast(bytes, output_bytes))
    console.console.print(
        f'[success]Document [item]{name}[/item] built at {href(out_path)}[/success]'
    )
    return out_path


async def build_document(
    document: Document,
    contest: Contest,
    output_type: Optional[StatementType] = None,
    custom_vars: Optional[Dict[str, Any]] = None,
) -> pathlib.Path:
    output_type = output_type or StatementType.PDF
    return _emit_simple(document, contest, output_type, custom_vars or {})
