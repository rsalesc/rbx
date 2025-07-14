#!/usr/bin/env python3
import sys

exit_code = int(sys.argv[1]) if len(sys.argv) > 1 else 1
print(f'Exiting with code {exit_code}')
sys.stderr.write('Error message to stderr\n')
sys.exit(exit_code)
