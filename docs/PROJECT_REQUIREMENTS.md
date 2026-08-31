# Project Requirements

## Purpose

Provide a private Discord interface through which authorized members can invoke an agent, retrieve information from approved Discord locations, receive project status, answer questions, and be intentionally alerted when a mapped project requires human input.

## Actors

- Authorized Discord member: invokes permitted slash commands.
- Project lead: receives an intentional user or role mention for a mapped project thread.
- Agent process: submits approved status or question actions through an internal application boundary.
- Operator: configures credentials, Discord permissions, reverse proxy, service process, allowed guild/resources, and lead mappings.

## Interaction endpoint and development commands

- Serve `POST /discord/interactions` behind HTTPS on a contributor-controlled domain such as `agents.example.com`.
- Verify `X-Signature-Ed25519` and `X-Signature-Timestamp` against the exact raw request body before parsing it.
- Return HTTP 401 for missing or invalid signatures without reflecting request data.
- Acknowledge Discord PING interactions with PONG.
- Handle the guild-scoped `/hello`, `/echo`, `/millis`, `/add`, `/dev_history`, `/dev_public`, `/dev_deferred`, `/respond`, `/prompt`, `/agent_thread`, `/explain`, `/summarize`, `/agent_list`, `/agent_config`, `/agent_reset`, `/agent_delete`, `/agent_report`, and `/help` commands discovered under `src/discord_agent_bot/commands/`.
- Keep each command's name, description, option schema, display order, and execution hook in one command module implementing the shared base class.
- Derive dispatch lookup, `/help`, registration payloads, and `config/discord_commands.json` from the same discovered definitions without command-specific branches elsewhere.
- Append one shared optional `public` boolean to every command definition and make `public:yes` channel-visible without weakening guild, destination, user, role, or moderator authorization.
- Return `world!` for `/hello` and the bounded supplied text for `/echo`.
- Return integer milliseconds since process startup for `/millis`.
- For `/add`, add two finite decimal strings when both are numeric; otherwise concatenate them.
- For `/dev_history`, read 1–10 newest messages from only the authorized invoking channel/thread, defaulting to one, without pagination or persistence.
- For `/help`, render every configured slash command and its description as bounded Discord Markdown without network or agent usage.
- For `/dev_public`, omit the ephemeral flag so the static mention-safe response is visible to the channel.
- For `/dev_deferred`, return callback type 5 inside Discord's three-second initial-response deadline, wait more than 15 seconds outside the request path, and edit the original interaction response.
- For `/respond`, defer privately by default, optionally defer publicly, submit one bounded prompt plus non-secret metadata over the private JSON WebSocket, and edit the original response with a bounded Codex answer.
- For `/prompt`, defer privately by default or publicly when explicitly requested, accept an optional validated persistent agent tag, resume a known tag, and initialize a new tagged workspace/conversation when the tag has not been used before.
- For `/agent_thread`, require an explicit validated existing/new agent tag and model shorthand, persist that selected model/reasoning profile, defer privately by default or publicly when explicitly requested, and bind a new public thread below the invoking channel to the invoking user without a `dev1` or thread-derived fallback.
- Forward only ordinary messages authored by that exact creator inside the bound thread. Accept bounded `.txt`, `.md`, `.json`, `.csv`, `.log`, `.pdf`, `.jpg`, `.jpeg`, and `.png` attachments into the selected workspace's request-specific `tmp/download/` directory; ignore other users, bots, webhooks, unrelated guilds/channels, empty messages, and duplicate message IDs.
- Return only validated files placed directly in the matching request-specific `tmp/upload/` directory, using one mention-safe multipart Discord response. Outbound files may use every inbound format plus `.zip`; ZIP is never an inbound format, including when its signature is hidden behind another extension. Limit each direction to three files, 10 MiB per file, and 20 MiB combined; reject paths, symlinks, nested outputs, unsupported or mismatched signatures, non-Discord download origins, and changed outbound digests.
- Archive or deletion of a bound Discord thread deactivates its binding and cancels undelivered local work without deleting its tagged worker conversation or workspace.
- For `/explain`, defer privately by default or publicly when explicitly requested, direct Codex to use the active workspace's application wiki first, allow clearly distinguished general knowledge, and return a bounded explanation.
- For `/summarize`, read up to 100 recent messages from only the authorized invoking channel/thread, build a bounded topic-focused prompt, defer privately by default or publicly when explicitly requested, and return a bounded Codex summary.
- For `/agent_list`, return configured, initialized, and durable queued/history agent tags without invoking Codex; default to a private response and allow deliberate public visibility.
- For `/agent_config`, require a moderator role, explicit agent tag, and bounded shorthand; map it to an explicit Sol, Luna, or Terra model plus low, medium, or high reasoning and persist the override without editing image configuration or falling back to `dev1`.
- For `/agent_reset`, require a moderator role, reject queued or active agents, delete every workspace modification, and reseed the workspace from the current bundled template while retaining its conversation and runtime configuration.
- For `/agent_delete`, require a moderator role, reject queued or active agents, and remove the workspace, worker jobs/activity, conversation metadata and matching Codex rollout, runtime profile/configuration, and Discord thread-binding state for the selected tag.
- For `/agent_report`, require a configured moderator role and an explicit agent tag, then return a private-by-default monospace report for only that agent without invoking Codex; allow public output only when that moderator explicitly requests it.
- Report that selected agent's running versus idle state, pending/processing/processed/completed/failed counts, durable total and current-day active minutes, configured reporting time zone, and newest content-free command records.
- Respond or defer inside Discord's three-second initial-response deadline.
- Make responses ephemeral by default except for `/dev_public`, allow any command to become channel-visible through explicit `public:yes`, and set `allowed_mentions` so echoed or generated input cannot trigger mentions.
- Enforce configured guild and optional channel/thread/user/role allowlists in application code.
- Deduplicate repeated interaction IDs for a bounded period or otherwise make handling idempotent.
- Expose a minimal local health/readiness route that returns no Discord identity, configuration, or secret data.
- Produce structured operational logs containing request/result metadata, not interaction tokens, credentials, raw message bodies, or private message content.

