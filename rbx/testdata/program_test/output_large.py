import sys

# Generate large output
for i in range(100000):
    print(f'Line {i}: ' + 'A' * 100)
    if i % 10000 == 0:
        print(f'Generated {i} lines so far', file=sys.stderr)
