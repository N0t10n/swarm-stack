#!/bin/sh
# Runs as root only to fix volume ownership, then drops to the hermes user.
set -eu
SSH=/home/hermes/.ssh
mkdir -p "$HERMES_HOME" "$SSH"
[ "$(stat -c %U "$HERMES_HOME")" = hermes ] || chown -R hermes:hermes "$HERMES_HOME"
[ "$(stat -c %U "$SSH")" = hermes ] || chown -R hermes:hermes "$SSH"
chmod 700 "$SSH"
as_hermes() { runuser -u hermes -- env HOME=/home/hermes PATH="/home/hermes/.local/bin:$PATH" "$@"; }

# key for reaching your other machines over the tailnet (authorize it there, or use Tailscale SSH)
[ -f "$SSH/id_ed25519" ] || as_hermes ssh-keygen -q -t ed25519 -N "" -f "$SSH/id_ed25519" -C swarm-hermes
[ -f "$SSH/config" ] || printf 'Host *\n  StrictHostKeyChecking accept-new\n' | as_hermes tee "$SSH/config" >/dev/null
echo "Public SSH key of this agent:"; cat "$SSH/id_ed25519.pub"

# point Hermes at LiteLLM; Opus plans, subagents run on the cheaper worker model
[ -n "${HERMES_API_KEY:-}" ] || echo "WARNING: HERMES_API_KEY is empty" >&2
as_hermes hermes config set model.provider custom >/dev/null
as_hermes hermes config set model.default "${HERMES_BRAIN_MODEL:-brain}" >/dev/null
as_hermes hermes config set model.base_url "$LITELLM_URL" >/dev/null
as_hermes hermes config set model.api_key "${HERMES_API_KEY:-}" >/dev/null
as_hermes hermes config set delegation.model "${HERMES_WORKER_MODEL:-glm-flash}" >/dev/null

exec runuser -u hermes -- env HOME=/home/hermes PATH="/home/hermes/.local/bin:$PATH" "$@"
