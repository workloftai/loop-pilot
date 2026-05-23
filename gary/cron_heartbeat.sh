#!/bin/bash
# Heartbeat: each Loop cron calls this with its name on success.
# Writes a unix timestamp to /var/lib/larry-bob/heartbeats/<name>.
set -eu
NAME="${1:?usage: cron_heartbeat.sh <cron-name>}"
DIR=/var/lib/larry-bob/heartbeats
mkdir -p "$DIR"
date +%s > "$DIR/$NAME"
