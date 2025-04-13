import sys

n = int(input())
lf, rg = 1, n + 1
while lf + 1 < rg:
    mid = (lf + rg) // 2
    print(mid)
    sys.stdout.flush()
    if input() == '<':
        rg = mid
    else:
        lf = mid
print('!', lf)
