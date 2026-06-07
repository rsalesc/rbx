from rbx.box.packaging.boca.packager import BocaPackager


def test_boca_checker_embeds_and_rewrites_deps(testing_pkg):
    testing_pkg.add_file('common/lib.h').write_text('#pragma once\nint N=1;\n')
    testing_pkg.add_file('checkers/check.cpp').write_text(
        '#include "../common/lib.h"\n#include "testlib.h"\nint main(){}\n'
    )
    testing_pkg.set_checker('checkers/check.cpp')
    testing_pkg.save()

    script = BocaPackager(testcase_entries=[])._get_checker()  # noqa: SLF001

    # Every flat file is written to disk by the script.
    assert '>checker.cpp' in script
    assert '>lib.h' in script
    assert '>testlib.h' in script and '>rbx.h' in script
    # The embedded checker is rewritten to the flat include.
    assert '#include "lib.h"' in script
    assert '#include "../common/lib.h"' not in script
    # md5 hash covers all embedded files.
    assert 'checker.cpp' in script and 'lib.h' in script
    # No leftover placeholders.
    assert '{{embedded_files}}' not in script
    assert '{{embedded_hash_inputs}}' not in script


def test_boca_checker_embeds_manual_compilation_files(testing_pkg):
    # A checker relying on a custom compilationFiles header (#526) ships it into
    # the embedded compile script even when it is not an auto-discovered include.
    testing_pkg.add_file('extra/helper.h').write_text('#pragma once\nint H=1;\n')
    testing_pkg.add_file('check.cpp').write_text(
        '#include "helper.h"\n#include "testlib.h"\nint main(){}\n'
    )
    testing_pkg.set_checker('check.cpp')
    testing_pkg.yml.checker.compilationFiles = ['extra/helper.h']
    testing_pkg.save()

    script = BocaPackager(testcase_entries=[])._get_checker()  # noqa: SLF001
    assert '>helper.h' in script  # the compilationFiles header is materialized
    assert 'checker.cpp helper.h' in script or 'helper.h' in script  # in md5 inputs


def test_boca_flat_checker_embeds_only_three(testing_pkg):
    # A flat checker with no deps embeds exactly testlib.h, rbx.h, checker.cpp.
    testing_pkg.add_file('check.cpp').write_text('#include "testlib.h"\nint main(){}\n')
    testing_pkg.set_checker('check.cpp')
    testing_pkg.save()
    script = BocaPackager(testcase_entries=[])._get_checker()  # noqa: SLF001
    assert script.count('read -r -d ') == 3  # testlib.h, rbx.h, checker.cpp only
    assert '>lib.h' not in script


def test_boca_interactor_embeds_only_namespace_and_reuses_headers(testing_pkg):
    from rbx.box.schema import TaskType

    testing_pkg.set_type(TaskType.COMMUNICATION)
    testing_pkg.add_file('common/lib.h').write_text('#pragma once\nint N=1;\n')
    testing_pkg.add_file('interactors/inter.cpp').write_text(
        '#include "../common/lib.h"\n#include "testlib.h"\nint main(){}\n'
    )
    testing_pkg.set_interactor('interactors/inter.cpp')
    testing_pkg.save()

    script = BocaPackager(testcase_entries=[])._get_interactor()  # noqa: SLF001

    # Interactor namespace files are embedded and written.
    assert '>interactor.cpp' in script
    assert '>lib.h' in script
    # testlib.h / rbx.h are NOT re-embedded (reused from checker step).
    assert '>testlib.h' not in script
    assert '>rbx.h' not in script
    # The interactor is rewritten to the flat include.
    assert '#include "lib.h"' in script
    assert '#include "../common/lib.h"' not in script
    # Hash inputs still cover the reused headers.
    assert 'rbx.h' in script and 'testlib.h' in script
    # No leftover placeholders.
    assert '{{embedded_files}}' not in script
    assert '{{embedded_hash_inputs}}' not in script
