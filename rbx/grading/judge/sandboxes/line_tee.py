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
        # Write merged capture first. The marker and the line are written in a
        # single call so that, when several tees append to the same merged file
        # concurrently (e.g. a solution's stdout and stderr in batch mode), the
        # marker can never be split away from its line by an interleaving write.
        sys.stderr.write(c + line)
        sys.stderr.flush()

        # Write to program.
        sys.stdout.write(line)
        sys.stdout.flush()

        # Write to extra file.
        f.write(line)
