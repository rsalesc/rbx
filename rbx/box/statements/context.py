"""Statements v2 namespaced template context (design §4, issue #561).

v1 collapsed everything into one merged ``vars``. v2 keeps three sources
distinct and unmerged:

- ``params`` — *this statement's* own params.
- ``vars`` — the problem/package vars (problem renders) or contest vars
  (contest renders).
- ``contest`` — ``title`` / ``location`` / ``date`` / ``contest.vars`` (always
  present; populated with neutral empty defaults in the contest-less bundled-default
  fallback — S15/#571).

Plus per-iteration handles for the overlay join: ``problem.import_dir`` /
``problem.import_file`` (the ``\\subimport`` handle for a problem in the contest
doc) and the ``sample.*`` handles (§6.3, populated by the sample stager).

The dataclasses here take primitive inputs (already-expanded var dicts, a title
string, resolved limits) rather than the heavy ``Package``/``Statement``
models, so context assembly is pure and unit-testable. The orchestration layer
(``build_statements`` / ``build_contest_statements``) extracts those primitives.
"""

import dataclasses
from typing import Any, Dict, List, Optional

from rbx.box.fields import Vars
from rbx.box.statements.latex_jinja import (
    JinjaDictGetter,
    JinjaDictWrapper,
    JinjaGroupsGetter,
)


@dataclasses.dataclass
class StatementCodeLanguage:
    id: str
    name: str
    command: str


def _wrap(vars: Vars, key: str) -> JinjaDictWrapper:
    return JinjaDictWrapper.from_dict(dict(vars or {}), wrapper_key=key)


@dataclasses.dataclass
class SampleHandle:
    """Per-sample handles exposed to templates (design §4/§6.3).

    Paths are anchored differently on purpose: ``input``/``output`` are
    **root-relative** for verbatim I/O (``\\VerbatimInput`` ignores the
    ``\\subimport`` base), while ``dir``/``explanation_file`` are
    **import-base-relative** for ``\\subimport`` of the explanation (§6.4).
    """

    index: int
    input: str
    output: Optional[str] = None
    dir: Optional[str] = None
    explanation_file: Optional[str] = None
    explanation: Optional[str] = None
    has_output: bool = True
    interaction: Optional[Any] = None


@dataclasses.dataclass
class ContestRenderContext:
    """The ``contest`` namespace, always available."""

    title: str
    vars: Vars = dataclasses.field(default_factory=dict)
    params: Vars = dataclasses.field(default_factory=dict)
    location: Optional[str] = None
    date: Optional[str] = None
    blocks: Dict[str, str] = dataclasses.field(default_factory=dict)

    def namespace(self) -> Dict[str, Any]:
        """The ``contest`` template namespace: ``title``/``vars`` (always) plus
        ``location``/``date``/``blocks`` when present."""
        res: Dict[str, Any] = {
            'title': self.title,
            'vars': _wrap(self.vars, 'contest.vars'),
        }
        if self.location is not None:
            res['location'] = self.location
        if self.date is not None:
            res['date'] = self.date
        if self.blocks:
            res['blocks'] = self.blocks
        return res


@dataclasses.dataclass
class ProblemRenderContext:
    """The ``problem`` namespace for one problem (standalone or a join member)."""

    title: str
    vars: Vars = dataclasses.field(default_factory=dict)
    params: Vars = dataclasses.field(default_factory=dict)
    short_name: Optional[str] = None
    limits: Any = None
    profiles: Dict[str, Any] = dataclasses.field(default_factory=dict)
    groups: Dict[str, Any] = dataclasses.field(default_factory=dict)
    samples: List[SampleHandle] = dataclasses.field(default_factory=list)
    import_dir: Optional[str] = None
    import_file: Optional[str] = None
    blocks: Dict[str, str] = dataclasses.field(default_factory=dict)

    def namespace(self) -> Dict[str, Any]:
        """The ``problem`` template namespace: title/limits/profiles/groups/
        samples/blocks plus its own ``vars``/``params`` (aliased here so the join
        document can reach a member problem's vars), and the
        ``short_name``/``import_dir``/``import_file`` handles when set."""
        res: Dict[str, Any] = {
            'title': self.title,
            'limits': self.limits,
            'profiles': JinjaDictGetter('profiles', **self.profiles),
            'groups': JinjaGroupsGetter('groups', dict(self.groups)),
            'samples': self.samples,
            'vars': _wrap(self.vars, 'vars'),
            'params': _wrap(self.params, 'params'),
            'blocks': self.blocks,
        }
        if self.short_name is not None:
            res['short_name'] = self.short_name
        if self.import_dir is not None:
            res['import_dir'] = self.import_dir
        if self.import_file is not None:
            res['import_file'] = self.import_file
        return res


def _common(lang: str, languages: List[StatementCodeLanguage]) -> Dict[str, Any]:
    return {
        'lang': lang,
        'languages': languages,
        'keyed_languages': {language.id: language for language in languages},
    }


def problem_jinja_kwargs(
    *,
    lang: str,
    languages: List[StatementCodeLanguage],
    problem: ProblemRenderContext,
    contest: ContestRenderContext,
) -> Dict[str, Any]:
    """Template context for a problem render (standalone full doc or a join
    fragment): top-level ``params``/``vars``/``contest`` are distinct, with the
    ``problem`` namespace carrying its own handles."""
    res = _common(lang, languages)
    res.update(
        {
            'params': _wrap(problem.params, 'params'),
            'vars': _wrap(problem.vars, 'vars'),
            'contest': contest.namespace(),
            'problem': problem.namespace(),
        }
    )
    return res


def contest_jinja_kwargs(
    *,
    lang: str,
    languages: List[StatementCodeLanguage],
    contest: ContestRenderContext,
    problems: List[ProblemRenderContext],
) -> Dict[str, Any]:
    """Template context for the joining contest document: ``params`` is the
    contest statement's own params, ``vars`` is the contest vars, and
    ``problems`` is the list of per-problem namespaces."""
    res = _common(lang, languages)
    res.update(
        {
            'params': _wrap(contest.params, 'params'),
            'vars': _wrap(contest.vars, 'vars'),
            'contest': contest.namespace(),
            'problems': [problem.namespace() for problem in problems],
        }
    )
    return res
