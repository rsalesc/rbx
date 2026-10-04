import pathlib
import threading

from mkdocs_review.builds import FAILED, READY, Builder, BuiltSite


def _site(sha):
    return BuiltSite(pathlib.Path(sha), {'index.html'}, {})


def test_background_queue_skips_snapshots_already_built():
    built = []

    def build(sha):
        built.append(sha)
        return _site(sha)

    builder = Builder(build)
    builder.add('a', _site('a'))
    builder.enqueue(['b', 'c', 'a'])
    assert builder.wait('c', timeout=5) == READY
    assert built == ['b', 'c']
    assert builder.sites['a'].root == pathlib.Path('a')
    assert builder.status == {'a': READY, 'b': READY, 'c': READY}


def test_prioritize_jumps_the_queue():
    started, gate = threading.Event(), threading.Event()
    built = []

    def build(sha):
        if sha == 'first':
            started.set()
            gate.wait(5)
        built.append(sha)
        return _site(sha)

    builder = Builder(build)
    builder.enqueue(['first', 'x', 'y', 'z'])
    assert started.wait(5)
    builder.prioritize('z')
    gate.set()
    assert builder.wait('y', timeout=5) == READY
    assert built == ['first', 'z', 'x', 'y']


def test_failures_are_reported_and_can_be_retried():
    attempts = []

    def build(sha):
        attempts.append(sha)
        if len(attempts) == 1:
            raise RuntimeError('boom')
        return _site(sha)

    builder = Builder(build)
    builder.enqueue(['a'])
    assert builder.wait('a', timeout=5) == FAILED
    assert builder.errors == {'a': 'boom'}
    builder.prioritize('a')
    assert builder.wait('a', timeout=5) == READY
    assert builder.errors == {}
