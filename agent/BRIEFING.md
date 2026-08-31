# Agent Briefing

## Project Context

This repository is an organization-neutral Discord interaction and local Codex-worker experiment. It includes a signed public HTTP receiver, bounded Discord REST operations, a narrow Gateway observer for creator-bound threads, and a sequential worker with persistent tagged workspaces.

Commands are discoverable `CommandDefinition` subclasses under `src/discord_agent_bot/commands/`. The registry derives dispatch, help, registration payloads, and `config/discord_commands.json`; do not add parallel command-name branches or hand-edit the generated catalog.

Runtime credentials, Discord content, Codex login state, agent workspaces, and deployment knowledge-base content are confidential machine-local inputs. Never inspect or publish them as part of repository cleanup. A public snapshot may ship only the explicitly synthetic `res/wiki/MOCKUP.md`; it must ship no deployment wiki, `secrets/`, `data/`, `logs/`, `test/`, or `tmp/` content.

## Start Route

1. Read `agent/GUIDELINES.md` and task-relevant entries in `agent/TIPS.md`.
2. Read `brief.md` and the task-relevant project documentation.
3. Check `docs/TODO.md` and follow `agent/TODO_WORKFLOW.md`.
4. Inspect the working tree before editing.

## Project Priorities

- Verify each Discord interaction against its raw request bytes before parsing or dispatch.
- Keep HTTP, Discord REST, Gateway observation, and local worker responsibilities separate.
- Enforce server-side guild, channel/thread, role, and user allowlists.
- Disable mentions for user-derived and model-derived content.
- Keep credentials outside Git and routine logs.
- Run Python only through the verified project-local `scripts/.venv`.
- Treat agent tags as continuity labels, not authorization or security boundaries.
- Preserve the distinction between offline verification and authorized live validation.

## Validation Boundary

Offline tests and local ASGI requests can prove parsing, signature rejection, authorization logic, command dispatch, and response formatting. They do not prove DNS, TLS, proxy behavior, Discord configuration, live message delivery, Codex access, or production security.
