# Manual Test Projects

Use `test/` for persistent machine-local testcase projects. This directory is distinct from version-controlled automated tests under `tests/` and disposable output under `tmp/`.

Everything below `test/` except this README and `.gitignore` is intentionally unversioned and may contain local environments or credentials. Never add that material to Git, logs, reports, or fixtures.

A testcase that runs Codex against its directory must have its own nested local Git repository so Git discovery cannot reach the parent checkout. Do not configure a Git remote unless the current human task explicitly requires it.
