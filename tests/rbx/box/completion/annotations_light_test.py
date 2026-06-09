import subprocess
import sys


def test_importing_annotations_does_not_import_config():
    code = 'import rbx.annotations, sys; print("rbx.config" in sys.modules)'
    out = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True)
    assert out.stdout.strip() == 'False', out.stdout + out.stderr


def test_checker_adapter_lists_checkers():
    from rbx import annotations

    cb = annotations._adapt('checker')  # noqa: SLF001
    values = cb('')
    assert any(v.endswith('.cpp') for v in values)
    assert 'boilerplate.cpp' not in values
    assert cb._completer_key == 'checker'  # noqa: SLF001
