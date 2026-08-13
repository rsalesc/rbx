import subprocess

import pytest

from rbx.config import get_default_app_path

TEMPLATES = ['c', 'cpp', 'py', 'java', 'kt']


def _scripts():
    return get_default_app_path() / 'packagers' / 'moj' / 'scripts'


def test_compare_stub_delegates_to_mojtools():
    text = (_scripts() / 'compare.sh').read_text()
    # The bridge must stay upstream: the package carries a pointer, never a copy.
    assert 'MOJTOOLS_DIR' in text
    assert 'checker-bridge.sh' in text
    assert 'exec "$_br"' in text


def test_every_template_has_compile_and_run():
    for template in TEMPLATES:
        assert (_scripts() / template / 'compile.sh').is_file()
        assert (_scripts() / template / 'run.sh').is_file()


def test_compile_templates_emit_the_bin_contract():
    for template in TEMPLATES:
        text = (_scripts() / template / 'compile.sh').read_text()
        # No BIN= line on stdout means Compilation Error, per build-and-test.sh.
        assert 'echo BIN=' in text
        assert 'cd /tmp/rwdir' in text


def test_run_templates_source_binfile():
    for template in TEMPLATES:
        text = (_scripts() / template / 'run.sh').read_text()
        assert 'source binfile.sh' in text
        assert '/tmp/in' in text and '/tmp/out' in text


def test_jvm_templates_size_the_runtime_from_the_problem_limit():
    for template in ['java', 'kt']:
        text = (_scripts() / template / 'run.sh').read_text()
        assert 'MOJ_MEMLIMITMB' in text
        assert 'MOJ_STACKKB' in text
        # The manifest jar removes any need to elect a main class at runtime.
        assert '-jar' in text


def test_java_compile_names_the_entry_point_in_the_manifest():
    text = (_scripts() / 'java' / 'compile.sh').read_text()
    assert 'Main-Class:' in text
    assert 'jar cfm' in text


@pytest.mark.parametrize('template', TEMPLATES)
def test_templates_are_valid_bash(template):
    for script in ['compile.sh', 'run.sh']:
        path = _scripts() / template / script
        proc = subprocess.run(['bash', '-n', str(path)], capture_output=True, text=True)
        assert proc.returncode == 0, f'{path}: {proc.stderr}'


def test_compare_stub_is_valid_bash():
    proc = subprocess.run(
        ['bash', '-n', str(_scripts() / 'compare.sh')], capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stderr
