import collections
import dataclasses
import json
import pathlib
import shutil
import typing
from typing import Dict, FrozenSet, List, Optional, Set, Tuple, Union

import typer

from rbx import console, utils
from rbx.box import environment, header, limits_info, package, timing_config
from rbx.box.dependencies import graph as deps_graph
from rbx.box.dependencies.amalgamation import AmalgamationError, amalgamate
from rbx.box.dependencies.scanner import DependencyKind
from rbx.box.generation_schema import GenerationTestcaseEntry
from rbx.box.packaging.moj import naming
from rbx.box.packaging.moj import statement as moj_statement
from rbx.box.packaging.moj import timing as moj_timing
from rbx.box.packaging.moj.extension import MojLanguageExtension
from rbx.box.packaging.moj.moj_language_utils import (
    get_emitted_moj_languages,
    get_moj_language_extension,
    get_moj_language_from_rbx_language,
    get_moj_template_name,
    get_rbx_language_from_moj_language,
    normalize_moj_language,
)
from rbx.box.packaging.moj.statement_assets import rasterize_pdf_assets
from rbx.box.packaging.packager import BasePackager, BuiltStatement
from rbx.box.schema import (
    CodeItem,
    ExpectedOutcome,
    ScoreType,
    Solution,
    TaskType,
    TimingMultipliers,
)
from rbx.box.statements import export
from rbx.box.statements.markdown_export import MojGateError
from rbx.box.statements.schema import (
    ConversionStep,
    ConversionType,
    Statement,
    StatementType,
    TexToPDF,
    rbxToTeX,
)
from rbx.config import get_default_app_path, get_testlib

# The package var the setter puts their name in. rbx has no first-class author field,
# and `vars` is where a problem already carries free-form metadata the statement can
# render (`\VAR{author}`), so MOJ's `author` file reads the same var rather than
# introducing a second place to say the same thing.
AUTHOR_VAR = 'author'

# MOJ hard-requires the file, so a package with no `vars.author` still gets a visible
# placeholder that keeps validate-problem.sh green until the setter fills it in on the
# server.
DEFAULT_AUTHOR = 'Unknown'

# `ULIMITS[-f]` in KB, and deliberately a **fixed, generous** number rather than the
# problem's `outputLimit`.
#
# MOJ applies this ulimit to the **compile** step, not only to the running solution --
# observed on the judge on 2026-08-21, packaging a problem whose `outputLimit` was
# 100 KB:
#
#     collect2: fatal error: ld terminated with signal 25 [File size limit exceeded]
#
# The linker could not write the executable, so *every* submission came back
# `Compilation Error` before reaching a single test. Any problem with a tight output
# limit was therefore unjudgeable on MOJ.
#
# One knob cannot serve both purposes: a compile needs megabytes, while a sane output
# limit is often a few hundred KB. Pinning it high is the side that fails safe -- the
# cost is that **MOJ no longer enforces the problem's `outputLimit`**, so a runaway
# solution is cut off here instead of at the setter's threshold. rbx still enforces
# `outputLimit` locally, and a solution that overruns it is a package bug the setter
# sees in `rbx run` long before MOJ would have said anything.
OUTPUT_ULIMIT_KB = 100 * 1024

# The group name rbx reserves for samples. MOJ requires them to be named `sample*`,
# so this group alone is exempt from the testset prefix.
SAMPLES_GROUP = 'samples'

# No title (MOJ injects an <h1> from the server-side display_title), no examples (MOJ
# injects them from tests/input/sample*), and no fenced code blocks (a fence trips
# validate-problem.sh's hand-written-example warning). The two headings are mandatory.
DUMMY_STATEMENT = """Enunciado ainda não disponível.

## Entrada

A descrever.

## Saída

A descrever.
"""

# Fallback compilation flags per bundled template, used when the rbx language's `moj`
# extension does not set `flags`.
DEFAULT_FLAGS = {
    'c': '-std=gnu11 -O2 -lm -static',
    'cpp': '-std=c++20 -O2 -lm -static',
}

# Suffixes the amalgamator can reduce to a single translation unit.
_AMALGAMATABLE_SUFFIXES = {'.c', '.cc', '.cpp', '.cxx'}

# The limits profile whose estimated time limits get pinned into `conf`. Named after
# the packager, as `rbx package boca` does with its own.
LIMITS_PROFILE = 'moj'


@dataclasses.dataclass(frozen=True)
class ProfilePinned:
    """Pin the limits to the `moj` limits profile. The default.

    What `rbx package moj` emits: `TLOVERRIDE[default]` plus a `TLOVERRIDE[<lang>]`
    for every language whose estimated limit differs from it. Requires the profile
    `rbx time -p moj` writes.
    """


@dataclasses.dataclass(frozen=True)
class JudgeCalibrated:
    """Let MOJ measure them. `rbx package moj --calibrate`.

    No `TLOVERRIDE` at all: the judge's own calibration decides, scaled by
    `TLMOD[calibrafactor]` = rbx's `acToTimeLimit`.
    """


@dataclasses.dataclass(frozen=True)
class ProbePinned:
    """Pin the limits a timing run measures under. What a probe package uploads.

    Deliberately *not* `ProfilePinned`, even though both end up emitting
    `TLOVERRIDE`: the numbers here are the ones **this run asked for**, not the
    ones the `moj` limits profile holds. `rbx time` measures in two phases and
    asks for a different shape in each (`timing.py`):

    - **Estimation** caps every accepted solution at one `inferenceTimeout`, so
      `default_ms` alone says it and there is no per-language entry at all.
    - **Validation** checks each solution expected to be too slow against
      `ceil(TL x timeLimitToTle)` for **its own language group**, so the limits
      genuinely differ per language and the probe has to be able to say so.

    Which is why this carries a mapping rather than the single number it did
    before the phases were split: a probe that could only pin one cap would have
    had to pick one of the validation limits and measure the other languages
    under a bound nobody asked for.

    `per_rbx_language_ms` is keyed by **rbx** language name -- what
    `solutions.TimelimitOverride` is keyed by -- and translated to MOJ ids by
    `MojPackager._probe_time_limits`, which is where the id spellings are already
    known. Pairs rather than a dict, so `frozen=True` is not a lie.
    """

    default_ms: int
    per_rbx_language_ms: Tuple[Tuple[str, int], ...] = ()
    # What this run submits, as a plural noun phrase, for the report line only.
    # Supplied by the caller because the packager cannot know it: it sees limits,
    # not phases, and "slow solutions" is true of the validation phase alone.
    measuring: str = 'solutions'

    def __post_init__(self) -> None:
        # The runner derives these from `ctx.timelimit_override`, exactly the kind
        # of value that arrives unset. `fmt_seconds` would happily emit `-1.500` or
        # `0.000`, and MOJ reads TLOVERRIDE with grep rather than evaluating it, so
        # the package would upload, calibrate, and TLE every single run -- with the
        # bad number visible only to whoever reads `conf`.
        for limit_ms in (self.default_ms, *(ms for _, ms in self.per_rbx_language_ms)):
            if limit_ms <= 0:
                raise ValueError(
                    f'A MOJ time limit must be a positive number of milliseconds, '
                    f'got `{limit_ms}`.'
                )
        languages = [language for language, _ in self.per_rbx_language_ms]
        if len(set(languages)) != len(languages):
            # Silently keeping one of them would pin a language to a limit the
            # caller did not choose, and nothing downstream could tell.
            raise ValueError(
                f'A probe package pins each language at most once, got `{languages}`.'
            )


