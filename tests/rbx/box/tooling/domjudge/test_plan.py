"""What `rbx tool domjudge configure` decides to send, before it sends it.

The three behaviours worth pinning are the three that fail silently on a real
server: a language dropped from the payload is *disabled* rather than skipped, a
compile command translated wrong compiles nothing while still returning 200, and
an extension list pushed as a replacement quietly stops accepting files that
worked yesterday.
"""

import io
import zipfile
from typing import Any, Dict, List, Optional

import pytest

from rbx.box.environment import (
    CompilationConfig,
    Environment,
    EnvironmentLanguage,
    ExecutionConfig,
)
from rbx.box.extensions import Extensions, LanguageExtensions
from rbx.box.tooling.domjudge.extension import (
    DomjudgeExtension,
    DomjudgeLanguageExtension,
)
from rbx.box.tooling.domjudge.plan import build_plan, config_payload


def language(
    name: str,
    extension: str,
    *,
    commands: Optional[List[str]] = None,
    extra_extensions: Optional[List[str]] = None,
    domjudge: Optional[DomjudgeLanguageExtension] = None,
    run: str = './{executable}',
) -> EnvironmentLanguage:
    return EnvironmentLanguage(
        name=name,
        extension=extension,
        extraExtensions=extra_extensions or [],
        compilation=CompilationConfig(commands=commands) if commands else None,
        execution=ExecutionConfig(command=run),
        extensions=LanguageExtensions(domjudge=domjudge) if domjudge else None,
    )


def environment(
    languages: List[EnvironmentLanguage],
    domjudge: Optional[DomjudgeExtension] = None,
) -> Environment:
    return Environment(
        languages=languages,
        extensions=Extensions(domjudge=domjudge) if domjudge else None,
    )


def server_language(id: str, extensions: List[str]) -> Dict[str, Any]:
    return {'id': id, 'name': id, 'extensions': extensions, 'time_factor': 1.0}


CPP = server_language('cpp', ['cpp', 'cc', 'cxx'])
C = server_language('c', ['c'])
JAVA = server_language('java', ['java'])


def find(plan, name: str):
    return next(entry for entry in plan.languages if entry.name == name)


def test_matches_a_language_by_its_file_extension():
    plan = build_plan(
        environment(
            [language('cpp', 'cpp', commands=['g++ -o {executable} {compilable}'])]
        ),
        [CPP, C],
        {},
    )

    entry = find(plan, 'cpp')
    assert entry.language_id == 'cpp'
    assert not entry.explicit
    assert entry.known


def test_keeps_languages_rbx_does_not_manage_enabled():
    """The POST disables everything absent from it, so absent is not neutral."""
    plan = build_plan(
        environment([language('cpp', 'cpp')]),
        [CPP, C, JAVA],
        {},
    )

    assert sorted(plan.preserved) == ['c', 'java']
    assert plan.languages_payload() == [
        {'id': 'cpp', 'allow_submit': True, 'extensions': ['cpp', 'cc', 'cxx']},
        {'id': 'c', 'allow_submit': True},
        {'id': 'java', 'allow_submit': True},
    ]


def test_adds_extensions_without_dropping_the_ones_the_server_has():
    plan = build_plan(
        environment([language('cpp', 'cpp', extra_extensions=['cpp17'])]),
        [CPP],
        {},
    )

    entry = find(plan, 'cpp')
    assert entry.added_extensions == ['cpp17']
    assert entry.all_extensions == ['cpp', 'cc', 'cxx', 'cpp17']


def test_names_a_language_the_server_has_disabled():
    """A disabled language is invisible to the API, so it can only be named.

    rbx knows nothing about it -- including its extension list -- so it must not
    send one, or it would overwrite the server's with a guess.
    """
    plan = build_plan(
        environment(
            [
                language(
                    'py',
                    'py',
                    domjudge=DomjudgeLanguageExtension(languages=['python3']),
                )
            ]
        ),
        [CPP],
        {},
    )

    entry = find(plan, 'py')
    assert entry.language_id == 'python3'
    assert entry.explicit
    assert not entry.known
    assert entry.payload() == {'id': 'python3', 'allow_submit': True}


def test_reports_a_language_that_matched_nothing():
    plan = build_plan(environment([language('rs', 'rs')]), [CPP], {})

    assert plan.unmatched == ['rs']
    assert not plan.languages


def test_refuses_two_rbx_languages_on_the_same_domjudge_language():
    with pytest.raises(ValueError, match='both map to'):
        build_plan(
            environment(
                [
                    language('cpp', 'cpp'),
                    language('cpp20', 'cc'),
                ]
            ),
            [CPP],
            {},
        )


