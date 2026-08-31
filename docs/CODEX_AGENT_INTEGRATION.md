# Codex Agent Integration

## Status and recommendation

The proof of concept is implemented as a separate `codex-agent-worker` container behind the Discord services. `/respond` sends a bounded explicit prompt to the default agent. `/prompt` remains the manual one-shot route and optionally selects or creates persistent tagged agent state. `/agent_thread` creates a creator-owned public Discord thread whose ordinary creator messages reach the same tagged worker through a narrow Gateway observer. `/explain` directs the default agent to consult its workspace's application wiki first and supplement it with clearly distinguished general knowledge. `/summarize` reads up to 100 recent messages from the invoking authorized channel/thread and sends a bounded topic-focused transcript prompt to the default agent. Slash-command agent flows acknowledge immediately, communicate over the Compose-private JSON WebSocket, and edit their original Discord response when the answer arrives. `/agent_list` combines a content-free worker request with retained thread-binding tags without creating a Codex turn.

The worker persists one idempotent sequential SQLite queue with a tag on every job, starts one transient `codex exec --json` child at a time, retains returned Codex thread IDs under their agent tags, and returns only the final agent message. Its unauthenticated WebSocket is deliberately not published outside the Compose network. Codex authentication, worker data, and tagged workspaces persist in separate named volumes. `dev1` is the default, while `/prompt` may route to another validated tag.

The worker also records durable activity intervals with one-second heartbeats and serves a content-free, explicitly tag-scoped status snapshot without invoking Codex. Moderator-only `/agent_report agent_tag:<tag>` renders only that agent's counters, observed runtime model/reasoning profile, and recent command/user/destination metadata, never prompt or response content. UTC defines the current-day boundary in Compose.

The workspace seed follows the repository's Python project, documentation-layer, project-island, and local-venv conventions. Its directory ownership and short-lived Codex-process model keep transport outside the agent while durable project files and conversation continuity remain inside the worker boundary.

Keeping these responsibilities separate gives the public endpoint a small attack surface and lets the Codex worker have a different filesystem, network, credential, and sandbox policy.

## Protocol limits that shape the design

