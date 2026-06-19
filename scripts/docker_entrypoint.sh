#!/bin/sh
set -eu

log_path="${APP_LOG_FILE_PATH:-logs/log_trace.jsonl}"
mkdir -p "$(dirname "$log_path")"
: > "$log_path"

exec python -m t212ai run bot
