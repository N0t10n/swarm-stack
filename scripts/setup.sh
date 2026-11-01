#!/bin/sh
# Prepares .env (LiteLLM keys + a budget-capped key for Hermes) and starts the stack. Safe to re-run.
# Local test:  echo 'COMPOSE_FILE=docker-compose.yml:docker-compose.local.yml' >> .env  (once)
set -eu
cd "$(dirname "$0")/.."
[ -f .env ] || cp .env.example .env
get() { sed -n "s/^$1=//p" .env | tail -1; }
put() { if grep -q "^$1=" .env; then sed -i.bak "s#^$1=.*#$2#" .env && rm -f .env.bak; else echo "$2" >> .env; fi; }
need() { case "$(get "$1")" in ""|sk-change-me) return 0 ;; *) return 1 ;; esac; }

need LITELLM_MASTER_KEY && put LITELLM_MASTER_KEY "LITELLM_MASTER_KEY=sk-$(openssl rand -hex 24)"
need LITELLM_SALT_KEY && put LITELLM_SALT_KEY "LITELLM_SALT_KEY=sk-$(openssl rand -hex 32)"
for k in ANTHROPIC_API_KEY TOGETHERAI_API_KEY; do
  [ -n "$(get $k)" ] || echo "!! $k is empty in .env: paste it before using the agent"
done

docker compose up -d postgres litellm
printf 'waiting for LiteLLM'
for _ in $(seq 1 60); do
  docker compose exec -T litellm python3 -c "import urllib.request as u; u.urlopen('http://localhost:4000/health/liveliness')" >/dev/null 2>&1 && break
  printf .; sleep 3
done; echo

if [ -z "$(get HERMES_API_KEY)" ]; then
  key=$(docker compose exec -T litellm python3 -c '
import json, os, urllib.request as u
body = {"key_alias": "hermes", "max_budget": float(os.environ.get("HERMES_BUDGET", 20)), "budget_duration": "30d"}
r = u.Request("http://localhost:4000/key/generate", json.dumps(body).encode(),
              {"Authorization": "Bearer " + os.environ["LITELLM_MASTER_KEY"], "Content-Type": "application/json"})
print(json.load(u.urlopen(r))["key"])') || { echo "could not create the Hermes key (does the alias 'hermes' already exist? delete it in the UI)"; exit 1; }
  put HERMES_API_KEY "HERMES_API_KEY=$key"
  echo "created Hermes key (budget \$20 / 30 days, change in the LiteLLM UI)"
fi

docker compose up -d
echo
echo "Stack is up. Talk to the agent:"
echo "  docker compose exec -u hermes hermes hermes"
echo "LiteLLM UI: http://localhost:$(get WEBUI_PORT)/ui  (user admin, password = LITELLM_MASTER_KEY in .env)"
