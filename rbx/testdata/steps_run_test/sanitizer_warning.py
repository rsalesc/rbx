#!/usr/bin/env python3
import sys

# Simulate sanitizer warnings in stderr
sys.stderr.write(
    '==12345==ERROR: AddressSanitizer: heap-use-after-free on address 0x123456\n'
)
sys.stderr.write('    #0 0x123456 in main test.cpp:10\n')
sys.stderr.write(
    "runtime error: signed integer overflow: 2147483647 + 1 cannot be represented in type 'int'\n"
)
sys.stderr.write('SUMMARY: AddressSanitizer: heap-use-after-free test.cpp:10 in main\n')

print('Program completed with sanitizer warnings')
