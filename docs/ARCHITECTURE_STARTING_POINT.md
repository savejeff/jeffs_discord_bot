# Architecture Starting Point

## Current topology

~~~text
Discord
  -> Gateway MESSAGE_CREATE / THREAD_UPDATE / THREAD_DELETE
  -> private Gateway observer
      -> creator and active-binding check in shared SQLite
      -> private Codex worker WebSocket
      -> mention-safe Discord REST response in the bound thread
  -> HTTPS POST https://agents.example.com/discord/interactions
  -> existing TLS reverse proxy
  -> loopback/private ASGI service
  -> raw-body signature verifier
  -> interaction parser and authorization policy
  -> bounded command dispatcher
  -> optional scoped Discord REST history read
  -> inline Discord interaction response or deferred acknowledgement
  -> bounded background completion through the interaction webhook
       -> JSON WebSocket client for /respond, /explain, and /summarize
       -> private Compose network
       -> durable single-consumer Codex worker
       -> codex exec --json inside the dedicated read-only-root worker container
       -> WebSocket answer
~~~

This direction matches the requested public endpoint while keeping Discord authentication and command policy inside the application. The reverse proxy should not parse, rewrite, decompress, or reserialize the request body before signature verification.

## Component boundaries

### HTTP adapter

Own route handling, raw request bytes, header extraction, body-size limits, response content type, status codes, and request deadlines. It must not dispatch an unverified body.

### Signature verifier

Own Discord Ed25519 verification using the configured application public key. It should return a simple verified/rejected result and never log key material, signatures, timestamps, or bodies at normal log levels.

### Interaction application service

Parse verified JSON, classify PING and application-command interactions, enforce guild/resource/actor policy, deduplicate interaction IDs, dispatch commands, and construct safe interaction responses.

### Command handlers

Each concrete `CommandDefinition` under `src/discord_agent_bot/commands/` owns one command's registration metadata and asynchronous hook. Package discovery requires exactly one concrete command class per non-private module, and the immutable registry validates unique names before exposing lookup, help text, and Discord schemas. Adding or removing a command therefore does not require edits to transport, dispatch, help, registration, or Docker code.

`/hello`, `/echo`, `/millis`, `/add`, `/dev_public`, `/dev_deferred`, and `/help` are deterministic. `/help` receives Markdown generated from the registry. `/dev_history` receives a narrowly scoped history-reader operation through `CommandContext` rather than credentials or arbitrary destination access. `/respond` receives only a default `AgentRequester` operation. `/prompt` may additionally pass one validated tag to that operation; it cannot pass a path or model credential. `/agent_thread` requires an explicit tag and shared model shorthand, receives the narrow `AgentManager` configuration capability followed by the thread-creation boundary, and persists the verified creator plus explicit tag after Discord creates the thread. `/explain` uses the default requester with a prompt that makes the bundled `docs/wiki` knowledge base primary and permits clearly distinguished general knowledge. `/summarize` composes history-reader and default requester operations: it reads at most 100 messages from the invoking destination, builds a bounded untrusted-data prompt, and sends it to the worker. `/agent_list` receives a content-free tag-list operation and does not invoke Codex. The moderator-only `/agent_config`, `/agent_reset`, and `/agent_delete` modules also receive the narrow `AgentManager` capability rather than filesystem or database access. The shared command base appends the optional `public` boolean to every registration schema and resolves visibility before acknowledgement; individual modules retain their own defer and default-visibility policy.

`/dev_deferred`, `/respond`, `/explain`, and `/summarize` return callback type 5 before their hooks run. The ASGI background task edits the original response through the interaction webhook. Agent commands submit to a durable worker queue, but callback delivery itself remains process-local: a Discord gateway restart can lose the eventual edit even though the worker job survives. Every normally private command omits the ephemeral response flag only when `public` is explicitly true; `/dev_public` remains public by default.

### Codex worker

`src/codex_agent_worker/` is a separate ASGI application. Its private `/ws` route accepts one bounded JSON prompt plus a validated agent tag per connection, persists both idempotently in SQLite, and returns an acknowledgement followed by a completed response or generic error. It also serves content-free status and agent-tag catalog requests. One global queue consumer invokes `codex exec --json` sequentially across tags and persists each thread ID separately for `codex exec resume`. `config/config_agents.json` supplies optional model and reasoning overrides plus a per-agent Codex permission mode for declared tags; an undeclared valid tag receives CLI/account defaults and the container-isolated mode. Worker startup seeds every declared workspace from the generic project template, while dynamic tags are initialized on first use. Each agent runs in persistent `/workspaces/<tag>`, derived internally rather than from a caller path. A later production policy should derive or authorize tags against verified Discord channels/threads instead of letting every authorized caller name or enumerate them freely. The worker has no Discord credentials, Docker socket, host project mount, or published host port.

