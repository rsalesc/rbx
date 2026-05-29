import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from rbx_boca.manifest import LanguageSpec


def render_argv(template: List[str], **subst: Any) -> List[str]:
    """Expand a {token} argv template.

    - A lone token '{name}' whose value is a list splices the list in.
    - A lone token '{name}' whose value is a str is split on whitespace
      (so '-O2 -static' becomes two args); an empty value is dropped.
    - Tokens embedded in larger strings are str-replaced (no splitting).
    """
    out: List[str] = []
    for tok in template:
        if tok.startswith('{') and tok.endswith('}') and tok.count('{') == 1:
            key = tok[1:-1]
            val = subst.get(key, '')
            if isinstance(val, list):
                out.extend(str(v) for v in val)
            else:
                out.extend(str(val).split())
        else:
            rendered = tok
            for key, val in subst.items():
                if not isinstance(val, list):
                    rendered = rendered.replace('{' + key + '}', str(val))
            out.append(rendered)
    return out


def resolve_compiler(spec: LanguageSpec) -> str:
    """Resolve the compiler/interpreter binary: PATH lookup of compiler_argv[0],
    then the first executable fallback. Mirrors `which X || X=/usr/bin/X` in the
    bash compile templates."""
    primary = spec.compiler_argv[0]
    found = shutil.which(primary)
    if found:
        return found
    for cand in spec.compiler_fallbacks:
        p = Path(cand)
        if p.is_file() and os.access(cand, os.X_OK):
            return cand
    raise FileNotFoundError(f'compiler not found for {spec.id}: {primary}')


KINDS = ('compiled_static', 'jvm_jar', 'interpreted')


def jvm_flags(memory_mb: int) -> List[str]:
    """JVM memory flags from run/java, run/kt: heap=memory, stack=heap/10."""
    heap_kb = memory_mb * 1000
    stack_kb = heap_kb // 10
    return [
        '-XX:+UseSerialGC',
        f'-Xmx{heap_kb}K',
        f'-Xss{stack_kb}K',
        f'-Xms{heap_kb}K',
    ]


def build_run_argv(
    spec: LanguageSpec, *, exe: str, memory_mb: int, **extra: Any
) -> List[str]:
    if spec.kind not in KINDS:
        raise ValueError(f'unknown kind: {spec.kind}')
    subst: Dict[str, Any] = {'exe': exe, 'jar': exe}
    subst.update(extra)
    if spec.kind == 'jvm_jar':
        subst['jvm_flags'] = jvm_flags(memory_mb)
    return render_argv(spec.run_argv, **subst)


@dataclass(frozen=True)
class CompilePlan:
    """Pure description of how to build a submission. Contains NO IO; the
    `compile` entrypoint (Phase 6) interprets these fields to perform the
    steps. Mirrors the BOCA bash compile templates.

    Fields:
    - steps: ordered argv commands to run (compiler/jar invocations).
    - artifact: 'exe' | 'jar' | 'script' -- what the build produces.
    - static_link_check: post-compile `file ... | grep 'statically linked'`
      (compiled_static only).
    - rename: (from, to) source rename, e.g. ('sol.kt', 'Main.kt') for kotlin.
    - manifest_class: jvm java Main-Class for the generated Manifest.txt.
    - shebang: interpreted shebang line, e.g. '#!python3'.
    - write_script: (source_path, exe_path) -- prepend shebang + chmod 755.
    - syntax_check_argv: interpreted `py_compile` pre-check step, if enabled.
    """

    steps: List[List[str]] = field(default_factory=list)
    artifact: str = 'exe'
    static_link_check: bool = False
    rename: Optional[Tuple[str, str]] = None
    manifest_class: Optional[str] = None
    shebang: Optional[str] = None
    write_script: Optional[Tuple[str, str]] = None
    syntax_check_argv: Optional[List[str]] = None


def build_compile_plan(
    spec: LanguageSpec,
    *,
    src: str,
    exe: str,
    basename: str,
    **extra: Any,
) -> CompilePlan:
    """Build a CompilePlan describing how to compile `src` into `exe`,
    branching on spec.kind / spec.build. Pure: performs no IO."""
    if spec.kind not in KINDS:
        raise ValueError(f'unknown kind: {spec.kind}')

    if spec.kind == 'compiled_static':
        step = render_argv(spec.compiler_argv, src=src, exe=exe, flags=spec.flags)
        return CompilePlan(steps=[step], artifact='exe', static_link_check=True)

    if spec.kind == 'interpreted':
        interp = extra.get('interp', '')
        syntax_check_argv = None
        if spec.syntax_check:
            syntax_check_argv = [interp, '-m', 'py_compile', src]
        return CompilePlan(
            steps=[],
            artifact='script',
            static_link_check=False,
            shebang='#!' + interp,
            write_script=(src, exe),
            syntax_check_argv=syntax_check_argv,
        )

    # spec.kind == 'jvm_jar'
    compiler = spec.compiler_argv[0]
    if spec.build == 'javac_then_jar':
        javac_step = render_argv(spec.compiler_argv, src=src, exe=exe, flags=spec.flags)
        jar_step = ['jar', 'cfm', exe, 'Manifest.txt', '.']
        return CompilePlan(
            steps=[javac_step, jar_step],
            artifact='jar',
            manifest_class=basename,
        )
    if spec.build == 'kotlinc_include_runtime':
        kotlinc_step = [compiler, '-d', exe, '-include-runtime', 'Main.kt']
        return CompilePlan(
            steps=[kotlinc_step],
            artifact='jar',
            rename=(src, 'Main.kt'),
        )
    raise ValueError(f'unknown jvm build variant: {spec.build}')
