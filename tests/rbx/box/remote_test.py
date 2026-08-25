import pathlib
from unittest import mock

import pytest
import typer

from rbx.box import package, remote
from rbx.box.runners.moj import cli
from rbx.box.runners.moj.cli import MojCliError
from rbx.box.schema import ExpectedOutcome
from rbx.box.testing import testing_package
from rbx.box.tooling.boca.scraper import BocaRun
from rbx.box.tooling.moj import api

# A submission id as MOJ issues one: an md5 digest.
_SUB = 'd89e6b7735c675fd7b50b3354ba64097'


class TestExpander:
    """Test the base Expander class."""

    def test_get_remote_path(self, testing_pkg: testing_package.TestingPackage):
        """Test get_remote_path returns correct path under remote directory."""
        expander = remote.MainExpander()
        test_path = pathlib.Path('test/path')

        result = expander.get_remote_path(test_path)

        # Should be under the problem remote directory
        assert result.parent.parent.name == '.remote'
        assert result.name == 'path'

    def test_cacheable_paths_default_empty(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test cacheable_paths returns empty list by default."""
        expander = remote.MainExpander()

        result = expander.cacheable_paths(pathlib.Path('test'))

        assert result == []

    def test_cacheable_globs_default_empty(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test cacheable_globs returns empty list by default."""
        expander = remote.MainExpander()

        result = expander.cacheable_globs(pathlib.Path('test'))

        assert result == []


class TestMainExpander:
    """Test the MainExpander class."""

    def test_expand_with_main_path(self, testing_pkg: testing_package.TestingPackage):
        """Test expand returns main solution path when given @main."""
        # Set up main solution
        testing_pkg.add_solution('sols/main.cpp', outcome=ExpectedOutcome.ACCEPTED)

        expander = remote.MainExpander()

        result = expander.expand(pathlib.Path('@main'))

        assert result == pathlib.Path('sols/main.cpp')

    def test_expand_with_non_main_path(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test expand returns None when path is not @main."""
        expander = remote.MainExpander()

        result = expander.expand(pathlib.Path('@other'))

        assert result is None

    def test_expand_with_no_main_solution(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test expand returns None when no main solution exists."""
        # Add a non-accepted solution
        testing_pkg.add_solution('sols/wa.cpp', outcome=ExpectedOutcome.WRONG_ANSWER)

        expander = remote.MainExpander()

        result = expander.expand(pathlib.Path('@main'))

        assert result is None


class TestBocaExpander:
    """Test the BocaExpander class."""

    def test_get_match_valid_run_with_site(self):
        """Test get_match parses valid BOCA run with site number."""
        expander = remote.BocaExpander()

        result = expander.get_match('@boca/123-2')

        assert result == (123, 2)

    def test_get_match_valid_run_without_site(self):
        """Test get_match parses valid BOCA run without site number (defaults to 1)."""
        expander = remote.BocaExpander()

        result = expander.get_match('@boca/456')

        assert result == (456, 1)

    def test_get_match_invalid_format(self):
        """Test get_match returns None for invalid format."""
        expander = remote.BocaExpander()

        result = expander.get_match('@invalid/format')

        assert result is None

    def test_get_match_non_boca_path(self):
        """Test get_match returns None for non-BOCA path."""
        expander = remote.BocaExpander()

        result = expander.get_match('@main')

        assert result is None

    def test_get_boca_path(self, testing_pkg: testing_package.TestingPackage):
        """Test get_boca_path returns correct path for run and site."""
        expander = remote.BocaExpander()

        result = expander.get_boca_path(123, 2)

        assert result.name == '123-2'
        assert result.parent.name == 'boca'

    def test_cacheable_globs_valid_boca_path(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test cacheable_globs returns correct glob pattern for valid BOCA path."""
        expander = remote.BocaExpander()

        result = expander.cacheable_globs(pathlib.Path('@boca/123-2'))

        assert len(result) == 1
        assert result[0].endswith('123-2.*')
        assert 'boca' in result[0]

    def test_cacheable_globs_invalid_path(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test cacheable_globs returns empty list for invalid path."""
        expander = remote.BocaExpander()

        result = expander.cacheable_globs(pathlib.Path('@main'))

        assert result == []

    @mock.patch('rbx.box.tooling.boca.scraper.get_boca_scraper')
    def test_expand_valid_boca_path(
        self, mock_get_scraper, testing_pkg: testing_package.TestingPackage
    ):
        """Test expand downloads and returns path for valid BOCA run."""
        # Mock the BOCA scraper
        mock_scraper = mock.MagicMock()
        mock_get_scraper.return_value = mock_scraper

        # Create a temporary file to simulate downloaded solution
        boca_folder = package.get_problem_remote_dir() / 'boca'
        boca_folder.mkdir(parents=True, exist_ok=True)
        downloaded_file = boca_folder / '123-2.cpp'

        mock_scraper.download_run.return_value = downloaded_file

        expander = remote.BocaExpander()

        result = expander.expand(pathlib.Path('@boca/123-2'))

        # Verify scraper was called correctly
        mock_scraper.login.assert_called_once()
        mock_scraper.download_run.assert_called_once_with(
            BocaRun.from_run_number(123, 2), expander.get_boca_folder()
        )

        assert result == downloaded_file

    def test_expand_invalid_boca_path(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test expand returns None for invalid BOCA path."""
        expander = remote.BocaExpander()

        result = expander.expand(pathlib.Path('@main'))

        assert result is None


class TestExpandFiles:
    """Test the expand_files function."""

    def test_expand_files_normal_paths(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test expand_files passes through normal paths unchanged."""
        files = ['normal.cpp', 'another.cpp']

        result = remote.expand_files(files)

        assert result == [pathlib.Path('normal.cpp'), pathlib.Path('another.cpp')]

    def test_expand_files_with_main_expansion(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test expand_files expands @main to main solution."""
        # Set up main solution
        testing_pkg.add_solution('sols/main.cpp', outcome=ExpectedOutcome.ACCEPTED)

        files = ['normal.cpp', '@main']

        result = remote.expand_files(files)

        assert result == [pathlib.Path('normal.cpp'), pathlib.Path('sols/main.cpp')]

    def test_expand_files_with_unexpandable_paths(
        self, testing_pkg: testing_package.TestingPackage, capsys
    ):
        """Test expand_files skips unexpandable paths and prints warning."""
        files = ['normal.cpp', '@unknown']

        result = remote.expand_files(files)

        # Should skip the unexpandable path
        assert result == [pathlib.Path('normal.cpp')]

        # Should print a warning
        captured = capsys.readouterr()
        assert 'could not be expanded' in captured.out

    def test_expand_files_with_cached_file(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test expand_files uses cached file when available."""
        # Create a cached file for BOCA expansion
        remote_dir = package.get_problem_remote_dir()
        boca_folder = remote_dir / 'boca'
        boca_folder.mkdir(parents=True, exist_ok=True)
        cached_file = boca_folder / '123-2.cpp'
        cached_file.write_text('cached content')

        files = ['@boca/123-2']

        result = remote.expand_files(files)

        # Should return the cached file path relative to package
        assert result == [testing_pkg.relpath(cached_file)]
        assert cached_file.read_text() == 'cached content'

    def test_expand_files_mixed_paths(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test expand_files handles mixed normal and remote paths."""
        # Set up main solution
        testing_pkg.add_solution('sols/main.cpp', outcome=ExpectedOutcome.ACCEPTED)

        files = ['normal1.cpp', '@main', 'normal2.cpp']

        result = remote.expand_files(files)

        assert result == [
            pathlib.Path('normal1.cpp'),
            pathlib.Path('sols/main.cpp'),
            pathlib.Path('normal2.cpp'),
        ]

    @mock.patch('rbx.box.cd.is_problem_package')
    def test_expand_files_not_in_package(
        self, mock_is_problem_package, testing_pkg: testing_package.TestingPackage
    ):
        """Test expand_files exits when not in a problem package."""
        mock_is_problem_package.return_value = False

        with pytest.raises(typer.Exit):
            remote.expand_files(['@main'])


class TestExpandFile:
    """Test the expand_file function."""

    def test_expand_file_single_result(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test expand_file returns single expanded file."""
        # Set up main solution
        testing_pkg.add_solution('sols/main.cpp', outcome=ExpectedOutcome.ACCEPTED)

        result = remote.expand_file('@main')

        assert result == pathlib.Path('sols/main.cpp')

    def test_expand_file_no_expansion(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test expand_file exits when expansion fails."""
        with pytest.raises(typer.Exit):
            remote.expand_file('@unknown')

    def test_expand_file_multiple_results(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test expand_file exits when multiple results returned (shouldn't happen in practice)."""
        # This is a bit artificial since expand_files normally returns one result per input
        # but we test the error handling
        with mock.patch.object(remote, 'expand_files') as mock_expand:
            mock_expand.return_value = [
                pathlib.Path('file1.cpp'),
                pathlib.Path('file2.cpp'),
            ]

            with pytest.raises(typer.Exit):
                remote.expand_file('@test')


class TestIsPathRemote:
    """Test the is_path_remote function."""

    def test_is_path_remote_true(self, testing_pkg: testing_package.TestingPackage):
        """Test is_path_remote returns True for paths under remote directory."""
        remote_dir = package.get_problem_remote_dir()
        remote_file = remote_dir / 'test.cpp'
        remote_file.parent.mkdir(parents=True, exist_ok=True)
        remote_file.write_text('test content')

        result = remote.is_path_remote(remote_file)

        assert result is True

    def test_is_path_remote_false(self, testing_pkg: testing_package.TestingPackage):
        """Test is_path_remote returns False for paths outside remote directory."""
        local_file = testing_pkg.path('local.cpp')
        local_file.write_text('local content')

        result = remote.is_path_remote(local_file)

        assert result is False

    def test_is_path_remote_relative_path(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test is_path_remote works with relative paths."""
        # Create a file in the remote directory
        remote_dir = package.get_problem_remote_dir()
        remote_file = remote_dir / 'test.cpp'
        remote_file.parent.mkdir(parents=True, exist_ok=True)
        remote_file.write_text('test content')

        # Test with the actual relative path to the remote file
        result = remote.is_path_remote(remote_file)

        assert result is True


class TestBocaRegex:
    """Test the BOCA_REGEX pattern."""

    def test_boca_regex_with_site(self):
        """Test BOCA_REGEX matches pattern with site number."""
        match = remote.BocaExpander.BOCA_REGEX.match('@boca/123-2')

        assert match is not None
        assert match.group(1) == '123'
        assert match.group(2) == '2'

    def test_boca_regex_without_site(self):
        """Test BOCA_REGEX matches pattern without site number."""
        match = remote.BocaExpander.BOCA_REGEX.match('@boca/456')

        assert match is not None
        assert match.group(1) == '456'
        assert match.group(2) is None

    def test_boca_regex_invalid_format(self):
        """Test BOCA_REGEX doesn't match invalid format."""
        match = remote.BocaExpander.BOCA_REGEX.match('@boca/invalid')

        assert match is None

    def test_boca_regex_non_boca_path(self):
        """Test BOCA_REGEX doesn't match non-BOCA paths."""
        match = remote.BocaExpander.BOCA_REGEX.match('@main')

        assert match is None


class TestMojExpander:
    """`@moj/<contest>/<submission>`."""

    def _who(self, login: str = 'ana.judge', **flags):
        return cli.ContestWhoami(login=login, **flags)

    # -- Parsing the reference. ------------------------------------------------

    def test_get_match_reads_the_contest_and_the_submission(self):
        expander = remote.MojExpander()

        assert expander.get_match(f'@moj/sbc2026/{_SUB}') == ('sbc2026', _SUB)

    def test_get_match_falls_back_to_moj_contest(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv('MOJ_CONTEST', 'sbc2026')
        expander = remote.MojExpander()

        assert expander.get_match(f'@moj/{_SUB}') == ('sbc2026', _SUB)

    def test_the_explicit_contest_wins_over_the_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """A reference committed to `problem.rbx.yml` has to mean one thing."""
        monkeypatch.setenv('MOJ_CONTEST', 'somewhere-else')
        expander = remote.MojExpander()

        assert expander.get_match(f'@moj/sbc2026/{_SUB}') == ('sbc2026', _SUB)

    def test_the_shorthand_without_moj_contest_says_what_is_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.delenv('MOJ_CONTEST', raising=False)
        expander = remote.MojExpander()

        with pytest.raises(MojCliError) as exc_info:
            expander.get_match(f'@moj/{_SUB}')
        assert 'MOJ_CONTEST' in str(exc_info.value)

    def test_a_malformed_id_is_refused_rather_than_ignored(self):
        """Refused, not passed over: the reference is plainly addressed here.

        Returning `None` would make the engine report "not a valid expansion",
        which describes the outcome and not the mistake. And the id rule is the
        server's own -- MOJ answers `400 id_invalid` -- so checking it locally
        costs a round-trip rather than buying one.
        """
        expander = remote.MojExpander()

        with pytest.raises(MojCliError) as exc_info:
            expander.get_match('@moj/sbc2026/123')
        assert '32' in str(exc_info.value)

    def test_an_uppercase_digest_is_not_a_submission_id(self):
        """MOJ generates the id with `md5`, and matches it lowercase."""
        expander = remote.MojExpander()

        with pytest.raises(MojCliError):
            expander.get_match(f'@moj/sbc2026/{_SUB.upper()}')

    def test_get_match_ignores_other_expanders_references(self):
        expander = remote.MojExpander()

        assert expander.get_match('@boca/123') is None
        assert expander.get_match('@main') is None
        assert expander.get_match('sols/main.cpp') is None

    # -- Caching. --------------------------------------------------------------

    def test_cacheable_globs_cover_any_extension(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """The extension is only known after the listing, so the glob spans them."""
        expander = remote.MojExpander()

        globs = expander.cacheable_globs(pathlib.Path(f'@moj/sbc2026/{_SUB}'))

        assert len(globs) == 1
        assert globs[0].endswith(f'moj/sbc2026/{_SUB}.*')

    # -- Downloading. ----------------------------------------------------------

    def test_expand_downloads_the_source_under_the_right_extension(
        self, testing_pkg: testing_package.TestingPackage, monkeypatch
    ):
        row = api.SubmissionRow(
            subid=_SUB, lang='cpp', epoch=1755000000, verdict='Accepted'
        )
        monkeypatch.setattr(
            remote.cli, 'contest_whoami', lambda c: self._who(is_judge=True)
        )
        monkeypatch.setattr(remote.api, 'read_token', lambda c: 'tok')
        monkeypatch.setattr(
            remote.api, 'list_submissions', lambda c, t, any_submission: {_SUB: row}
        )
        monkeypatch.setattr(
            remote.api, 'download_source', lambda c, t, r: 'int main(){}\n'
        )

        result = remote.MojExpander().expand(pathlib.Path(f'@moj/sbc2026/{_SUB}'))

        assert result is not None
        assert result.name == f'{_SUB}.cpp'
        assert result.read_text() == 'int main(){}\n'

    def test_a_judge_is_asked_for_every_submission(
        self, testing_pkg: testing_package.TestingPackage, monkeypatch
    ):
        """The two listing endpoints are not interchangeable.

        `/contest/allsubmissions` answers `403 judge_required` to a competitor, and
        `/contest/history` never carries anyone else's rows -- so the role decides
        which one can be asked at all.
        """
        seen = {}
        row = api.SubmissionRow(
            subid=_SUB, lang='cpp', epoch=1755000000, verdict='Accepted'
        )

        def fake_list(contest, token, any_submission):
            seen['any'] = any_submission
            return {_SUB: row}

        monkeypatch.setattr(
            remote.cli, 'contest_whoami', lambda c: self._who(is_judge=True)
        )
        monkeypatch.setattr(remote.api, 'read_token', lambda c: 'tok')
        monkeypatch.setattr(remote.api, 'list_submissions', fake_list)
        monkeypatch.setattr(remote.api, 'download_source', lambda c, t, r: 'x\n')

        remote.MojExpander().expand(pathlib.Path(f'@moj/sbc2026/{_SUB}'))

        assert seen['any'] is True

    def test_a_competitor_is_asked_only_for_their_own(
        self, testing_pkg: testing_package.TestingPackage, monkeypatch
    ):
        seen = {}
        row = api.SubmissionRow(
            subid=_SUB, lang='cpp', epoch=1755000000, verdict='Accepted'
        )

        def fake_list(contest, token, any_submission):
            seen['any'] = any_submission
            return {_SUB: row}

        monkeypatch.setattr(remote.cli, 'contest_whoami', lambda c: self._who('ana'))
        monkeypatch.setattr(remote.api, 'read_token', lambda c: 'tok')
        monkeypatch.setattr(remote.api, 'list_submissions', fake_list)
        monkeypatch.setattr(remote.api, 'download_source', lambda c, t, r: 'x\n')

        remote.MojExpander().expand(pathlib.Path(f'@moj/sbc2026/{_SUB}'))

        assert seen['any'] is False

    def test_an_unknown_id_is_reported_before_the_download(
        self, testing_pkg: testing_package.TestingPackage, monkeypatch
    ):
        """The download would answer a bare 404 that cannot say which case it is."""
        downloaded = []
        monkeypatch.setattr(remote.cli, 'contest_whoami', lambda c: self._who('ana'))
        monkeypatch.setattr(remote.api, 'read_token', lambda c: 'tok')
        monkeypatch.setattr(
            remote.api, 'list_submissions', lambda c, t, any_submission: {}
        )
        monkeypatch.setattr(
            remote.api,
            'download_source',
            lambda c, t, r: downloaded.append(r) or 'x\n',
        )

        with pytest.raises(MojCliError) as exc_info:
            remote.MojExpander().expand(pathlib.Path(f'@moj/sbc2026/{_SUB}'))

        message = str(exc_info.value)
        assert _SUB in message
        assert 'ana' in message
        # A competitor is told what would let them read someone else's.
        assert 'judge account' in message
        assert not downloaded

    def test_an_unknown_language_falls_back_to_mojs_own_id(
        self, testing_pkg: testing_package.TestingPackage, monkeypatch
    ):
        """What MOJ's web UI names the download, when rbx claims no such language."""
        row = api.SubmissionRow(
            subid=_SUB, lang='Kt', epoch=1755000000, verdict='Accepted'
        )
        monkeypatch.setattr(
            remote.cli, 'contest_whoami', lambda c: self._who(is_judge=True)
        )
        monkeypatch.setattr(remote.api, 'read_token', lambda c: 'tok')
        monkeypatch.setattr(
            remote.api, 'list_submissions', lambda c, t, any_submission: {_SUB: row}
        )
        monkeypatch.setattr(remote.api, 'download_source', lambda c, t, r: 'fun main\n')

        result = remote.MojExpander().expand(pathlib.Path(f'@moj/sbc2026/{_SUB}'))

        assert result is not None
        assert result.name == f'{_SUB}.kt'

    def test_expand_ignores_a_reference_that_is_not_ours(
        self, testing_pkg: testing_package.TestingPackage
    ):
        assert remote.MojExpander().expand(pathlib.Path('@boca/123')) is None

    def test_the_download_needs_review(self):
        """Third-party code entering the package, exactly as with BOCA."""
        assert remote.MojExpander().needs_review()

    def test_a_submission_still_being_judged_is_not_downloaded(
        self, testing_pkg: testing_package.TestingPackage, monkeypatch
    ):
        """Observed live on 2026-08-24, and the reason this check exists.

        MOJ archives the source only after the judging daemon produces a verdict,
        so asking for a pending one gets `404 source_notfound` -- byte for byte
        the reply for an id that does not exist, about a submission rbx has just
        listed. Saying "still judging" is the difference between waiting a moment
        and hunting for a wrong id.
        """
        downloaded = []
        row = api.SubmissionRow(
            subid=_SUB, lang='cpp', epoch=1755000000, verdict='Not Answered Yet'
        )
        monkeypatch.setattr(
            remote.cli, 'contest_whoami', lambda c: self._who(is_judge=True)
        )
        monkeypatch.setattr(remote.api, 'read_token', lambda c: 'tok')
        monkeypatch.setattr(
            remote.api, 'list_submissions', lambda c, t, any_submission: {_SUB: row}
        )
        monkeypatch.setattr(
            remote.api,
            'download_source',
            lambda c, t, r: downloaded.append(r) or 'x\n',
        )

        with pytest.raises(MojCliError) as exc_info:
            remote.MojExpander().expand(pathlib.Path(f'@moj/sbc2026/{_SUB}'))

        assert 'still judging' in str(exc_info.value)
        assert not downloaded

    # -- Reusing the listing. --------------------------------------------------

    def _rows(self, *subids: str, verdict: str = 'Accepted'):
        return {
            subid: api.SubmissionRow(
                subid=subid, lang='cpp', epoch=1755000000, verdict=verdict
            )
            for subid in subids
        }

    def _serve(self, monkeypatch, rows, who=None, source='x\n'):
        """One fake MOJ, counting what each expansion actually asks of it."""
        asked = {'listing': 0, 'whoami': 0, 'source': 0}

        def fake_whoami(contest):
            asked['whoami'] += 1
            return who if who is not None else self._who(is_judge=True)

        def fake_list(contest, token, any_submission):
            asked['listing'] += 1
            return dict(rows)

        def fake_source(contest, token, row):
            asked['source'] += 1
            return source(row) if callable(source) else source

        monkeypatch.setattr(remote.cli, 'contest_whoami', fake_whoami)
        monkeypatch.setattr(remote.api, 'read_token', lambda c: 'tok')
        monkeypatch.setattr(remote.api, 'list_submissions', fake_list)
        monkeypatch.setattr(remote.api, 'download_source', fake_source)
        return asked

    def _listing_cache(self) -> pathlib.Path:
        return (
            package.get_problem_remote_dir()
            / 'moj'
            / 'sbc2026'
            / remote.MojExpander.LISTING_CACHE_NAME
        )

    def test_a_listing_answers_every_submission_it_carries(
        self, testing_pkg: testing_package.TestingPackage, monkeypatch
    ):
        """The whole listing is kept, not just the row that was asked for.

        A fresh expander downloads the second one on purpose: what makes it free
        is the file on disk, so it has to outlive the process that wrote it.
        """
        other = 'a' * 32
        asked = self._serve(monkeypatch, self._rows(_SUB, other))

        remote.MojExpander().expand(pathlib.Path(f'@moj/sbc2026/{_SUB}'))
        remote.MojExpander().expand(pathlib.Path(f'@moj/sbc2026/{other}'))

        assert asked['listing'] == 1
        assert asked['source'] == 2

    def test_a_cached_row_costs_neither_a_listing_nor_a_subprocess(
        self, testing_pkg: testing_package.TestingPackage, monkeypatch
    ):
        """`whoami` is a subprocess, and a settled row needs nothing it answers."""
        asked = self._serve(monkeypatch, self._rows(_SUB))
        remote.MojExpander().expand(pathlib.Path(f'@moj/sbc2026/{_SUB}'))
        before = dict(asked)

        remote.MojExpander().expand(pathlib.Path(f'@moj/sbc2026/{_SUB}'))

        assert asked['listing'] == before['listing']
        assert asked['whoami'] == before['whoami']
        assert asked['source'] == before['source'] + 1

    def test_a_pending_row_is_never_served_from_the_cache(
        self, testing_pkg: testing_package.TestingPackage, monkeypatch
    ):
        """Its verdict is still moving, and the source only exists once it stops."""
        pending = self._serve(monkeypatch, self._rows(_SUB, verdict='On queue'))
        with pytest.raises(MojCliError):
            remote.MojExpander().expand(pathlib.Path(f'@moj/sbc2026/{_SUB}'))
        assert pending['listing'] == 1

        judged = self._serve(monkeypatch, self._rows(_SUB))
        result = remote.MojExpander().expand(pathlib.Path(f'@moj/sbc2026/{_SUB}'))

        assert result is not None
        assert judged['listing'] == 1

    def test_a_submission_the_cache_does_not_carry_is_asked_for(
        self, testing_pkg: testing_package.TestingPackage, monkeypatch
    ):
        """A miss is the whole reason the server still gets asked."""
        other = 'a' * 32
        first = self._serve(monkeypatch, self._rows(other))
        remote.MojExpander().expand(pathlib.Path(f'@moj/sbc2026/{other}'))
        assert first['listing'] == 1

        second = self._serve(monkeypatch, self._rows(other, _SUB))
        result = remote.MojExpander().expand(pathlib.Path(f'@moj/sbc2026/{_SUB}'))

        assert result is not None
        assert second['listing'] == 1

    def test_a_miss_asks_the_server_once_per_run(
        self, testing_pkg: testing_package.TestingPackage, monkeypatch
    ):
        """A second miss milliseconds later is not a different question."""
        asked = self._serve(monkeypatch, self._rows('a' * 32))
        expander = remote.MojExpander()

        for _ in range(2):
            with pytest.raises(MojCliError):
                expander.expand(pathlib.Path(f'@moj/sbc2026/{_SUB}'))

        assert asked['listing'] == 1
        assert asked['whoami'] == 1

    def test_a_cached_row_that_no_longer_downloads_falls_back_to_the_listing(
        self, testing_pkg: testing_package.TestingPackage, monkeypatch
    ):
        """The refusal MOJ gives here has no name; the listing path has one.

        A source download that fails against a cached row says only `404
        source_notfound` -- which is what MOJ answers for a submission that was
        never yours as much as for one that never existed. So the row is dropped
        and the question is put to the listing, which knows how to say it.
        """
        self._serve(monkeypatch, self._rows(_SUB))
        remote.MojExpander().expand(pathlib.Path(f'@moj/sbc2026/{_SUB}'))

        def refuse(row):
            raise MojCliError('MOJ answered 404 for `/submission/source`.')

        asked = self._serve(monkeypatch, {}, who=self._who('ana'), source=refuse)

        with pytest.raises(MojCliError) as exc_info:
            remote.MojExpander().expand(pathlib.Path(f'@moj/sbc2026/{_SUB}'))

        message = str(exc_info.value)
        assert 'has no submission' in message
        assert 'ana' in message
        assert asked['listing'] == 1
        # And the row is gone, so the next run does not pay for it again.
        assert _SUB not in self._listing_cache().read_text()

    def test_an_unreadable_cache_reads_as_no_cache(
        self, testing_pkg: testing_package.TestingPackage, monkeypatch
    ):
        """Half-written, older, corrupt -- all of it means "ask MOJ"."""
        asked = self._serve(monkeypatch, self._rows(_SUB))
        remote.MojExpander().expand(pathlib.Path(f'@moj/sbc2026/{_SUB}'))
        self._listing_cache().write_text('{"rows": {"broken')

        result = remote.MojExpander().expand(pathlib.Path(f'@moj/sbc2026/{_SUB}'))

        assert result is not None
        assert asked['listing'] == 2

    def test_a_row_that_failed_to_download_is_dropped_even_if_moj_is_down(
        self, testing_pkg: testing_package.TestingPackage, monkeypatch
    ):
        """Otherwise a poisoned row costs a doomed request on every later run.

        The listing that would have replaced it cannot be fetched either -- the
        network is the thing that is broken -- so nothing else is going to take
        the bad row out of the cache.
        """
        self._serve(monkeypatch, self._rows(_SUB))
        remote.MojExpander().expand(pathlib.Path(f'@moj/sbc2026/{_SUB}'))
        assert _SUB in self._listing_cache().read_text()

        def unreachable(*args, **kwargs):
            raise MojCliError('Could not reach MOJ at `https://moj.example`.')

        self._serve(monkeypatch, {}, source=unreachable)
        monkeypatch.setattr(remote.api, 'list_submissions', unreachable)

        with pytest.raises(MojCliError):
            remote.MojExpander().expand(pathlib.Path(f'@moj/sbc2026/{_SUB}'))

        assert _SUB not in self._listing_cache().read_text()
