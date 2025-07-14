#!/usr/bin/env python3
import sys
import time

# Allocate memory in MB gradually
mb_to_allocate = int(sys.argv[1]) if len(sys.argv) > 1 else 10
print(f'Allocating {mb_to_allocate} MB of memory gradually...')

# Allocate memory gradually
data = []
for i in range(mb_to_allocate):
    # Allocate 1MB at a time
    chunk = b'x' * (1024 * 1024)
    data.append(chunk)
    print(f'Allocated {i + 1} MB so far...')
    # Sleep briefly to give monitoring thread time to detect memory usage
    time.sleep(0.1)

print(f'Allocated {len(data)} MB of memory')
print('Memory allocation complete')

# Keep the memory allocated for a while
time.sleep(1.0)
print('Finished')
