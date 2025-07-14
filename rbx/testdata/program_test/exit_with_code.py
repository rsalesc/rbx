import sys

if len(sys.argv) > 1:
    exit_code = int(sys.argv[1])
    print(f'Exiting with code {exit_code}')
    sys.exit(exit_code)
else:
    print('Hello, World!')
    sys.exit(0)
