# Project Guide

Frequently used development, Compose, runner, and Discord command lines belong in
[`docs/USEFUL_COMMANDS.md`](../USEFUL_COMMANDS.md). Add reusable commands there
rather than leaving them only in chat history.

## Project Identity

- Name: Discord Agent Bot
- Repository name: `discord_agent_bot`
- Purpose: provide a controlled Discord interface for agent commands, approved knowledge retrieval, project-thread status, questions, and project-lead escalation.
- Primary users: authorized members and project leads in a configured Discord server.
- Supported target: a Dockerized Python service behind a contributor-controlled HTTPS domain and reverse proxy.
- Lifecycle stage: development command service with an isolated Codex response proof of concept.

## Execution and Ownership

The repository root is the primary implementation target. Put reusable application code under `src/discord_agent_bot/`, automated tests under `tests/`, deployment examples under `docs/` or a later dedicated deployment directory, and thin maintenance tools under `scripts/`. Runtime state must not be written to `res/`.

Use a source package instead of placing the application in a one-off script. Keep these responsibilities distinct:

- HTTP transport and raw-body signature verification;
- interaction parsing, authorization, and command dispatch;
- Discord REST operations for channel/thread reads and outbound messages;
- narrow Gateway ingestion for creator-owned bound thread messages and closure;
- project/thread/lead configuration;
- redacted observability and audit events.

The Discord HTTP service uses Starlette as the small ASGI boundary, Uvicorn as the container server, PyNaCl for Ed25519 verification, and minimal standard-library Discord REST adapters for `/dev_history`, `/agent_thread`, bound-thread answers, and deferred-response completion. A separate Gateway observer receives only reviewed creator-message and thread-closure events. A separate Starlette worker uses a JSON WebSocket, SQLite queue, and the Codex CLI for tagged `/respond`, `/prompt`, `/agent_thread`, `/explain`, and `/summarize` work. It maintains one sequential queue with independent conversations and template-backed persistent workspaces per tag, plus named volumes for worker and login state, but no host project mount or Discord credentials. The destination host needs Docker rather than a host Python or Codex installation.

## Development Route

1. Confirm the target server platform, Docker runtime, reverse proxy, public interaction route, and secret-injection mechanism.
2. Create and verify `scripts/.venv` with the platform-specific activation helper for local development.
3. Run the offline suite before registering or invoking a live command.
4. Build the pinned Python 3.12 image and test it only on loopback/private networking first.
5. Obtain narrow authorization before changing the Discord application, configured server, reverse proxy, DNS, TLS, or service manager.
6. Validate first in a dedicated test channel with a guild-scoped command, then record production promotion steps.

## Intended Commands

The active commands are `/hello`, `/echo`, `/millis`, `/add`, `/dev_history`, `/dev_public`, `/dev_deferred`, `/respond`, `/prompt`, `/agent_thread`, `/explain`, `/summarize`, `/agent_list`, `/agent_config`, `/agent_reset`, `/agent_delete`, `/agent_report`, and `/help`. Each is a separate discoverable `CommandDefinition` module under `src/discord_agent_bot/commands/`, containing its schema metadata, default response visibility/defer policy, moderator policy, and hook. The central registry derives dispatch, `/help`, registration payloads, and the generated `config/discord_commands.json` review artifact from that package. The command base appends an optional `public` boolean to every schema; `public:yes` makes the response channel-visible without bypassing authorization. Responses are private by default except for `/dev_public`, and automatic mentions are always suppressed. `/prompt` may pass only a validated agent tag, never a path. `/agent_thread` requires an explicit tag and shared model shorthand, configures the local lifecycle manager, creates a public child thread, and persists the verified creator/tag binding. `/explain` receives only the default worker requester and points it at that workspace wiki; `/summarize` receives only scoped history-reader and default-agent requester operations. `/agent_list` receives only a typed content-free tag reader. `/agent_config`, `/agent_reset`, and `/agent_delete` receive the typed lifecycle manager and require `DISCORD_MOD_ROLE_IDS`. `/agent_report` receives only a typed content-free status reader, requires an explicit agent tag, and displays only that tag's worker counters and recent metadata. It is also moderator-only. Runtime profiles derive from Codex rollout `turn_context`.

To add or remove a command, add or remove its module, update focused tests, then run `python scripts/generate_command_config.py`. Do not add command-name branches elsewhere and do not hand-edit the generated JSON.

Future commands should be added only after their authorization and data boundaries are specified. Candidate families include project search, status reporting, and focused questions, but their names and payloads are not fixed by this handoff.

## Development Commands

~~~text
Setup: platform-specific scripts/activate_venv helper
Test: python -m pytest
Run locally: uvicorn discord_agent_bot.application:create_app --factory --app-dir src --host 127.0.0.1 --port 8080
Build images: docker compose build
Authenticate Codex volume: sh scripts/codex_login.sh
Run container: see docs/DEPLOYMENT_DOCKER.md
Update deployment: sh scripts/docker_compose_update.sh
~~~

## External Services

- Discord Interactions HTTP delivery to the public HTTPS URL.
- Discord HTTP API authenticated with the bot token for command registration, channel/thread retrieval, and outbound messages.
- Discord Gateway connection limited to bound-thread creator messages and thread closure events.
- An HTTPS reverse proxy and TLS termination for a contributor-controlled domain such as `agents.example.com`.
- OpenAI access from the private worker through the Codex CLI using a human-authenticated named credential volume.

## Validation Boundaries

Unit tests should cover signatures, PING, every configured command, malformed bodies, unknown commands, guild/channel authorization before REST access, mention suppression, duplicate interaction IDs, REST request scope, worker JSON parsing, queue recovery, and redaction. Local integration tests use a fake Codex runner and require no credentials or network. Live command registration, Codex login/model access, worker image build, webhook validation, Discord permissions, and production deployment are explicit external validations.

## Stable Constraints

- No secrets or private Discord content in Git or routine logs.
- One configured guild by default.
- Explicit channel/thread scope and least privilege.
- No broad message indexing or external AI disclosure by default.
- No automatic `@everyone`, `@here`, arbitrary user, or arbitrary role mentions.
- No global command promotion until the guild-scoped behavior is reviewed.
