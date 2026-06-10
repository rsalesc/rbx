from rbx.box.completion import completers, registry


def _ctx(**kw):
    base = dict(args=[], command=(), option_values={}, package_root=None)
    base.update(kw)
    return registry.CompletionContext(**base)


def test_language_completer_returns_config_languages():
    items = completers.complete_language(_ctx(), '')
    assert any(i.value for i in items)


def test_checker_completer_lists_bundled_checkers_without_boilerplate():
    values = {i.value for i in completers.complete_checker(_ctx(), '')}
    assert 'boilerplate.cpp' not in values
    assert any(v.endswith('.cpp') for v in values)


def test_problem_completer_reads_contest_problems(tmp_path):
    # package peek must not require pydantic; a minimal yaml is enough
    (tmp_path / 'contest.rbx.yml').write_text(
        'problems:\n  - short_name: A\n  - short_name: B\n'
    )
    values = {
        i.value for i in completers.complete_problem(_ctx(package_root=tmp_path), '')
    }
    assert {'A', 'B'} <= values


def test_solutions_completer_lists_paths_with_outcome_help_and_prefixes(tmp_path):
    (tmp_path / 'problem.rbx.yml').write_text(
        'solutions:\n'
        '  - path: sols/main.cpp\n'
        '    outcome: ac\n'
        '  - path: sols/wa.cpp\n'
        '    outcome: wa\n'
    )
    items = completers.complete_solutions(_ctx(package_root=tmp_path), '')
    by_value = {i.value: i for i in items}
    assert 'sols/main.cpp' in by_value
    assert by_value['sols/main.cpp'].help == 'ac'
    assert '@main' in by_value
    assert '@boca/' in by_value


def test_solutions_completer_without_package_offers_prefixes(tmp_path):
    values = {
        i.value for i in completers.complete_solutions(_ctx(package_root=None), '')
    }
    assert {'@main', '@boca/'} <= values
