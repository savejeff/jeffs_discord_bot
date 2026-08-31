# Security and Operations

## Credential boundary

The application needs the Discord application public key for interaction verification. REST history and registration need the bot token. Deferred commands temporarily hold the interaction token needed to edit their original response. The worker separately keeps Codex login tokens under `CODEX_HOME` in the `codex-home` volume. Treat bot, OAuth, interaction, and Codex authentication tokens as passwords. The Discord public key is not secret, but it is deployment configuration and should not be hard-coded into reusable source.

Supported configuration direction:

- production values injected by the existing service manager or approved host secret mechanism;
- developer values injected into the process environment from an ignored machine-local mechanism;
- no token on command lines, in shell history, `.env` files committed to Git, prompts, exception strings, logs, reports, screenshots, or test fixtures;
- no new `secret/` directory assumed secure merely because it is ignored.

The example at `config/discord.env.example` lists names only. Do not fill it with real values.

## Discord permissions

Request only the permissions required by the active milestone.

| Capability | Expected access |
|---|---|
| Slash command only | `applications.commands`; HTTP interaction verification uses the application public key. |
| View configured server channels | Bot installed to the guild plus `VIEW_CHANNEL` on those channels. |
| Read configured history | `READ_MESSAGE_HISTORY`; message-content availability must be verified with the current Discord intent rules. |
| Post to text channels | `SEND_MESSAGES` only where configured. |
| Post to threads | `SEND_MESSAGES_IN_THREADS`; private threads may require explicit membership. |
| Passive message-event processing | Relevant Gateway intents; `MESSAGE_CONTENT` is privileged and must be enabled/approved as applicable. |

Do not request `Administrator`. Do not grant channel/thread-management permissions simply to bypass a clear membership or allowlist design.

## Application authorization

Discord installation and command visibility are not sufficient authorization controls. Check the configured guild ID on every guild command. Before later sensitive commands, also check channel/thread ID and at least one explicit user or role policy. Default deny on missing configuration or ambiguous context.

`/agent_thread` may be invoked only after the ordinary interaction policy accepts its guild, parent channel, and actor. It requires an explicit tag and model shorthand, persists that runtime profile, creates a new public thread, and records that exact actor as creator of the durable binding. The Gateway observer accepts ordinary message text only when guild ID, thread ID, active binding, and author ID all match in one SQLite transaction. Other members may read and participate in the public thread, but their messages are never forwarded to Codex. Tags remain continuity labels rather than authorization boundaries: selecting an existing tag deliberately shares and can reconfigure that agent's conversation and workspace for the new creator-owned thread.

`/agent_report`, `/agent_config`, `/agent_reset`, and `/agent_delete` add a second command-level check: the invoking member must hold at least one role in `DISCORD_MOD_ROLE_IDS`, in addition to passing the ordinary guild, destination, and actor policy. Each per-agent administration command requires an explicit agent tag; `/agent_list` is the catalog exception. Missing moderator configuration denies these commands. The report is private by default, filters status to the selected tag, and contains no prompts, responses, history content, credentials, or interaction tokens. A moderator who selects `public:yes` deliberately exposes the selected command's result to other members in that destination.

Use a dedicated development channel and guild-scoped command while testing. Promote to a global command only after behavior and permissions have been reviewed.

## Mentions

Set `allowed_mentions.parse` to an empty list for echoes, summaries, retrieved content, and model-generated text. Escape or otherwise neutralize `@everyone`, `@here`, user, and role mention forms in untrusted content.

For a deliberate project-lead alert, the policy layer must resolve configured numeric user or role IDs and provide only those IDs in the explicit allowed-mentions list. Never accept an arbitrary mention ID or raw mention string from a slash-command option, retrieved message, or model output.

## Response visibility and deferred work

Responses are ephemeral by default, and the shared optional `public` parameter can make an authorized result channel-visible. `/dev_public` remains the deliberate public-by-default development command. Both public and ephemeral responses must disable automatic mentions, and unauthorized denials remain private regardless of the requested visibility.

