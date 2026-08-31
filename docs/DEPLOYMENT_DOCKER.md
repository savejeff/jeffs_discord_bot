# Docker Deployment

## Runtime boundary

Compose runs three services from two images. `discord-agent-bot` contains the public interaction service and no Codex installation, and the same image runs `discord-gateway-observer`. `codex-agent-worker` contains the Codex CLI, a private WebSocket service, one durable sequential SQLite queue, independently persisted tagged Codex conversations, and a persistent workspace volume. The default agent tag is `dev1`, and each tag works in `/workspaces/<tag>`. The worker receives no Discord credential.

Before the first worker start on the server, use the synthetic `res/wiki/MOCKUP.md` as a format example and add the application-specific Markdown knowledge base beside it. Deployment-specific pages are intentionally ignored by Git but included in the worker's Docker build context. Docker combines the wiki with the tracked generic project seed under `config/codex-worker/workspace-template/`. A new `/workspaces/<tag>` receives the complete prepared project: layered agent guidance, project documentation, `scripts/activate_venv.sh`, `scripts/requirements.txt`, and the `data/`, `logs/`, `tmp/`, `res/`, `src/`, and `tests/` lifecycle directories. An older sparse workspace receives only missing template files. Existing maintained files and wiki content are not overwritten, except that root `AGENTS.md` is refreshed from the current image as operational policy. Operator wiki baseline changes therefore require an intentional wiki-maintenance operation. Do not put secrets in the wiki: its contents are retained in the built image and persistent workspace volume.

Codex runs with `-C /workspaces/<tag> --dangerously-bypass-approvals-and-sandbox`. The nested Codex Linux sandbox is deliberately disabled because it cannot initialize reliably inside the Docker security boundary. This flag is acceptable here only because the worker is a dedicated non-root container with a read-only root filesystem, no host checkout, no Docker socket, no Discord credentials, and no published port. Compose mounts the writable `codex-workspaces`, `codex-home`, and `codex-worker-data` named volumes plus a bounded `/tmp` tmpfs. Agent-created workspace files, `scripts/.venv`, data, logs, utilities, and explicit wiki changes therefore survive ordinary restarts, image rebuilds, and container recreation. The agent instructions treat the wiki as read-only for normal questions and development work, while leaving it filesystem-writable for a request that explicitly asks to extend or correct the knowledge base. Tagged workspaces are logical continuity boundaries, not security boundaries: bypass-mode Codex processes share the container and mounted `/workspaces` volume.

Do not reuse the sandbox-bypass launch mode in a worker with broad host mounts, a Docker socket, host credentials, or unrelated agent workspaces. Multi-agent expansion should preserve a separate container or comparably strong external boundary per mutually untrusted agent.

The Discord HTTP container listens internally on port `8080`; Compose publishes it as `127.0.0.1:6700` on the host. Point the HTTPS reverse proxy to `http://127.0.0.1:6700` and keep the exact request body unchanged because signature verification covers those bytes. The Gateway observer exposes no port. The local Codex worker listens on `8090` only inside the Compose network and has no host port.

## Agent configuration

`config/config_agents.json` optionally declares fixed-purpose agents that must be
prepared when the image starts. It is intentionally empty by default:

```json
{
	"agents": {}
}
```

Fresh startup therefore creates no workspace. A valid tag supplied by `/prompt`,
`/agent_thread`, or an administration command creates `/workspaces/<tag>` and an
independent conversation on demand; it is not added to the JSON automatically.
`CODEX_AGENT_TAG=dev1` remains only the compatibility fallback when routing is
omitted and does not eagerly create `dev1`.

For a future fixed-purpose entry, set `model` to an identifier supported by the
installed Codex CLI and account. Set `reasoning_level` to `minimal`, `low`,
`medium`, `high`, or `xhigh`. A null value retains the Codex account or CLI
default. The worker validates tags before using them as directory names, and
callers cannot supply workspace paths. Rebuild and recreate the worker after
changing the image-bundled file:

```sh
docker compose up --detach --build --force-recreate codex-agent-worker
```

Production routing should derive or authorize a tag from the verified Discord channel/thread ID. The current socket accepts validated tags from the gateway, creates undeclared tags with default settings, and processes every tag through one sequential queue.

## Required Discord configuration

The local ignored template is `secrets/secrets.json`. Its fields are:

- `DISCORD_APPLICATION_ID`: needed for deliberate command registration, but not read by the running service;
- `DISCORD_PUBLIC_KEY`: required 32-byte Ed25519 public key as hexadecimal text;
- `DISCORD_BOT_TOKEN`: required by `/dev_history`, `/agent_thread`, the Gateway observer, and deliberate command registration;
- `DISCORD_GUILD_ID`: required permitted guild ID;
- `DISCORD_ALLOWED_CHANNEL_IDS` and `DISCORD_ALLOWED_THREAD_IDS`: recommended JSON string arrays of permitted destinations;
- `DISCORD_ALLOWED_USER_IDS` and `DISCORD_ALLOWED_ROLE_IDS`: optional JSON string arrays of permitted actors.
- `DISCORD_MOD_ROLE_IDS`: required JSON string array of role IDs allowed to run `/agent_report`, `/agent_config`, `/agent_reset`, and `/agent_delete`; these roles must also pass the ordinary actor allowlist when one is configured.

