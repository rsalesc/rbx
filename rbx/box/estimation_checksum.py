"""What a saved time limit was estimated against, folded into one string.

A `.limits/<profile>.yml` records the time limit `rbx time` computed, but not
what it computed it *from*. Edit a solution, add a slow one, regenerate the
tests, and the number stays there looking authoritative. This module produces a
checksum of the inputs that can move an estimate, so the profile can say when it
predates them.

The checksum is a single dotted string, and deliberately so: one field to store,
one field to compare, but segmented so a mismatch still names *which* bucket
moved rather than only that something did.

    v1.h.9f3a1c22.4b7e0d81.c1a8f930
    │  │ solutions  interactor  tests
    │  └ level: `l` (light) or `h` (heavy)
    └ format version

The **light** level covers the solutions alone, and is always computable. The
**heavy** level adds the interactor and a digest of every built test input, and
needs a finished build to read them from -- so a checker asks for whatever it can
compute and compares only the segments both sides carry. A heavy record checked
against a light recomputation still compares its solutions.

The version prefix is what lets the recipe below change later: an unknown version
compares as "cannot tell", not as a mismatch, so a new rbx never greets an old
package with a warning about a checksum it simply does not speak.
"""

import dataclasses
import enum
import io
import pathlib
from typing import List, Optional, Tuple

from pydantic import BaseModel

from rbx import console, utils
from rbx.box import package
from rbx.box.dependencies import graph
from rbx.box.schema import CodeItem
from rbx.grading.judge.digester import Digester, digest_cooperatively

CHECKSUM_VERSION = 'v1'

# Enough to make an accidental collision irrelevant -- this gates a warning, not
# a cache -- while keeping the whole string short enough to read in a diff.
_SEGMENT_LENGTH = 8

_LIGHT = 'l'
_HEAVY = 'h'

# Stands in for a segment whose subject the package does not have (a problem with
# no interactor), so segment *positions* stay fixed and a package that gains an
# interactor reads as a change rather than as a different format.
_ABSENT = '-'

# What a digest says about a file that is not there. Distinct from any real
# digest, so a deleted dependency moves the checksum.
_MISSING = 'missing'


class ChecksumBucket(enum.Enum):
    """The part of the package a mismatch points at."""

    SOLUTIONS = 'solutions'
    INTERACTOR = 'interactor'
    TESTS = 'tests'


_BUCKET_DESCRIPTION = {
    ChecksumBucket.SOLUTIONS: 'the solutions it was estimated from have changed',
    ChecksumBucket.INTERACTOR: 'the interactor has changed',
    ChecksumBucket.TESTS: 'the tests have changed',
}


class _CodeFingerprint(BaseModel):
    """One code item, with everything about it that can move a measured time."""

    path: str
    language: Optional[str] = None
    # The root's own digest plus its transitive source closure, package-relative
    # and in deterministic order. A C++ solution whose hot loop lives in an
    # included header changes timing without its own bytes moving at all.
    files: List[Tuple[str, str]] = []


class _SolutionFingerprint(BaseModel):
    code: _CodeFingerprint
    # `lower` or `upper` -- which bound the solution contributes to. A solution
    # promoted from lower to upper changes what the estimate means even when not
    # one byte of it changed.
    role: str


class _SolutionsSegment(BaseModel):
    solutions: List[_SolutionFingerprint]


class _InteractorSegment(BaseModel):
    interactor: _CodeFingerprint


class _TestsSegment(BaseModel):
    # (group, index, input digest), sorted.
    tests: List[Tuple[str, int, str]]


def _digest_model(model: BaseModel) -> str:
    """Hash a pydantic model by its canonical JSON dump.

    The same trick `grading.caching` uses to key a cache entry on its inputs: the
    dump is stable for a fixed model definition, and adding a field to one of the
    models above changes every checksum -- which is exactly why the string above
    carries a version.
    """
    payload = model.model_dump_json().encode()
    return digest_cooperatively(io.BytesIO(payload))[:_SEGMENT_LENGTH]


def _digest_path(path: pathlib.Path) -> str:
    if not path.is_file():
        return _MISSING
    digester = Digester()
    with path.open('rb') as f:
        digester.update(f.read())
    return digester.digest()


