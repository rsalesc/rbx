import pathlib
from unittest import mock

from rbx.box.presets import _collect_expansions, _expand_content, _should_expand_file
from rbx.box.presets.schema import ReplacementMode, VariableExpansion


class TestShouldExpandFile:
    def test_regular_text_file(self, tmp_path):
        f = tmp_path / 'hello.txt'
        f.write_text('hello world')
        content = f.read_bytes()
        assert _should_expand_file(f, content) is True

    def test_symlink_excluded(self, tmp_path):
        target = tmp_path / 'target.txt'
        target.write_text('hello')
        link = tmp_path / 'link.txt'
        link.symlink_to(target)
        content = target.read_bytes()
        assert _should_expand_file(link, content) is False

    def test_binary_file_excluded(self, tmp_path):
        f = tmp_path / 'binary.bin'
        f.write_bytes(b'hello\x00world')
        content = f.read_bytes()
        assert _should_expand_file(f, content) is False

    def test_large_file_excluded(self, tmp_path):
        f = tmp_path / 'large.txt'
        content = b'a' * (1024 * 1024 + 1)
        f.write_bytes(content)
        assert _should_expand_file(f, content) is False

    def test_exactly_1024kb_included(self, tmp_path):
        f = tmp_path / 'exact.txt'
        content = b'a' * (1024 * 1024)
        f.write_bytes(content)
        assert _should_expand_file(f, content) is True


class TestExpandContent:
    def test_simple_replacement(self):
        content = b'Hello __NAME__, welcome!'
        expansions = [('__NAME__', 'Alice', [])]
        result = _expand_content(content, expansions, pathlib.PurePosixPath('file.txt'))
        assert result == b'Hello Alice, welcome!'

    def test_multiple_replacements(self):
        content = b'__A__ and __B__'
        expansions = [('__A__', 'X', []), ('__B__', 'Y', [])]
        result = _expand_content(content, expansions, pathlib.PurePosixPath('file.txt'))
        assert result == b'X and Y'

    def test_glob_match_applies(self):
        content = b'Hello __NAME__!'
        expansions = [('__NAME__', 'Alice', ['*.txt'])]
        result = _expand_content(
            content, expansions, pathlib.PurePosixPath('readme.txt')
        )
        assert result == b'Hello Alice!'

    def test_glob_no_match_skips(self):
        content = b'Hello __NAME__!'
        expansions = [('__NAME__', 'Alice', ['*.py'])]
        result = _expand_content(
            content, expansions, pathlib.PurePosixPath('readme.txt')
        )
        assert result == b'Hello __NAME__!'

    def test_empty_glob_matches_all(self):
        content = b'Hello __NAME__!'
        expansions = [('__NAME__', 'Alice', [])]
        result = _expand_content(
            content, expansions, pathlib.PurePosixPath('any/path/file.xyz')
        )
        assert result == b'Hello Alice!'

    def test_multiple_occurrences_replaced(self):
        content = b'__X__ is __X__'
        expansions = [('__X__', 'Y', [])]
        result = _expand_content(content, expansions, pathlib.PurePosixPath('f.txt'))
        assert result == b'Y is Y'

    def test_nested_path_glob(self):
        content = b'__NAME__'
        expansions = [('__NAME__', 'val', ['subdir/*.tex'])]
        result = _expand_content(
            content, expansions, pathlib.PurePosixPath('subdir/main.tex')
        )
        assert result == b'val'


class TestCollectExpansions:
    def test_prompt_mode_asks_user(self):
        expansions = [
            VariableExpansion(
                needle='__NAME__',
                replacement=ReplacementMode.PROMPT,
                prompt='Enter the problem name:',
            ),
        ]
        with mock.patch('rbx.box.presets.questionary') as mock_q:
            mock_q.text.return_value.ask.return_value = 'my-problem'
            result = _collect_expansions(expansions)

        assert result == [('__NAME__', 'my-problem', [])]
        mock_q.text.assert_called_once_with('Enter the problem name:')

    def test_multiple_expansions(self):
        expansions = [
            VariableExpansion(
                needle='__A__',
                prompt='A?',
                glob=['*.txt'],
            ),
            VariableExpansion(
                needle='__B__',
                prompt='B?',
            ),
        ]
        with mock.patch('rbx.box.presets.questionary') as mock_q:
            mock_q.text.return_value.ask.side_effect = ['val_a', 'val_b']
            result = _collect_expansions(expansions)

        assert result == [
            ('__A__', 'val_a', ['*.txt']),
            ('__B__', 'val_b', []),
        ]

    def test_empty_expansions(self):
        result = _collect_expansions([])
        assert result == []
