import sys

r = int(sys.stdin.readline())
for _ in range(r):
    v = int(sys.stdin.readline())
    print(v ^ 12345, flush=True)
