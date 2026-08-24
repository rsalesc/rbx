import sys
from collections import Counter


def main():
    data = sys.stdin.buffer.read().split()
    n, k = int(data[0]), int(data[1])
    values = Counter(map(int, data[2 : 2 + n]))

    pairs = 0
    for value, count in values.items():
        other = k - value
        if other < value:
            continue
        if other == value:
            pairs += count * (count - 1) // 2
        else:
            pairs += count * values.get(other, 0)
    print(pairs)


main()
