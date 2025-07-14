#!/usr/bin/env python3

import sys

# Simple solution that communicates with interactor
queries = ['hello', 'test', 'goodbye']

# Output number of queries
print(len(queries), flush=True)

for query in queries:
    print(query, flush=True)
    response = input().strip()
    print(f'Received: {response}', file=sys.stderr, flush=True)

print('Solution finished', file=sys.stderr, flush=True)
