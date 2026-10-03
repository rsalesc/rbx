#!/usr/bin/env python3

import os
import sys
import time

# Interactor that closes its stdout before rejecting the solution, so the tee
# capturing its side of the interaction exits (and is reaped) before it does.
os.close(sys.stdout.fileno())
time.sleep(0.5)
sys.exit(1)
