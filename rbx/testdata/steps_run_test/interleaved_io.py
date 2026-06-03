#!/usr/bin/env python3
import sys

# Interleave writes to stdout and stderr so the merged capture can be checked
# for true line-order teeing.
print('out line 1', flush=True)
print('err line 1', file=sys.stderr, flush=True)
print('out line 2', flush=True)
print('err line 2', file=sys.stderr, flush=True)
