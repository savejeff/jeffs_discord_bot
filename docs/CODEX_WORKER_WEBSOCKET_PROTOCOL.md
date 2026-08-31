# Codex Worker WebSocket Protocol

## Scope

The proof-of-concept endpoint is `ws://codex-agent-worker:8090/ws` on the private Compose network. It has no authentication or TLS and must not be published outside that network. One connection submits one prompt, status request, or agent-list request. Prompt connections remain open for the acknowledgement and terminal event.

Text frames contain UTF-8 JSON objects. Binary frames are not supported. Attachment bytes use the paired private HTTP endpoints described below rather than the WebSocket. The worker accepts at most one request per connection and uses one global sequential execution queue. Each validated tag has its own persistent workspace and Codex conversation. The gateway may supply a tag but never a workspace path.

## Prompt request

```json
{
  "type": "prompt",
  "request_id": "caller-generated-id",
  "agent_tag": "dev1",
  "prompt": "explain what Example Organization is",
  "metadata": {
    "source": "discord",
    "command": "respond",
    "guild_id": "123",
    "channel_id": "456"
  }
}
```

`request_id` must contain 1-64 ASCII letters, digits, underscores, or hyphens. `agent_tag` is optional and defaults to the configured `dev1`; when present it must contain 1-64 lowercase letters, digits, underscores, or hyphens and begin with a letter or digit. `prompt` must be non-empty and at most 4,000 characters. `metadata` is an arbitrary JSON object whose canonical encoding is at most 4,096 bytes. The Discord adapter deliberately limits `/respond` and `/prompt` input to 1,000 characters and `/explain` topics to 1,000 characters, leaving room for command-specific instructions.

Submitting the same `request_id`, agent tag, prompt, and metadata again is idempotent and returns the existing job. Reusing an identifier with any different value is rejected. Prompts and metadata are confidential application data even though this proof of concept does not authenticate the transport.

## Accepted event

```json
{
  "type": "accepted",
  "request_id": "caller-generated-id",
  "status": "pending",
  "metadata": {
    "conversation": "tagged",
    "agent_tag": "dev1",
    "queue_position": 1
  }
}
```

The status can already be `processing`, `completed`, or `failed` when an idempotent request is resubmitted. Queue position is zero after a job leaves the active queue.

## Completed response

```json
{
  "type": "response",
  "request_id": "caller-generated-id",
  "status": "completed",
  "answer": "Example Organization appears to refer to ...",
  "metadata": {
    "conversation": "tagged",
    "agent_tag": "dev1",
    "request": {
      "source": "discord",
      "command": "respond",
      "guild_id": "123",
      "channel_id": "456"
    }
  }
}
```

The worker bounds stored answers to 64,000 characters. The Discord adapter further truncates them to Discord's 2,000-character message limit and disables automatic mentions.

For `discord_gateway` / `agent_thread` jobs, a completed response may also include a bounded artifact manifest:

```json
{
  "attachments": [
    {
      "filename": "report.md",
      "content_type": "text/markdown",
      "size": 1234,
      "sha256": "64-lowercase-hex-characters"
    }
  ]
}
```

The manifest never contains a workspace path or URL. The observer retrieves each file from the private HTTP endpoint using the agent tag, request ID, filename, and digest, verifies the bytes, and then sends one Discord multipart message.

## Private attachment HTTP endpoints

`POST /artifacts/inbound` accepts one raw file with `agent_tag`, `request_id`, `attachment_id`, and `filename` query parameters. It stores the validated file beneath `/workspaces/<tag>/tmp/download/<request-id>/` and returns only its relative workspace path. `GET /artifacts/outbound` accepts `agent_tag`, `request_id`, `filename`, and `sha256`, then returns a matching file from `/workspaces/<tag>/tmp/upload/<request-id>/`.

These endpoints have the same unauthenticated private-Compose proof-of-concept boundary as `/ws`; they must not receive a host port or reverse-proxy route. Inbound files may use `.txt`, `.md`, `.json`, `.csv`, `.log`, `.pdf`, `.jpg`, `.jpeg`, or `.png`. Outbound files may additionally use `.zip`. ZIP archives are never accepted inbound, including when renamed. Both directions allow at most three files, 10 MiB per file and 20 MiB total. Symlinks, nested output directories, path traversal, unsupported names, mismatched signatures, invalid outbound ZIPs, and digest changes are rejected; archives are never extracted by the transport.

