import pathlib

import pytest

from rbx.box import promotion_plan as pp
from rbx.box import promotion_sinks as sinks
from rbx.box.schema import GeneratorScript
from rbx.box.testing import testing_package


def _read(pkg: testing_package.TestingPackage, rel: str) -> str:
    return (pkg.root / rel).read_text()


def _write(pkg: testing_package.TestingPackage, rel: str, text: str) -> None:
    path = pkg.root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


async def _promote(selectors, sink_name, **kwargs) -> pp.Plan:
    sources = await pp.resolve_sources(selectors)
    sink = sinks.find_sink(sink_name)
    assert sink is not None, sink_name
    plan = await pp.plan_promotion(sources, sink, **kwargs)
    pp.apply_plan(plan)
    return plan


# --- sinks ---------------------------------------------------------------------


def test_sinks_are_globs_and_txt_plans(testing_pkg: testing_package.TestingPackage):
    testing_pkg.add_testgroup_from_glob('samples', 'tests/samples/*.in')
    testing_pkg.add_testgroup_from_plan('main', 'gen 1\n')
    testing_pkg.add_testgroup_with_manual_testcases('inline', [])

    assert [(s.name, s.kind, s.path, s.scope) for s in sinks.list_sinks()] == [
        ('samples', 'glob', 'tests/samples/*.in', None),
        ('main', 'plan', 'testplan/main.txt', None),
    ]


def test_a_shared_script_scopes_each_group_to_its_testgroup(
    testing_pkg: testing_package.TestingPackage,
):
    _write(testing_pkg, 'tests/plan.txt', 'gen 1\n')
    testing_pkg.yml.generatorScript = GeneratorScript(
        path=pathlib.Path('tests/plan.txt')
    )
    testing_pkg.yml.testcases = testing_pkg.yml.testcases + [
        testing_package.TestcaseGroup(name='main'),
        testing_package.TestcaseGroup(name='large'),
    ]
    testing_pkg.save()

    assert [(s.name, s.kind, s.scope) for s in sinks.list_sinks()] == [
        ('main', 'plan', 'main'),
        ('large', 'plan', 'large'),
    ]


def test_subgroups_are_sinks_too(testing_pkg: testing_package.TestingPackage):
    _write(testing_pkg, 'tests/big.txt', 'gen 1\n')
    testing_pkg.yml.testcases = [
        testing_package.TestcaseGroup(
            name='main',
            subgroups=[
                testing_package.TestcaseSubgroup(
                    name='small', testcaseGlob='tests/small/*.in'
                ),
                testing_package.TestcaseSubgroup(
                    name='big',
                    generatorScript=GeneratorScript(path=pathlib.Path('tests/big.txt')),
                ),
            ],
        )
    ]
    testing_pkg.save()

    assert [(s.name, s.kind) for s in sinks.list_sinks()] == [
        ('main/small', 'glob'),
        ('main/big', 'plan'),
    ]


# --- @copy paths ------------------------------------------------------------------


def test_copy_pattern_is_inferred_from_sibling_copies(
    testing_pkg: testing_package.TestingPackage,
):
    testing_pkg.add_testgroup_from_plan(
        'main',
        '@copy tests/edge/edge-001.in\ngen 1\n@copy tests/edge/edge-007.in\n',
    )
    sink = sinks.find_sink('main')
    assert sink is not None

    pattern = sinks.suggest_copy_pattern(sink)
    assert pattern == 'tests/edge/edge-*.in'
    taken = sinks.copy_siblings(sink, sinks.read_script(sink))
    assert sinks.allocate_stems(pattern, 2, taken=taken) == ['008', '009']


def test_copy_pattern_falls_back_to_a_folder_per_group(
    testing_pkg: testing_package.TestingPackage,
):
    testing_pkg.add_testgroup_from_plan('main', 'gen 1\n')
    sink = sinks.find_sink('main')
    assert sink is not None

    assert sinks.suggest_copy_pattern(sink) == 'tests/main/*.in'
    assert sinks.allocate_stems('tests/main/*.in', 2) == ['000', '001']


def test_unnumbered_siblings_generalize_around_what_differs():
    assert sinks._generalize(['big-a', 'big-b']) == 'big-*'  # noqa: SLF001
    assert sinks._generalize(['x']) is None  # noqa: SLF001


# --- plans ----------------------------------------------------------------------


async def test_freeze_replaces_the_statement_in_place(
    testing_pkg: testing_package.TestingPackage,
):
    testing_pkg.add_testgroup_from_plan(
        'main', '@copy tests/main/005.in\n# the sample\n@input "1 2"\ngen 3\n'
    )
    _write(testing_pkg, 'tests/main/005.in', '5\n')

    plan = await _promote(['testplan/main.txt:3'], 'main', form='copy')

    assert _read(testing_pkg, 'testplan/main.txt') == (
        '@copy tests/main/005.in\n# the sample\n@copy tests/main/006.in\ngen 3\n'
    )
    assert _read(testing_pkg, 'tests/main/006.in') == '1 2'
    assert [p.to_json() for p in plan.promoted] == [
        {
            'source': 'testplan/main.txt:3',
            'form': 'copy',
            'to': 'tests/main/006.in',
            'inPlace': True,
            'moved': True,
        }
    ]