# How a package settles its time limits. The packager refuses to guess between these,
# which is why it is a mode object rather than a defaulted number: each one carries a
# different precondition (an estimated profile / `timing.multipliers` / nothing at all).
TimingMode = Union[ProfilePinned, JudgeCalibrated, ProbePinned]

# The mode `rbx package moj` uses. A frozen dataclass with no fields carries no state,
# so one shared instance is as good as many -- and a default argument may not be a
# call (ruff B008).
DEFAULT_TIMING_MODE = ProfilePinned()


# The verdicts mojtools has a `STOPWHEN_*` bit for, in the order `conf` spells
# them. A set for membership and a tuple for emission, so the emitted block is
# ordered by mojtools' own convention rather than by whatever order a caller
# happened to build its request in -- an unstable order would re-fingerprint the
# package, and a re-fingerprinted package is an upload and a calibration.
HALT_VERDICT_ORDER = ('WA', 'TLE', 'RE')
HALT_VERDICTS = frozenset(HALT_VERDICT_ORDER)


@dataclasses.dataclass(frozen=True)
class ProbePackage:
    """A throwaway package uploaded to measure timings, never judged by students.

    Kept separate from `TimingMode` because "what limits" and "what is in the package
    / who may submit" are genuinely orthogonal: a probe package is defined by shipping
    only the model solution (`moj testrun` sends the timed source in the request body,
    so the rest never have to be there) and by whitelisting every language rbx may
    testrun rather than the languages it ships.
    """

    # The MOJ ids `.moj-meta.json` allows submissions in. The API rejects a submission
    # outside this list -- a testrun included -- so it must cover every language rbx
    # may time, including the slow and wrong solutions, which are never ACCEPTED by
    # construction and so would never make the usual accepted-solutions whitelist.
    # A tuple rather than a list, so `frozen=True` is not a lie: this really is
    # immutable and hashable, which a package cache key will want.
    submission_languages: Tuple[str, ...]

    # Which verdicts end a solution's run early, as `STOPWHEN_*` bits. The judge
    # is the only place this can be decided: a testrun has already run the whole
    # submission by the time rbx sees any of it, so the local abort gate has no
    # counterpart here (`MojRunner` declares `supports_abort=False`), and what
    # rbx would have stopped locally has to be stopped by the package instead.
    #
    # It is therefore the caller's rule, translated -- not a packaging
    # preference. `rbx time` aborts on a timeout and only a timeout, so it asks
    # for `{'TLE'}`; `rbx run --fail-fast` aborts on any non-accepted verdict, so
    # it asks for all three; a plain `rbx run` aborts on nothing, so it asks for
    # none and every test comes back with a real verdict.
    #
    # Defaulted to the timing rule, which is what every probe asked for before
    # `rbx run` had a `--runner` flag.
    halt_on: FrozenSet[str] = frozenset({'TLE'})

    def __post_init__(self) -> None:
        # Empty would *work*, in the permissive direction: `_write_moj_meta` omits an
        # empty `languages` and the server then preserves whatever the problem already
        # had. That is luck, not intent -- an empty list means the caller could not
        # enumerate a single testrunnable language, and the resulting package would
        # silently inherit some earlier run's whitelist.
        if not self.submission_languages:
            raise ValueError(
                'A probe package must whitelist at least one submission language: '
                'the MOJ API rejects a submission outside `.moj-meta.json`, a '
                'testrun included.'
            )
        unknown = sorted(self.halt_on - HALT_VERDICTS)
        if unknown:
            # mojtools reads `conf` with grep, so a misspelled bit is not an
            # error there -- it is a line nothing ever matches, and a run that
            # silently fails to stop where the caller asked it to.
            raise ValueError(
                f'A probe package can only halt on {sorted(HALT_VERDICTS)}, got '
                f'`{unknown}`.'
            )


def _resolved_multipliers() -> Optional[TimingMultipliers]:
    """The problem's timing multipliers, or None when it estimates with a formula."""
    strategy = timing_config.resolve_strategy(
        environment.get_environment().timing,
        package.find_problem_package_or_die().timing,
    )
    if not strategy.uses_multipliers:
        return None
    return strategy.multipliers_or_die()


def _inference_timeout_ms() -> int:
    """The cap rbx enforced on a solution while estimating.

    Fed to `CALIBRATIONTL` so calibration waits at least as long as estimation did.
    Every strategy estimates under a cap, formula mode included.
    """
    return timing_config.resolve_inference_timeout(
        environment.get_environment().timing,
        package.find_problem_package_or_die().timing,
    )


def _ac_to_time_limit_or_die() -> float:
    """The ratio `--calibrate` hands MOJ as `TLMOD[calibrafactor]`.

    It only exists in multiplier mode: a problem estimating with a formula has no
    single ratio between the slowest accepted solution and the limit, so there is
    nothing to hand the judge and the setter has to pin the limits instead.
    """
    multipliers = _resolved_multipliers()
    if multipliers is None:
        console.console.print(
            '[error][item]--calibrate[/item] needs an [item]acToTimeLimit[/item], but '
            'this problem estimates time limits with a formula.[/error]\n'
            '[error]MOJ scales the measured runtime of the accepted solutions by a '
            'single ratio, which a formula does not define.[/error]\n'
            '[error]Set [item]timing.multipliers[/item] in [item]env.rbx.yml[/item], '
            f'or run [item]rbx time -p {LIMITS_PROFILE}[/item] and package without '
            '[item]--calibrate[/item] to pin the limits instead.[/error]'
        )
        raise typer.Exit(1)
    return multipliers.acToTimeLimit


def _require_limits_profile() -> None:
    """Fail unless the `moj` profile exists to pin the time limits from.

    MOJ is the one target where rbx does not own the time limit, so the two ways to
    settle it are made explicit rather than defaulted: the estimated profile pins
    them, or `--calibrate` leaves them to the judge.
    """
    if limits_info.get_saved_limits_profile(LIMITS_PROFILE) is not None:
        return
    console.console.print(
        f'[error]Required limits profile [item]{LIMITS_PROFILE}[/item] not '
        'found.[/error]\n'
        f'[error]Run [item]rbx time -p {LIMITS_PROFILE}[/item] to estimate the '
        'time limits this package should pin, or pass [item]--calibrate[/item] to '
        'let MOJ measure them on the judge machine.[/error]'
    )
    raise typer.Exit(1)


def check_timing_setup(timing_mode: TimingMode) -> None:
    """Reject a packaging run whose time limits cannot be decided, before building.

    Called from the CLI, so a setter who has not run `rbx time` hears about it
    before a full build rather than after one. The same failures are checked again
    while `conf` is written, which is what covers every other caller.

    `ProbePinned` has nothing to check: it carries its own numbers, and consults
    neither the `moj` profile nor `timing.multipliers`.

    Every mode is named explicitly, with no fall-through: this and
    `_time_limit_lines` are the two places that decide what a mode *means*, and a
    fourth mode silently inheriting a different default in each would be exactly the
    guessing the union exists to prevent.
    """
    if isinstance(timing_mode, ProbePinned):
        return
    if isinstance(timing_mode, ProfilePinned):
        _require_limits_profile()
        return
    if isinstance(timing_mode, JudgeCalibrated):
        _ac_to_time_limit_or_die()
        if limits_info.get_saved_limits_profile(LIMITS_PROFILE) is not None:
            console.console.print(
                f'[warning]A [item]{LIMITS_PROFILE}[/item] limits profile exists, but '
                '[item]--calibrate[/item] hands the time limits to MOJ, so its '
                'estimated limits are not pinned into the package.[/warning]'
            )
        return
    typing.assert_never(timing_mode)