def _closure_of(code: CodeItem) -> List[pathlib.Path]:
    """`code`'s own path plus everything it transitively pulls in.

    `graph.expand` returns None whenever it cannot answer -- no scanner for the
    language, a source outside the package root -- and a checksum over the root
    alone is the honest answer there, not a failure.
    """
    paths = [code.path]
    try:
        expanded = graph.expand(code)
    except Exception:
        # A checksum is a convenience; a package that cannot be scanned must
        # still be packageable.
        expanded = None
    if expanded is not None:
        paths.extend(expanded.files())
    for extra in (code.compilationFiles or []) + (code.executionFiles or []):
        paths.append(pathlib.Path(extra))
    # Deduplicated and ordered, so the same package always hashes the same way
    # regardless of how the scanner happened to walk it.
    return sorted(set(paths))


def _fingerprint_code(code: CodeItem) -> _CodeFingerprint:
    return _CodeFingerprint(
        path=code.path.as_posix(),
        language=code.language,
        files=[(path.as_posix(), _digest_path(path)) for path in _closure_of(code)],
    )


def _solutions_segment() -> str:
    """Hash every solution that can move the estimate.

    Only solutions carrying an inference role are included. A `lower` solution
    sets the base estimate and an `upper` one validates the bound; everything
    else -- `inference: false`, `accepted-or-tle` -- is measured for the report
    and never feeds the number. Deriving the set from the package this way is
    what lets the estimator and the checker agree without the profile having to
    store a roster of paths.
    """
    from rbx.box.solutions import inference_role_of

    fingerprints = []
    for solution in package.get_solutions():
        role = inference_role_of(solution)
        if role is None:
            continue
        fingerprints.append(
            _SolutionFingerprint(code=_fingerprint_code(solution), role=role.value)
        )
    fingerprints.sort(key=lambda fingerprint: fingerprint.code.path)
    return _digest_model(_SolutionsSegment(solutions=fingerprints))


def _interactor_segment() -> str:
    pkg = package.find_problem_package_or_die()
    if pkg.interactor is None:
        return _ABSENT
    return _digest_model(
        _InteractorSegment(interactor=_fingerprint_code(pkg.interactor))
    )


def _tests_segment() -> Optional[str]:
    """Hash the built test inputs, or None when they cannot be trusted.

    None -- which downgrades the whole checksum to light -- on any of:

    * no manifest, or one written by a different manifest version;
    * a build that did not prove its generators deterministic (`-v0`), since an
      unseeded generator would otherwise mismatch on every single build and turn
      the warning into noise;
    * a build restricted to a subset of the groups (`--samples-only`), whose
      manifest describes a testset that is not the one an estimate ran against.

    That last one is read off the flag the build recorded, not inferred by
    comparing the manifest's groups against the declared ones. A group can be
    declared and still legitimately produce no tests -- a `testcaseGlob` matching
    nothing -- and inferring would read that as a partial build forever, silently
    disabling the heavy level for the whole package.
    """
    # Local import: the manifest module imports half of box, and this module is
    # imported from the CLI's hot paths.
    from rbx.box import testset_manifest

    manifest = testset_manifest.read_manifest()
    if manifest is None:
        return None
    if manifest.version != testset_manifest.MANIFEST_VERSION:
        return None
    if not manifest.deterministic or manifest.partial:
        return None

    tests = []
    for test in manifest.tests:
        if test.input_digest is None:
            return None
        tests.append((test.group, test.index, test.input_digest))
    tests.sort()
    return _digest_model(_TestsSegment(tests=tests))


@dataclasses.dataclass(frozen=True)
class EstimationChecksum:
    version: str
    level: str
    solutions: str
    interactor: Optional[str] = None
    tests: Optional[str] = None

    @property
    def is_heavy(self) -> bool:
        return self.level == _HEAVY

    def encode(self) -> str:
        if not self.is_heavy:
            return '.'.join([self.version, _LIGHT, self.solutions])
        return '.'.join(
            [
                self.version,
                _HEAVY,
                self.solutions,
                self.interactor or _ABSENT,
                self.tests or _ABSENT,
            ]
        )

    @staticmethod
    def decode(value: str) -> Optional['EstimationChecksum']:
        """Parse a stored checksum, or None if it is not one we can read.

        Anything unparseable is `None` rather than an error: the field is
        hand-editable YAML, and a garbled one should cost the user a missing
        warning, never a failed package build.
        """
        parts = value.strip().split('.')
        if len(parts) == 3 and parts[1] == _LIGHT:
            return EstimationChecksum(
                version=parts[0], level=_LIGHT, solutions=parts[2]
            )
        if len(parts) == 5 and parts[1] == _HEAVY:
            return EstimationChecksum(
                version=parts[0],
                level=_HEAVY,
                solutions=parts[2],
                interactor=parts[3],
                tests=parts[4],
            )
        return None


