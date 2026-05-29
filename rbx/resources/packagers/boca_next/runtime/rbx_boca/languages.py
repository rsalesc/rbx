from typing import Any, List


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
