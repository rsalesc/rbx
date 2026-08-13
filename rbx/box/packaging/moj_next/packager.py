import collections
import json
import pathlib
import shutil
from typing import Dict, List, Optional

import typer

from rbx import console, utils
from rbx.box import header, package
from rbx.box import naming as box_naming
from rbx.box.dependencies import graph as deps_graph
from rbx.box.dependencies.amalgamation import AmalgamationError, amalgamate
from rbx.box.dependencies.scanner import DependencyKind
from rbx.box.packaging.moj_next import naming
from rbx.box.packaging.moj_next.extension import MojLanguageExtension
from rbx.box.packaging.moj_next.moj_language_utils import (
    get_emitted_moj_languages,
    get_moj_language_extension,
    get_moj_language_from_rbx_language,
    get_moj_template_name,
)
from rbx.box.packaging.packager import BasePackager, BuiltStatement
from rbx.box.schema import CodeItem, ExpectedOutcome, ScoreType, Solution, TaskType
from rbx.box.statements.schema import Statement, StatementType
from rbx.config import get_default_app_path, get_testlib

# rbx has no author field, and MOJ hard-requires the file, so a visible placeholder
# keeps validate-problem.sh green until the setter fills it in on the server.
DEFAULT_AUTHOR = 'Unknown\n'

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


