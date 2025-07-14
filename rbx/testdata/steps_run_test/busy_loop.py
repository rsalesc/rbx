#!/usr/bin/env python3
import sys
import time


def busy_loop(duration_seconds):
    """Run a busy loop for the specified duration in seconds."""
    start_time = time.time()
    end_time = start_time + duration_seconds

    # Busy loop that actually consumes CPU time
    counter = 0
    while time.time() < end_time:
        counter += 1
        # Do some meaningless computation to consume CPU
        _ = counter * counter % 1000

    print(f'Busy loop completed after {counter} iterations')
    return counter


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print('Usage: python busy_loop.py <duration_seconds>')
        sys.exit(1)

    duration = float(sys.argv[1])
    result = busy_loop(duration)
    print(f'Final result: {result}')
