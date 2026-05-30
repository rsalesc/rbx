from rbx_boca import manifest

TASK_JSON = '{"task_type": "interactive", "output_kb": 65536}'
LANG_JSON = """
{
  "language": {
    "id": "cpp",
    "kind": "compiled_static",
    "compiler_argv": ["g++", "{flags}", "-o", "{exe}", "{src}"],
    "compiler_fallbacks": ["/usr/bin/g++"],
    "flags": "-std=c++20 -O2 -lm -static",
    "run_argv": ["{exe}"],
    "compile_time_sec": 45
  },
  "limits": {"time_sec": 3, "runs": 2, "memory_mb": 256, "wall_time_sec": 12}
}
"""


def test_task_config_parses():
    t = manifest.TaskConfig.from_json(TASK_JSON)
    assert t.task_type == 'interactive'
    assert t.output_kb == 65536


def test_language_manifest_parses():
    m = manifest.LanguageManifest.from_json(LANG_JSON)
    assert m.language.id == 'cpp'
    assert m.language.kind == 'compiled_static'
    assert m.language.run_argv == ['{exe}']
    assert m.language.build is None
    assert m.language.syntax_check is False
    assert m.language.sandbox_overrides == {}
    assert m.language.compile_time_sec == 45
    assert m.limits.runs == 2
    assert m.limits.wall_time_sec == 12


def test_language_spec_compile_time_sec_defaults_to_30():
    spec = manifest.LanguageSpec.from_dict(
        {
            'id': 'cpp',
            'kind': 'compiled_static',
            'compiler_argv': ['g++', '{src}'],
            'compiler_fallbacks': [],
            'flags': '',
            'run_argv': ['{exe}'],
        }
    )
    assert spec.compile_time_sec == 30


def test_language_spec_optional_fields():
    spec = manifest.LanguageSpec.from_dict(
        {
            'id': 'java',
            'kind': 'jvm_jar',
            'compiler_argv': ['javac', '{src}'],
            'compiler_fallbacks': [],
            'flags': '',
            'run_argv': ['java', '-jar', '{jar}', '{jvm_flags}'],
            'build': 'javac_then_jar',
        }
    )
    assert spec.build == 'javac_then_jar'
