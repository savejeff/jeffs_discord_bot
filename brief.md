# Project Brief

## Purpose

Develop a security-conscious Discord interaction service for experimentation with deterministic commands and a local sequential Codex worker. The project is organization-neutral and must be configured with the contributor's own Discord application, HTTPS domain, allowlists, and Codex account.

## Implementation Boundary

- The repository root is the primary implementation target.
- Application source belongs under `src/`; version-controlled automated tests belong under `tests/`.
- `test/`, `tmp/`, `logs/`, `data/`, `scripts/.venv/`, and `res/wiki/` hold ignored machine-local or runtime material and must not enter a public snapshot.
- Secrets must remain outside Git and must never be printed, copied into prompts, fixtures, logs, reports, or exceptions.
- Live Discord changes, deployments, DNS or proxy changes, and repository publication require explicit human authorization.

## Current Scope

The repository contains a signed Discord Interactions endpoint, deterministic command handlers, bounded Discord REST operations, a narrow Gateway observer, and a private sequential Codex worker. Persistent tagged workspaces support one-shot prompts and creator-bound Discord threads.

The local worker is a proof of concept rather than a complete production security boundary. Its Compose-private WebSocket is unauthenticated, tagged workspaces share one container and volume, retention cleanup is incomplete, and restart-safe delivery is limited to the documented paths. Use non-confidential test data until the remaining controls are implemented and reviewed.

## Starting Route

1. Read `AGENTS.md` and `agent/BRIEFING.md`.
2. Read `docs/PROJECT_REQUIREMENTS.md`, `docs/ARCHITECTURE_STARTING_POINT.md`, and `docs/SECURITY_AND_OPERATIONS.md`.
3. Check `docs/TODO.md` for the current backlog.
4. Create or verify `scripts/.venv`, then run project Python commands only through that environment.
5. Run offline tests before any authorized live integration test.

Offline tests can prove parsing, signature rejection, authorization logic, command dispatch, and response formatting. They do not prove DNS, TLS, Discord Developer Portal settings, guild permissions, live delivery, Codex account access, or production security.
