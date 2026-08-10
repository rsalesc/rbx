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


def _lift(namespace: Dict[str, Any], vars: Vars, key: str) -> Dict[str, Any]:
    """Bind a var block's keys into the namespace that contains it (#630).

    ``\\VAR{N.max}`` is shorthand for ``\\VAR{vars.N.max}``. The real namespace
    keys are merged last so they win: ``RESERVED_STATEMENT_VAR_NAMES`` already
    rejects a colliding var name at load time, and this ordering means a
    namespace key added *without* reserving its name loses the shorthand rather
    than being shadowed by user data.

    ``JinjaDictWrapper.from_dict`` rebuilds dotted keys into nested wrappers, so
    the lifted entries carry their own prefix -- ``\\VAR{N.typo}`` still reports
    ``"N.typo" was not found in "vars"``.
    """
    wrapper = _wrap(vars, key)
    return {**wrapper, **namespace, 'vars': wrapper}


class GroupView:
    """A testcase group as seen by a statement template.

    Attribute access proxies to the underlying ``TestcaseGroup`` model
    (``g.name``, ``g.score``, ...), with one deliberate exception: ``vars`` is
    the **resolved** var set for the group (package vars with that group's
    overrides applied), not the raw override block declared on the model.

    That distinction is the whole point. A subtasks table reads
    ``g.vars.AB.max`` for *every* group; if this exposed the raw override, every
    group that does not override ``AB.max`` would render a blank instead of the
    inherited value — the silent degradation per-group vars exist to remove.

    The group's resolved vars are also bound directly onto the view, so
    ``g.N.max`` is shorthand for ``g.vars.N.max`` (#630). Model fields win over
    the shorthand; ``RESERVED_STATEMENT_VAR_NAMES`` rejects a var named after
    one of them before a render ever sees it.

    The raw override block is not part of the template surface: ``g.vars`` is
    always the resolved set. It is not *inaccessible* — rbx renders with a plain
    ``jinja2.Environment``, not a sandboxed one, so a template that deliberately
    reaches for ``g._group.vars`` still gets the raw model. Nothing degrades
    silently through that path, and closing it would cost more complexity than
    the (non-)threat is worth.
    """

    def __init__(self, group: Any, vars: Vars):
        self._group = group
        self.vars = _wrap(vars, f'groups.{group.name}.vars')

    def __getattr__(self, name: str) -> Any:
        # Guard dunders so copy/pickle probes do not recurse through the proxy.
        if name.startswith('__') and name.endswith('__'):
            raise AttributeError(name)
        try:
            return getattr(self._group, name)
        except AttributeError:
            # Group var shorthand (#630): `g.N.max` == `g.vars.N.max`. Model
            # fields win; a miss returns the wrapper's strict undefined, which
            # carries the `groups.<name>.vars` hint.
            return self.vars[name]

    def __repr__(self) -> str:
        return f'GroupView({self._group!r})'


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
    blocks: Dict[str, str] = dataclasses.field(default_factory=dict)

    def namespace(self) -> Dict[str, Any]:
        """The ``contest`` template namespace: ``title``/``vars`` (always) plus
        ``blocks`` when present.

        Contest metadata beyond the title -- a date, a location -- is contest
        ``vars``, reachable as ``\\VAR{contest.date}`` through the shorthand
        (#630). The schema carried dedicated ``date``/``location`` fields until
        then, but nothing read them: every preset and template already used vars.
        """
        res: Dict[str, Any] = {
            'title': self.title,
        }
        if self.blocks:
            res['blocks'] = self.blocks
        return _lift(res, self.vars, 'contest.vars')


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
            'params': _wrap(self.params, 'params'),
            'blocks': self.blocks,
        }
        if self.short_name is not None:
            res['short_name'] = self.short_name
        if self.import_dir is not None:
            res['import_dir'] = self.import_dir
        if self.import_file is not None:
            res['import_file'] = self.import_file
        return _lift(res, self.vars, 'vars')


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
            'contest': contest.namespace(),
            'problem': problem.namespace(),
        }
    )
    return _lift(res, problem.vars, 'vars')


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
            'contest': contest.namespace(),
            'problems': [problem.namespace() for problem in problems],
        }
    )
    return _lift(res, contest.vars, 'vars')
