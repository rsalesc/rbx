from dataclasses import dataclass, field
from typing import Any, List

from rbx_boca import entrypoints


@dataclass
class _FakeTask:
    """Records calls to the BOCA lifecycle hooks and returns a canned code."""

    code: int = 0
    calls: List[Any] = field(default_factory=list)

    def compile(self, ctx, *, src, exe, basename):
        self.calls.append(('compile', src, exe, basename))
        return self.code

    def run(self, ctx, args):
        self.calls.append(('run', list(args)))
        return self.code

    def compare(self, ctx, args):
        self.calls.append(('compare', list(args)))
        return self.code


@dataclass
class _FakeLimits:
    time_sec: int
    runs: int
    memory_mb: int


@dataclass
class _FakeLang:
    limits: _FakeLimits


@dataclass
class _FakeTaskConfig:
    task_type: str
    output_kb: int


@dataclass
class _FakeCtx:
    task: _FakeTaskConfig
    lang: _FakeLang


def _fake_ctx(task_type='batch', output_kb=65536):
    return _FakeCtx(
        task=_FakeTaskConfig(task_type=task_type, output_kb=output_kb),
        lang=_FakeLang(limits=_FakeLimits(time_sec=3, runs=2, memory_mb=256)),
    )


def _install_fakes(monkeypatch, code=0):
    """Replace BatchTask/InteractiveTask with recording fakes; return them."""
    batch = _FakeTask(code=code)
    interactive = _FakeTask(code=code)
    monkeypatch.setattr(entrypoints, 'BatchTask', lambda: batch)
    monkeypatch.setattr(entrypoints, 'InteractiveTask', lambda: interactive)
    return batch, interactive


def test_dispatch_compile(monkeypatch):
    batch, interactive = _install_fakes(monkeypatch, code=7)
    ctx = _fake_ctx(task_type='batch')
    rc = entrypoints.main(
        ['compile', 'sol.cpp', 'run', '3', '256'], context_factory=lambda: ctx
    )
    assert rc == 7
    assert batch.calls == [('compile', 'sol.cpp', 'run', 'run')]
    assert interactive.calls == []


def test_dispatch_run(monkeypatch):
    batch, interactive = _install_fakes(monkeypatch, code=9)
    ctx = _fake_ctx(task_type='batch')
    rc = entrypoints.main(
        ['run', 'run', 'in', '3', '2', '256', '65536'], context_factory=lambda: ctx
    )
    assert rc == 9
    assert batch.calls == [('run', ['run', 'in', '3', '2', '256', '65536'])]


def test_dispatch_compare(monkeypatch):
    batch, interactive = _install_fakes(monkeypatch, code=6)
    ctx = _fake_ctx(task_type='batch')
    rc = entrypoints.main(
        ['compare', 'team.out', 'exp.out', 'in.txt'], context_factory=lambda: ctx
    )
    assert rc == 6
    assert batch.calls == [('compare', ['team.out', 'exp.out', 'in.txt'])]


def test_dispatch_interactive_task_type_selects_interactive_task(monkeypatch):
    batch, interactive = _install_fakes(monkeypatch, code=0)
    ctx = _fake_ctx(task_type='interactive')
    entrypoints.main(
        ['run', 'run', 'in', '3', '1', '256', '65536'], context_factory=lambda: ctx
    )
    assert interactive.calls == [('run', ['run', 'in', '3', '1', '256', '65536'])]
    assert batch.calls == []


def test_dispatch_limits(capsys):
    ctx = _fake_ctx(output_kb=65536)
    rc = entrypoints.main(['limits'], context_factory=lambda: ctx)
    assert rc == 0
    out = capsys.readouterr().out.split()
    assert out == ['3', '2', '256', '65536']


def test_dispatch_tests():
    ctx = _fake_ctx()
    assert entrypoints.main(['tests'], context_factory=lambda: ctx) == 0


def test_dispatch_unknown_entry_returns_nonzero():
    ctx = _fake_ctx()
    rc = entrypoints.main(['bogus'], context_factory=lambda: ctx)
    assert rc != 0


def test_dispatch_interactor_launcher(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        entrypoints.interactor_launcher,
        'launch',
        lambda argv, *, ittime, notify_fd: captured.update(
            argv=argv, ittime=ittime, notify_fd=notify_fd
        ),
    )
    rc = entrypoints.main(
        [
            '__interactor_launcher__',
            '7',
            '5',
            '--',
            './interactor.exe',
            'stdin0',
            'stdout0',
        ]
    )
    assert rc == 0
    assert captured['ittime'] == 7 and captured['notify_fd'] == 5
    assert captured['argv'] == ['./interactor.exe', 'stdin0', 'stdout0']


def test_interactor_launcher_does_not_require_context_factory(monkeypatch):
    # No context_factory passed and load_context must NOT be invoked.
    def _boom():
        raise AssertionError('load_context should not be called')

    monkeypatch.setattr(entrypoints, 'load_context', _boom)
    monkeypatch.setattr(
        entrypoints.interactor_launcher,
        'launch',
        lambda argv, *, ittime, notify_fd: None,
    )
    rc = entrypoints.main(['__interactor_launcher__', '1', '2', '--', './i.exe'])
    assert rc == 0
