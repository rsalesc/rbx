from rbx.box.presets import _should_expand_file


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
