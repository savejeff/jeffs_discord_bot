# Project Guide

## Project Identity

- Name: Tagged Discord worker workspace
- Purpose: Persistent project work requested through one Discord agent tag
- Runtime: Codex CLI inside the isolated worker container
- Lifecycle stage: Generic starting workspace

## Architecture and Ownership

The Discord service verifies and authorizes interactions. The private worker queues prompts, selects this tagged workspace, resumes its stored Codex conversation, and relays the final answer. This directory owns only the agent's project files and work products; it does not own Discord transport, worker deployment, Docker, proxy configuration, or host services.

Update this guide with concrete modules, dependencies, commands, and validation boundaries when the workspace acquires an application-specific purpose.

## Python Development

Use `scripts/.venv` and declare utility dependencies in `scripts/requirements.txt`.

```text
Setup: source scripts/activate_venv.sh
Test:  scripts/.venv/bin/python -m pytest
Run:   scripts/.venv/bin/python scripts/<utility>.py
```

Only run commands that match files and dependencies actually present in the evolving workspace.

