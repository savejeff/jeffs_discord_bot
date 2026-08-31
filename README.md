# Discord Agent Bot

Discord Agent Bot is an experimental Python service that connects verified Discord interactions to deterministic commands and an isolated local Codex worker. A private Gateway observer forwards creator-owned thread messages to persistent tagged workspaces.

The service verifies Discord signatures before parsing, applies explicit guild, channel/thread, user, and role allowlists, defaults responses to private, and disables automatic mentions. It is intended for contributors who supply their own Discord application, HTTPS domain, allowlists, and Codex account.

Start with the [project overview and getting-started guide](docs/PROJECT_OVERVIEW.md). Detailed requirements, design boundaries, and operations are documented in [project requirements](docs/PROJECT_REQUIREMENTS.md), the [starting architecture](docs/ARCHITECTURE_STARTING_POINT.md), and [security and operations](docs/SECURITY_AND_OPERATIONS.md). Thread routing is documented in [Discord agent threads](docs/DISCORD_AGENT_THREADS.md). The worker design and protocol are in [Codex agent integration](docs/CODEX_AGENT_INTEGRATION.md) and [Codex worker WebSocket protocol](docs/CODEX_WORKER_WEBSOCKET_PROTOCOL.md). Deployment examples use `agents.example.com`; replace it with a domain you control.

## Local development

Keep automated tests in `tests/`. Put machine-local live-integration testcases under ignored [`test/`](test/README.md), and reserve `tmp/` for disposable output and caches.

Create and activate the project-local environment:

~~~powershell
. .\scripts\activate_venv.ps1
~~~

Run the offline suite, which creates its own Ed25519 keys and requires no Discord credentials or network access:

~~~powershell
python -m pytest
~~~

For a local service run, inject `DISCORD_PUBLIC_KEY`, `DISCORD_GUILD_ID`, and `DISCORD_BOT_TOKEN` through a protected mechanism, then run:

~~~powershell
uvicorn discord_agent_bot.application:create_app --factory --app-dir src --host 127.0.0.1 --port 8080
~~~

Offline tests do not prove Discord configuration, TLS, reverse-proxy behavior, live Codex access, or safe production operation. Use your own Discord application and Codex account for authorized live checks, and never commit their credentials or runtime state.

## Docker quick start

Populate the ignored `secrets/secrets.json`, build the worker, and authenticate its persistent Codex volume before the first start:

~~~sh
docker compose build codex-agent-worker
sh scripts/codex_login.sh
docker compose up --detach --build --wait
~~~

The login helper uses device authentication, so the credential does not appear as a command argument. Compose mounts Discord secrets read-only and stores Codex authentication and worker state in named volumes. See [Docker deployment](docs/DEPLOYMENT_DOCKER.md).

## Command development

Commands are discoverable `CommandDefinition` subclasses in `src/discord_agent_bot/commands/`. Each module owns its registration metadata and execution hook. `config/discord_commands.json` is generated; refresh it with `python scripts/generate_command_config.py` and verify it with `python scripts/generate_command_config.py --check`.

Adding or removing a command requires updating its module and focused tests, then regenerating the command catalog. Runtime dispatch, `/help`, Docker image generation, and guild registration all discover the same modules.

## License

This project is licensed under the [PolyForm Noncommercial License 1.0.0](LICENSE.md). Noncommercial use, modification, and redistribution are permitted under its terms. Commercial use, including selling the original or a modified version, requires separate permission from the licensor.

This project supplies no project-specific `Required Notice:` line.
