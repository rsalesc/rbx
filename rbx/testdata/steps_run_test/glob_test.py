#!/usr/bin/env python3
import sys

# Print all command line arguments to show glob expansion
print(f'Number of arguments: {len(sys.argv) - 1}')
for i, arg in enumerate(sys.argv[1:], 1):
    print(f'Arg {i}: {arg}')

# Also write to output file for verification
with open('glob_output.txt', 'w') as f:
    f.write(f"Arguments: {' '.join(sys.argv[1:])}\n")
    f.write(f'Count: {len(sys.argv) - 1}\n')
