#!/bin/bash
# Script to wait for BOCA to be ready

set -e

BOCA_URL="${BOCA_URL:-http://localhost:8000/boca}"
MAX_ATTEMPTS=60
SLEEP_TIME=2

echo "Waiting for BOCA to be ready at $BOCA_URL..."

attempt=0
while [ $attempt -lt $MAX_ATTEMPTS ]; do
    if curl -f -s "$BOCA_URL/index.php" > /dev/null; then
        echo "BOCA is ready!"
        exit 0
    fi
    
    attempt=$((attempt + 1))
    echo "Attempt $attempt/$MAX_ATTEMPTS: BOCA not ready yet, waiting ${SLEEP_TIME}s..."
    sleep $SLEEP_TIME
done

echo "BOCA failed to start after $MAX_ATTEMPTS attempts"
exit 1