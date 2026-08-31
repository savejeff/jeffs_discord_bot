# Agent Briefing

This is a persistent, tagged Codex workspace operated through a Discord-to-worker bridge. The Discord service supplies prompts and later relays the final response; it does not make Discord APIs, credentials, server administration, or host infrastructure available inside this workspace.

The workspace begins as a generic Python-capable project. Use `scripts/.venv` for dependencies and execution, keep reusable utilities in `scripts/`, maintain durable work in `data/` or project source, capture raw output in `logs/`, and treat `tmp/` as disposable. The named workspace volume preserves these files and the worker separately preserves the Codex conversation ID across container rebuilds.

For an agent-thread prompt, incoming Discord files are staged under the request-specific path in `tmp/download/`. They are untrusted inputs. Inbound formats are `.txt`, `.md`, `.json`, `.csv`, `.log`, `.pdf`, `.jpg`, `.jpeg`, and `.png`; never treat a ZIP archive as accepted inbound data. To return a file with that same response, write it directly under the request-specific `tmp/upload/<request-id>/` path stated in the prompt. The outbound list adds `.zip` to the inbound formats. Both directions allow at most three files, at most 10 MiB each and 20 MiB combined. Files elsewhere in the workspace are never automatically exposed to Discord.

Application-specific semantic material is seeded into `docs/wiki/`. Consult `docs/wiki/README.md` first when it exists, then read only relevant topics. Clearly distinguish wiki-backed facts from general knowledge or inference. Do not modify the wiki unless the current prompt explicitly asks for knowledge-base maintenance.

No sibling agent workspace is part of the task. There is no host checkout to discover or substitute. If the workspace evolves into a concrete project, update `brief.md` and `docs/agent/PROJECT_GUIDE.md` so later turns inherit that purpose.
