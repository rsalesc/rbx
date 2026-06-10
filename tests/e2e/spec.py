import copy
import pathlib
from typing import Annotated, Dict, List, Optional, Union

import yaml
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from rbx.box.schema import ExpectedOutcome


class _Forbid(BaseModel):
    model_config = ConfigDict(extra='forbid')


class SolutionMatcher(_Forbid):
    star: Optional[ExpectedOutcome] = None
    entries: Dict[str, ExpectedOutcome] = Field(default_factory=dict)

    @model_validator(mode='after')
    def _non_empty(self):
        if self.star is None and not self.entries:
            raise ValueError(
                'solution matcher must specify at least one of `*` or a '
                'per-group entry; an empty matcher asserts nothing'
            )
        return self


def _coerce_solution_matcher(value):
    if isinstance(value, SolutionMatcher):
        return value
    if isinstance(value, str):
        return SolutionMatcher(star=ExpectedOutcome(value), entries={})
    if isinstance(value, dict):
        star_raw = value.get('*')
        return SolutionMatcher(
            star=ExpectedOutcome(star_raw) if star_raw is not None else None,
            entries={k: ExpectedOutcome(v) for k, v in value.items() if k != '*'},
        )
    raise ValueError(f'invalid solution matcher: {value!r}')


class TestsMatcher(_Forbid):
    """Assertions about the output of ``rbx build`` under ``build/tests/``.

    Fields:

    * ``count``: optional total count of generated ``*.in`` files.
    * ``groups``: mapping of group name (the immediate subdirectory of
      ``build/tests/``) to expected ``*.in`` count.
    * ``exist``: literal paths under ``build/tests/`` that must exist
      after the step runs.
    * ``all_valid``: reserved for future enforcement of "every generated
      test passed validation". ``rbx build`` does not currently persist a
      structured per-testcase validation report on disk, so we cannot
      verify this matcher field. It is kept in the schema with default
      ``None`` so existing fixtures don't accidentally enable it; setting
      it explicitly raises ``NotImplementedError`` at check time. See
      ``docs/plans/2026-05-03-e2e-testing-strategy.md`` Task 8 notes.
    """

    # Disable pytest collection -- the ``Test`` prefix in the class name
    # is otherwise heuristically treated as a test class.
    __test__ = False

    count: Optional[int] = None
    groups: Dict[str, int] = Field(default_factory=dict)
    all_valid: Optional[bool] = None
    exist: List[str] = Field(default_factory=list)

    @model_validator(mode='after')
    def _non_empty(self):
        if (
            self.count is None
            and not self.groups
            and self.all_valid is None
            and not self.exist
        ):
            raise ValueError(
                'tests matcher must specify at least one of `count`, '
                '`groups`, `exist`, or `all_valid`; an empty matcher '
                'asserts nothing'
            )
        return self


class ZipMatcher(_Forbid):
    path: str
    entries: List[str]


class ZipFileMatcher(_Forbid):
    """Assert the *content* of named entries inside a zip.

    ``path`` is a glob locating the zip under the package root; ``entries`` maps
    a literal zip entry name to a matcher with the same substring/regex
    semantics as ``file_contains`` (a value wrapped in slashes and longer than
    two chars is a regex, otherwise a literal substring).
    """

    path: str
    entries: Dict[str, str]


class StatementExpect(_Forbid):
    """Substring assertions on the fields of a single uploaded Polygon statement.

    Each ``*_contains`` is a substring (or list of substrings) that must appear
    in the corresponding field of the captured ``save_statement`` payload.
    """

    name_contains: Union[str, List[str], None] = None
    legend_contains: Union[str, List[str], None] = None
    input_contains: Union[str, List[str], None] = None
    output_contains: Union[str, List[str], None] = None
    interaction_contains: Union[str, List[str], None] = None
    notes_contains: Union[str, List[str], None] = None


class PolygonUploadMatcher(_Forbid):
    """Assertions over the recording-fake capture written by ``package polygon -u``.

    ``dir`` is the capture directory relative to the package root (default
    ``.rbx/polygon_capture``; override when the upload ran in a subdirectory,
    e.g. ``A/.rbx/polygon_capture``). ``statements`` maps an uploaded-language
    key (e.g. ``english``) to per-field substring assertions.
    ``resources_present``/``resources_absent`` assert (by normalized name) which
    statement resources were / were not uploaded. ``resources_referenced_consistent``
    parses every ``\\includegraphics{...}`` across all uploaded statement fields
    and asserts each reference resolves to an uploaded resource.
    """

    dir: str = '.rbx/polygon_capture'
    statements: Dict[str, StatementExpect] = Field(default_factory=dict)
    resources_present: List[str] = Field(default_factory=list)
    resources_absent: List[str] = Field(default_factory=list)
    resources_referenced_consistent: Optional[bool] = None


class Expect(_Forbid):
    stdout_contains: Union[str, List[str], None] = None
    stdout_not_contains: Union[str, List[str], None] = None
    stderr_contains: Union[str, List[str], None] = None
    stdout_matches: Optional[str] = None
    files_exist: List[str] = Field(default_factory=list)
    files_absent: List[str] = Field(default_factory=list)
    file_contains: Dict[str, str] = Field(default_factory=dict)
    zip_contains: Optional[ZipMatcher] = None
    zip_not_contains: Optional[ZipMatcher] = None
    zip_file_contains: Optional[ZipFileMatcher] = None
    solutions: Optional[
        Dict[str, Annotated[SolutionMatcher, BeforeValidator(_coerce_solution_matcher)]]
    ] = None
    tests: Optional[TestsMatcher] = None
    polygon_upload: Optional[PolygonUploadMatcher] = None


class Step(_Forbid):
    cmd: str
    cwd: Optional[str] = None
    expect_exit: int = 0
    expect: Expect = Field(default_factory=Expect)


_ALLOWED_MARKERS = frozenset({'slow', 'docker', 'pdflatex'})


class Scenario(_Forbid):
    name: str
    description: Optional[str] = None
    markers: List[str] = Field(default_factory=list)
    # Name of a preset under ``rbx/resources/presets/<name>/``. When set, the
    # scenario's temp package is seeded at run time from that preset's
    # ``problem/`` package (dereferencing symlinks, skipping build cruft), so
    # the fixture dir itself need only contain ``e2e.rbx.yml``.
    seed_from_preset: Optional[str] = None
    steps: List[Step] = Field(default_factory=list)

    @field_validator('markers')
    @classmethod
    def _validate_markers(cls, v):
        bad = [m for m in v if m not in _ALLOWED_MARKERS]
        if bad:
            raise ValueError(
                f'unknown markers: {bad}; allowed: {sorted(_ALLOWED_MARKERS)}'
            )
        return v


class E2ESpec(_Forbid):
    scenarios: List[Scenario]

    @model_validator(mode='after')
    def _unique_scenario_names(self):
        names = [s.name for s in self.scenarios]
        if len(set(names)) != len(names):
            raise ValueError(f'duplicate scenario names: {names}')
        return self


def parse_spec(data: dict) -> E2ESpec:
    return E2ESpec.model_validate(copy.deepcopy(data))


def load_spec(path: pathlib.Path) -> E2ESpec:
    return parse_spec(yaml.safe_load(path.read_text()))
