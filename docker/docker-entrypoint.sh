#!/bin/sh
set -e

# PUID/PGID let the container write the mounted /config and /data with the
# correct host ownership (Unraid: 99:100). Defaults match LinuxServer images.
: "${PUID:=1000}"
: "${PGID:=1000}"

mkdir -p /config/logs /data/input /data/processed /data/failed /data/output

# Seed default configs on first start so the container does not crash-loop when
# /config is a fresh empty mount. The user must edit config.yaml (pocketlog.base_url)
# before actual imports will work. rules.yaml ships a set of example rules.
if [ ! -f /config/config.yaml ]; then
    cp /app/config/config.example.yaml /config/config.yaml
    echo "$(date '+%Y-%m-%d %H:%M:%S') WARNING bank_importer /config/config.yaml was missing — copied from example. Edit pocketlog.base_url (and set POCKETLOG_API_KEY) before importing."
fi
if [ ! -f /config/rules.yaml ]; then
    cp /app/config/rules.example.yaml /config/rules.yaml
    echo "$(date '+%Y-%m-%d %H:%M:%S') WARNING bank_importer /config/rules.yaml was missing — copied from example. Edit the rules whitelist before importing."
fi

chown -R "${PUID}:${PGID}" /config /data

exec gosu "${PUID}:${PGID}" "$@"
