import sys

# Allocate a large amount of memory
data = []
try:
    for i in range(100000):
        data.append([0] * 10000)  # Each iteration allocates ~400KB
        if i % 1000 == 0:
            print(f'Allocated {i * 400}KB', file=sys.stderr)
except MemoryError:
    print('Out of memory!', file=sys.stderr)
    sys.exit(1)
