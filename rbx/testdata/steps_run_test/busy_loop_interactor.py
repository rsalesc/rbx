#!/usr/bin/env python3

import sys

# Interactor that uses busy loop to consume CPU time
try:
    n = int(input())
    print(f'Interactor received: {n} queries')

    # Busy loop to consume CPU time
    counter = 0
    while counter < 10**8:  # Large number to consume significant CPU time
        counter += 1

    for _ in range(n):
        query = input().strip()
        print(f'Response to {query}')

except EOFError:
    print('Interactor: EOF reached')
    sys.exit(0)
