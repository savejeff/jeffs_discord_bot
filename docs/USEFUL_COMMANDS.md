# Useful Commands

Run these commands from the repository root. Never store a live Discord token or Codex credential in documentation, script arguments, or shell history.

## Start the local worker

The shipped `config/config_agents.json` has an empty catalog. Rebuild and start the worker without creating a workspace:

```sh
docker compose up --detach --build --force-recreate codex-agent-worker
```

Start the complete Discord stack:

```sh
docker compose up --detach --build
```

Create a persistent local agent from an allowed Discord channel:

```text
/agent_thread agent_tag:<new-tag> model:low
```

The `low` shorthand selects the documented Sol profile. The available Sol, Luna, and Terra choices are generated into the command catalog.

Useful checks:

```sh
docker compose ps
docker compose logs --tail 100 discord-agent-bot discord-gateway-observer codex-agent-worker
```

```text
/agent_list
/agent_report agent_tag:<tag>
```

## Run offline validation

Activate the project-local Python environment and run the complete suite:

```powershell
. .\scripts\activate_venv.ps1
python -m pytest --basetemp tmp/pytest
python scripts/generate_command_config.py --check
```

Validate deployment configuration without starting services:

```sh
docker compose config --quiet
```
