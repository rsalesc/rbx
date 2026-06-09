from rbx.box.completion import entry


def test_returns_false_when_not_completing(monkeypatch, capsys):
    monkeypatch.delenv(entry.COMPLETE_VAR, raising=False)
    assert entry.handle_completion() is False
    assert capsys.readouterr().out == ''


def test_complete_bash_writes_root_completions(monkeypatch, capsys):
    monkeypatch.setenv(entry.COMPLETE_VAR, 'complete_bash')
    monkeypatch.setenv('_TYPER_COMPLETE_ARGS', 'rbx ')
    monkeypatch.setenv('COMP_WORDS', 'rbx ')
    monkeypatch.setenv('COMP_CWORD', '1')
    assert entry.handle_completion() is True
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert 'plain,ui' in lines


def test_source_bash_writes_install_script(monkeypatch, capsys):
    monkeypatch.setenv(entry.COMPLETE_VAR, 'source_bash')
    assert entry.handle_completion() is True
    out = capsys.readouterr().out
    assert out.strip(), 'expected a non-empty source script'
    assert '_rbx_completion' in out or 'complete ' in out


def test_unknown_instruction_writes_nothing(monkeypatch, capsys):
    monkeypatch.setenv(entry.COMPLETE_VAR, 'bogus_bash')
    assert entry.handle_completion() is True
    assert capsys.readouterr().out == ''
