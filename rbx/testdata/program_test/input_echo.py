import sys

try:
    for line in sys.stdin:
        print(f'Echo: {line.strip()}')
        sys.stderr.write(f'Read line: {line.strip()}\n')
except KeyboardInterrupt:
    print('Interrupted', file=sys.stderr)
    sys.exit(1)