## Error event

```json
{
  "type": "error",
  "request_id": "caller-generated-id",
  "code": "codex_failed",
  "message": "Codex could not complete the prompt."
}
```

Errors are intentionally generic. Request values, Codex output, credentials, and subprocess diagnostics must not be copied into routine logs or error frames.

## Status request and response

A status request identifies one agent tag, contains no prompt, and does not invoke Codex or create a queue job:

```json
{"type":"status","request_id":"caller-generated-id","agent_tag":"dev1"}
```

The response contains only the selected tag's queue counts, actual Codex child-process activity seconds, and up to ten recent content-free command records:

```json
{
  "type": "status",
  "request_id": "caller-generated-id",
  "status": {
    "state": "idle",
    "agent_tag": "dev1",
    "model": "gpt-5.6-sol",
    "reasoning_level": "high",
    "runtime_profile_scope": "most_recent",
    "queued": 0,
    "processing": 0,
    "processed": 12,
    "completed": 11,
    "failed": 1,
    "total_active_seconds": 725.4,
    "today_active_seconds": 120.2,
    "time_zone": "UTC",
    "recent_commands": [
      {
        "received_at": "2026-08-29T14:00:00+02:00",
        "command": "summarize",
        "status": "completed",
        "user_id": "123",
        "channel_id": "456"
      }
    ]
  }
}
```

`queued` counts pending work for the requested tag, while `processing` identifies whether that tag owns the active child. `processed` is completed plus failed. Activity durations and recent commands are filtered to the same tag. Durations exclude idle container time and, after interrupted recovery, exclude time after the last durable heartbeat. Existing jobs created before the activity table was introduced contribute to processed counts but not historical active minutes.

`model` and `reasoning_level` come from Codex's persisted runtime `turn_context`, not from the requested values in `config_agents.json`. `runtime_profile_scope` is `current` only when that record was observed for the active child, `most_recent` for the durable last observed turn, or `unavailable` before any turn has supplied runtime evidence. In the unavailable case both values are `null`; an unrecorded reasoning level may also be `null` even when the model is known.

## Agent-list request and response

An agent-list request contains no prompt, creates no queue job, and does not invoke Codex:

```json
{"type":"agent_list","request_id":"caller-generated-id"}
```

The response is sorted and combines tags declared in `config/config_agents.json`, valid initialized directories beneath `/workspaces`, and tags retained by durable jobs:

```json
{
  "type": "agent_list",
  "request_id": "caller-generated-id",
  "agent_tags": ["dev1", "project_two"]
}
```

The gateway validates every tag again and bounds the protocol response to 1,024 tags. Discord's 2,000-character response limit may require `/agent_list` to show a final `... N more` line instead of rendering every returned name. Tags can disclose project labels and the proof of concept does not yet enforce tag ownership, so callers should not make the list public unless those names are appropriate for the destination.

## Agent lifecycle requests

The Discord service sends these private, prompt-free management documents only after moderator authorization:

```json
{"type":"agent_config","request_id":"caller-generated-id","agent_tag":"dev1","model":"gpt-5.6-sol","reasoning_level":"low"}
{"type":"agent_reset","request_id":"caller-generated-id","agent_tag":"dev1"}
{"type":"agent_delete","request_id":"caller-generated-id","agent_tag":"dev1"}
```

Successful operations return an `agent_management` document containing the same `request_id`, `agent_tag`, and an `operation` of `config`, `reset`, or `delete`; configuration responses also echo the exact model and reasoning level. The worker accepts only the three configured model families and low/medium/high reasoning. It refuses reset or deletion while the selected agent has pending or processing work. Reset restores the whole workspace template. Delete tombstones even a statically configured tag so `/agent_list` does not recreate or display it; a later prompt or configuration for that tag explicitly creates it again.

## Persistence and recovery

The SQLite database returns a job left in `processing` state to `pending` when the worker restarts. Completed answers, each job's tag, and Codex thread IDs keyed by tag persist in the `codex-worker-data` volume; `/workspaces/<tag>` persists separately in `codex-workspaces`. The WebSocket client currently waits on its original connection; if the Discord gateway restarts, the job may finish but its Discord interaction response is not recovered. Restart-safe callback delivery, tag ownership/authorization, quotas, and cleanup are production follow-ups.
