#!/usr/bin/env python3

import sys

# Interactor that crashes early
try:
    n = int(input())
    print(f'Interactor received: {n} queries')

    # Crash on first query
    query = input().strip()
    raise RuntimeError('Interactor crashed!')

except EOFError:
    print('Interactor: EOF reached')
    sys.exit(0)
