#!/usr/bin/env python3


# Solution that crashes after some interaction
print('2')  # number of queries
print('hello', flush=True)
response = input().strip()

# Crash with runtime error
raise RuntimeError('Solution crashed!')