async def test_a_statement_already_in_that_form_is_left_alone(
    testing_pkg: testing_package.TestingPackage,
):
    testing_pkg.add_testgroup_from_plan('main', 'gen 3\n')

    sources = await pp.resolve_sources(['testplan/main.txt:1'])
    plan = await pp.plan_promotion(sources, sinks.find_sink('main'))

    assert plan.changes == []
    assert [s.source for s in plan.skipped] == ['testplan/main.txt:1']


async def test_moving_into_a_glob_removes_the_statement(
    testing_pkg: testing_package.TestingPackage,
):
    testing_pkg.add_testgroup_from_glob('handmade', 'tests/handmade/*.in')
    testing_pkg.add_testgroup_from_plan('main', 'gen 1\n# why\n@input "7"\n')

    await _promote(['testplan/main.txt:3'], 'handmade', name='seven')

    assert _read(testing_pkg, 'tests/handmade/seven.in') == '7'
    assert _read(testing_pkg, 'testplan/main.txt') == 'gen 1\n'


async def test_keep_source_copies_instead(testing_pkg: testing_package.TestingPackage):
    testing_pkg.add_testgroup_from_glob('handmade', 'tests/handmade/*.in')
    testing_pkg.add_testgroup_from_plan('main', '@input "7"\n')

    await _promote(['testplan/main.txt:1'], 'handmade', keep_source=True)

    assert _read(testing_pkg, 'tests/handmade/000.in') == '7'
    assert _read(testing_pkg, 'testplan/main.txt') == '@input "7"\n'


async def test_moving_between_scopes_of_a_shared_plan(
    testing_pkg: testing_package.TestingPackage,
):
    _write(
        testing_pkg,
        'tests/plan.txt',
        '@testgroup main {\n  gen 1\n  gen 2\n}\n@testgroup large {\n  gen 9\n}\n',
    )
    testing_pkg.yml.generatorScript = GeneratorScript(
        path=pathlib.Path('tests/plan.txt')
    )
    testing_pkg.yml.testcases = [
        testing_package.TestcaseGroup(name='main'),
        testing_package.TestcaseGroup(name='large'),
    ]
    testing_pkg.save()

    await _promote(['tests/plan.txt:3'], 'large')

    assert _read(testing_pkg, 'tests/plan.txt') == (
        '@testgroup main {\n  gen 1\n}\n@testgroup large {\n  gen 9\n  gen 2\n}\n'
    )


async def test_a_glob_test_moves_with_its_answer_into_a_plan(
    testing_pkg: testing_package.TestingPackage,
):
    testing_pkg.add_testgroup_from_glob('handmade', 'tests/handmade/*.in')
    testing_pkg.add_testgroup_from_plan('main', '@copy tests/main/main-01.in\n')
    _write(testing_pkg, 'tests/main/main-01.in', '1\n')
    _write(testing_pkg, 'tests/handmade/a.in', '42\n')
    _write(testing_pkg, 'tests/handmade/a.ans', 'yes\n')

    await _promote(['handmade/0'], 'main')

    assert _read(testing_pkg, 'testplan/main.txt') == (
        '@copy tests/main/main-01.in\n@copy tests/main/main-02.in\n'
    )
    assert _read(testing_pkg, 'tests/main/main-02.in') == '42\n'
    assert _read(testing_pkg, 'tests/main/main-02.ans') == 'yes\n'
    assert not (testing_pkg.root / 'tests/handmade/a.in').exists()
    assert not (testing_pkg.root / 'tests/handmade/a.ans').exists()


async def test_a_moved_copy_deletes_its_file_unless_another_test_reads_it(
    testing_pkg: testing_package.TestingPackage,
):
    testing_pkg.add_testgroup_from_glob('handmade', 'tests/handmade/*.in')
    testing_pkg.add_testgroup_from_plan(
        'main', '@copy tests/x/a.in\n@copy tests/x/b.in\n@copy tests/x/b.in\n'
    )
    _write(testing_pkg, 'tests/x/a.in', 'a\n')
    _write(testing_pkg, 'tests/x/b.in', 'b\n')

    await _promote(['testplan/main.txt:1'], 'handmade')
    assert not (testing_pkg.root / 'tests/x/a.in').exists()

    await _promote(['testplan/main.txt:1'], 'handmade')
    assert (testing_pkg.root / 'tests/x/b.in').exists()
    assert _read(testing_pkg, 'tests/handmade/001.in') == 'b\n'


