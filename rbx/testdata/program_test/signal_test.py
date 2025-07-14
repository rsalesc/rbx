import signal
import sys
import time


def signal_handler(signum, frame):
    print(f'Received signal {signum}', file=sys.stderr)
    sys.exit(128 + signum)


signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)

print('Starting signal test program')
try:
    time.sleep(10)  # Wait for signal
    print('Program finished normally')
except KeyboardInterrupt:
    print('Interrupted by keyboard', file=sys.stderr)
    sys.exit(1)
