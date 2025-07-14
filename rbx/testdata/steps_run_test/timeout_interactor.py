#!/usr/bin/env python3

import sys
import time

# Interactor that sleeps to cause timeout
try:
    n = int(input())
    print(f'Interactor received: {n} queries')

    # Sleep for a long time to cause timeout
    time.sleep(10)

    for _ in range(n):
        query = input().strip()
        print(f'Response to {query}')

except EOFError:
    print('Interactor: EOF reached')
    sys.exit(0)
