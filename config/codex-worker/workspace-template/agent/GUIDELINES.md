# Working Guidelines

- Lead with the requested outcome and keep Discord-bound responses concise.
- Inspect before editing, preserve existing work, and avoid broad mechanical rewrites.
- Prefer small reusable scripts over repeated ad-hoc command sequences.
- Add script dependencies to `scripts/requirements.txt`, activate `scripts/.venv`, and run tools through that local interpreter.
- Never place credentials, confidential prompt content, or full private datasets in logs.
- Use `data/` for persistent mutable inputs and outputs, `logs/` for raw diagnostics, `res/` for maintained read-only resources, and `tmp/` for material that may be deleted.
- Validate at the level claimed. Offline tests do not prove Discord delivery, host deployment, external services, or hardware behavior.
- Record durable findings in `docs/`; keep run-specific evidence in `logs/`.

