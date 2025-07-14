#!/usr/bin/env python3
import sys
import time

# Allocate memory in MB
mb_to_allocate = int(sys.argv[1]) if len(sys.argv) > 1 else 10
print(f'Allocating {mb_to_allocate} MB of memory...')

# Allocate memory and force actual allocation by touching pages
data = []
for _ in range(mb_to_allocate):
    chunk = bytearray(1024 * 1024)  # 1MB chunks
    # Touch every page to force actual allocation
    for j in range(0, len(chunk), 4096):
        chunk[j] = 1
    data.append(chunk)

print(f'Allocated {len(data)} MB of memory')
print('Memory allocation complete')

# Hold onto the memory for a bit to ensure it's measured
time.sleep(0.1)
print('Finished')