class MojNextPackager(BasePackager):
    """Packager for the MOJ format as `mojtools` consumes it.

    Deliberately shares no code with the legacy `moj` packager. Two decisions shape
    everything else:

    - **Calibration-only time limits.** MOJ measures the limit by running every
      `sols/good` solution and scaling by `TLMOD[calibrafactor]`; it is never
      authored. So no `tl` is emitted and `conf` carries the only limit knobs.
    - **A single-file checker.** MOJ's bridge compiles `scripts/checker.cpp` with only
      `testlib.h` reachable, so the checker is amalgamated rather than shipped with
      its headers.
    """

    @classmethod
    def name(cls) -> str:
        return 'moj-next'

    @classmethod
    def task_types(cls) -> List[TaskType]:
        # MOJ's interactive support uses its own arbiter protocol (test in argv[1],
        # last stderr line `WRONG <reason>`, FIFO driver), not a testlib interactor.
        # The legacy `moj` packager still covers interactive problems.
        return [TaskType.BATCH]

    def statement_types(self) -> List[StatementType]:
        # MOJ's statement format is not supported by rbx yet; a dummy enunciado.md is
        # written instead, so no statement is built.
        return []

    # -- metadata -------------------------------------------------------------

    def _get_main_statement(self) -> Optional[Statement]:
        """The statement the title is taken from: the topmost declared one.

        Statements are not *built* for MOJ (`statement_types()` is empty), but a
        package still declares them, and the first one is what every other packager
        treats as the main one.
        """
        pkg = package.find_problem_package_or_die()
        if not pkg.expanded_statements:
            return None
        return pkg.expanded_statements[0]

    def _display_title(self) -> str:
        """MOJ's `display_title`, resolved through the shared naming helper.

        `naming.get_problem_title` is what BOCA uses: it honors a statement's own
        `title` override, falls back to the package title and then to the package
        name, and raises an actionable error when a package has several titles and no
        statement to disambiguate them.
        """
        statement = self._get_main_statement()
        language = statement.language if statement is not None else None
        return box_naming.get_problem_title(language, statement, fallback_to_title=True)

    def _submission_languages(self) -> List[str]:
        """The MOJ ids to allow submissions in: the languages with an accepted
        solution.

        This is MOJ's own criterion rather than an rbx invention. The judge measures
        a time limit per language from `sols/good`, and mojtools' guide is explicit:
        put a good solution in every language you want to enable, because a language
        without one never gets a time limit and so the student cannot use it. Deriving
        the whitelist from the emitted script dirs instead would key it off the
        setter's env, which says nothing about who may submit what.

        Sorted for a deterministic file, and normalized the way the server would.
        """
        from rbx.box.code import find_language

        languages = set()
        for solution in package.get_solutions():
            if solution.outcome != ExpectedOutcome.ACCEPTED:
                continue
            rbx_language = find_language(solution)
            moj_language = get_moj_language_from_rbx_language(rbx_language.name)
            if moj_language is None:
                console.console.print(
                    f'[warning]{solution.href()} is written in '
                    f'[item]{rbx_language.name}[/item], which maps to no MOJ language, '
                    'so it will not be listed in the allowed submission '
                    'languages.[/warning]'
                )
                continue
            languages.add(moj_language)

        allowed = sorted(languages)
        self._report_submission_languages(allowed)
        return allowed

    def _report_submission_languages(self, allowed: List[str]) -> None:
        """Say out loud which languages students may submit in, and which were left
        out for lack of an accepted solution.

        This whitelist is *derived*, not authored, and it is a real restriction -- the
        MOJ API rejects submissions outside it. A setter who ships only a C++ solution
        gets a C++-only problem even though the package carries scripts for every
        configured language, so that consequence must never be silent.
        """
        if not allowed:
            # `_write_solutions` fails right after this with a precise error.
            return

        console.console.print(
            'MOJ will accept submissions in: '
            f'[item]{"[/item], [item]".join(allowed)}[/item].'
        )

        skipped = sorted(
            language
            for language in get_emitted_moj_languages()
            if language not in allowed
        )
        if not skipped:
            return
        console.console.print(
            f'[warning]Not enabling [item]{"[/item], [item]".join(skipped)}[/item]: '
            'no [item]ACCEPTED[/item] solution in those languages.[/warning]\n'
            '[warning]MOJ calibrates a time limit per language from the accepted '
            'solutions, so a language without one never gets a limit and students '
            'cannot submit in it. Add an accepted solution in a language to enable '
            'it.[/warning]'
        )

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

    def _write_metadata(self, into_path: pathlib.Path) -> None:
        (into_path / 'author').write_text(DEFAULT_AUTHOR)
        (into_path / 'tags').write_text('')
        self._write_moj_meta(into_path)

        docs_path = into_path / 'docs'
        docs_path.mkdir(parents=True, exist_ok=True)
        (docs_path / 'enunciado.md').write_text(DUMMY_STATEMENT)

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
            '# Output limit, in KB on both sides.',
            f'ULIMITS[-f]={pkg.outputLimit}',
            '',
            '# MOJ MEASURES the time limit; it is never authored. The judge runs every',
            '# sols/good solution, takes the worst time per language, and scales it by',
            '# this factor.',
            '# TODO(rbx): derive this from the authored timeLimit divided by the',
            '# measured model-solution runtime, so the calibrated limit lands near the',
            "# problem's own time limit instead of 1.35x the model solution.",
            'TLMOD[calibrafactor]=1.35',
            '',
        ]
        lines.extend(self._stopwhen_lines())
        (into_path / 'conf').write_text('\n'.join(lines))

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
        """
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

    # -- tests ----------------------------------------------------------------

    def _group_indices(self) -> Dict[str, int]:
        pkg = package.find_problem_package_or_die()
        return {group.name: index for index, group in enumerate(pkg.testcases)}

    def _write_tests(self, into_path: pathlib.Path) -> List[str]:
        """Write `tests/input` and `tests/output`; return the group names that got
        at least one test, in encounter order."""
        inputs_path = into_path / 'tests' / 'input'
        outputs_path = into_path / 'tests' / 'output'
        inputs_path.mkdir(parents=True, exist_ok=True)
        outputs_path.mkdir(parents=True, exist_ok=True)

        indices = self._group_indices()
        counters: Dict[str, int] = collections.defaultdict(int)
        seen_groups: List[str] = []
        has_sample = False

        for entry in self.get_built_testcase_entries():
            group_name = entry.group_entry.group
            if group_name not in counters:
                seen_groups.append(group_name)
            counters[group_name] += 1

            is_sample = entry.is_sample()
            has_sample = has_sample or is_sample
            name = naming.testcase_name(
                group_name,
                group_index=indices.get(group_name, 0),
                index=counters[group_name],
                is_sample=is_sample,
            )

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
            get_default_app_path() / 'packagers' / 'moj_next' / 'scripts' / 'compare.sh'
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

    def _solution_content(self, solution: Solution) -> bytes:
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

    def _write_solutions(self, into_path: pathlib.Path) -> None:
        sols_path = into_path / 'sols'
        written: Dict[str, Dict[str, pathlib.Path]] = collections.defaultdict(dict)

        for solution in package.get_solutions():
            tag = self._tag_for(solution)
            basename = solution.path.name
            if basename in written[tag]:
                console.console.print(
                    f'[error]Cannot package for MOJ: {solution.href()} and '
                    f'[item]{written[tag][basename]}[/item] would both be written to '
                    f'[item]sols/{tag}/{basename}[/item].[/error]\n'
                    '[error]MOJ derives the language from the file name, and Java '
                    'requires it to match the public class, so rbx will not rename '
                    'them. Give one of them a different file name.[/error]'
                )
                raise typer.Exit(1)
            written[tag][basename] = solution.path

            dest_path = sols_path / tag / basename
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            dest_path.write_bytes(self._solution_content(solution))

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
        templates_root = get_default_app_path() / 'packagers' / 'moj_next' / 'scripts'

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

        shutil.make_archive(str(build_path / self.package_basename()), 'zip', into_path)
        return (build_path / self.package_basename()).with_suffix('.zip')
