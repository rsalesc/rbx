from unittest import mock

from rbx.box import package
from rbx.box.packaging.polygon import polygon_api as api
from rbx.box.packaging.polygon import upload
from rbx.box.schema import ExpectedOutcome, GeneratorCall

# ---------------------------------------------------------------------------
# Part A -- namespace builder
# ---------------------------------------------------------------------------


def _bare_checker(testing_pkg) -> None:
    testing_pkg.add_file('check.cpp').write_text('#include "testlib.h"\nint main(){}\n')
    testing_pkg.set_checker('check.cpp')


def test_build_namespace_same_basename_generators_get_distinct_names(testing_pkg):
    # #527 core: two generators with the SAME basename in different dirs.
    _bare_checker(testing_pkg)
    testing_pkg.add_file('gens/a/gen.cpp').write_text('int main(){}\n')
    testing_pkg.add_file('gens/b/gen.cpp').write_text('int main(){}\n')
    testing_pkg.add_generator('gens/a/gen.cpp', alias='gen_a')
    testing_pkg.add_generator('gens/b/gen.cpp', alias='gen_b')
    testing_pkg.add_testgroup_with_generators(
        'main',
        generators=[
            {'name': 'gen_a', 'args': '1'},
            {'name': 'gen_b', 'args': '2'},
        ],
    )
    testing_pkg.save()

    ns = upload._build_upload_namespace()  # noqa: SLF001

    gen_a = package.get_generator_or_nil('gen_a')
    gen_b = package.get_generator_or_nil('gen_b')
    assert gen_a is not None and gen_b is not None
    name_a = ns.flat_name_for(gen_a)
    name_b = ns.flat_name_for(gen_b)
    assert name_a == 'gens__a__gen.cpp'
    assert name_b == 'gens__b__gen.cpp'
    # Distinct flat names AND distinct stems (Polygon compiles by stem).
    assert name_a != name_b
    import pathlib

    assert pathlib.Path(name_a).stem != pathlib.Path(name_b).stem


def test_build_namespace_checker_keeps_reserved_name(testing_pkg):
    _bare_checker(testing_pkg)
    testing_pkg.save()

    ns = upload._build_upload_namespace()  # noqa: SLF001

    checker = package.get_checker_or_builtin()
    assert ns.flat_name_for(checker) == upload._get_checker_name()  # noqa: SLF001


def test_build_namespace_same_basename_solutions_get_distinct_names(testing_pkg):
    # #527 for solutions: two same-basename solutions in different dirs.
    _bare_checker(testing_pkg)
    testing_pkg.add_file('sols/a/sol.cpp').write_text('int main(){}\n')
    testing_pkg.add_file('sols/b/sol.cpp').write_text('int main(){}\n')
    testing_pkg.add_solution('sols/a/sol.cpp', outcome=ExpectedOutcome.ACCEPTED)
    testing_pkg.add_solution('sols/b/sol.cpp', outcome=ExpectedOutcome.ACCEPTED)
    testing_pkg.save()

    ns = upload._build_upload_namespace()  # noqa: SLF001

    sols = package.get_solutions()
    names = {ns.flat_name_for(s) for s in sols}
    assert names == {'sols__a__sol.cpp', 'sols__b__sol.cpp'}


def test_build_namespace_flat_package_keeps_bare_basenames(testing_pkg):
    # Byte-identical guard: when basenames are globally unique, names stay bare.
    _bare_checker(testing_pkg)
    testing_pkg.add_file('sol.cpp').write_text('int main(){}\n')
    testing_pkg.add_solution('sol.cpp', outcome=ExpectedOutcome.ACCEPTED)
    testing_pkg.save()

    ns = upload._build_upload_namespace()  # noqa: SLF001

    flat_names = {f.flat_name for f in ns.files}
    # check.cpp is reserved as checker.cpp; sol.cpp keeps its bare name.
    assert 'sol.cpp' in flat_names
    sol = package.get_solutions()[0]
    assert ns.flat_name_for(sol) == 'sol.cpp'


def test_build_namespace_subdir_checker_rewrites_and_ships_dep(testing_pkg):
    testing_pkg.add_file('common/lib.h').write_text('#pragma once\nint N=1;\n')
    testing_pkg.add_file('checkers/check.cpp').write_text(
        '#include "../common/lib.h"\n#include "testlib.h"\nint main(){}\n'
    )
    testing_pkg.set_checker('checkers/check.cpp')
    testing_pkg.save()

    ns = upload._build_upload_namespace()  # noqa: SLF001

    checker = package.get_checker_or_builtin()
    checker_text = ns.content_for(checker).decode()
    assert '#include "lib.h"' in checker_text
    assert '#include "../common/lib.h"' not in checker_text
    assert '#include "testlib.h"' in checker_text  # builtin, untouched
    # The dep is shipped as a non-root file.
    assert 'lib.h' in {f.flat_name for f in ns.dep_files()}