async def test_moving_a_copy_onto_its_own_file_moves_only_the_line(
    testing_pkg: testing_package.TestingPackage,
):
    _write(
        testing_pkg,
        'tests/plan.txt',
        '@testgroup main {\n  @copy tests/x/a.in\n}\n@testgroup large {\n}\n',
    )
    _write(testing_pkg, 'tests/x/a.in', 'a\n')
    testing_pkg.yml.generatorScript = GeneratorScript(
        path=pathlib.Path('tests/plan.txt')
    )
    testing_pkg.yml.testcases = [
        testing_package.TestcaseGroup(name='main'),
        testing_package.TestcaseGroup(name='large'),
    ]
    testing_pkg.save()

    plan = await _promote(['tests/plan.txt:2'], 'large', path='tests/x/a.in')

    assert [c.action for c in plan.changes] == ['modify']
    assert _read(testing_pkg, 'tests/plan.txt') == (
        '@testgroup main {\n}\n@testgroup large {\n  @copy tests/x/a.in\n}\n'
    )
    assert _read(testing_pkg, 'tests/x/a.in') == 'a\n'


async def test_a_file_source_carries_its_answer(
    testing_pkg: testing_package.TestingPackage,
):
    testing_pkg.add_testgroup_from_glob('samples', 'tests/samples/*.in')
    _write(testing_pkg, 'scratch/in.txt', '3\n')
    _write(testing_pkg, 'scratch/out.txt', '9\n')

    await _promote(['file:scratch/in.txt:scratch/out.txt'], 'samples')

    assert _read(testing_pkg, 'tests/samples/000.in') == '3\n'
    assert _read(testing_pkg, 'tests/samples/000.ans') == '9\n'
    assert (testing_pkg.root / 'scratch/in.txt').exists()


async def test_inline_tests_are_copied_only_on_request(
    testing_pkg: testing_package.TestingPackage,
):
    testing_pkg.add_testgroup_from_glob('handmade', 'tests/handmade/*.in')
    _write(testing_pkg, 'manual/1.in', '1\n')
    testing_pkg.add_testgroup_with_manual_testcases(
        'inline', [{'inputPath': 'manual/1.in'}]
    )

    sources = await pp.resolve_sources(['inline/0'])
    with pytest.raises(pp.PromotionError, match='--keep-source'):
        await pp.plan_promotion(sources, sinks.find_sink('handmade'))

    await _promote(['inline/0'], 'handmade', keep_source=True)
    assert _read(testing_pkg, 'tests/handmade/000.in') == '1\n'


async def test_a_recipe_needs_a_generator_call(
    testing_pkg: testing_package.TestingPackage,
):
    testing_pkg.add_testgroup_from_plan('main', '@input "1"\n')

    sources = await pp.resolve_sources(['testplan/main.txt:1'])
    with pytest.raises(pp.PromotionError, match='only be promoted as a copy'):
        await pp.plan_promotion(sources, sinks.find_sink('main'), form='recipe')


async def test_a_copy_may_not_land_under_another_groups_glob(
    testing_pkg: testing_package.TestingPackage,
):
    testing_pkg.add_testgroup_from_glob('handmade', 'tests/handmade/*.in')
    testing_pkg.add_testgroup_from_plan('main', 'gen 1\n')
    _write(testing_pkg, 'scratch/in.txt', '3\n')

    sources = await pp.resolve_sources(['file:scratch/in.txt'])
    with pytest.raises(pp.PromotionError, match='glob of test group handmade'):
        await pp.plan_promotion(
            sources, sinks.find_sink('main'), path='tests/handmade/*.in'
        )


async def test_a_new_group_is_part_of_the_plan(
    testing_pkg: testing_package.TestingPackage,
):
    testing_pkg.add_testgroup_from_plan('main', '@input "4"\n')
    _write(testing_pkg, 'scratch/in.txt', '3\n')

    sources = await pp.resolve_sources(['file:scratch/in.txt'])
    plan = await pp.plan_promotion(
        sources,
        new_group=pp.NewGroup(name='edge', script=pathlib.Path('tests/edge.txt')),
    )
    assert [(c.action, pathlib.Path(c.path).name) for c in plan.changes] == [
        ('create', 'edge.txt'),
        ('create', '000.in'),
        ('modify', 'problem.rbx.yml'),
    ]
    pp.apply_plan(plan)

    assert _read(testing_pkg, 'tests/edge.txt') == '@copy tests/edge/000.in\n'
    assert [s.name for s in sinks.list_sinks()] == ['main', 'edge']


async def test_a_stale_plan_is_refused(testing_pkg: testing_package.TestingPackage):
    testing_pkg.add_testgroup_from_plan('main', '@input "1"\n')

    sources = await pp.resolve_sources(['testplan/main.txt:1'])
    plan = await pp.plan_promotion(sources, sinks.find_sink('main'), form='copy')
    _write(testing_pkg, 'testplan/main.txt', '@input "1"\n@input "2"\n')

    with pytest.raises(pp.PromotionError, match='changed since'):
        pp.apply_plan(plan)
    assert not (testing_pkg.root / 'tests/main/000.in').exists()


async def test_a_file_promoted_into_a_glob_sorts_last(
    testing_pkg: testing_package.TestingPackage,
):
    testing_pkg.add_testgroup_from_glob('samples', 'tests/*.in')
    for name in ('01', '02', '03'):
        _write(testing_pkg, f'tests/{name}.in', f'{name}\n')
    _write(testing_pkg, 'scratch/in.txt', '4\n')

    await _promote(['file:scratch/in.txt'], 'samples')

    assert _read(testing_pkg, 'tests/04.in') == '4\n'