## Milestone 1 acceptance criteria

- Valid signed PING fixture returns a valid PONG response.
- Invalid, missing, and modified signatures return 401.
- Authorized `/hello` returns `world!`.
- Authorized `/echo` returns bounded text without generating a user, role, `@everyone`, or `@here` mention.
- `/millis` uses process-local monotonic uptime and `/add` follows the numeric-or-concatenation contract.
- `/dev_history` cannot select an arbitrary destination, defaults to one message, rejects counts outside 1–10, and never logs or persists returned content.
- `/help` reflects the complete version-controlled slash-command catalog and cannot generate mentions.
- `/dev_public` is visible to the channel while keeping automatic mentions disabled.
- `/dev_deferred` acknowledges before running its delayed hook and edits the original response without bot authentication.
- `/respond` acknowledges before contacting Codex, sends no Discord credential or history, and returns a bounded mention-safe worker answer with the requested visibility.
- `/prompt` cannot provide a workspace path, keeps conversations separate by validated tag, and uses the default agent when its tag is omitted.
- `/explain` acknowledges before contacting Codex, sends no Discord credential or history, and does not invent application-specific facts when the bundled wiki lacks coverage.
- `/summarize` cannot choose another destination, acknowledges before Discord/Codex work, sends no credentials, and keeps both private and public summaries mention-safe.
- `/agent_list` invokes no Codex child, returns only validated agent tags, and remains bounded to Discord's response limit.
- Agent configuration, reset, and deletion deny non-moderators and cannot race queued or processing work for the selected tag.
- `/agent_report` denies ordinary authorized users without a configured moderator role, requires an agent tag, filters all metrics to it, counts only actual Codex child runtime, and exposes no prompt or response content.
- Requests from a different guild or outside configured scope are denied without revealing configuration.
- Unknown commands and malformed payloads return stable, non-secret errors.
- Duplicate delivery cannot repeat a side effect.
- Tests run without a bot token, network access, Discord server access, or production public key.
- A local timing test demonstrates the simple response path stays well within three seconds.
- The command-registration step is separate from test execution and targets the configured development guild.

## Phase 2: approved information retrieval

The initial `/dev_history` command provides bounded request-time reads from the authorized invoking location. Broader enumeration, pagination, search, and provenance-rich retrieval remain in this phase.

