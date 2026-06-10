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


def test_outcome_completer_offers_canonical_tokens():
    values = {i.value for i in completers.complete_outcome(_ctx(), '')}
    assert {'ac', 'wa', 'tle', 'any'} <= values
    helps = {i.value: i.help for i in completers.complete_outcome(_ctx(), '')}
    assert helps['ac']  # has descriptive help


def test_verification_level_completer_offers_int_values_with_names():
    items = completers.complete_verification_level(_ctx(), '')
    by_value = {i.value: i.help for i in items}
    assert by_value['0'] == 'NONE'
    assert by_value['4'] == 'FULL'


def test_profile_completer_lists_limits_files(tmp_path):
    limits = tmp_path / '.limits'
    limits.mkdir()
    (limits / 'local.yml').write_text('')
    (limits / 'codeforces.yml').write_text('')
    (limits / 'notes.txt').write_text('')  # ignored
    values = {
        i.value for i in completers.complete_profile(_ctx(package_root=tmp_path), '')
    }
    assert values == {'local', 'codeforces'}


def test_testgroup_completer_lists_group_names(tmp_path):
    (tmp_path / 'problem.rbx.yml').write_text(
        'testcases:\n  - name: samples\n  - name: main\n  - name: edge\n'
    )
    values = {
        i.value for i in completers.complete_testgroup(_ctx(package_root=tmp_path), '')
    }
    assert {'samples', 'main', 'edge'} <= values


def test_contest_variant_completer_lists_sibling_ids(tmp_path):
    (tmp_path / 'contest.rbx.yml').write_text('name: c\n')
    (tmp_path / 'contest.div1.rbx.yml').write_text('name: d1\n')
    (tmp_path / 'contest.div2.rbx.yml').write_text('name: d2\n')
    values = {
        i.value
        for i in completers.complete_contest_variant(_ctx(package_root=tmp_path), '')
    }
    assert values == {'div1', 'div2'}


def test_contest_variant_completer_walks_up_from_problem_dir(tmp_path):
    (tmp_path / 'contest.rbx.yml').write_text('name: c\n')
    (tmp_path / 'contest.div1.rbx.yml').write_text('name: d1\n')
    prob = tmp_path / 'A'
    prob.mkdir()
    (prob / 'problem.rbx.yml').write_text('name: A\n')
    values = {
        i.value
        for i in completers.complete_contest_variant(_ctx(package_root=prob), '')
    }
    assert values == {'div1'}


def test_problem_completer_includes_aliases(tmp_path):
    (tmp_path / 'contest.rbx.yml').write_text(
        'problems:\n  - short_name: A\n    aliases: [apple, alpha]\n  - short_name: B\n'
    )
    values = {
        i.value for i in completers.complete_problem(_ctx(package_root=tmp_path), '')
    }
    assert {'A', 'B', 'apple', 'alpha'} <= values
