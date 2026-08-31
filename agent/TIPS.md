# Agent Tips and Known Traps

This file records concise, high-value lessons from recurring agent failures or avoidable friction. Read it before repository, shell, environment, or validation work relevant to these topics. Add a tip only when it is specific, repeatedly useful, and not already obvious from the core guidelines.

## Windows Git Ownership Checks

Managed or sandboxed Windows processes may run under a different identity than the human who owns a checkout. Git then reports `fatal: detected dubious ownership` even when the repository is the correct declared target.

- Resolve and verify the exact repository path and identity first.
- Use a command-local override: `git -c safe.directory=<absolute-repository-path> <command>`.
- Never solve this with `git config --global --add safe.directory ...`; that modifies user-wide configuration and trusts the path beyond the current operation.
- In wrapper workspaces, the launcher root and a nested implementation repository are different Git trust targets. Apply the override to the exact nested repository when needed.
- Confirm branch creation succeeded before copying or editing files. PowerShell does not automatically stop after every native command returns a nonzero exit code.

## PowerShell Native Exit Codes and Pipelines

- Capture `$LASTEXITCODE` immediately after the native command whose result matters. A following pipeline or native command can replace it.
- Use explicit fail-fast checks before starting the next mutating operation.
- Treat non-terminating PowerShell errors deliberately; use `-ErrorAction Stop` when partial completion would make a result ambiguous.

## Narrow File Discovery on Windows

- Prefer `rg --files` with `-g` filters, then operate on the returned paths. Wildcard path arguments can fail on Windows or select more material than intended.
- Explicitly exclude generated and dependency trees such as `scripts/.venv/` from documentation or source scans.
- Do not read arbitrary files as text after a recursive enumeration; binary dependencies can produce huge logs and waste context.

## Windows Python Discovery and Virtual-Environment Bootstrap

An activation helper failing to resolve `python3`, `py -3`, or `python` does not by itself prove that Python is not installed. The agent process and the human's terminal may have different `PATH` state, and Windows app aliases can obscure the actual executable.

- Use existing installed Python as the bootstrap interpreter for `python -m venv scripts/.venv`; only project dependency installation and project execution must move to the resulting local interpreter.
- Discover interpreters without changing the machine. Useful checks include `Get-Command python, python3, py -All`, `where.exe python`, `py --list-paths`, and `python -c "import sys; print(sys.executable)"` for a command that launches successfully.
- `python -where` is not a valid discovery command. Its error banner may happen to expose an executable path, but use `sys.executable` or the Windows launcher instead.
- If a compatible executable is found outside the current `PATH`, invoke that absolute executable to create `scripts/.venv` or update the project helper to discover it reliably. Do not propose installing another Python version merely because the first aliases failed.
- After bootstrap, verify the local interpreter path and prefix before installing requirements or running project Python commands. Never install missing packages into the discovered global interpreter.
