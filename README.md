# swarm-stack

A [Hermes](https://github.com/NousResearch/hermes-agent) agent whose **brain is Claude Opus** and whose **subagents run on cheaper Together.ai models**, all through a **LiteLLM** gateway. Built to run on ZimaOS and be used over Tailscale.

```
you ──ssh (tailscale)──► server ──► hermes ──► LiteLLM ──► Anthropic (brain: Opus)
                                       │                └─► Together.ai (subagents: llama-70b, ...)
                                       └─ ssh <pc> over the tailnet to read your other machines
```

## Set up (any machine with Docker)

1. `./scripts/setup.sh`: creates `.env`, generates the LiteLLM keys, starts the stack and creates a budget-capped key for Hermes ($20 / 30 days).
2. Paste your two provider keys into `.env`, then `docker compose up -d`:
   - `ANTHROPIC_API_KEY`: console.anthropic.com (API credit, not a Claude subscription)
   - `TOGETHERAI_API_KEY`: api.together.ai, Settings, API Keys
3. Talk to the agent: `docker compose exec -u hermes hermes hermes`

Local testing on a Mac: add `COMPOSE_FILE=docker-compose.yml:docker-compose.local.yml` to `.env` first.

## On ZimaOS

Install `docker-compose.yml` as a custom app and set `ANTHROPIC_API_KEY`, `TOGETHERAI_API_KEY`, `LITELLM_MASTER_KEY`, `LITELLM_SALT_KEY` (`sk-` + `openssl rand -hex 24` / `-hex 32`; never change the salt). Set `SWARM_BIND` to `tailscale ip -4` so LiteLLM's UI is tailnet-only. From any of your machines:

```sh
ssh <server> -t docker exec -it -u hermes swarm-hermes-1 hermes
```

## Reading your other machines

The agent runs `ssh <pc>` from inside the container. Either let the PC trust the agent's key (printed in the hermes container logs: `docker compose logs hermes`) by adding it to `authorized_keys` of a restricted user, or use Tailscale SSH (`tailscale up --ssh` on the PC plus an ACL rule). Tell the agent your machine names once; it keeps them in memory.

## Choosing models

`litellm.yaml` (in the config dir, created on first run) defines `brain` and the workers. `HERMES_WORKER_MODEL` picks which one subagents use (default `llama-70b`). Together model IDs change: check them at api.together.ai/models.

## Releases

Branches `feat/*` bump the minor version and `hotfix/*` the patch when merged to `staging`. Merging `staging` into `main` publishes `ghcr.io/n0t10n/swarm-hermes`. The Dockerfile pins the sha256 of Hermes' `install.sh`: after upstream changes it, read it and bump `INSTALL_SHA256`.