def compute(light_only: bool = False) -> EstimationChecksum:
    """The checksum of the package as it stands right now.

    Heavy whenever the built tests can be trusted, light otherwise. Callers do
    not normally choose the level -- the package does.

    `light_only` is for the one case where they must: a caller that is *not*
    about to build cannot treat whatever `build/` happens to hold as evidence
    about the run it is starting. A leftover manifest from an earlier build would
    otherwise satisfy the tests segment and report a match that describes nothing
    this run will do.
    """
    solutions = _solutions_segment()
    tests = None if light_only else _tests_segment()
    if tests is None:
        return EstimationChecksum(
            version=CHECKSUM_VERSION, level=_LIGHT, solutions=solutions
        )
    return EstimationChecksum(
        version=CHECKSUM_VERSION,
        level=_HEAVY,
        solutions=solutions,
        interactor=_interactor_segment(),
        tests=tests,
    )


def compare(
    recorded: str,
    current: Optional[EstimationChecksum] = None,
    light_only: bool = False,
) -> Optional[ChecksumBucket]:
    """The first bucket where `recorded` and the package disagree.

    None means "no complaint", which covers both a match and every case where the
    two are not comparable -- an unreadable string, a version this rbx does not
    speak, or a segment only one side has. Silence is the right answer for all of
    them: the point of the checksum is to catch a stale estimate, and a checksum
    we cannot interpret is not evidence of one.
    """
    parsed = EstimationChecksum.decode(recorded)
    if parsed is None or parsed.version != CHECKSUM_VERSION:
        return None
    if current is None:
        current = compute(light_only=light_only)
    if parsed.solutions != current.solutions:
        return ChecksumBucket.SOLUTIONS
    if not parsed.is_heavy or not current.is_heavy:
        # One side has no opinion on the interactor or the tests. Comparing the
        # segments it does not carry would flag every package whose build dir
        # happens to be clean.
        return None
    if parsed.interactor != current.interactor:
        return ChecksumBucket.INTERACTOR
    if parsed.tests != current.tests:
        return ChecksumBucket.TESTS
    return None


def check_profile(profile: str, light_only: bool = False) -> Optional[ChecksumBucket]:
    """Compare the checksum saved in `profile` against the package.

    None whenever there is nothing to say -- no such profile, a profile that was
    never estimated (`--strategy inherit`, `--strategy custom`), or a match.
    """
    from rbx.box import limits_info

    saved = limits_info.get_saved_limits_profile(profile)
    if saved is None or saved.estimationChecksum is None:
        return None
    return compare(saved.estimationChecksum, light_only=light_only)


def warn_if_stale(
    profile: Optional[str], light_only: bool = False
) -> Optional[ChecksumBucket]:
    """Print the staleness warning for `profile`, if it has one coming.

    Accepts None -- "no profile is active" -- so a caller can hand over whatever
    `limits_info.get_active_profile()` returned without branching on it.
    """
    if profile is None:
        return None
    try:
        bucket = check_profile(profile, light_only=light_only)
    except Exception as e:
        # Never let a checksum take down a build. The estimate might be stale;
        # the package is still fine.
        console.console.print(
            f'[warning]Could not verify the estimation checksum: '
            f'{utils.escape_markup(str(e))}[/warning]'
        )
        return None
    if bucket is None:
        return None
    console.console.print(
        f'[warning]The time limit saved in profile [item]{profile}[/item] is stale: '
        f'{_BUCKET_DESCRIPTION[bucket]} since it was estimated.[/warning]'
    )
    console.console.print(
        f'[warning]Re-run [item]rbx time -p {profile}[/item] to refresh it.[/warning]'
    )
    return bucket