The same route accepts a content-free status request with an explicit agent tag. SQLite activity intervals begin when a job is claimed, receive a one-second heartbeat while the Codex child runs, and close on completion or failure. Startup closes an interrupted interval at its last heartbeat before re-queuing the job. `/agent_report` consumes a tag-filtered snapshot through a typed client only after the generic command dispatcher verifies the configured moderator role.

### Generated command configuration

`config/discord_commands.json` is a reviewable generated artifact, not the command source of truth. `scripts/generate_command_config.py` constructs it from the discovered definitions and supports a non-mutating `--check` mode. The Docker build generates its bundled copy from source, and deliberate registration consumes the registry directly so stale checked-in JSON cannot change runtime or registration behavior.

### Discord REST adapter

The minimal adapter owns bot-token authentication, a two-second request timeout, response-size limits, safe API error mapping, and one request-time message read from the invoking channel/thread. A separate bot-token-free webhook adapter can edit an original deferred response using the verified interaction's application ID and short-lived interaction token. Command registration remains a separate deliberate operation. Pagination, search, and outbound project-thread posts remain future work.

### Project mapping policy

Add before outbound project communication. Map project IDs to exact guild/channel/thread IDs and approved lead user/role IDs. Treat mappings as non-secret but deployment-sensitive configuration and review changes like access-control changes.

### Gateway observer

`src/discord_gateway_observer/` is a separate process built from the interaction-service image. It identifies with only `GUILDS`, `GUILD_MESSAGES`, and privileged `MESSAGE_CONTENT`; owns heartbeat, reconnect, in-memory resume state, bounded event decoding, and clean shutdown; and exposes no host port. `MESSAGE_CREATE` is accepted only when the shared SQLite store atomically matches guild, thread, active state, and exact creator ID. Discord message IDs deduplicate intake, deterministic worker request IDs deduplicate Codex submission, and Discord nonces reduce duplicate outbound posts. `THREAD_UPDATE` with `archived:true` and `THREAD_DELETE` deactivate the binding while preserving its agent tag.

The shared `discord-gateway-data` volume is a narrow cross-process boundary between the signed interaction service and observer. It retains bindings and restart-safe prompt/answer delivery state, but delivered prompt and answer text is scrubbed from this local store. The Codex worker remains the owner of tagged conversation/workspace persistence. The HTTP interaction path and `/prompt` do not depend on Gateway event dispatch.

## Suggested package shape

The names are guidance, not an implemented API:

~~~text
src/discord_agent_bot/
  application.py
  config.py
  interactions.py
  authorization.py
  discord_rest.py
  codex_worker_client.py
  commands/
src/discord_gateway_observer/
src/codex_agent_worker/
  application.py
  codex_runner.py
  storage.py
tests/
config/discord.env.example
~~~

Framework entry points should remain thin and call reusable package code. Keep command-registration tooling under `scripts/` or an explicit package CLI so imports and service startup never mutate Discord automatically.

## Interaction sequence

1. Read headers and bounded raw bytes.
2. Verify Discord signature over timestamp plus the unchanged body.
3. Parse JSON only after verification.
4. Return PONG immediately for type 1.
5. For a slash command, validate interaction type, guild, channel/thread, actor, command, and option schema.
6. Reserve/deduplicate the interaction ID.
7. Produce the immediate response or type-5 acknowledgement. Deferred hooks run only after the acknowledgement is sent and edit the original response afterward. `/respond`, `/explain`, and `/summarize` traverse the private worker WebSocket during this deferred phase.
8. Set allowed mentions explicitly on every response or outbound message.
9. Log only redacted metadata and outcome.

## Search direction for phase 2

Start with bounded, on-demand Discord REST history reads across an explicit channel/thread allowlist. This avoids accumulating a second copy of private discussions. If response quality or latency later requires an index, document its data model, storage location, encryption, access, retention, deletion, rebuild, and external-model boundary before implementation.

Do not assume a Discord-wide search endpoint is the correct or stable foundation. Preserve source message IDs and locations so every result can be traced back to Discord and permission failures remain visible.

## Communication direction for phase 3

Expose one internal application-level operation such as `post_project_update(project_id, text, mention_lead=False)` rather than accepting arbitrary Discord destination IDs or mention syntax from an agent. The policy layer resolves the destination and allowed lead IDs. The Discord adapter sends text with explicit `allowed_mentions`; it does not parse arbitrary mentions.

## Production decisions left open

- In-memory versus external deduplication when multiple workers are used.
- Authenticated worker transport and per-caller conversation mapping.
- Queue retention, encryption, cleanup, and restart-safe Discord callback delivery.
- Reviewed worker repository mounts, tools, network policy, and write sandbox.
- A pinned and integrity-verified Codex CLI installation artifact.
