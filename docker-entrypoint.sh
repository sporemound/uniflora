#!/bin/sh
set -eu

# Railway volumes replace the build-time directory and are mounted as root.
# Give the bot access to its data, then run the application without root rights.
chown -R interior:interior /app/data
exec gosu interior "$@"
