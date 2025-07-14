#!/usr/bin/env python3
import sys
import time

sleep_time = float(sys.argv[1]) if len(sys.argv) > 1 else 1.0
print(f'Sleeping for {sleep_time} seconds...')
time.sleep(sleep_time)
print('Done sleeping!')
