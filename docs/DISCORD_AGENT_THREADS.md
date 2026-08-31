# Discord Agent Threads

## User contract

`/agent_thread <agent_tag> <model> [public]` creates a public Discord thread below the invoking channel. Both `agent_tag` and the Sol/Luna/Terra model shorthand are required. The command configures a persistent local worker tag and never silently selects `dev1` or derives a tag from the Discord thread.

Only the member who executed `/agent_thread` can prompt the bound agent through ordinary messages and supported attachments in that thread. Other members can see and write in the public thread according to Discord permissions, but the observer ignores their messages and files. `/prompt` remains the explicit one-shot text command for a selected tag.

Archiving or deleting the Discord thread deactivates the binding and cancels undelivered observer work. It does not delete the Codex conversation, workspace, or tag. Unarchiving does not reactivate the old binding.

## Runtime flow

~~~text
/agent_thread interaction
  -> signed HTTP interaction service
  -> local worker configuration
  -> Discord REST creates public thread
  -> shared SQLite stores thread + creator + agent tag

ordinary creator message
  -> Discord Gateway observer
  -> atomic active-binding and creator check
  -> signed Discord CDN download and private worker staging
  -> /workspaces/<tag>/tmp/download/<request-id>
  -> durable local pending row
  -> private Codex worker
  -> durable local answer row
  -> validated /workspaces/<tag>/tmp/upload/<request-id> files
  -> mention-safe Discord REST message in source thread
~~~

The interaction service and observer mount the private `discord-gateway-data` volume at `/var/lib/discord-gateway`. The Codex worker does not mount it and owns its separate queue, conversations, and workspaces. The observer has no published port.

Incoming Discord message IDs deduplicate Gateway redelivery. The observer derives the worker request ID as `gateway_<message-id>`, so a restart cannot create a second Codex job for the same accepted message. Inbound files are stored under `tmp/download/gateway_<message-id>/`; the agent may place response files directly under `tmp/upload/gateway_<message-id>/`. Outbound Discord messages reuse the source message ID as a nonce with `enforce_nonce:true`. Delivered rows have their prompt, answer, and attachment manifest erased from the observer database.

The attachment policy accepts `.txt`, `.md`, `.json`, `.csv`, `.log`, `.pdf`, `.jpg`, `.jpeg`, and `.png` inbound. Outbound responses additionally allow `.zip`; ZIP is rejected inbound even if renamed. Both directions allow at most three files, 10 MiB each and 20 MiB combined. Filenames use conservative ASCII, and PDF/image/ZIP signatures are checked. The observer accepts signed download URLs only from Discord CDN hosts, transfers bytes through private worker HTTP endpoints, and never mounts the Codex workspace volume. Files are untrusted and are never executed or automatically extracted.

## Required Discord setup

Enable the privileged Message Content intent for the application. The observer identifies with only `GUILDS`, `GUILD_MESSAGES`, and `MESSAGE_CONTENT`. In approved parent channels, grant only `VIEW_CHANNEL`, `CREATE_PUBLIC_THREADS`, `SEND_MESSAGES_IN_THREADS`, and `ATTACH_FILES`. Do not grant `Administrator`, `MANAGE_GUILD`, `MANAGE_MESSAGES`, or `MANAGE_THREADS` for this feature.

## Proof-of-concept boundaries

- One worker processes every tag sequentially, so one long turn delays later prompts.
- A tag can be bound to multiple threads; those bindings share conversation memory and workspace state.
- Gateway resume state exists only in observer memory. Messages missed outside Discord's resumable event window are not backfilled.
- SQLite makes accepted prompt and answer delivery restart-safe on one Compose host, but a small duplicate-post risk remains around process failure and Discord's nonce window.
- Binding closure does not implement agent deletion, retention cleanup, quotas, or ownership transfer.