# ---------------------------------------------------------------------------
# Part B -- wiring with a mocked Polygon problem
# ---------------------------------------------------------------------------


def test_update_checker_uploads_rewritten_bytes(testing_pkg):
    testing_pkg.add_file('common/lib.h').write_text('#pragma once\nint N=1;\n')
    testing_pkg.add_file('checkers/check.cpp').write_text(
        '#include "../common/lib.h"\n#include "testlib.h"\nint main(){}\n'
    )
    testing_pkg.set_checker('checkers/check.cpp')
    testing_pkg.save()

    ns = upload._build_upload_namespace()  # noqa: SLF001
    checker = package.get_checker_or_builtin()

    problem = mock.Mock()
    upload._update_checker(problem, ns)  # noqa: SLF001

    # save_file got the REWRITTEN bytes under the reserved checker name.
    problem.save_file.assert_called_once()
    _, kwargs = problem.save_file.call_args
    assert kwargs['type'] == api.FileType.SOURCE
    assert kwargs['name'] == upload._get_checker_name()  # noqa: SLF001
    assert kwargs['file'] == ns.content_for(checker)
    assert b'#include "lib.h"' in kwargs['file']
    problem.set_checker.assert_called_once_with(upload._get_checker_name())  # noqa: SLF001


def test_upload_dep_files_ships_dep_as_resource(testing_pkg):
    testing_pkg.add_file('common/lib.h').write_text('#pragma once\nint N=1;\n')
    testing_pkg.add_file('checkers/check.cpp').write_text(
        '#include "../common/lib.h"\n#include "testlib.h"\nint main(){}\n'
    )
    testing_pkg.set_checker('checkers/check.cpp')
    testing_pkg.save()

    ns = upload._build_upload_namespace()  # noqa: SLF001
    dep = ns.dep_files()[0]

    problem = mock.Mock()
    upload._upload_dep_files(problem, ns)  # noqa: SLF001

    problem.save_file.assert_called_once_with(
        type=api.FileType.RESOURCE,
        name=dep.flat_name,
        file=dep.content,
        source_type=None,
    )


def test_upload_generator_uses_flat_name(testing_pkg):
    # #527: a subdir generator colliding with another basename uploads by flat name.
    _bare_checker(testing_pkg)
    testing_pkg.add_file('gens/a/gen.cpp').write_text('int main(){}\n')
    testing_pkg.add_file('gens/b/gen.cpp').write_text('int main(){}\n')
    testing_pkg.add_generator('gens/a/gen.cpp', alias='gen_a')
    testing_pkg.add_generator('gens/b/gen.cpp', alias='gen_b')
    testing_pkg.add_testgroup_with_generators(
        'main',
        generators=[
            {'name': 'gen_a', 'args': '1'},
            {'name': 'gen_b', 'args': '2'},
        ],
    )
    testing_pkg.save()

    ns = upload._build_upload_namespace()  # noqa: SLF001
    gen_a = package.get_generator_or_nil('gen_a')
    assert gen_a is not None

    problem = mock.Mock()
    upload._upload_generator(problem, gen_a, ns)  # noqa: SLF001

    problem.save_file.assert_called_once()
    _, kwargs = problem.save_file.call_args
    assert kwargs['name'] == ns.flat_name_for(gen_a)
    assert kwargs['name'] == 'gens__a__gen.cpp'
    assert kwargs['file'] == ns.content_for(gen_a)


def test_upload_solutions_uses_flat_names(testing_pkg):
    _bare_checker(testing_pkg)
    testing_pkg.add_file('sols/a/sol.cpp').write_text('int main(){}\n')
    testing_pkg.add_file('sols/b/sol.cpp').write_text('int main(){}\n')
    testing_pkg.add_solution('sols/a/sol.cpp', outcome=ExpectedOutcome.ACCEPTED)
    testing_pkg.add_solution('sols/b/sol.cpp', outcome=ExpectedOutcome.ACCEPTED)
    testing_pkg.save()

    ns = upload._build_upload_namespace()  # noqa: SLF001

    problem = mock.Mock()
    problem.solutions.return_value = []
    upload._upload_solutions(problem, ns)  # noqa: SLF001

    saved_names = {c.args[0] for c in problem.save_solution.call_args_list}
    assert saved_names == {'sols__a__sol.cpp', 'sols__b__sol.cpp'}


# ---------------------------------------------------------------------------
# Part C -- freemarker script references flat stems
# ---------------------------------------------------------------------------


def test_freemarker_uses_given_name():
    script = upload._get_freemarker_for_calls(  # noqa: SLF001
        [GeneratorCall(name='gens__a__gen', args='5')]
    )
    assert script.strip() == 'gens__a__gen 5 > 1'
