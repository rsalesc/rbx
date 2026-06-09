"""Corpus generator: walk the static completion spec and yield many
``(args, incomplete)`` command-lines to drive the differential parity test.

For every node we emit:
- groups: ``(path, '')`` (complete child names) and a prefix case
  ``(path, <first 2 chars of a child's raw name>)``.
- leaves: ``(path, '--')`` (option names), for each value-taking option
  ``(path + [opt_first_name], '')`` (option value), and ``(path, '')``
  (positional value).
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

    walk(spec, [], True)
    # de-dup while preserving order
    seen, uniq = set(), []
    for args, inc in out:
        key = (tuple(args), inc)
        if key not in seen:
            seen.add(key)
            uniq.append((args, inc))
    return uniq
