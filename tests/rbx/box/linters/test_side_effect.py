from rbx.box.linters.cpp.side_effect import SideEffectLinter
from rbx.box.linters.linter import LinterSeverity
from rbx.box.schema import CodeItem


def _lint(src: str):
    return SideEffectLinter().lint(CodeItem(path='gen.cpp'), src)


def _wrap(body: str) -> str:
    return 'void f() {\n' + body + '\n}\n'


def test_two_side_effect_args_warns():
    msgs = _lint(_wrap('some_function(rnd.next(), rnd.next());'))
    assert len(msgs) == 1
    assert msgs[0].severity is LinterSeverity.WARNING


def test_one_side_effect_arg_is_ok():
    assert _lint(_wrap('some_function(rnd.next(), 3);')) == []


def test_unknown_side_effect_func_not_flagged_v1():
    # fn_with_side_effect uses the SIDE_EFFECT macro, deferred to a follow-up.
    assert _lint(_wrap('some_function(fn_with_side_effect(), rnd.next());')) == []


def test_nested_call_is_flagged():
    msgs = _lint(_wrap('outer(g(rnd.next(), rnd.next()));'))
    assert len(msgs) == 1


def test_cout_chain_not_flagged():
    assert _lint(_wrap('std::cout << rnd.next() << rnd.next();')) == []


def test_clean_source_no_warnings():
    assert _lint(_wrap('int x = 1; some_function(x, x);')) == []


def test_message_has_location():
    msgs = _lint(_wrap('some_function(rnd.next(), rnd.next());'))
    assert msgs[0].line is not None and msgs[0].col is not None