Discord requires an initial interaction response within three seconds and invalidates the interaction token if that deadline is missed. A `DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE` response, callback type `5`, acknowledges the command and shows a loading state. The application can later edit the original response with `PATCH /webhooks/{application_id}/{interaction_token}/messages/@original`. Interaction tokens remain valid for 15 minutes, and response visibility is fixed by the initial response: an ephemeral defer cannot later become public, or vice versa. See [Discord receiving and responding](https://docs.discord.com/developers/interactions/receiving-and-responding).

Consequences:

- every agent command must validate and defer before starting Codex;
- the job must normally finish and edit the original response inside 15 minutes;
- a job that may exceed 15 minutes needs another result route, such as a bot-authenticated post to a pre-authorized thread or a later `/job_status` lookup;
- interaction tokens are short-lived confidential credentials and must not appear in logs, queue diagnostics, process arguments, or agent prompts;
- automatic mentions must remain disabled for all model-produced text.

`/dev_deferred`, `/respond`, `/explain`, and `/summarize` use the deferred callback path. Agent commands have a durable worker queue, but their Discord completion task is still process-local: a gateway restart can lose delivery even though the Codex job survives. The universal optional `public` boolean fixes a channel-visible response at defer time; omission keeps these agent responses private.

## Implemented proof-of-concept topology

~~~text
Discord
  -> HTTPS interaction service
      -> raw-body signature verification
      -> guild/channel/thread/user/role authorization
      -> type-5 deferred acknowledgement within three seconds
      -> private JSON WebSocket request
  -> private Codex worker
      -> persist an idempotent SQLite job
      -> resolve configured settings or dynamic defaults for the validated tag
      -> derive /workspaces/<tag> internally and resolve its thread ID
      -> start transient `codex exec --json` child
      -> parse progress, thread ID, and final agent message
      -> read actual model/reasoning from Codex rollout turn_context
      -> persist job state, thread ID, and last observed runtime profile
  -> response adapter
      -> edit original interaction within 15 minutes
~~~

SQLite is sufficient for this one-host, one-worker proof of concept. The worker recovers interrupted `processing` jobs to `pending`, processes one job at a time, and preserves completed results for idempotent resubmission. It does not yet implement leases, cleanup, cancellation, a durable Discord outbox, or high availability.

## What the worker image needs

The existing Python service image remains the gateway image. `Dockerfile.codex-worker` builds the second image with:

- a minimal supported Linux base with CA certificates, Git, a shell, and only the build tools required by approved target repositories;
- the [Codex CLI](https://learn.chatgpt.com/docs/codex/cli), installed as a non-root service user;
- a verified `codex --version` build check;
- the queue client and a small supervisor that invokes and monitors Codex;
- writable named volumes for Codex authentication and queue/conversation state;
- persistent `/workspaces/<tag>` directories with no host repository mount, each initialized from a generic Python-capable worker project plus the application-specific knowledge base under `docs/wiki`;
- `config/config_agents.json`, which can optionally select the active agent's model and reasoning level;
- no Docker socket, host root mount, Discord bot token, or unrelated server directories.

The official Linux installer is currently:

~~~sh
curl -fsSL https://chatgpt.com/codex/install.sh | sh
~~~

That command is suitable for proving the image layout, but it installs the current release and therefore makes builds drift. Before production use, select a reviewed Codex version, pin the installation source and checksum if the distribution mechanism supports it, and fail the image build unless the expected version is present. Run the installer as the final non-root worker user and add its verified binary directory to `PATH`.

The proof of concept supports a per-agent `codex_permission_mode`. `container-isolated` invokes Codex with `--dangerously-bypass-approvals-and-sandbox` because the nested Linux sandbox has not initialized reliably in every Docker runtime used for this worker. In that mode Docker becomes the enforcement boundary: the worker runs as a dedicated non-root user, its root filesystem is read-only, and it has no host checkout, Docker socket, Discord credentials, or published port. `workspace-write` uses the Codex workspace sandbox without interactive approvals. `auto-review` combines that workspace sandbox with on-request approvals routed to Codex's separate automatic reviewer. The shipped catalog is empty, so on-demand agents use `container-isolated` unless a future fixed-purpose entry declares another policy. Only the named workspace, Codex login-state volume, worker-data volume, and bounded `/tmp` tmpfs are writable at the container level. A later worker that edits a mounted repository will also need the repository plus its reviewed toolchain. Codex can only use compilers, test runners, and project tools that exist in the container. Prefer separate worker-image variants or reviewed project profiles over one privileged image containing every tool.

Container-level permissions and auto-approved sandbox escalation mean a Codex child is not a hard security boundary from other writable paths mounted into the same worker container. Tags currently provide separate working directories and conversation continuity, not protection from each other. Only one child runs at a time, but mutually untrusted agents require a separate worker container or equivalently strong external sandbox per workspace, plus separation of supervisor data and provider credentials from agent-controlled filesystem access.

### Filesystem layout

A practical layout is:

~~~text
/opt/discord-agent/            read-only worker application
/var/lib/discord-agent/        durable queue and job metadata
/var/lib/codex/                CODEX_HOME and session state, protected
/workspaces/<agent-tag>/       one persistent workspace per approved agent
/tmp/discord-agent/<job-id>/   bounded temporary job material
~~~

The Codex child process lives inside the worker container only while a turn is running. Its current working directory is `/workspaces/<tag>`, derived from a validated tag rather than a path supplied by Discord. The image combines `config/codex-worker/workspace-template/` with the deployment-local `res/wiki/` seed. Worker startup seeds only tags declared in `config/config_agents.json`; the shipped empty catalog therefore creates no workspace. Initializing a dynamic tag copies the same complete generic project on first use. Initializing an existing tag fills missing seed files without replacing maintained work or its wiki; only root `AGENTS.md` is deliberately refreshed as current operational policy. The template supports project-local Python dependencies in `scripts/.venv`, reusable utilities in `scripts/`, persistent work data in `data/`, raw output in `logs/`, disposable material in `tmp/`, and durable documentation. The `codex-workspaces` volume preserves all files across container recreation. Instructions make the wiki read-only by default, but an explicit request to maintain the knowledge base may write it because no filesystem read-only restriction is applied. Each conversation survives through Codex session data plus the thread ID stored under its tag; processes do not remain alive between messages.

`config/config_agents.json` maps declared tags to optional `model` and `reasoning_level` values plus a `codex_permission_mode`. Null model values keep the installed CLI/account defaults. A configured model is passed with `--model`; a configured reasoning level is passed as the CLI configuration override `model_reasoning_effort`. `CODEX_AGENT_TAG=dev1` selects the default. `/prompt` may supply another validated tag; undeclared tags use null/default model settings and `container-isolated` permissions and are not written into configuration. `/agent_list` combines declared tags, initialized valid workspace directory names, tags retained in the durable worker job store, and tags retained by active or closed agent-thread bindings. The worker always selects the tagged workspace and thread ID together. Production should add ownership beyond the exact creator check applied to bound threads.

Moderator-only `/agent_config` requires an explicit tag and stores its runtime override in the worker database; it takes precedence over `config_agents.json` and survives container rebuilds. `/agent_thread` also requires an explicit tag plus the same model shorthand before creating its binding; neither command falls back to `dev1`. The shorthand values `low`/`medium`/`high` select `gpt-5.6-sol`, while the `luna-` and `terra-` forms select those families with the suffix reasoning effort. `/agent_reset` replaces the complete workspace with the current template but retains the tag's conversation/configuration. `/agent_delete` removes the workspace and durable agent-specific state; a later `/prompt` using the same tag creates a fresh agent. Lifecycle changes are refused while that tag has queued or active work.

Configuration expresses what the worker requests, not proof of what Codex used. The authoritative report source is the newest matching `turn_context` record written under `CODEX_HOME/sessions`; Codex records the selected model slug and turn effort there. During a child run, `/agent_report` labels the profile `CURRENT` only after a turn-context record newer than that process start is visible. Otherwise it reports the most recently observed profile from the durable worker database. Before the first observed turn, both values are `unknown`. The parser reads only the runtime fields and does not include rollout prompts or responses in the status payload. See the official Codex [`TurnContextItem` construction](https://github.com/openai/codex/blob/main/codex-rs/core/src/session/turn_context.rs).

For a future repository-capable version, use a dedicated checkout or worktree per concurrently writable conversation. A shared writable checkout with concurrent agents will create ambiguous ownership and conflicts. Keep any future host mount narrowly scoped to the approved workspace rather than broadening the sandbox or exposing unrelated paths.

### Authentication and secrets

Codex supports ChatGPT login for subscription access and API-key login for usage-based access. This proof of concept deliberately selects ChatGPT device authentication so the worker can use the signed-in account's available Codex plan. Run `sh scripts/codex_login.sh`, open the displayed URL in a trusted browser, enter the short-lived code, and complete login with the intended account. The [authentication guide](https://learn.chatgpt.com/docs/auth) documents this headless flow and warns that cached credentials under `CODEX_HOME`, including `auth.json`, contain access tokens and must be treated like a password.

The implemented credential boundary is:

1. `scripts/codex_login.sh` starts a temporary worker container with the persistent `codex-home` volume attached.
2. The human completes `codex login --device-auth` in a browser; no access token is passed as a script argument.
3. Normal worker containers mount the same volume at `/home/codex/.codex`.
4. Rebuilding or running `docker compose down` retains the login; deleting Compose volumes removes it.

Do not bake OpenAI credentials into an image or Compose file. Do not place them in the same long-lived environment as arbitrary repository build scripts. OpenAI explicitly warns that repository-controlled code can read job-level environment variables. The worker must therefore define whether target repositories are fully trusted, or use a credential proxy/broker that keeps the provider credential outside the repository execution environment.

Discord credentials and OpenAI credentials should have different owners:

- the interaction gateway verifies Discord and owns the short-lived interaction token;
- a narrowly scoped response component owns only the ability to complete an approved Discord job;
- the Codex worker owns only its OpenAI authentication and approved project filesystem;
- the Codex child receives neither the Discord bot token nor the interaction token.

## Starting, prompting, and resuming the agent

The [non-interactive Codex mode](https://learn.chatgpt.com/docs/non-interactive-mode) is the smallest integration surface. It emits progress on `stderr`, can emit machine-readable JSON Lines with `--json`, and emits events including `thread.started`, command execution, file changes, agent messages, and turn completion.

The worker should construct arguments as a list, set the child working directory directly, and send the prompt through standard input rather than placing user or private text in process arguments. Conceptually:

~~~text
codex exec --json --dangerously-bypass-approvals-and-sandbox --skip-git-repo-check -C /workspaces/dev1 -
~~~

For each job, the worker should:

1. claim the oldest durable queued prompt;
2. create a minimal child environment and expose the OpenAI credential only for that invocation;
3. set the child working directory to `/workspaces/<agent-tag>`;
4. build a bounded prompt from the authorized command, approved context, project instructions, and explicit response contract;
5. stream that prompt to standard input and close it;
6. parse JSONL incrementally with record-size and total-output limits;
7. persist the `thread.started` identifier as soon as it appears;
8. capture the latest completed agent message as the candidate final answer;
9. enforce a wall-clock timeout and cooperative cancellation, then terminate the child if needed;
10. record a redacted result and hand the final text to the response adapter.

For another user turn associated with the same mapped conversation, invoke `codex exec resume <SESSION_ID>` and again pass the new prompt through standard input. Store the session ID by an explicit conversation key, for example guild plus project plus thread plus authorized user policy. Do not let a caller provide an arbitrary Codex session ID.

Start with one Codex turn at a time. Controlled concurrency can be added later with separate checkouts, per-project locks, resource limits, and cost limits.

### SDK and app-server alternatives

The [Codex SDK](https://learn.chatgpt.com/docs/codex-sdk) is a strong later replacement for direct subprocess parsing. The stable Python package can start, continue, and resume local Codex threads and includes a pinned CLI runtime dependency, which fits this Python service better than adding a separate Node application.

The [Codex app server](https://learn.chatgpt.com/docs/app-server) exposes richer lifecycle, approval, and streaming events. It adds protocol and supervision complexity, and its WebSocket transport is currently experimental. Use it only if interactive approvals or detailed live progress justify that complexity. For a first queued command, `codex exec --json` is easier to isolate and matches the investigated reference.

## Returning results to Discord

For jobs expected to complete within 15 minutes:

1. the gateway returns a type-5 defer with its final visibility flag;
2. the job runs outside the request handler;
3. the response adapter validates that the job still owns the interaction;
4. it converts the final agent text to bounded Discord Markdown;
5. it disables mentions, limits or splits text to Discord message limits, and edits the original response;
6. it records only delivery metadata, never the full confidential response by default.

The current `/dev_deferred` implementation uses this same Discord callback sequence but runs a fixed 16-second sleep in a Starlette background task. A production agent command must enqueue before returning and must not depend on the gateway process staying alive.

Progress updates should be coarse and rate-limited. They may edit the loading response while the token is valid, but raw chain-of-thought, command output, repository secrets, and unrestricted logs must never be sent to Discord. Suitable progress states are queued, inspecting, testing, waiting for approval, completed, failed, and cancelled.

For jobs that can exceed 15 minutes, choose one reviewed contract before implementation:

- post the final answer through the bot token only to the exact mapped channel/thread;
- store a bounded result and return it through an authorized `/job_status` command;
- split the task into turns that each complete within the token window.

The `/agent_thread` flow implements the first option narrowly for creator-owned bound threads, with outbound permission checks, message-ID deduplication, and a durable local outbox. General long-running slash-command delivery still needs an approved destination-mapping contract.

## Worker boundary rationale

The worker design relies on these reusable queue and process boundaries:

- a lightweight observer owns the communication token and stays responsive while Codex works;
- incoming work and session IDs are persisted in SQLite;
- one transient `codex exec --json` child runs per batch;
- the project root is both the child working directory and its explicit CLI directory;
- prompts use standard input, not command-line arguments;
- `thread.started` and the final completed agent message are parsed from JSONL;
- later messages resume the persisted Codex thread;
- communication-service secrets are stripped from the Codex child environment;
- one Codex turn runs at a time, with bounded timeout and cooperative cancellation;
- interrupted queue work returns to pending so the observer can recover after restart.

The Discord design retains those boundaries while improving them in four places:

- use sandbox bypass only inside the dedicated externally isolated worker container;
- separate the public interaction gateway from the more capable worker;
- use the implemented durable thread outbox and idempotent completion pattern for any later approved destination routes;
- account explicitly for Discord's 15-minute interaction-token expiry.

## Decisions required before production expansion

- Which repositories may the agent access, and are they trusted enough to execute while provider credentials are available?
- Should future commands use the current workspace-writing policy or select a narrower policy per command?
- Which OpenAI authentication method, workspace, model policy, cost ceiling, and retention policy are approved?
- Is one worker and SQLite sufficient, or must jobs survive host failure?
- How are Discord threads mapped to projects and Codex thread IDs?
- What is the maximum turn duration, queue depth, prompt size, output size, and concurrent job count?
- What delivery path is approved for work exceeding 15 minutes?
- What actions require a human approval round trip, and how is that approval bound to the pending job?
- Which private Discord content may enter the agent prompt and OpenAI processing boundary?

The implemented proof of concept is intentionally limited to explicit prompts, creator-owned agent-thread messages and bounded attachments, tagged sequential conversations, tag enumeration, wiki-guided explanations, bounded current-destination summaries, persistent template-backed writable workspaces, and private Compose-only worker transports. Inbound files are limited to text, PDF, JPEG, and PNG formats; generated outbound files may additionally be ZIP archives, while inbound ZIP signatures are rejected. Prompts, summary transcripts, answers, session mappings, thread bindings, and workspace files persist unencrypted in named volumes. Tags are caller-enumerable continuity labels and not access-control boundaries. Do not add broad history ingestion, indexing, host repository mounts, additional callers, more attachment formats, or public worker exposure until ownership, quotas, retention, malware scanning, and stronger isolation are reviewed.
