"""Benchmark cold completion latency. Run: `mise run bench-completion`."""

import os
import subprocess
import sys
import time

# (label, args-before-incomplete, incomplete)
SCENARIOS = [
    ('rbx <tab>', '', ''),
    ('rbx ru<tab>', '', 'ru'),
    ('rbx run <tab>', 'run', ''),
    ('rbx run --<tab>', 'run', '--'),
    ('rbx run --lang <tab>', 'run --lang', ''),
    ('rbx package <tab>', 'package', ''),
]


def _one(comp_words: str, cword: int, n: int = 5) -> float:
    env = dict(os.environ)
    env['_RBX_COMPLETE'] = 'complete_bash'
    env['_TYPER_COMPLETE_ARGS'] = comp_words
    env['COMP_WORDS'] = comp_words
    env['COMP_CWORD'] = str(cword)
    best = float('inf')
    for _ in range(n):
        t = time.perf_counter()
        subprocess.run(['rbx'], env=env, capture_output=True)
        best = min(best, time.perf_counter() - t)
    return best * 1000


def main() -> None:
    print(f'{"scenario":24s} {"ms (best of 5)":>16s}')
    for label, before, inc in SCENARIOS:
        comp_words = ('rbx ' + before + ' ' + inc).replace('  ', ' ').rstrip()
        cword = len(comp_words.split())
        print(f'{label:24s} {_one(comp_words, cword):16.1f}')


if __name__ == '__main__':
    sys.exit(main())
