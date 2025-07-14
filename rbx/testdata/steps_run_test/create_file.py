#!/usr/bin/env python3
import sys

filename = sys.argv[1] if len(sys.argv) > 1 else 'output.txt'
content = sys.argv[2] if len(sys.argv) > 2 else 'default content'

with open(filename, 'w') as f:
    f.write(content)

print(f'Created file {filename} with content: {content}')