- Enumerate only configured channels and threads visible to the bot.
- Read history with bounded pagination and explicit time/result limits.
- Report permission and inaccessible/private-thread conditions clearly.
- Preserve message identity, author, timestamp, channel/thread source, and jump URL when results need provenance.
- Decide before implementation whether search is request-time only or uses a local index.
- Do not ingest or retain all server content by default.
- Do not send private content to an external AI/search service without explicit approval of provider, fields, retention, and deletion behavior.

## Phase 3: project-thread communication

- Map a stable project identifier to one configured guild, thread/channel ID, and approved lead user/role IDs.
- Post status only in the mapped target and only when the initiating workflow is authorized to communicate.
- Ask concise, actionable questions and avoid repetitive reminders.
- Mention a lead only through the mapping and an explicit `allowed_mentions` allowlist.
- Never permit arbitrary mention syntax from user, model, or retrieved Discord text.
- Record success/failure metadata locally without copying full confidential message content into routine logs.

## Phase 4: optional event-driven operation

- Use the implemented Discord Gateway observer only for the reviewed `/agent_thread` ordinary-message and thread-closure events.
- Request only the events/intents needed by that requirement.
- Treat reconnects, resume state, backoff, duplicate events, shutdown, and supervision as production requirements.
- Keep Gateway event ingestion separate from HTTP interaction acknowledgement.

## Non-functional requirements

- Use a supported Python 3 version available on the target server and a project-local `scripts/.venv`.
- Keep dependencies minimal, maintained, pinned or locked, and documented.
- Use bounded HTTP timeouts, Discord rate-limit handling, and graceful shutdown.
- Keep the public endpoint stateless for milestone 1 except for bounded deduplication state.
- Run the upstream application on loopback or a private service network behind the reverse proxy.
- Use least-privilege service and filesystem permissions.
- Provide operator-visible health, redacted diagnostics, and restart behavior.
- Keep source, tests, deployment configuration examples, and operational documentation reviewable without credentials.

## Codex worker proof-of-concept extension

- Run the Codex CLI in a second non-root container with no host project mount and no Discord credentials.
- Accept bounded JSON prompt envelopes over a Compose-private unauthenticated WebSocket and return accepted plus terminal response/error events.
- Persist an idempotent SQLite queue with an agent tag per job and the Codex conversation identifier keyed by tag across ordinary container recreation.
- Execute one `codex exec` turn at a time across all tags, select the declared agent's reviewed Codex permission mode, grant each agent a writable `/workspaces/<tag>` directory in the workspace volume, and resume the matching tagged conversation on later prompts. The container-isolated mode bypasses the nested CLI sandbox and relies on the dedicated read-only-root container as the external isolation boundary; workspace-write and auto-review modes retain the Codex workspace sandbox.
- Load the active agent's optional model, reasoning level, and permission mode from `config/config_agents.json`; null model values retain Codex CLI account defaults and dynamic tags use the container-isolated permission mode.
- Seed every explicitly configured agent workspace from the generic template during worker startup while preserving existing work and wiki contents.
- Report the active or most recently observed model and reasoning level from Codex runtime turn metadata, never by treating requested configuration as execution evidence.
- Persist the tagged workspace in a dedicated Compose volume. Initialize new workspaces from the generic tracked worker-project template with layered instructions, a project-local Python virtual-environment bootstrap, reusable scripts, data, logs, temporary, source, test, resource, and documentation directories. Fill missing template files in older sparse workspaces without overwriting their maintained work or wiki. Treat `docs/wiki` as read-only through agent instructions during ordinary work, while retaining filesystem write access for explicit knowledge-base maintenance.
- Keep account authentication as a separate human device-login operation whose credentials live in a named volume.
- Treat tag-level authorization/ownership beyond creator-bound threads, WebSocket authentication/TLS, queue cleanup, confidential content, repository access, stronger per-agent isolation, and restart-safe interaction-webhook delivery as future production work.

## Explicit non-goals for the first milestone

- Searching message history, broad channel discovery, or building a semantic index.
- General-purpose Discord Gateway ingestion beyond bound agent-thread message and closure events.
- Posting proactive status or questions.
- Mentioning project leads.
- Deploying to the production webserver.
- Changing DNS, TLS, reverse-proxy, system service, Developer Portal, guild, channel, thread, role, or bot configuration.
- Any LLM integration beyond the explicitly approved isolated `/respond`, `/prompt`, `/agent_thread`, `/explain`, and `/summarize` flows.