Discord IDs must remain JSON strings because their integer values are too large for some JSON consumers to represent safely. Do not add the OAuth client secret: neither this service nor guild-command registration needs it.

The secrets directory is excluded by both Git and `.dockerignore`. This prevents live credentials from entering image layers, build cache, image exports, or registries. The service receives the file as a read-only runtime bind mount. Individual environment variables remain supported and override matching JSON fields.

## First-time Codex account setup

Codex supports signing in with ChatGPT for subscription access. Build the worker image, then run the device-login helper from the repository root:

```sh
docker compose build codex-agent-worker
sh scripts/codex_login.sh
```

The command prints an OpenAI URL and a short-lived device code. Open the URL on a trusted browser, sign in to the ChatGPT account whose plan should be used, and enter the code. The CLI stores its resulting credentials under `CODEX_HOME` in the Compose-managed `codex-home` volume. Treat that volume like a password store.

Authentication is a deliberate human operation and is not performed by image build or service startup. To inspect login state without printing credential contents, run:

```sh
docker compose run --rm --no-deps --entrypoint codex \
  codex-agent-worker login status
```

ChatGPT-plan access depends on the account's current Codex entitlement. API-key authentication is also supported by Codex, but it uses usage-based API billing and is not the procedure described here.

## Build and run

From the repository root, populate the ignored `secrets/secrets.json`, complete the one-time Codex login above, then build and start all services:

```sh
docker compose up --detach --build --wait
```

Inspect service state and redacted logs:

```sh
docker compose ps
docker compose logs --tail 100 discord-agent-bot discord-gateway-observer codex-agent-worker
```

Stop and remove the containers and Compose network while retaining the images, local secrets file, Codex login, queue, and conversation:

```sh
docker compose down
```

Do not add `--volumes` unless you intentionally want to remove `codex-home`, `codex-worker-data`, `codex-workspaces`, and `discord-gateway-data`. Removing those volumes deletes cached login state, queued prompts and answers, persisted conversations/workspaces, and agent-thread bindings.

The reverse proxy should forward only `POST /discord/interactions` to the Discord container and may use `GET /health` for local readiness checks. Do not expose `/health` publicly unless the existing operational policy requires it.

Verify the host-side port locally with:

```sh
curl http://127.0.0.1:6700/health
```

## Update the services and guild commands

Command modules under `src/discord_agent_bot/commands/` are the source of truth. Each module contains one `CommandDefinition` subclass with its Discord metadata and execution hook. `config/discord_commands.json` is generated for review with `python scripts/generate_command_config.py`; `python scripts/generate_command_config.py --check` verifies that it is current. The Docker build independently generates its bundled JSON from the discovered modules.

The registration utility uses Discord's bulk-overwrite endpoint: discovered commands are created or updated, while previously registered guild commands whose modules were removed are deleted. An empty or ambiguous registry is rejected locally to protect against accidental deletion.

After pulling a reviewed update, run:

```sh
sh scripts/docker_compose_update.sh
```

The helper:

1. builds the updated Discord and Codex worker images;
2. recreates and starts all four default Compose services;
3. waits up to 60 seconds for their health checks;
4. explicitly restarts the HTTP interaction service and Gateway observer so bind-mounted secret changes, including moderator ID lists and bot-token rotation, are loaded;
5. waits for both restarted Discord services to become healthy;
6. asks whether all guild commands should be synchronized;
7. after `y`, runs the registration utility in a temporary Discord container.

The explicit restart also covers secret-only updates that do not change the image or Compose configuration. The prompt is the external-mutation boundary. Answering anything other than `y` or `yes` leaves Discord commands unchanged. The helper does not repeat Codex login; the named volume retains it across normal rebuilds.

For deliberate standalone registration, use:

```sh
docker compose run --rm --no-deps discord-agent-bot \
  python /app/scripts/register_commands.py \
  /run/secrets/discord-agent-bot.json
```

The Python utility asks for its own confirmation. Its optional `--yes` flag is intended only when an already reviewed wrapper has obtained confirmation.

## Runtime behavior and permissions

For `/dev_history`, the installed bot needs `VIEW_CHANNEL` and `READ_MESSAGE_HISTORY` in every allowed destination. Message text may be empty unless Message Content access is configured for the application. The command performs one request with a two-second timeout, returns at most ten messages in an ephemeral response, and never stores or logs retrieved content.

