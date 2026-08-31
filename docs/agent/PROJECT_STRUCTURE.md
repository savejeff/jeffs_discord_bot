# Project Structure and Directory Conventions

## Purpose

This structure gives developers, scripts, and AI agents predictable locations for durable documentation, reports, logs, resources, runtime data, temporary material, and development utilities.

```text
project/
|-- AGENTS.md
|-- agent/
|   |-- BRIEFING.md
|   |-- GUIDELINES.md
|   |-- TIPS.md
|   `-- TODO_WORKFLOW.md
|-- data/
|-- docs/
|   |-- agent/
|   |   |-- PROJECT_GUIDE.md
|   |   |-- PROJECT_ISLAND_MODEL.md
|   |   `-- PROJECT_STRUCTURE.md
|   |-- ideas.md
|   |-- notes.md
|   |-- TODO.md
|   |-- reports/
|   `-- whitepaper/
|-- logs/
|-- res/
|-- scripts/
|-- develop/               ignored persistent manual experiments
|-- test/                  ignored machine-local testcase projects
|-- tests/                 version-controlled automated tests
`-- tmp/
```

## Responsibilities

### `AGENTS.md`

The concise, automatically discoverable entry point for agent rules and documentation routing. Critical safety rules remain directly in this file.

### `agent/`

Concise operational material compiled for agents working on the project. `agent/BRIEFING.md` provides project-type orientation and task routing, `agent/GUIDELINES.md` defines working and validation behavior, `agent/TIPS.md` records recurring specific traps and workarounds, and `agent/TODO_WORKFLOW.md` defines backlog handling.

### `docs/`

Durable knowledge about the actual project, including architecture, integration plans, decisions, technical procedures, and development workflows. Update it when the behavior or process it describes changes.

`docs/agent/` contains detailed project-specific instructions and workflows. `docs/agent/PROJECT_GUIDE.md` provides project orientation, `docs/agent/PROJECT_ISLAND_MODEL.md` defines the default external mutation boundary, and `docs/agent/PROJECT_STRUCTURE.md` defines artifact handling. Elsewhere, `docs/TODO.md` is the live human-authored backlog and contains no instructional examples. `docs/ideas.md` and `docs/notes.md` are primarily human managed; agents may polish them without promoting their contents into requirements. `docs/whitepaper/` contains agent-compiled concept studies and considerations. `docs/reports/` records results from concrete tests, evaluations, investigations, benchmarks, and experiments.

### `logs/`

Raw run-specific evidence such as serial recordings, diagnostic output, protocol traces, and application logs. Logs are not maintained documentation and are ignored by default except for the directory marker.

### `res/`

Version-controlled resources such as CSV, JSON, images, and reference databases. Runtime code treats these files as read-only; writable copies belong in `data/`.

This project has one explicit exception: `res/wiki/` is an unversioned, deployment-local application knowledge-base seed apart from the synthetic tracked `MOCKUP.md`. The tracked generic seed under `config/codex-worker/workspace-template/` and this wiki are combined in the worker image. New `/workspaces/<tag>` directories receive the complete template; existing workspaces receive only missing template files, except that root `AGENTS.md` is refreshed as operational policy. An existing workspace wiki is never overwritten. The workspace remains filesystem-writable, while its `AGENTS.md` policy permits wiki changes only for an explicit knowledge-base maintenance request. Do not place credentials or tokens in the wiki because Docker image layers and the workspace volume retain bundled content.

### `data/`

Mutable runtime data such as application databases, state, and persistent working datasets. Runtime content is ignored by default except for the directory marker. Explicitly opt in individual fixtures or seed data when they belong in version control.

### `tmp/`

Disposable pytest output, caches, downloads, experiments, intermediate output, and temporary storage. Nothing here may be the sole copy of important information or a durable dependency. Maintained testcase projects do not belong here.

### `develop/`

Ignored persistent project islands used for manual experimentation. They may retain machine-specific environments, credentials, and mutable state, so their contents must never be committed to the parent repository. Initialize each as its own nested local Git repository to stop parent-repository discovery. Keep the tracked policy in `develop/README.md`.

### `test/`

Ignored machine-local testcase projects. Maintained automated test source stays in `tests/`, disposable output belongs in `tmp/`, and persistent manual experiments belong in `develop/`.

### `tests/`

Version-controlled automated tests and maintained non-secret fixtures. Test suites
may prepare isolated projects under `test/runners/` and use `tmp/` for smaller
disposable output, but the test source and fixtures remain here.

### `scripts/`

Utility and standalone workflow scripts. When Python packages are required, declare them in `scripts/requirements.txt` and use the platform activation helper. The helper creates `scripts/.venv/`, installs requirements on first creation, and activates it in the current shell.

```sh
source scripts/activate_venv.sh
```

```powershell
. .\scripts\activate_venv.ps1
```

```bat
scripts\activate_venv.bat
```

## Maintenance Principles

- Keep durable knowledge separate from reports and raw logs.
- Keep version-controlled resources separate from mutable runtime data.
- Keep temporary material out of version control.
- Give every artifact one obvious owner based on its purpose and lifecycle.
- Document project-specific exceptions rather than silently changing directory meaning.
