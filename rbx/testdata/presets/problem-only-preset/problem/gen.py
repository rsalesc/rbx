#!/usr/bin/env python3
import random


def generate_test(n):
    print(n)
    for _ in range(n):
        print(random.randint(1, 100))


if __name__ == '__main__':
    generate_test(10)