Every command accepts `public:yes` for a channel-visible result; omission remains private except for `/dev_public`. `/respond`, `/prompt`, `/agent_list`, and `/explain` need no additional Discord permission. `/prompt` uses the worker default when `agent_tag` is omitted and creates or resumes persistent tagged state when it is supplied. `/agent_thread` needs `VIEW_CHANNEL`, `CREATE_PUBLIC_THREADS`, `SEND_MESSAGES_IN_THREADS`, and `ATTACH_FILES` in its parent channel. Its observer needs the `GUILDS`, `GUILD_MESSAGES`, and privileged `MESSAGE_CONTENT` Gateway intents; enable Message Content under the application bot settings in the Discord Developer Portal before starting the observer. `/agent_list` does not invoke Codex; it also retains tags referenced by closed thread bindings because closing a thread does not delete its agent. `/explain` consults the wiki bundled into the current worker image; rebuild the worker to update the seed for agents created later. `/summarize` needs the same `VIEW_CHANNEL` and `READ_MESSAGE_HISTORY` access as `/dev_history`, plus Message Content availability. Agent commands wait up to 14 minutes for the worker. Tagged agents have separate conversations/workspaces but share one sequential queue and the same container/security boundary.

Use `/agent_thread agent_tag:<tag> model:<shorthand>` in an allowed text channel to configure and bind a public thread to an existing or new tag. Both fields are required, so the command never silently selects `dev1` or derives a tag. Only ordinary messages and supported files from the member who executed the command are accepted; messages and files from every other member, bots, and webhooks are ignored. Inbound files appear under the selected workspace's request-specific `tmp/download/` directory. Files that the agent writes directly to the supplied request-specific `tmp/upload/` directory are attached to its answer after validation. Inbound formats are `.txt`, `.md`, `.json`, `.csv`, `.log`, `.pdf`, `.jpg`, `.jpeg`, and `.png`; outbound responses additionally allow `.zip`. ZIP is rejected inbound even when renamed. Both directions allow at most three files, 10 MiB each, and 20 MiB combined. Archiving or deleting the thread closes the binding and cancels undelivered observer work. It does not delete the Codex conversation or `/workspaces/<tag>`, and reopening an archived thread does not reactivate the binding. See `docs/DISCORD_AGENT_THREADS.md` for the delivery and recovery boundaries.

The proof of concept stores `/respond` and `/prompt` prompts, `/explain` questions, `/summarize` transcript prompts, agent tags, metadata, and answers in the worker data volume. A summary reads at most the newest 100 messages from the invoking channel/thread in one Discord request; it does not paginate older history or inspect attachments and embeds. Do not use confidential content until the retention and provider boundary has been reviewed.

`/agent_report agent_tag:<tag>` does not invoke Codex and remains moderator-only regardless of visibility. The tag is required, like the other per-agent administration commands. `/agent_list` is the catalog exception because it intentionally lists all tags. The report is private by default, but a moderator can deliberately use `public:yes`; that exposes the selected agent tag plus its recent user and channel/thread IDs to everyone who can see the destination. Every counter, activity duration, runtime profile, and recent-command row is filtered to the selected tag. It reports `RUNNING` only while that agent owns the active Codex child; otherwise it reports `IDLE`. It also reports the model and reasoning level actually observed in Codex's runtime `turn_context`, labeled `CURRENT` or `MOST RECENT`; it never substitutes requested values from `config_agents.json`. Before the first observed Codex turn, these fields are `unknown`. Queued excludes the currently processing job, while processed is completed plus failed. Active minutes are accumulated from durable execution intervals rather than container uptime. The `today` counter uses UTC as configured in Compose. Metrics begin when this version first creates the activity table; older jobs remain in processed counts but have no reconstructed runtime. The recent list contains command name, state, received time, user ID, and channel/thread ID, never prompt or response content.

`/agent_config`, `/agent_reset`, and `/agent_delete` use the same `DISCORD_MOD_ROLE_IDS` check. `/agent_config` requires both `agent_tag` and `model`; it has no `dev1` fallback. Its nine model choices are `low`, `medium`, `high`, `luna-low`, `luna-medium`, `luna-high`, `terra-low`, `terra-medium`, and `terra-high`. `/agent_thread` uses that same mapping while retaining its ordinary interaction authorization policy. Configuration is durable in `codex-worker-data` and takes effect on the next turn. Reset deletes the complete tagged workspace and reseeds it from the current image while preserving conversation/configuration. Delete removes the tagged workspace, worker history and metadata, matching Codex conversation rollout, and all matching Discord thread bindings; it does not delete the shared Codex login. Reset and delete are refused while the selected tag has queued or active work.

Add the moderator role to the ignored server-side `secrets/secrets.json` before updating commands:

```json
"DISCORD_MOD_ROLE_IDS": ["YOUR_MOD_ROLE_ID"]
```

This is one field within the existing JSON object, so ensure the preceding field has a comma. Do not paste the role ID into tracked configuration.

## Remaining live steps

Building and starting the containers does not register or update any guild command in Discord. A human/operator still needs to:

1. route the HTTPS interaction path to the private Discord container port without modifying request bodies;
2. validate the endpoint URL in the Discord Developer Portal;
3. run the deliberate update helper and approve synchronization of the guild command list;
4. test permitted and denied locations/users in a dedicated test channel;
5. enable the privileged Message Content intent and grant only the required public-thread permissions;
6. test `/agent_list`, `/prompt`, `/agent_thread`, `/respond`, and `/explain` with non-confidential text and confirm creator-only thread routing, archive cleanup, tag persistence, the prepared workspace structure, the Codex account's plan, wiki access, and limits behave as expected.

Those are external mutations and are intentionally not performed by offline tests or container startup.
