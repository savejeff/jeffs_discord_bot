# Discord Worker Agent Brief

## Purpose

This workspace belongs to one persistent Codex agent selected by a Discord agent tag. It is a generic starting point for research, planning, Python utilities, generated work data, and project-specific implementation requested through that conversation.

## Execution Context

- Workspace root: `.`
- Primary implementation target: `.`
- Persistent mutable material: `data/`, maintained source, scripts, and documentation
- Raw diagnostic output: `logs/`
- Disposable caches, experiments, and imported temporary material: `tmp/`
- Operator-supplied semantic knowledge: `docs/wiki/`
- External checkout: none

The worker container has no host-project checkout, Discord credentials, Docker socket, or authority to modify external infrastructure. An absent required input blocks that part of the task rather than authorizing discovery outside this workspace.

## Working Baseline

Use the project-local environment at `scripts/.venv` for Python dependencies and commands. Create reusable helpers under `scripts/`, document non-obvious usage, and keep outputs in the directory matching their lifecycle. Update this brief and `docs/agent/PROJECT_GUIDE.md` when the workspace gains a concrete long-lived project purpose.