class MojPackager(BasePackager):
    """Packager for the MOJ format as `mojtools` consumes it.

    Extends `BasePackager` directly and shares no code with BOCA. Two decisions
    shape everything else:

    - **Time limits go through `conf`, never `tl`.** MOJ measures the limit by
      running every `sols/good` solution and scaling by `TLMOD[calibrafactor]`, so
      `conf` carries the only limit knobs: by default rbx pins them there with
      `TLOVERRIDE` from the `moj` limits profile, and `--calibrate` leaves them to
      the judge. A remote timing run takes the third mode, `ProbePinned`. See
      `rbx.box.packaging.moj.timing`.
    - **A single-file checker.** MOJ's bridge compiles `scripts/checker.cpp` with only
      `testlib.h` reachable, so the checker is amalgamated rather than shipped with
      its headers.
    """

    def __init__(
        self,
        testcase_entries: List[GenerationTestcaseEntry],
        main_language: Optional[str] = None,
        timing_mode: TimingMode = DEFAULT_TIMING_MODE,
        probe: Optional[ProbePackage] = None,
        reference_only: bool = False,
    ):
        super().__init__(testcase_entries)
        # A MOJ package holds ONE statement, so the language is chosen here and
        # used for both the body and `display_title` -- see `_get_main_statement`.
        self.main_language = main_language
        # How the time limits are settled: pinned from the profile, measured by the
        # judge, or pinned to what a timing run asked for. See `_time_limit_lines`.
        self.timing_mode = timing_mode
        # Set only when this package exists to *measure* timings rather than to be
        # judged: it then ships only the model solution and whitelists the languages
        # rbx may testrun. See `ProbePackage`.
        self.probe = probe
        # Ship only the model solution, dropping the rest. A probe package does this
        # by construction; a setter asks for it with `rbx package moj
        # --reference-only`, to keep the calibration MOJ runs on upload short.
        # See `_solutions_to_ship`.
        self.reference_only = reference_only

        # The two axes are separate arguments because they are separate questions --
        # but of their product only one cell is legal. A probe pinned from the profile
        # would be measured under the limits of the *previous* estimate -- the very
        # thing this run exists to replace -- and a calibrated one under whatever the
        # judge decided, which rbx never sees. Neither is a package worth uploading,
        # so neither is constructible.
        if probe is not None and not isinstance(timing_mode, ProbePinned):
            raise ValueError(
                'A probe package must pin the limits the timing run asked for: it '
                'exists to measure solutions under limits rbx chose, and both '
                '`ProfilePinned` and `JudgeCalibrated` would measure them under '
                f'some other ones. Got `{type(timing_mode).__name__}`.'
            )

    @classmethod
    def name(cls) -> str:
        return 'moj'

    @classmethod
    def task_types(cls) -> List[TaskType]:
        # MOJ's interactive support uses its own arbiter protocol (test in argv[1],
        # last stderr line `WRONG <reason>`, FIFO driver), not a testlib interactor.
        # Interactive problems are not supported yet; it deserves its own design.
        return [TaskType.BATCH]

    # NOTE: `statement_types()` is overridden below ONLY to return nothing for a
    # probe package, which carries no statement at all. Every package a setter builds
    # keeps the default `[StatementType.PDF]` -- exactly as for `PolygonPackager`, the
    # other block-consuming packager. `statement_types` names the *output* a statement is
    # built into, and v2 can only emit pdf/tex/md (`build_statements._emit_output`);
    # `rbxTeX` is a *source* type and returning it fails the build outright. What
    # declares "I consume blocks, not a PDF" is `statement_export_params` below --
    # and the PDF build is what produces the artifacts it asks for, since both
    # externalization and demacro live inside `render.compile_pdf`. Asking for TeX
    # or Markdown output would skip that call entirely and leave no macros.json and
    # no externalized TikZ.

    def statement_types(self) -> List[StatementType]:
        # A probe package carries no statement (see `_write_statement`), so there is
        # nothing to build. This is what lets a runner call `package()` without
        # `run_packager` having built statements first -- and, if a probe ever does
        # go through `run_packager`, what stops it paying for a pdflatex run whose
        # output nobody will ever read.
        if self.probe is not None:
            return []
        return super().statement_types()

    def statement_export_params(self) -> List[ConversionStep]:
        # Declaring these is what makes `run_packager` build every statement with
        # TikZ externalized (so each figure becomes a PDF the bundle can place) and
        # macros extracted (so the blocks reduce to the Polygon TeX subset the
        # markdown converter expects). Without them the overlay carries no
        # blocks.sub.yml/macros.json and there is nothing to read. Mirrors
        # `PolygonPackager.statement_export_params`.
        #
        # Same decision as `statement_types` above: a probe consumes no blocks, so it
        # asks for none of the artifacts producing them.
        if self.probe is not None:
            return []
        return [
            rbxToTeX(type=ConversionType.rbxToTex, externalize=True),
            TexToPDF(type=ConversionType.TexToPDF, externalize=True, demacro=True),
        ]

    # -- metadata -------------------------------------------------------------

    def _get_main_statement(self) -> Optional[Statement]:
        """The single statement this package ships; `--language` picks it.

        Shared with `rbx tooling moj summary`, which reports the title a MOJ
        upload would carry without building anything -- see
        `moj_statement.get_main_statement`.
        """
        return moj_statement.get_main_statement(self.main_language)

    def _display_title(self) -> str:
        """MOJ's `display_title`, resolved from `_get_main_statement`."""
        return moj_statement.get_display_title(self.main_language)

    def _submission_languages(self) -> List[str]:
        """The MOJ ids to allow submissions in: the languages the environment
        declares, which are exactly the ones this package ships `scripts/` for.

        The whitelist answers "what may a student write this in", and that is a
        property of the environment (`env.rbx.yml`) -- the same place every other
        language decision in rbx comes from -- not of which solutions the setter
        happened to write. Deriving it from the accepted solutions instead made a
        problem with a single C++ solution a C++-only problem, which is a contest-wide
        policy decision taken by accident. Every language emitted here has a
        `scripts/<lang>/` dir in the package and a `TLOVERRIDE` in `conf`, so MOJ can
        compile, run and time all of them.

        Under `--calibrate` the limits are MOJ's to measure, and it measures them from
        `sols/good`: a whitelisted language with no accepted solution falls back to
        `TL[default]`, the tightest measured limit. That is the one case where the
        whitelist outruns what the package can justify, and
        `_report_submission_languages` says so out loud.

        A probe package overrides all of that. Its whitelist is *authored* -- every
        language rbx may testrun -- rather than derived, because the API refuses a
        submission outside the whitelist, a testrun included, and a timing run must
        never be refused over a language the whitelist failed to name.

        Sorted for a deterministic file, and normalized the way the server would.
        """
        if self.probe is not None:
            # `_report_submission_languages` is skipped on purpose: it is about what
            # the setter's env enables for students, and nobody else submits to a
            # throwaway probe package.
            allowed = sorted(
                {
                    normalize_moj_language(language)
                    for language in self.probe.submission_languages
                }
            )
            self._warn_about_unscripted_languages(allowed)
            return allowed

        allowed = sorted(
            {
                normalize_moj_language(language)
                for language in get_emitted_moj_languages()
            }
        )
        self._report_submission_languages(allowed)
        return allowed

    def _warn_about_unscripted_languages(self, allowed: List[str]) -> None:
        """Warn about a probe whitelisting a language the package ships no scripts for.

        On the real path this cannot happen: the whitelist *is* the emitted
        languages, so every entry has a `scripts/<lang>/` dir by construction. An
        authored whitelist loses that for free, and the
        failure is quiet in a bad way -- MOJ accepts the submission (it is on the
        whitelist) and then runs it under its own `lang/<lang>` scripts, which rbx
        never validated, with no signal on this side at all.

        A warning rather than a refusal, deliberately: MOJ's own scripts may well work,
        and refusing would block a whole timing run over a language that might be fine.
        A timing measured through scripts rbx did not emit is the thing to be
        suspicious of, and now it says so.
        """
        emitted = set(get_emitted_moj_languages())
        # Compared under normalization on both sides: `get_emitted_moj_languages`
        # can yield the legacy `py3` spelling, which the whitelist has folded to `py`.
        normalized_emitted = {normalize_moj_language(language) for language in emitted}
        unscripted = sorted(
            language for language in allowed if language not in normalized_emitted
        )
        if not unscripted:
            return
        console.console.print(
            f'[warning]This package whitelists [item]'
            f'{"[/item], [item]".join(unscripted)}[/item] but ships no '
            '[item]scripts/[/item] for them.[/warning]\n'
            '[warning]MOJ will accept those submissions and run them with its own '
            'compile/run scripts, which rbx has not validated -- any timing measured '
            'through them is not comparable to the rest.[/warning]'
        )

    def _report_submission_languages(self, allowed: List[str]) -> None:
        """Say out loud which languages students may submit in.

        The whitelist is a real restriction -- the MOJ API rejects submissions outside
        it -- and it comes from `env.rbx.yml`, so a setter working in an environment
        trimmed down to C++ gets a C++-only problem. That consequence must never be
        silent, and the fix lives somewhere the message has to point at.

        Under `--calibrate` a second line names the whitelisted languages with no
        accepted solution. MOJ calibrates a limit per language from `sols/good`, so
        those fall back to `TL[default]` -- the *tightest* measured limit, which on a
        typical problem is the C++ one, and no Python submission survives it. The
        pinned modes emit a `TLOVERRIDE` for every emitted language, so there is
        nothing to warn about there.
        """
        if not allowed:
            # `_write_solutions` fails right after this with a precise error.
            return

        console.console.print(
            'MOJ will accept submissions in: '
            f'[item]{"[/item], [item]".join(allowed)}[/item] '
            '(the languages declared in [item]env.rbx.yml[/item]).'
        )

        if not isinstance(self.timing_mode, JudgeCalibrated):
            return

        uncalibrated = sorted(
            set(allowed) - self._languages_with_an_accepted_solution()
        )
        if not uncalibrated:
            return
        console.console.print(
            f'[warning]No [item]ACCEPTED[/item] solution in [item]'
            f'{"[/item], [item]".join(uncalibrated)}[/item], and this package lets MOJ '
            'calibrate the time limits.[/warning]\n'
            '[warning]MOJ measures a limit per language from the accepted solutions '
            'the package ships, so those languages are judged under the tightest '
            'measured limit. '
            + (
                'Drop [item]--reference-only[/item], which is why this package '
                'ships no accepted solution in them, '
                if self.reference_only
                else 'Add an accepted solution in them, '
            )
            + 'or pin the limits with [item]rbx time -p moj[/item].[/warning]'
        )

    def _languages_with_an_accepted_solution(self) -> Set[str]:
        """The MOJ ids MOJ can calibrate a time limit for: those of the accepted
        solutions this package ships in `sols/good`.

        The solutions *shipped*, not the ones declared -- under
        `--reference-only` every language but the model solution's loses its
        measured limit, which is precisely what the caller is warned about."""
        from rbx.box.code import find_language

        languages = set()
        for solution in self._solutions_to_ship():
            if solution.outcome != ExpectedOutcome.ACCEPTED:
                continue
            moj_language = get_moj_language_from_rbx_language(
                find_language(solution).name
            )
            if moj_language is not None:
                languages.add(moj_language)
        return languages

    def _write_moj_meta(self, into_path: pathlib.Path) -> None:
        """Write `.moj-meta.json`.

        On a tar upload the server treats this file in two tiers: the *content* fields
        (`display_title`, `collections`, `languages`) are taken from it, while the
        *access* fields (`public`, `public_at`, `owner`) are never accepted from a tar
        and only move through dedicated API routes. So rbx writes the content fields it
        can know and omits everything else:

        - `display_title` is required and never empty.
        - `languages` restricts who may submit what; see `_submission_languages`.
          Omitted when empty, since absent means "server preserves what it has"
          whereas an empty list is a meaningless no-op.
        - `collections` is author-editable but rbx has no notion of them, and absent
          means the server keeps the existing ones.
        - `public`, `public_at`, `owner` and `gitea` are server-owned. Beyond being
          ignored from a tar, `public` is fail-closed in `gen-problem-json.sh`, so
          emitting it is both useless and the kind of thing that leaks an unpublished
          problem into an index served to anonymous users.
        """
        meta: Dict[str, object] = {'display_title': self._display_title()}
        languages = self._submission_languages()
        if languages:
            meta['languages'] = languages
        (into_path / '.moj-meta.json').write_text(
            json.dumps(meta, ensure_ascii=False, indent=2) + '\n'
        )

    def _author(self) -> str:
        """The `author` file's contents, taken from `vars.author`.

        Any primitive var is accepted and stringified -- `vars` is untyped by design,
        and a name that happens to parse as a number is still a name. A var that is
        absent, or that is blank once stripped, falls back to `DEFAULT_AUTHOR`: MOJ
        requires the file to be non-empty, so an empty `author: ""` must not travel
        through as an empty file.
        """
        author = package.find_problem_package_or_die().expanded_vars.get(AUTHOR_VAR)
        if author is None:
            return DEFAULT_AUTHOR
        author = str(author).strip()
        return author or DEFAULT_AUTHOR

    def _write_metadata(self, into_path: pathlib.Path) -> None:
        (into_path / 'author').write_text(self._author() + '\n')
        (into_path / 'tags').write_text('')
        self._write_moj_meta(into_path)
        self._write_statement(into_path)

    def _write_statement(self, into_path: pathlib.Path) -> None:
        """Write `docs/enunciado.md`, its assets and the per-sample notes.

        The whole shape is dictated by mojtools; see
        `rbx.box.packaging.moj.statement`. A package that declares no statement
        falls back to `DUMMY_STATEMENT`: MOJ hard-requires the two headings, and
        a statement-less package must still package.

        **A probe package always takes that fallback**, and this is what makes it
        buildable at all outside `run_packager`. The real path reads `blocks.sub.yml`
        and the externalized TikZ PDFs out of the v2 overlay, which only the forced
        externalize statement build writes -- so a direct `package()` call would raise
        `StatementExportError` on any problem that declares an rbxTeX statement. A
        runner's only escapes would be to run pdflatex locally for a document nobody
        reads, or to go through `run_packager` and pay for the full local verification
        run it exists to avoid. Nothing on MOJ ever renders a probe's statement, and a
        `MojGateError` over one would make `rbx time --runner moj` refuse a timing run
        for a document that is never read.
        """
        docs_path = into_path / 'docs'
        docs_path.mkdir(parents=True, exist_ok=True)

        main_statement = None if self.probe is not None else self._get_main_statement()
        if main_statement is None:
            (docs_path / 'enunciado.md').write_text(DUMMY_STATEMENT)
            return

        try:
            bundle = export.build_statement_bundle(
                main_statement, layout=moj_statement.moj_layout()
            )
        except export.StatementExportError as e:
            console.console.print(f'[error]{e}[/error]')
            raise typer.Exit(1) from e

        bundle.materialize(into_path)
        # After materialize, so the PDFs are on disk under the .png names the
        # layout already rewrote every reference to.
        rasterize_pdf_assets(bundle, into_path)

        try:
            # `docs_root` is what an inlining build reads the figures out of, so
            # both calls come after materialize + rasterize above.
            body = moj_statement.build_enunciado(
                bundle.blocks,
                language=main_statement.language,
                docs_root=docs_path,
            )
            notes = moj_statement.build_notes(bundle.explanations, docs_root=docs_path)
        except MojGateError as e:
            console.console.print(
                f'[error]Cannot package this statement for MOJ.[/error]\n'
                f'[error]{e}[/error]'
            )
            raise typer.Exit(1) from e

        (docs_path / 'enunciado.md').write_text(body)
        for name, content in notes.items():
            note_path = into_path / moj_statement.note_path(name)
            note_path.parent.mkdir(parents=True, exist_ok=True)
            note_path.write_text(content)

        # Last, and only in the inlining mode: the documents that were just
        # written carry the figures themselves, so the files are dead weight.
        moj_statement.discard_inlined_assets(bundle, into_path)

    def _write_conf(self, into_path: pathlib.Path) -> None:
        pkg = package.find_problem_package_or_die()
        lines = [
            '# Generated by rbx. Do not edit by hand.',
            '',
            '# Memory limit by measured peak RSS. Setting this also makes MOJ drop the',
            '# virtual-memory ulimit, which unfairly penalizes runtimes that reserve a',
            '# large heap without touching it, and feeds the JVM -Xmx via binfile.sh.',
            f'MEMLIMITMB={pkg.memoryLimit}',
            '',
            '# File-size ulimit, in KB. Fixed at 100 MiB and deliberately NOT the',
            "# problem's outputLimit: MOJ applies this to the compile step too, so a",
            '# tight output limit makes the linker fail and every submission comes back',
            '# Compilation Error. See OUTPUT_ULIMIT_KB.',
            f'ULIMITS[-f]={OUTPUT_ULIMIT_KB}',
            '',
        ]
        lines.extend(self._time_limit_lines())
        lines.extend(self._stopwhen_lines())
        lines.extend(self._parallelism_lines())
        (into_path / 'conf').write_text('\n'.join(lines))

    # -- time limits ----------------------------------------------------------

    def _time_limit_lines(self) -> List[str]:
        """The `conf` block that decides the time limits.

        Three modes, and the packager refuses to guess between them: the `moj` limits
        profile pins them (the default), `--calibrate` hands the decision to the
        judge, or a timing run pins one uniform cap. Each precondition is checked
        here rather than only in the CLI, so no caller can emit a `conf` with limits
        nothing decided. Every mode is named explicitly and none falls through, for
        the reason `check_timing_setup` gives.
        """
        if isinstance(self.timing_mode, JudgeCalibrated):
            return moj_timing.calibrated_limit_lines(_ac_to_time_limit_or_die())
        if isinstance(self.timing_mode, ProbePinned):
            # Note `_require_limits_profile` deliberately does NOT fire here: that
            # check is about the `moj` profile, and this package does not consult it.
            # `inferenceTimeout` still feeds `CALIBRATIONTL`, since calibration runs
            # on this package too and must not be tighter than what rbx waits for.
            return moj_timing.fixed_limit_lines(
                self._probe_time_limits(),
                inference_timeout_ms=_inference_timeout_ms(),
                explanation=moj_timing.PROBE_EXPLANATION,
            )
        if isinstance(self.timing_mode, ProfilePinned):
            _require_limits_profile()
            return moj_timing.fixed_limit_lines(
                self._fixed_time_limits(), inference_timeout_ms=_inference_timeout_ms()
            )
        typing.assert_never(self.timing_mode)

    def _fixed_time_limits(self) -> moj_timing.FixedTimeLimits:
        """The limits of the `moj` profile, as a default plus per-language limits.

        Keyed by MOJ language id, since that is what mojtools keys `TLOVERRIDE` by
        -- and under the legacy spelling too when a package emits one, because MOJ
        looks the entry up under whatever id the submission's file extension yields.
        """
        limits_by_language: Dict[str, int] = {}
        for moj_language in get_emitted_moj_languages():
            rbx_language = get_rbx_language_from_moj_language(moj_language)
            limits = limits_info.get_limits(
                rbx_language, profile=LIMITS_PROFILE, fallback_to_package_profile=False
            )
            assert limits.time is not None
            limits_by_language[moj_language] = limits.time
            normalized = normalize_moj_language(moj_language)
            limits_by_language.setdefault(normalized, limits.time)

        base_limits = limits_info.get_limits(
            profile=LIMITS_PROFILE, fallback_to_package_profile=False
        )
        assert base_limits.time is not None
        return moj_timing.build_fixed_limits(limits_by_language, base_limits.time)

    def _probe_time_limits(self) -> moj_timing.FixedTimeLimits:
        """The limits a timing run asked for, as a default plus per-language limits.

        Translated here rather than in the runner because this is where the MOJ id
        spellings are already known. `ProbePinned` is keyed by rbx language name;
        `TLOVERRIDE` is keyed by whatever id the submission's file extension yields,
        which is the *emitted* spelling -- so each language is pinned under that and
        under its normalized alias, exactly as `_fixed_time_limits` does.

        A language the run named but this package emits no scripts for silently
        contributes nothing: `TLOVERRIDE[<lang>]` for a language MOJ cannot run is
        an entry nothing ever reads. It cannot hide a real limit either, since
        `MojRunner` refuses up front to testrun a solution whose language has no MOJ
        counterpart.
        """
        mode = self.timing_mode
        assert isinstance(mode, ProbePinned)
        per_rbx_language = dict(mode.per_rbx_language_ms)

        limits_by_language: Dict[str, int] = {}
        for moj_language in get_emitted_moj_languages():
            rbx_language = get_rbx_language_from_moj_language(moj_language)
            if rbx_language is None or rbx_language not in per_rbx_language:
                continue
            limit_ms = per_rbx_language[rbx_language]
            limits_by_language[moj_language] = limit_ms
            limits_by_language.setdefault(
                normalize_moj_language(moj_language), limit_ms
            )

        # `build_fixed_limits` is deliberately NOT reused: it derives the default
        # from the tightest limit involved, which is right when every language has
        # one. Here the default is the limit for the languages the run did *not*
        # name, and the run chose it.
        return moj_timing.FixedTimeLimits(
            base_ms=mode.default_ms,
            per_language_ms={
                language: limit_ms
                for language, limit_ms in limits_by_language.items()
                if limit_ms != mode.default_ms
            },
        )

    def _report_time_limits(self) -> None:
        """Show what the package will be judged with.

        The pinned limits are the profile's, so the profile's own table is the honest
        report -- exactly as `BocaPackager` does. Under `--calibrate` there is
        nothing to show: the numbers are the judge's to measure. Under a probe pin
        the profile's table would be a lie, so the limits this run asked for are
        named instead -- they are what every timing it produces is measured against.

        Under a probe pin the line names **what is being measured**, not what MOJ
        would judge an arbitrary submission with. Naming the solutions is what
        makes the language list self-explanatory: the validation phase runs only
        the solutions expected to be too slow, so a package whose slow solutions
        are all C++ pins C++ and nothing else. The earlier wording listed the
        languages and then added "and every other language under <default>",
        which reads as a claim about how Java would be judged -- and is how a
        setter with a deliberately higher Java limit concludes the packager
        dropped it. The fallback is not mentioned at all now, because nothing
        this run submits can reach it.
        """
        if isinstance(self.timing_mode, JudgeCalibrated):
            return
        if isinstance(self.timing_mode, ProbePinned):
            measuring = self.timing_mode.measuring
            if not self.timing_mode.per_rbx_language_ms:
                console.console.print(
                    f'MOJ will measure {measuring} under a single time limit of '
                    f'[item]{self.timing_mode.default_ms} ms[/item].'
                )
                return
            per_language = ' and '.join(
                f'[item]{language}[/item] at [item]{limit_ms} ms[/item]'
                for language, limit_ms in sorted(self.timing_mode.per_rbx_language_ms)
            )
            console.console.print(f'MOJ will measure {measuring} in {per_language}.')
            return
        if isinstance(self.timing_mode, ProfilePinned):
            profile = limits_info.get_display_limits_profile(LIMITS_PROFILE)
            if profile is None:
                return
            limits_info.render_limits_table(
                profile, title='MOJ time limits (per language group)'
            )
            return
        typing.assert_never(self.timing_mode)

    def _stopwhen_lines(self) -> List[str]:
        """The `STOPWHEN_*` block, which halts a run at the first failing test.

        Enabled for BINARY problems: the verdict is already decided by the first
        failure, so running the rest only burns judge time.

        **Not** enabled for POINTS problems, and that is a correctness matter rather
        than a preference. `build-and-test.sh` checks `STOPWHEN_*` *before* the
        `RUNALL` guard, so it breaks out of the test loop even when the caller asked
        for every test. `score-summary.sh` then sees a group with no executed tests
        and scores it `null` -- counted as failed. A solution that legitimately failed
        group 1 but would have passed group 2 would silently lose group 2's points.

        A probe package takes **whatever rule its caller asked for**
        (`ProbePackage.halt_on`), which is not a compromise between the two cases
        above but an exact translation of the abort predicate rbx would have
        enforced locally. Both `rbx time` phases pass the same predicate --
        `abort_on=lambda ctx: ctx.evaluation.result.outcome.is_slow()` -- so they
        ask for `STOPWHEN_TLE` alone. `rbx run --fail-fast` aborts on any
        non-accepted verdict, so it asks for all three. A plain `rbx run` aborts
        on nothing and asks for none: every test then comes back with a real
        verdict, which is what the local run reports, and halting there would
        turn the tests after the first timeout into SKIPPED on a run that never
        asked to stop.

        It matters because the local abort has no counterpart here. The gate in
        `run_solutions` works by not *dispatching* the testcases after a timeout,
        and a testrun has already run the whole submission by the time rbx sees
        any of it -- which is why `MojRunner` declares `supports_abort=False`.
        Without this, a solution expected to be too slow runs to the limit on
        **every** test of the testset when one test already settled the question:
        by definition the most expensive solutions in the run, at full cost, on a
        shared judge park.

        `STOPWHEN_WA` and `STOPWHEN_RE` stay off, and the asymmetry is the whole
        point. The upper-bound solutions are the ones expecting TLE
        (`TIME_LIMIT_EXCEEDED`, `TLE_OR_RTE`), and a `TLE_OR_RTE` one may
        legitimately crash; `_record_validation_run` reads a non-slow bad verdict
        as "broke for another reason" and reports it, which needs the run to have
        continued. Halting there would also truncate the timings of a solution
        that is *not* too slow, which is the case that has a real measurement to
        hand back. Locally a WA does not abort either.

        The truncation itself is safe to read: the probe watched a `STOPWHEN_*`
        run come back with 4 entries and `total_tests: 72`, and `ran_nothing`
        keys on `total_tests`, so a truncated run is never mistaken for a
        submission that failed to build. The tests MOJ did not report become
        `SKIPPED` with no timing -- exactly what the local abort gate writes.

        The POINTS hazard above does not reach a probe either: it is about
        `score-summary.sh` scoring an unexecuted group `null`, and nothing reads a
        probe's score. `MojRunner` reads `tests[]`, `verdict_canon` and
        `total_tests`, and never a score.

        Note the early break is mojtools' best-effort optimization rather than a
        guarantee -- it fires only from inside the `JOBSCOUNT > NPROC-1` branch.
        A probe is the case where it does fire: `ALLOWPARALLELTEST=n` pins
        `NPROC=1`, so the condition holds from the second test onward. Nothing
        here depends on it. A run that stops early and one that does not produce
        the same verdict, at different cost.
        """
        if self.probe is not None:
            halting = [
                verdict
                for verdict in HALT_VERDICT_ORDER
                if verdict in self.probe.halt_on
            ]
            if not halting:
                return [
                    '# No STOPWHEN_* at all: the run this package serves asked for every',
                    '# test to be judged. A halt here would come back as tests rbx never',
                    '# saw -- reported as SKIPPED -- on a run that never asked to stop.',
                    '',
                ]
            return [
                '# Halt a solution at the verdicts rbx would have stopped it at locally.',
                '# The local abort gate has no counterpart on a judge -- a testrun has',
                '# already run the whole submission by the time rbx sees any of it -- so',
                "# the caller's own abort predicate is enforced here instead, and the",
                '# tests that never run come back as SKIPPED, exactly as that gate writes',
                '# them.',
                *[f'STOPWHEN_{verdict}=y' for verdict in halting],
                '',
            ]
        pkg = package.find_problem_package_or_die()
        if pkg.scoring != ScoreType.BINARY:
            return [
                '# STOPWHEN_* is deliberately unset: this problem scores by groups, and',
                '# halting early leaves later groups unexecuted, which score-summary.sh',
                '# counts as failed -- the submission would lose points it had earned.',
                '',
            ]
        return [
            '# Halt at the first failing test. The verdict of an all-or-nothing problem',
            '# is already decided by then, so the remaining tests only cost judge time.',
            'STOPWHEN_WA=y',
            'STOPWHEN_TLE=y',
            'STOPWHEN_RE=y',
            '',
        ]

    def _parallelism_lines(self) -> List[str]:
        """What a probe changes so the judge *measures* rather than judges.

        Two knobs, one argument: `ALLOWPARALLELTEST` and `TLERERUN`. Both are
        MOJ defaults tuned for judging throughput, and both corrupt a measurement.

        `build-and-test.sh` runs the testset **in parallel by default** -- it sets
        `NPROC=$(nproc)` and only drops to one job when `ALLOWPARALLELTEST` is exactly
        `n` (lines 434-436). The MOJ park reports 56 CPUs, so a package that says
        nothing is measured with dozens of tests competing for the machine, and every
        time it reports is inflated by however much contention it happened to meet.
        (It is also why the `tests` array comes back unordered.)

        A probe package exists *only* to measure, so it must not be judged that way --
        and mojtools already agrees: `calibreitor.sh:125` exports `ALLOWPARALLELTEST=n`
        before running the accepted solutions, for exactly this reason. Calibration
        measures, so it serialises; the probe measures, so it serialises too.

        Left at MOJ's default for a package a setter builds: there, parallelism is a
        judging-speed feature and the limits are pinned through `TLOVERRIDE`, so what
        the judge measures decides nothing.

        Note `MAXPARALLELTESTS` is applied *after* this knob (line 437) and would
        override it. The packager emits it nowhere, and a probe must never grow one.
        """
        if self.probe is None:
            return []
        return [
            '# Run the testset one test at a time. build-and-test.sh otherwise uses',
            '# NPROC=$(nproc) -- 56 on the MOJ park -- and a timing measured against',
            '# dozens of competing tests is inflated by whatever contention it met.',
            '# calibreitor.sh exports this same value before it measures; a probe',
            '# package exists only to measure, so it does the same.',
            'ALLOWPARALLELTEST=n',
            '',
            '# And do not re-run a test that hit the limit. TLERERUN defaults to y and',
            '# exists to absorb a false TLE caused by parallel tests -- its own log line',
            '# says so -- which is a problem the line above already removed. Left on, it',
            '# would replace the measured time with a second one taken under different',
            '# conditions, spend the judge twice on the slowest solutions, and do it',
            '# only until some test stays TLE (build-and-test.sh latches TLERERUN=n from',
            '# then on), so which tests got a second chance would depend on the order',
            '# they finished in.',
            'TLERERUN=n',
            '',
        ]

    # -- tests ----------------------------------------------------------------

    def _group_indices(self) -> Dict[str, int]:
        pkg = package.find_problem_package_or_die()
        return {group.name: index for index, group in enumerate(pkg.testcases)}

    def testcase_names(self) -> List[Tuple[GenerationTestcaseEntry, str]]:
        """Every built testcase paired with the file name it takes in the package.

        **Public on purpose.** The MOJ runner pairs a testrun's per-test results back
        onto rbx testcases *by name*, which is what stops a timing being attributed to
        the wrong test -- and a caller cannot reproduce these names from the entries
        alone. `index` here is a **1-based running counter over the built entries of
        each group**, not `entry.group_entry.index`, which is 0-based and counts the
        *declared* ones; and `group_index` is the group's position in
        `problem.rbx.yml`. Reimplementing that yields an off-by-one that still
        produces well-formed names -- for the wrong tests, silently.

        `_write_tests` consumes this exact list, so what the runner pairs on and what
        the package contains cannot drift apart. In emission order, which is also the
        order MOJ's lexicographic judging loop reports.
        """
        indices = self._group_indices()
        counters: Dict[str, int] = collections.defaultdict(int)
        named: List[Tuple[GenerationTestcaseEntry, str]] = []

        for entry in self.get_built_testcase_entries():
            group_name = entry.group_entry.group
            counters[group_name] += 1
            named.append(
                (
                    entry,
                    naming.testcase_name(
                        group_name,
                        group_index=indices.get(group_name, 0),
                        index=counters[group_name],
                        is_sample=entry.is_sample(),
                    ),
                )
            )
        return named

    def _write_tests(self, into_path: pathlib.Path) -> List[str]:
        """Write `tests/input` and `tests/output`; return the group names that got
        at least one test, in encounter order."""
        inputs_path = into_path / 'tests' / 'input'
        outputs_path = into_path / 'tests' / 'output'
        inputs_path.mkdir(parents=True, exist_ok=True)
        outputs_path.mkdir(parents=True, exist_ok=True)

        seen_groups: List[str] = []
        has_sample = False

        for entry, name in self.testcase_names():
            group_name = entry.group_entry.group
            if group_name not in seen_groups:
                seen_groups.append(group_name)
            has_sample = has_sample or entry.is_sample()

            testcase = entry.metadata.copied_to
            shutil.copyfile(testcase.inputPath, inputs_path / name)
            if testcase.outputPath is not None:
                shutil.copyfile(testcase.outputPath, outputs_path / name)
            else:
                (outputs_path / name).touch()

        if not has_sample:
            console.console.print(
                '[error]This problem has no testcases in the [item]samples[/item] '
                'group, but MOJ requires at least one.[/error]\n'
                "[error]MOJ builds the statement's examples from "
                '[item]tests/input/sample*[/item], and [item]validate-problem.sh[/item] '
                'hard-fails a package without any.[/error]'
            )
            raise typer.Exit(1)

        return seen_groups

    def _write_score(self, into_path: pathlib.Path, seen_groups: List[str]) -> None:
        """Write `tests/score` for POINTS problems.

        BINARY problems get no score file: MOJ then scores by percentage of tests and
        still requires every one to pass, which is the correct ICPC semantics.
        """
        pkg = package.find_problem_package_or_die()
        if pkg.scoring != ScoreType.POINTS:
            return

        indices = self._group_indices()
        groups: List[naming.ScoreGroup] = []
        for group in pkg.testcases:
            # A group with no built tests would match nothing, and score-summary.sh
            # treats an unmatched group as "not executed", which can never be
            # Accepted. Skip it rather than poison the verdict.
            if group.name not in seen_groups:
                continue
            glob = (
                naming.SAMPLES_GLOB
                if group.name == SAMPLES_GROUP
                else naming.group_glob(group.name, indices[group.name])
            )
            groups.append(naming.ScoreGroup(glob=glob, weight=group.score))

        (into_path / 'tests' / 'score').write_text(naming.build_score_file(groups))

    # -- checker --------------------------------------------------------------

    def _builtin_header_roots(self) -> List[pathlib.Path]:
        """Directories holding the headers rbx injects beside a source.

        These are what make `testlib.h` and `rbx.h` inlinable; the amalgamator itself
        knows nothing about them.
        """
        return [get_testlib().parent, header.get_header().parent]

    def _amalgamate(self, code: CodeItem, what: str) -> bytes:
        try:
            result = amalgamate(
                utils.abspath(code.path), extra_roots=self._builtin_header_roots()
            )
        except AmalgamationError as e:
            console.console.print(
                f'[error]Cannot package {code.href()} for MOJ.[/error]\n'
                f'[error]{e}[/error]\n'
                f'[error]MOJ compiles the {what} from a single file, so it must '
                'reduce to one self-contained translation unit.[/error]'
            )
            raise typer.Exit(1) from e
        return result.content

    def _amalgamate_checker(self) -> bytes:
        checker = package.get_checker_or_builtin()
        if checker.path.suffix.lower() not in _AMALGAMATABLE_SUFFIXES:
            console.console.print(
                f'[error]Cannot package {checker.href()} for MOJ: the checker must be '
                'C++.[/error]\n'
                "[error]MOJ's checker bridge compiles [item]scripts/checker.cpp[/item] "
                'with g++ and knows no other language.[/error]'
            )
            raise typer.Exit(1)

        # Checked against the ORIGINAL source, never the amalgamated output: testlib
        # itself declares `quitp` and `_points`, so the inlined header would make this
        # fire for every checker, the builtin one included.
        source = checker.path.read_text(encoding='utf-8', errors='replace')
        if 'quitp' in source or '_points' in source:
            console.console.print(
                '[warning]The checker references [item]quitp[/item]/'
                '[item]_points[/item], but MOJ maps a testlib partial result to a '
                'judge error, not to partial credit.[/warning]\n'
                '[warning]Express subtasks with [item]tests/score[/item] groups '
                'instead.[/warning]'
            )
        return self._amalgamate(checker, 'checker')

    def _write_checker(self, into_path: pathlib.Path) -> None:
        scripts_path = into_path / 'scripts'
        scripts_path.mkdir(parents=True, exist_ok=True)

        (scripts_path / 'checker.cpp').write_bytes(self._amalgamate_checker())

        # The compare driver runs on the judge HOST, where mojtools exists, so the
        # package ships the canonical stub rather than a copy of the bridge. A
        # bundled bridge copy is what spread one bwrap bug across 198 packages.
        stub_path = (
            get_default_app_path() / 'packagers' / 'moj' / 'scripts' / 'compare.sh'
        )
        compare_path = scripts_path / 'compare.sh'
        shutil.copyfile(stub_path, compare_path)
        # Without +x the judge gets "Permission denied" and every test is a judge error.
        compare_path.chmod(0o755)

    # -- solutions ------------------------------------------------------------

    def _tag_for(self, solution: Solution) -> str:
        """The `sols/` directory a solution belongs in.

        `ANY` asserts nothing about the outcome, so none of good/pass/slow/wrong
        describes it -- shipping it under any of those would state an expectation the
        package does not make. It goes to `upcoming/`, MOJ's home for drafts, which is
        both the honest classification and better than dropping the file.

        Note `upcoming/` is *not* executed by `calibreitor.sh`: it runs `sols/good`
        for the time limit, then `pass`, `slow` and `wrong` for verification. Nor is
        it covered by `tl-checksum.sh` (which hashes only `sols/good`), so adding or
        changing a draft never forces a recalibration.
        """
        outcome = solution.outcome
        if outcome == ExpectedOutcome.ACCEPTED:
            return 'good'
        if outcome == ExpectedOutcome.ACCEPTED_OR_TLE:
            return 'pass'
        if outcome.is_slow():
            return 'slow'
        if outcome == ExpectedOutcome.ANY:
            return 'upcoming'
        return 'wrong'

    def solution_content(self, solution: Solution) -> bytes:
        """The bytes to ship for a solution.

        A solution is compiled from a single file inside MOJ's jail, so a C/C++
        solution pulling in `rbx.h` or a local header gets the same amalgamation
        treatment as the checker. Other languages have no amalgamator, so a
        multi-file closure is an error rather than a package that fails to compile
        on the judge.
        """
        if solution.path.suffix.lower() in _AMALGAMATABLE_SUFFIXES:
            return self._amalgamate(solution, 'solution')

        graph = deps_graph.expand(solution, require_kind=DependencyKind.COMPILATION)
        if graph is not None and len(graph.nodes) > 1:
            deps = ', '.join(
                str(path)
                for path in sorted(graph.nodes)
                if path != package.get_relative_source_path(solution)
            )
            console.console.print(
                f'[error]Cannot package {solution.href()} for MOJ: it depends on '
                f'[item]{deps}[/item], but MOJ compiles a submission from a single '
                'file and rbx cannot amalgamate this language.[/error]'
            )
            raise typer.Exit(1)
        return solution.path.read_bytes()

    def _solutions_to_ship(self) -> List[Solution]:
        """The solutions this package carries.

        Every declared one, normally -- MOJ verifies them during calibration. Only the
        model solution in two cases:

        - A probe package. `moj testrun` sends the source of the solution being timed
          in the request body, so the timed solutions never have to be in the package
          at all, and `calibreitor.sh` needs exactly one `sols/good` to succeed.
        - `--reference-only`. Calibration runs every solution the package ships --
          `sols/good` to measure the limits, then the rest to check their verdicts --
          so on a problem with many solutions it is the slowest part of an upload.
          Dropping all but the model solution is what makes an upload iterated on
          repeatedly cheap; what is lost is exactly what calibration would have
          verified, so the package is no longer one to hand to students.

        Both keep the single `sols/good` `calibreitor.sh` cannot do without.
        """
        if self.probe is None and not self.reference_only:
            return package.get_solutions()
        main_solution = package.get_main_solution()
        # An empty list rather than an error: `_write_solutions` already reports a
        # package with no accepted solution, and precisely.
        return [main_solution] if main_solution is not None else []

    def _write_solutions(self, into_path: pathlib.Path) -> None:
        if self.reference_only and self.probe is None:
            # Loud, because the dropped solutions are the ones calibration would have
            # checked the verdicts of: this package is for iterating on an upload, not
            # for handing to students.
            console.console.print(
                '[warning]Shipping only the reference solution: [item]--reference-only'
                '[/item] is set.[/warning]\n'
                '[warning]MOJ runs every solution the package ships when it '
                'calibrates, so this is much faster -- but nothing verifies the '
                'dropped solutions on the judge. Package again without the flag '
                'before the problem goes live.[/warning]'
            )

        sols_path = into_path / 'sols'
        written: Dict[str, Dict[str, pathlib.Path]] = collections.defaultdict(dict)

        for solution in self._solutions_to_ship():
            tag = self._tag_for(solution)
            basename = solution.path.name
            if basename in written[tag]:
                console.console.print(
                    f'[error]Cannot package for MOJ: {solution.href()} and '
                    f'[item]{written[tag][basename]}[/item] would both be written to '
                    f'[item]sols/{tag}/{basename}[/item].[/error]\n'
                    '[error]MOJ derives the language from the file name, so rbx ships '
                    'each solution under its own name rather than renaming them. Give '
                    'one of them a different file name.[/error]'
                )
                raise typer.Exit(1)
            written[tag][basename] = solution.path

            dest_path = sols_path / tag / basename
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            dest_path.write_bytes(self.solution_content(solution))

        if not written['good']:
            console.console.print(
                '[error]No accepted solution found, but MOJ needs at least one in '
                '[item]sols/good[/item].[/error]\n'
                '[error]MOJ measures the time limit by running them; a language with '
                'no accepted solution never gets one, and a package with none can '
                'never be calibrated.[/error]'
            )
            raise typer.Exit(1)

    # -- per-language scripts -------------------------------------------------

    def _write_language_scripts(self, into_path: pathlib.Path) -> None:
        scripts_path = into_path / 'scripts'
        scripts_path.mkdir(parents=True, exist_ok=True)
        templates_root = get_default_app_path() / 'packagers' / 'moj' / 'scripts'

        for language in get_emitted_moj_languages():
            template = get_moj_template_name(language)
            src_path = templates_root / template
            if not src_path.is_dir():
                console.console.print(
                    f'[warning]No MOJ script template [item]{template}[/item] for '
                    f'language [item]{language}[/item]; MOJ will fall back to its own '
                    f'[item]lang/{language}[/item] scripts.[/warning]'
                )
                continue

            dest_path = scripts_path / language
            shutil.copytree(src_path, dest_path, dirs_exist_ok=True)
            self._expand_language_vars(language, template, dest_path)

    def _expand_language_vars(
        self, language: str, template: str, dest_path: pathlib.Path
    ) -> None:
        extension: MojLanguageExtension = get_moj_language_extension(language)
        flags = extension.flags
        if flags is None:
            flags = DEFAULT_FLAGS.get(template, '')

        for path in dest_path.glob('**/*'):
            if not path.is_file():
                continue
            path.write_text(path.read_text().replace('{{rbxFlags}}', flags))
            if path.suffix == '.sh':
                # These run in the jail and are executed directly; without +x every
                # test is a judge error, and validate-problem.sh checks for it.
                path.chmod(0o755)

    # -- entry point ----------------------------------------------------------

    def package(
        self,
        build_path: pathlib.Path,
        into_path: pathlib.Path,
        built_statements: List[BuiltStatement],
    ) -> pathlib.Path:
        into_path.mkdir(parents=True, exist_ok=True)

        self._write_metadata(into_path)
        self._write_conf(into_path)
        seen_groups = self._write_tests(into_path)
        self._write_score(into_path, seen_groups)
        self._write_checker(into_path)
        self._write_solutions(into_path)
        self._write_language_scripts(into_path)
        self._report_time_limits()

        shutil.make_archive(str(build_path / self.package_basename()), 'zip', into_path)
        return (build_path / self.package_basename()).with_suffix('.zip')