def test_translates_the_compilation_command_into_a_compile_wrapper():
    plan = build_plan(
        environment(
            [
                language(
                    'cpp',
                    'cpp',
                    commands=['g++ -std=c++20 -O2 -o {executable} {compilable}'],
                )
            ]
        ),
        [CPP],
        {},
    )

    script = find(plan, 'cpp').compile_script
    assert script is not None
    assert script.command == 'g++ -std=c++20 -O2 -o "$DEST" "$@"'
    assert 'DEST="$1" ; shift' in script.script
    assert script.script.startswith('#!/bin/sh')


def test_compile_command_overrides_the_environments_own():
    plan = build_plan(
        environment(
            [
                language(
                    'cpp',
                    'cpp',
                    commands=['g++ -O2 -o {executable} {compilable}'],
                    domjudge=DomjudgeLanguageExtension(
                        compileCommand='g++ -O2 -static -o {executable} {compilable}'
                    ),
                )
            ]
        ),
        [CPP],
        {},
    )

    script = find(plan, 'cpp').compile_script
    assert script is not None
    assert script.command == 'g++ -O2 -static -o "$DEST" "$@"'


@pytest.mark.parametrize(
    'kwargs,reason',
    [
        ({}, 'not compiled'),
        (
            {'commands': ['javac {compilable}', 'jar cvf {executable} *.class']},
            'single one',
        ),
        (
            {'commands': ['kotlinc -d {executable} -include-runtime {other}']},
            'both {compilable} and {executable}',
        ),
        (
            {
                'commands': [
                    'javac -o {executable} {compilable} -cp {javaClass}',
                ]
            },
            '{javaClass}',
        ),
        (
            {
                'commands': ['g++ -o {executable} {compilable}'],
                'domjudge': DomjudgeLanguageExtension(compile=False),
            },
            'compile is false',
        ),
    ],
)
def test_keeps_the_servers_compile_script_when_it_cannot_translate(kwargs, reason):
    """A wrong wrapper still returns 200 and then fails every submission."""
    plan = build_plan(environment([language('cpp', 'cpp', **kwargs)]), [CPP], {})

    entry = find(plan, 'cpp')
    assert entry.compile_script is None
    assert entry.compile_skipped is not None
    assert reason in entry.compile_skipped


def test_the_compile_zip_carries_both_scripts_marked_executable():
    plan = build_plan(
        environment(
            [language('cpp', 'cpp', commands=['g++ -o {executable} {compilable}'])]
        ),
        [CPP],
        {},
    )

    script = find(plan, 'cpp').compile_script
    assert script is not None
    with zipfile.ZipFile(io.BytesIO(script.zip_bytes())) as archive:
        assert archive.namelist() == ['run', 'build']
        for info in archive.infolist():
            assert info.external_attr >> 16 == 0o100755
        assert archive.read('run').decode() == script.script


def test_pushes_only_the_time_factor_that_was_asked_for():
    plan = build_plan(
        environment(
            [
                language(
                    'cpp',
                    'cpp',
                    domjudge=DomjudgeLanguageExtension(timeFactor=2.5),
                ),
                language('c', 'c'),
            ]
        ),
        [CPP, C],
        {},
    )

    assert find(plan, 'cpp').payload()['time_factor'] == 2.5
    assert 'time_factor' not in find(plan, 'c').payload()


def test_plans_only_the_limits_that_differ_from_the_server():
    plan = build_plan(
        environment(
            [],
            domjudge=DomjudgeExtension(
                memoryLimit=1024, outputLimit=8192, processLimit=64
            ),
        ),
        [],
        {'memory_limit': 2097152, 'output_limit': 8192, 'process_limit': 64},
    )

    assert config_payload(plan.config) == {'memory_limit': 1048576}
    assert plan.config[0].current == 2097152


def test_an_environment_with_nothing_to_say_plans_nothing():
    plan = build_plan(environment([]), [CPP], {})

    assert plan.is_empty()
    assert plan.preserved == ['cpp']


def test_keeps_the_compile_script_of_a_language_whose_artifact_is_not_the_program():
    """Kotlin compiles in one command, and pushing it would still break judging.

    `kotlinc -d {executable}` leaves a jar, and DOMjudge execs whatever the
    compile script left behind -- its own script emits a shell wrapper for that
    reason, and the run wrapper that would be the other place to fix it has no
    write endpoint at all.
    """
    plan = build_plan(
        environment(
            [
                language(
                    'kt',
                    'kt',
                    commands=['kotlinc -d {executable} -include-runtime {compilable}'],
                    run='java -cp {executable} MainKt',
                )
            ]
        ),
        [server_language('kotlin', ['kt'])],
        {},
    )

    entry = find(plan, 'kt')
    assert entry.language_id == 'kotlin'
    assert entry.compile_script is None
    assert 'executing its build product' in (entry.compile_skipped or '')
