import sys

# CPU-intensive computation
total = 0
for i in range(10000000):
    total += i * i
    if i % 1000000 == 0:
        print(f'Processed {i} iterations', file=sys.stderr)

print(f'Final total: {total}')
