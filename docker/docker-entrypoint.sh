#!/bin/sh
set -e

# PUID/PGID let the container write the mounted /config and /data with the
# correct host ownership (Unraid: 99:100). Defaults match LinuxServer images.
: "${PUID:=1000}"
: "${PGID:=1000}"

mkdir -p /config/logs /data/input /data/processed /data/failed /data/output
chown -R "${PUID}:${PGID}" /config /data

exec gosu "${PUID}:${PGID}" "$@"
