# Agent Instructions

This file is the mandatory entry point for AI agents working in this repository. Keep it concise; compiled agent guidance belongs in `agent/`, while durable project documentation belongs in `docs/`.

## Non-negotiable Rules

- Never push commits, tags, branches, releases, or other Git changes to a remote. Other persistent external mutations require explicit human approval, except for task-scoped outgoing text communication allowed by the project-island model.
- Never commit directly on `main` or `master`.
- On other branches, create commits only when the user explicitly requests them. A branch clearly dedicated to agent work, such as `agent_XXX`, grants implicit permission for sensible local commits.
- Preserve unrelated and pre-existing user changes.
- Treat this project as an island with the declared working directory as its mutation boundary. The agent may research online, download authorized inputs into the project, read relevant material elsewhere on the computer, communicate outward by text, and interact with task-authorized peripherals; these are not permission to mutate external state.
- Without an explicit current human request or approval, do not install global/user Python packages, system software or drivers; modify another project or external directory; upload files to cloud storage, source hosts, or permanent archives; push Git changes; or create, update, or delete records in an externally hosted database. See `docs/agent/PROJECT_ISLAND_MODEL.md`.
- Use TAB indentation in all languages except Flutter/Dart.
- Add meaningful comments to generated code. Except for small utility functions, every function must have a description comment explaining its intent.
- Installed system or user-level tools and toolchains are available for task-scoped use and read-only discovery. Use an existing compatible system Python to bootstrap this project's `scripts/.venv`; this does not make the system interpreter the project environment. Install Python packages and run project Python commands, tests, and Python-based tools only through the verified project-local environment. Do not install into, update, or reconfigure a global toolchain without explicit human approval.
- Treat files in `res/` as read-only at runtime and files in `tmp/` as disposable, unversioned material. Maintained manual testcase projects belong under `test/`; their contents remain unversioned because they may contain machine-local credentials and runtime state. A testcase that runs Codex must have its own nested local Git repository so Git discovery cannot reach the parent checkout. Version-controlled automated tests remain under `tests/`.
- Treat `res/wiki/` as a deployment-local, unversioned knowledge-base seed, except for the explicitly synthetic tracked `MOCKUP.md`. Its source remains read-only to project tooling, while each tagged worker copy lives under `/workspaces/<agent-tag>/docs/wiki`. Agent instructions make that copy read-only by default but permit writes for an explicit wiki-maintenance request; do not enforce that policy with filesystem permissions. Do not copy deployment wiki contents into tracked files, logs, prompts outside the worker, or reports.
- Treat Discord bot tokens, application credentials, interaction tokens, and private Discord content as confidential. Never print, copy into prompts, commit, or include them in fixtures, logs, reports, or exceptions.
- Do not register commands, change Developer Portal settings, alter server roles or permissions, send live Discord messages, read private message history, deploy services, or change DNS/reverse-proxy configuration without a current human request or narrow approval covering that external mutation.
- Reject unverified interaction requests before parsing or dispatching them. Keep server-side guild, channel/thread, role, and user authorization checks even when Discord command permissions are configured.
- Keep mentions disabled for echoed or generated content. A project-lead mention must use an explicitly configured allowlisted ID and an intentional action.

## Start of a New Task or Session

1. For a newly created interactive agent chat, derive a concise title from the concrete project name or working directory name and set the chat title when the active interface exposes a rename operation. If it does not, continue without pretending the title was changed. Do this once per new chat, not for resumed chats or ordinary follow-ups.
2. Read [`agent/BRIEFING.md`](agent/BRIEFING.md).
3. Read the task-relevant entries in [`agent/TIPS.md`](agent/TIPS.md), especially before Git, PowerShell, environment, or broad file-discovery work.
4. Check [`docs/TODO.md`](docs/TODO.md) for a related human-authored task.
5. Use the maps below to read only the agent guidance and project documentation relevant to the task.
6. Inspect the working tree before editing and do not overwrite unrelated work.

If the task context is compacted, resumed after a long interruption, or materially changes scope, revisit this file, the briefing, and the task-relevant documents before continuing. Do not reload unchanged documents on every follow-up prompt within the same task.

## Agent Guidance Map

- Compiled project briefing and task routing: [`agent/BRIEFING.md`](agent/BRIEFING.md)
- Compiled working and validation guidelines: [`agent/GUIDELINES.md`](agent/GUIDELINES.md)
- Crucial recurring traps and proven workarounds: [`agent/TIPS.md`](agent/TIPS.md)
- How to maintain the human task backlog: [`agent/TODO_WORKFLOW.md`](agent/TODO_WORKFLOW.md)

## Project Documentation Map

- Public architecture, implemented features, and setup: [`docs/PROJECT_OVERVIEW.md`](docs/PROJECT_OVERVIEW.md)
- Project purpose, architecture, and development workflow: [`docs/agent/PROJECT_GUIDE.md`](docs/agent/PROJECT_GUIDE.md)
- Project-island mutation boundary and external interaction model: [`docs/agent/PROJECT_ISLAND_MODEL.md`](docs/agent/PROJECT_ISLAND_MODEL.md)
- Directory ownership and lifecycle conventions: [`docs/agent/PROJECT_STRUCTURE.md`](docs/agent/PROJECT_STRUCTURE.md)
- Human-authored project backlog: [`docs/TODO.md`](docs/TODO.md)
- Requirements and milestone boundaries: [`docs/PROJECT_REQUIREMENTS.md`](docs/PROJECT_REQUIREMENTS.md)
- Starting architecture: [`docs/ARCHITECTURE_STARTING_POINT.md`](docs/ARCHITECTURE_STARTING_POINT.md)
- Discord security and deployment controls: [`docs/SECURITY_AND_OPERATIONS.md`](docs/SECURITY_AND_OPERATIONS.md)
- Test, evaluation, and investigation results: [`docs/reports/`](docs/reports/)

## Completion Checkpoint

- Run checks appropriate to the changed artifacts and report what was and was not verified.
- Update durable documentation when behavior, structure, or methodology changed.
- If the work completes an entry in `docs/TODO.md`, polish and update that entry according to `agent/TODO_WORKFLOW.md`.
- Confirm that no Git remote write or other unapproved persistent external mutation occurred, and report any remaining limitations.
