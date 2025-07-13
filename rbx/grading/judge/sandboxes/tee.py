#!/usr/bin/env python3
"""
Forked from https://github.com/RagnarGrootKoerkamp/BAPCtools/blob/master/bin/interactive.py

Takes a character and a file name as arguments.

Reads from stdin, and writes to stdout and stderr, with the given character prepended to
every line read from stdin.
"""

import sys

c = sys.argv[1]
extra = sys.argv[2]

new = True

with open(extra, 'w') as f:
    while True:
        rd = sys.stdin.read(1)
        if rd == '':
            break
        sys.stdout.write(rd)
        sys.stdout.flush()
        if new:
            sys.stderr.write(c)
        sys.stderr.write(rd)
        sys.stderr.flush()

        f.write(rd)
        new = rd == '\n'
