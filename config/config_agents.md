# Agent Configuration

`config_agents.json` defines optional startup model and permission settings for named
Codex agents. The shipped configuration has an empty `agents` object, so a fresh
worker volume contains no workspace until a command creates a tagged agent on
demand. It is configuration, not a secrets file; do not place API keys, Discord
tokens, or other credentials in it.

## Fields

### `agents`

Required object containing every configured agent. Each property name inside this object is an agent tag.

### Agent tag

Each optional key beneath `agents` uniquely identifies one preconfigured agent and
its persistent state.

- It must contain 1–64 lowercase letters, digits, underscores, or hyphens.
- It must begin with a lowercase letter or digit.
- `CODEX_AGENT_TAG` in `compose.yaml` selects the default tag used when routing is omitted.
- Its workspace is `/workspaces/<agent-tag>`.
- Its Codex conversation ID is stored separately under the same tag.

Every configured tag is seeded from the complete workspace template when the worker
starts. With the shipped empty configuration, startup seeds nothing. This mechanism
is reserved for future fixed-purpose agents, such as a knowledge-base agent that
must exist immediately when the image starts. Existing files and wiki contents are
preserved according to the normal workspace-template rules.

The `/prompt` command accepts an `agent_tag`. It can select a configured tag, resume a tag created by an earlier request, or initialize a new valid tag. Callers can never supply a workspace path: the worker validates the tag and derives `/workspaces/<agent-tag>` internally. New tags initially use the signed-in Codex defaults. A moderator may give any existing or new tag an explicit durable override with `/agent_config`; that override is stored in the worker database and takes precedence over this image configuration until the agent is deleted. `/agent_list` combines tags declared here with initialized workspace names, durable queue/history tags, and runtime-configured tags. Tag ownership and automatic channel/thread-derived routing remain production-hardening work.

### `model`

Optional Codex model identifier for this agent.

- A string is passed to the Codex CLI through `--model`.
- `null` omits the override and uses the model selected by the Codex account or CLI configuration.
- The configured model must be available to the account used by the worker.

#### Current Codex models

The following model IDs are documented for Codex CLI as of 2026-08-29:

| Configuration value | Intended use | Availability note |
| --- | --- | --- |
| `null` | Use the recommended model selected by Codex | Safest default when account availability may change |
| `gpt-5.6` | Alias for GPT-5.6 Sol | Current recommended default family |
| `gpt-5.6-sol` | Strongest choice for complex coding, research, computer use, and difficult open-ended work | Recommended when quality matters most |
| `gpt-5.6-terra` | Balanced everyday model | Recommended balance of capability and cost |
| `gpt-5.6-luna` | Fast model for clear, repeatable, or high-volume tasks | Recommended when speed and cost matter most |
| `gpt-5.3-codex-spark` | Near-instant, text-only coding iteration | Research preview available to ChatGPT Pro users |
| `gpt-5.5` | Previous-generation flagship | Retained for compatibility with existing workflows |

The official model guide also lists `gpt-5.4` and `gpt-5.4-mini`, but both retire from Codex with ChatGPT sign-in on 2026-08-31. Do not use them for new agent configurations. `gpt-5.2` and `gpt-5.3-codex` are already deprecated for Codex authenticated through ChatGPT.

See the [official Codex model guide](https://learn.chatgpt.com/docs/models) for the current list. Model access can vary by ChatGPT plan, administrator policy, staged rollout, authentication method, and installed Codex CLI version. The signed-in worker is therefore the authoritative check.

To inspect the models actually offered to the worker account, start an interactive one-off Codex container:

```sh
docker compose run --rm --no-deps --entrypoint codex codex-agent-worker
```

Enter `/model` in that session to open the account-specific model selector. Exit without starting work after checking the list.

### `reasoning_level`

Optional reasoning-effort override for this agent. Supported values are:

- `minimal`
- `low`
- `medium`
- `high`
- `xhigh`
- `null`, which uses the Codex account or CLI default

The worker passes a non-null value to Codex as the `model_reasoning_effort` configuration override.

### `codex_permission_mode`

Optional per-agent Codex execution policy. It defaults to `container-isolated` for configured and dynamic agents when omitted.

| Value | Codex invocation | Intended use |
| --- | --- | --- |
| `auto-review` | `workspace-write`, approval policy `on-request`, reviewer `auto_review` | Self-approval through Codex's separate reviewer agent while retaining the Codex workspace sandbox |
| `workspace-write` | `workspace-write`, approval policy `never` | Strict unattended work that cannot request an operation outside the workspace |
| `container-isolated` | `--dangerously-bypass-approvals-and-sandbox` | Existing local-worker mode that relies on the dedicated Docker container as its isolation boundary |

Auto-review can approve a request that crosses the selected workspace boundary.
All tags in one local worker share its container, Unix user, Codex login, and
`/workspaces` volume, so they are separate working directories and conversations
but not hard security boundaries.

## Example

```json
{
	"agents": {
		"knowledge_base": {
			"model": "gpt-5.6-terra",
			"reasoning_level": "medium",
			"codex_permission_mode": "container-isolated"
		}
	}
}
```

## Applying changes

The moderator-only command uses these model shorthands and sets both fields at once:

| Command value | Model | Reasoning level |
| --- | --- | --- |
| `low`, `medium`, `high` | `gpt-5.6-sol` | matching value |
| `luna-low`, `luna-medium`, `luna-high` | `gpt-5.6-luna` | matching suffix |
| `terra-low`, `terra-medium`, `terra-high` | `gpt-5.6-terra` | matching suffix |

For example, `/agent_config agent_tag:project_alpha model:low` configures `project_alpha` as `gpt-5.6-sol` with low reasoning. Both fields are required; this command no longer falls back to `dev1`. The command creates the workspace when necessary and does not edit `config_agents.json`.

The JSON file is copied into the Codex worker image. After adding or changing a
fixed-purpose agent, rebuild and recreate the worker. Startup then prepares every
declared workspace in the existing volume. Removing an entry prevents future eager
setup but deliberately does not delete an existing persistent workspace:

```sh
docker compose up --detach --build --force-recreate codex-agent-worker
```

The existing `codex-workspaces`, `codex-worker-data`, and `codex-home` volumes remain intact. Do not add `-v` to `docker compose down`, because that would delete the persistent agent workspaces, conversation state, and Codex login data.
