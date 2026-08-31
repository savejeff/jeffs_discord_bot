# Discord Codex Worker Workspace

This is a persistent project workspace for one Codex agent reached through the Discord worker. The workspace begins as a generic Python-capable project and may evolve in response to authorized prompts.

The worker owns transport and conversation routing. The agent works only in this directory, stores durable work under `data/` or maintained project files, writes reusable utilities under `scripts/`, puts raw output under `logs/`, and uses `tmp/` only for disposable material. Agent-thread files arrive in the request-specific `tmp/download/` path stated in the prompt; only validated files written directly to that request's `tmp/upload/` path can be returned through Discord.

## Python utilities

Create or activate the workspace-local Python environment from the workspace root:

```sh
source scripts/activate_venv.sh
```

Add utility dependencies to `scripts/requirements.txt`. Run Python utilities through `scripts/.venv/bin/python`; do not install packages into the container's global Python environment.

## Starting points

- `AGENTS.md`: mandatory operational and safety rules
- `brief.md`: workspace purpose and execution boundary
- `docs/agent/PROJECT_GUIDE.md`: project-specific guidance to maintain as the workspace evolves
- `docs/TODO.md`: human-owned task backlog
- `docs/wiki/`: application knowledge supplied by the operator
- `scripts/`: reusable project-local utilities
