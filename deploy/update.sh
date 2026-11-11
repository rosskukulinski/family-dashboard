#!/bin/sh
# Pull the latest image, restart only if it changed, and update the Roku app if its
# version changed. Safe to run often (cron / launchd / systemd timer).
set -eu
cd "$(dirname "$0")"
export PATH="$HOME/.orbstack/bin:/Applications/OrbStack.app/Contents/MacOS/xbin:/usr/local/bin:/opt/homebrew/bin:$PATH"
ts() { date '+%Y-%m-%d %H:%M:%S'; }

before=$(docker compose images -q dashboard 2>/dev/null || true)
docker compose pull -q >/dev/null 2>&1
docker compose up -d --remove-orphans >/dev/null 2>&1
after=$(docker compose images -q dashboard 2>/dev/null || true)
[ "$before" = "$after" ] || echo "$(ts) image updated: ${before:-none} -> $after"

if grep -q '^ROKU_TV_IP=..*' .env 2>/dev/null; then
  # wait for the new container to come up before talking to the TV
  for _ in 1 2 3 4 5 6; do docker compose exec -T dashboard true 2>/dev/null && break; sleep 5; done
  out=$(docker compose exec -T dashboard python -m familydash roku-install 2>&1) || echo "$(ts) roku-install failed: $out"
  case "$out" in *"already has"*) ;; *) echo "$(ts) $out" ;; esac
fi
