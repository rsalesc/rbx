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

with open(extra, 'w') as f:
    for line in sys.stdin:
        # Write merged capture first.
        sys.stderr.write(c)
        sys.stderr.write(line)
        sys.stderr.flush()

        # Write to program.
        sys.stdout.write(line)
        sys.stdout.flush()

        # Write to extra file.
        f.write(line)
