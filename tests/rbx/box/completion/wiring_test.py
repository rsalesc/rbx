"""Assert every issue #575 param resolves to its completer in the committed spec.

This guards the wiring (annotations._adapt(...) on CLI params) end-to-end: it
reads the regenerated _spec.py, so a removed/misspelled wiring fails here even if
drift_test stays green.
"""

import pytest

from rbx.box.completion import _spec


def _node(path):
    node = _spec.SPEC
    for token in path:
        node = next(
            c
            for c in node['children']
            if token in [s.strip() for s in c['name'].split(',')]
        )
    return node


def _arg_value(node):
    return next(p for p in node['params'] if p['kind'] == 'argument')['value']


def _opt_value(node, name):
    return next(
        p for p in node['params'] if p['kind'] == 'option' and name in p['names']
    )['value']


WIRINGS = [
    (['run'], 'arg', None, 'solutions', 'file'),
    (['irun'], 'arg', None, 'solutions', 'file'),
    (['run'], 'opt', '--outcome', 'outcome', None),
    (['irun'], 'opt', '--testcase', 'testgroup', None),
    (['build'], 'opt', '--verification-level', 'verification_level', None),
    (['time'], 'opt', '--profile', 'profile', None),
    (['stress'], 'opt', '--finder', 'solutions', 'file'),
    (['stress'], 'opt', '--fuzz-on', 'testgroup', None),
    (['stress'], 'opt', '--reference', 'solutions', 'file'),
    (['on'], 'arg', None, 'problem', None),
]


@pytest.mark.parametrize('path,kind,name,completer,file_flag', WIRINGS)
def test_param_wired_to_completer(path, kind, name, completer, file_flag):
    node = _node(path)
    value = _arg_value(node) if kind == 'arg' else _opt_value(node, name)
    assert value.get('kind') == 'completer'
    assert value.get('completer') == completer
    assert value.get('file') == file_flag


def test_contest_variant_flag_wired():
    value = _opt_value(_spec.SPEC, '-C')
    assert value.get('completer') == 'contest_variant'
