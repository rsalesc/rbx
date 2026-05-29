import os
import shutil
from pathlib import Path
from typing import Any, List

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
