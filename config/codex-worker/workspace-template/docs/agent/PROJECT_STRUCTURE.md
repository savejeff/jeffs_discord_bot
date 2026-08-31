# Project Structure

```text
workspace/
|-- AGENTS.md
|-- agent/                 compiled agent guidance
|-- data/                  persistent mutable work data
|-- docs/                  durable project knowledge
|   |-- agent/             project-specific agent guidance
|   |-- reports/           maintained evaluation reports
|   `-- wiki/              operator-supplied semantic knowledge
|-- logs/                  raw diagnostic and run output
|-- res/                   maintained read-only resources
|-- scripts/               reusable utilities and local Python environment
|-- src/                   project source when needed
|-- tests/                 offline tests when needed
`-- tmp/                   disposable caches, downloads, and response uploads
```

The workspace volume makes files persistent, but lifecycle ownership remains important. Never make `tmp/` or `logs/` the sole location of an important deliverable. Keep generated environments under `scripts/.venv/` and credentials out of the workspace.

`tmp/download/<request-id>/` contains bounded, creator-supplied Discord thread files. `tmp/upload/<request-id>/` is the only export surface: files placed directly there can be attached to that request's Discord response after validation. Both locations are temporary transport areas, not durable project storage.