Work that may approach Discord's three-second deadline must return a type-5 deferred acknowledgement first. The initial acknowledgement fixes whether the final response is public or ephemeral. Keep the interaction token only in memory for the minimum completion interval, exclude it from hook inputs and logs, and edit only the original response. The implemented `/dev_deferred` background task demonstrates the protocol but is not restart-safe. Durable or AI work requires the queue and separate worker boundary in `docs/CODEX_AGENT_INTEGRATION.md`.

## Confidential Discord content

Assume non-public channels, private threads, attachments, member identities, and message history are confidential. Any retrieval must be scoped, bounded, and attributable to source messages. The current thread proof of concept stores creator messages and supported attachment bytes as described below; it is not a production retention boundary.

The approved `/dev_history` development command performs one request-time read from only the authorized channel/thread in the signed interaction. It accepts no destination ID, returns at most ten messages ephemerally, suppresses mentions, and does not persist or routinely log message content. `/summarize` uses the same destination boundary but reads up to 100 recent messages and deliberately sends a bounded transcript to the Codex worker and OpenAI. A missing permission, unavailable content, timeout, or rate limit must produce a generic non-secret response.

The `/agent_thread` observer deliberately persists accepted creator prompts, answers, and outbound attachment manifests in `discord-gateway-data` until delivery succeeds. Delivered rows retain only routing/status metadata; prompt, answer, and manifest content is scrubbed. Supported creator attachments are copied into `codex-workspaces` under `tmp/download/<request-id>/`, and validated agent outputs are read only from `tmp/upload/<request-id>/`. These temporary files currently have no automatic cleanup. The Codex worker independently retains its ordinary job and conversation data. Archiving/deleting a thread cancels queued local delivery and prevents an in-flight answer from being posted, but it does not erase worker history or workspace data. Define retention and deletion controls before treating this as a production confidentiality boundary.

Before expanding this bounded proof of concept or adding local indexing, obtain a production decision covering:

- exactly which channels/threads may be ingested;
- whether deleted or edited Discord messages must be removed or updated;
- storage host, encryption, backup, retention, and access;
- which attachment types, limits, retention, malware scanning, and deletion semantics are approved beyond the current bounded document/image input and outbound-ZIP proof of concept;
- model/provider and which content leaves the server;
- provider retention/training settings;
- operator deletion and audit procedures.

`/respond` sends only its explicit prompt plus non-content guild/channel routing metadata. `/prompt` sends the same data and may select a validated persistent agent tag. `/explain` sends its topic and directs Codex to read the bundled wiki; wiki content may therefore cross the OpenAI model boundary even though it is not copied into the WebSocket request. `/summarize` additionally sends message authors, timestamps, and bounded content from the current authorized channel/thread. Agent-thread attachments cross the OpenAI boundary when Codex reads them. `/agent_list` sends no prompt and returns only configured or durable tag names, but those names may still disclose project labels when made public. The prompts tell Codex to treat wiki, history, and attached files as untrusted evidence rather than instructions, but that does not make prompt injection impossible. The worker stores prompts, transcripts, agent tags, metadata, answers, queue state, and tagged conversation identifiers unencrypted in `codex-worker-data`; workspaces, including temporary attachment bytes, are unencrypted in `codex-workspaces`. It has no retention cleanup yet. All authorized callers can currently enumerate, name, and therefore share an existing tag or create persistent workspace state, so tags are continuity labels rather than authorization boundaries. This can also consume storage; add ownership, quotas, cleanup, and channel-derived routing before production use. Every command supports deliberate public output without weakening authorization. Callers must consider whether echoed text, channel history, wiki facts, agent tags, or moderator-report identifiers are appropriate for everyone in the destination before choosing `public:yes`.

The worker WebSocket and artifact HTTP endpoints are internal service interfaces. They are exposed only to the private Compose network and must never have a host `ports` mapping or public proxy route. The Discord gateway has no worker credential because network isolation is the current access boundary. Add mutual authentication, authorization, replay controls, transport protection where needed, per-caller conversation isolation, retention, and audit policy before treating the worker as a reusable production service.

The same private socket exposes explicitly tag-scoped, content-free status requests and catalog-wide agent-list requests used by `/agent_report` and `/agent_list`. Neither starts Codex nor adds a queue job. Durable one-second heartbeats measure Codex child activity; interrupted open intervals close at their last heartbeat during recovery so container downtime is not counted as active usage.

