import subprocess
import sys
import textwrap

# `rbx.box.dump_cli_docs` writes the CLI reference through `mkdocs_gen_files`,
# which resolves its destination from whatever mkdocs build is in flight. Under
# the `gen-files` plugin that is a temp directory, but a plain import happens
# outside any build, so the fallback editor writes into `docs_dir` -- the real
# source tree. `griffe_fieldz` performs exactly that import while mkdocstrings
# walks `rbx.box`, which is how the generated reference kept reappearing as a
# working-tree modification (#843).
PROBE = textwrap.dedent(
    """
    import io
    import sys
    import types

    calls = []

    def record(*args, **kwargs):
        calls.append(args)
        return io.StringIO()

    stub = types.ModuleType('mkdocs_gen_files')
    stub.open = record
    sys.modules['mkdocs_gen_files'] = stub

    import rbx.box.dump_cli_docs  # noqa: F401

    print(len(calls))
    """
)


def test_importing_the_module_does_not_generate():
    result = subprocess.run(
        [sys.executable, '-c', PROBE],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == '0', (
        'importing rbx.box.dump_cli_docs called mkdocs_gen_files.open, which '
        'writes the CLI reference into docs/ when no mkdocs build is running'
    )
