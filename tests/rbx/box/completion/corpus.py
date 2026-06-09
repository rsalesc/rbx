"""Corpus generator: walk the static completion spec and yield many
``(args, incomplete)`` command-lines to drive the differential parity test.

For every node we emit:
- groups: ``(path, '')`` (complete child names) and a prefix case
  ``(path, <first 2 chars of a child's raw name>)``.
- leaves: ``(path, '--')`` (option names), for each value-taking option
  ``(path + [opt_first_name], '')`` (option value), and ``(path, '')``
  (positional value). Also, to guard Typer parity for already-supplied options
  and ``--opt=value``: ``(path + [flag], '--')`` for the first ``--`` boolean
  flag and ``(path + [opt, 'x'], '--')`` for the first ``--`` value-taking option
  (both must NOT be re-offered), plus ``(path, '--opt=')`` (complete the value).
- a few ALIAS-descent variants: when a child's raw name has an alias
  (``', '``-joined), descend using the alias token instead of the canonical.

Descent ``path`` tokens use the CANONICAL name (first comma-split part) except
for the explicit alias-descent variants. Alias-descent recursion is capped to
top-level only to keep the corpus bounded.
"""


def _canonical(raw):
    return raw.split(',')[0].strip()


def _aliases(raw):
    parts = [p.strip() for p in raw.split(',')]
    return parts[1:]


def command_lines(spec):
    out = []

    def walk(node, path, allow_alias_descent):
        if node.get('is_group'):
            out.append((list(path), ''))
            for c in node.get('children', []):
                raw = c['name']
                if raw:
                    out.append((list(path), raw[:2]))  # prefix on raw name
                walk(c, path + [_canonical(raw)], allow_alias_descent)
                if allow_alias_descent:
                    for alias in _aliases(raw):  # alias-descent variant
                        # Cap alias-descent to top level only: do not recurse
                        # alias variants deeper, to keep the corpus bounded.
                        walk(c, path + [alias], False)
        else:
            out.append((list(path), '--'))
            for p in node.get('params', []):
                if p['kind'] == 'option' and p.get('takes_value') and p['names']:
                    out.append((path + [p['names'][0]], ''))
            out.append((list(path), ''))

            opts = [p for p in node.get('params', []) if p['kind'] == 'option']

            # Fix 1 guard -- supplied-then-dashdash: a non-`multiple` option that
            # was already given must NOT be re-offered. Use the FIRST boolean flag
            # and the FIRST value-taking option (bounded) starting with '--'.
            flag = next(
                (
                    p
                    for p in opts
                    if not p.get('takes_value')
                    and any(n.startswith('--') for n in p['names'])
                ),
                None,
            )
            if flag is not None:
                fname = next(n for n in flag['names'] if n.startswith('--'))
                out.append((path + [fname], '--'))
            valued = next(
                (
                    p
                    for p in opts
                    if p.get('takes_value')
                    and any(n.startswith('--') for n in p['names'])
                ),
                None,
            )
            if valued is not None:
                vname = next(n for n in valued['names'] if n.startswith('--'))
                # Supply an arbitrary value then complete options.
                out.append((path + [vname, 'x'], '--'))
                # Fix 2 guard -- opt=value: complete the option's VALUE.
                out.append((list(path), vname + '='))

    walk(spec, [], True)
    # de-dup while preserving order
    seen, uniq = set(), []
    for args, inc in out:
        key = (tuple(args), inc)
        if key not in seen:
            seen.add(key)
            uniq.append((args, inc))
    return uniq