The private socket also exposes moderator-triggered configuration, reset, and deletion operations through the Discord service. The worker validates tags and model profiles again and serializes lifecycle changes against prompt submission and claiming. An agent with pending or processing work cannot be reset or deleted. Reset deliberately removes all workspace modifications, including agent-written wiki changes and temporary attachments. Delete additionally removes worker queue/history, conversation/profile metadata, durable runtime overrides, and matching Discord thread bindings. The shared Codex authentication volume is never deleted by an agent command.

Codex runs as a non-root user in a dedicated container with no Discord secrets, Docker socket, host project mount, or published port. Its nested CLI sandbox is bypassed because that Linux sandbox failed to initialize inside Docker. The external boundary instead uses a read-only container root plus explicit writable mounts for `/workspaces`, Codex login state, worker data, and `/tmp`. Every validated tag receives `/workspaces/<tag>` backed by the `codex-workspaces` volume and seeded with the generic worker project. Its bundled instructions keep Python dependencies in `scripts/.venv`, route mutable data, logs, and temporary material explicitly, and make `docs/wiki` read-only by default while permitting knowledge-base writes when the current user asks for them; these are instruction policies rather than additional filesystem restrictions. Wiki content is sent to the model when Codex reads it, is retained in the workspace volume and Docker seed image, and must never contain credentials or tokens. Model access still requires outbound network access to OpenAI; filesystem isolation does not imply network isolation. Do not add host mounts or mutually untrusted agents to this shared bypass-mode container. The implementation details and future hardening path are documented in `docs/CODEX_AGENT_INTEGRATION.md`.

## Public HTTP endpoint

- Accept only the required methods and content type.
- Bound request size and request-processing time.
- Verify the exact raw bytes before parsing.
- Return generic errors without request reflection or stack traces.
- Bind the upstream application to loopback or a private service network.
- Configure trusted proxy headers narrowly; do not trust forwarded headers from arbitrary clients.
- Apply rate limits without blocking legitimate Discord delivery.
- Keep a health endpoint separate from the interaction route and free of identifying configuration.
- Make dependency and framework security updates an explicit maintenance responsibility.

## Gateway observer

- Enable only `GUILDS`, `GUILD_MESSAGES`, and privileged `MESSAGE_CONTENT` for the implemented event flow.
- Keep the observer as a private Compose process with no published port and no reverse-proxy route.
- Grant `VIEW_CHANNEL`, `CREATE_PUBLIC_THREADS`, and `SEND_MESSAGES_IN_THREADS` only in approved parent channels; do not grant `Administrator` or thread-management permission.
- Treat archive and delete events as binding closure. Reopening an archived thread does not silently restore agent access.
- Keep message IDs as the intake deduplication key, use deterministic worker request IDs, and enforce Discord nonces on outbound responses.
- The current resume state is process-local. Events missed after the Discord resume window or while the observer is unavailable are not backfilled from channel history.

## Logging and audit

Useful fields include timestamp, interaction ID hash or safely retained ID, interaction type, command name, configured guild/channel match result, outcome, HTTP status, elapsed time, Discord REST status/rate-limit metadata, and correlation ID.

Do not log authorization headers, bot tokens, OAuth tokens, interaction tokens, signatures, raw bodies, command option values by default, retrieved messages, outbound full text, or lead mappings. Use structured redaction tests.

## Deployment and rollback

Deployment remains an external mutation requiring approval. Before the first live deployment:

1. Record the host OS, Python version, reverse proxy, service manager, service account, filesystem path, port/socket, and secret-injection mechanism.
2. Back up or capture the existing relevant reverse-proxy/service configuration before modifying it.
3. Bind and test the service locally before exposing the route.
4. Validate TLS and raw-body forwarding with a controlled request.
5. Register the guild command only after the endpoint passes offline checks.
6. Configure the Interactions Endpoint URL and capture only non-secret evidence of Discord's validation result.
7. Test in the dedicated channel with a non-privileged account and verify denials elsewhere.
8. Define rollback for the service, reverse-proxy route, command registration, and leaked-token response.

If a token is exposed, stop the service's use of it, rotate it in the Discord Developer Portal, replace the deployment secret, check logs/history for propagation, invalidate exposed artifacts, and document the incident without repeating the token.
