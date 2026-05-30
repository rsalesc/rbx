import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class LanguageSpec:
    id: str
    kind: str  # 'compiled_static' | 'jvm_jar' | 'interpreted'
    compiler_argv: List[str]
    compiler_fallbacks: List[str]
    flags: str
    run_argv: List[str]
    build: Optional[str] = None  # jvm: 'javac_then_jar' | 'kotlinc_include_runtime'
    syntax_check: bool = False  # interpreted (py3) py_compile pre-check
    sandbox_overrides: Dict[str, Any] = field(default_factory=dict)
    # Absolute compile-phase time limit (seconds). Compile uses cpu == wall ==
    # this value, decoupled from the problem timelimit (e.g. JVM langs set it
    # higher). A per-language property, hence it lives on the spec.
    compile_time_sec: int = 30

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> 'LanguageSpec':
        return LanguageSpec(
            id=d['id'],
            kind=d['kind'],
            compiler_argv=list(d['compiler_argv']),
            compiler_fallbacks=list(d.get('compiler_fallbacks', [])),
            flags=d.get('flags', ''),
            run_argv=list(d['run_argv']),
            build=d.get('build'),
            syntax_check=bool(d.get('syntax_check', False)),
            sandbox_overrides=dict(d.get('sandbox_overrides', {})),
            compile_time_sec=int(d.get('compile_time_sec', 30)),
        )


@dataclass(frozen=True)
class LimitsConfig:
    time_sec: int
    runs: int
    memory_mb: int
    # Absolute run-phase wall time limit (seconds), used directly as safeexec -T.
    # A per-problem limit, hence it lives in the limits rather than being a
    # hardcoded multiple of the cpu timelimit.
    wall_time_sec: int

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> 'LimitsConfig':
        return LimitsConfig(
            time_sec=int(d['time_sec']),
            runs=int(d['runs']),
            memory_mb=int(d['memory_mb']),
            wall_time_sec=int(d['wall_time_sec']),
        )


@dataclass(frozen=True)
class TaskConfig:
    task_type: str  # 'batch' | 'interactive'
    output_kb: int

    @staticmethod
    def from_json(text: str) -> 'TaskConfig':
        d = json.loads(text)
        return TaskConfig(task_type=d['task_type'], output_kb=int(d['output_kb']))


@dataclass(frozen=True)
class LanguageManifest:
    language: LanguageSpec
    limits: LimitsConfig

    @staticmethod
    def from_json(text: str) -> 'LanguageManifest':
        d = json.loads(text)
        return LanguageManifest(
            language=LanguageSpec.from_dict(d['language']),
            limits=LimitsConfig.from_dict(d['limits']),
        )
