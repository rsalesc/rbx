#!/usr/bin/env python3

import sys

# Simple interactor that reads from stdin (solution output) and writes to stdout (solution input)
# Expected format: solution should output number of queries, then interact

# Read the number of interactions from solution
try:
    n = int(input())
    # Log to stderr for verification
    print(f'Interactor starting with {n} queries', file=sys.stderr, flush=True)

    for _ in range(n):
        # Read query from solution
        query = input().strip()

        # Send response back to solution (only this should go to stdout)
        if query == 'hello':
            print('world', flush=True)
        else:
            print(f'echo_{query}', flush=True)

    print('Interactor finished', file=sys.stderr, flush=True)

except EOFError:
    print('Interactor: EOF reached', file=sys.stderr, flush=True)
    sys.exit(0)
