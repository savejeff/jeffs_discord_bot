# Source References

Research snapshot date: 2026-08-30. These links point to current official Discord documentation rather than copied pages so the implementing agent can recheck details that may change.

## Discord interactions and commands

- [Interactions overview](https://docs.discord.com/developers/interactions/overview): a configured HTTP endpoint must acknowledge PING and validate the `X-Signature-Ed25519` and `X-Signature-Timestamp` headers; invalid signatures must receive HTTP 401.
- [Receiving and responding to interactions](https://docs.discord.com/developers/interactions/receiving-and-responding): an initial response is required within three seconds; callback type 5 acknowledges slow work; interaction tokens remain valid for 15 minutes; and the original response can be edited through its interaction webhook.
- [Application commands](https://docs.discord.com/developers/interactions/application-commands): commands are registered over HTTP; guild commands update promptly and are recommended for development, while global commands are for broader release.
- [Markdown Text 101](https://support.discord.com/hc/en-us/articles/210298617-Markdown-Text-101-Chat-Formatting-Bold-Italic-Underline): Discord messages support headings, lists, bold text, and inline code formatting used by `/help`.

## Bot access, server data, and threads

- [Bots overview](https://docs.discord.com/developers/bots/overview): a bot may combine Gateway events and HTTP API operations; the bot token authenticates Gateway and most REST requests.
- [OAuth2 and permissions](https://docs.discord.com/developers/platform/oauth2-and-permissions): installations grant scopes and bot permissions; least privilege is expected and bot tokens must remain secret.
- [Gateway and intents](https://docs.discord.com/developers/events/gateway): Gateway connections provide server events; most events require intents, and message content is a privileged intent that also affects content fields returned across APIs.
- [Gateway events](https://docs.discord.com/developers/events/gateway-events): HELLO/heartbeat, identify/resume, message creation, thread updates, and thread deletion define the observer lifecycle and event fields.
- [Message resource](https://docs.discord.com/developers/resources/message): channel history retrieval requires `VIEW_CHANNEL` and `READ_MESSAGE_HISTORY`; message creation requires the destination's send permission and should constrain allowed mentions.
- [Rate limits](https://docs.discord.com/developers/topics/rate-limits): REST limits are dynamic; handle HTTP 429 and its retry guidance rather than hard-coding quota assumptions.
- [Threads](https://docs.discord.com/developers/topics/threads): thread access follows parent permissions with thread-specific send rules; private threads also have membership constraints.
- [Permissions](https://docs.discord.com/developers/topics/permissions): channel overwrites and thread inheritance affect the bot's effective access.

## Conclusions used by this handoff

- The public slash-command endpoint and access to server history are separate capabilities.
- A Gateway connection is unnecessary for the simple HTTP interaction milestone and ordinary REST reads/posts; it becomes relevant for passive real-time event processing.
- The reviewed `/agent_thread` requirement now justifies a narrow Gateway observer using only guild, guild-message, and message-content intents.
- Guild-scoped commands are the safest first registration target for a contributor-controlled test server.
- A Markdown heading, bullet list, and inline-code command signatures provide a native Discord lookup without embeds or additional API calls.
- Reading and posting must be tested against effective channel/thread permissions, not inferred from guild-level roles alone.
- Message-content access and any privileged intent should be verified against current Developer Portal behavior before phase 2.
- A three-second response budget makes blocking search or AI work unsuitable for the initial inline path; later commands should defer before doing slow work.

## Codex CLI and integration

- [Codex CLI](https://learn.chatgpt.com/docs/codex/cli): official Linux installation, project-directory operation, and repeatable CLI automation entry point.
- [Non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode): `codex exec`, explicit sandbox selection, JSONL events, scoped automation credentials, and session resume behavior.
- [Authentication](https://learn.chatgpt.com/docs/auth): API-key and ChatGPT login choices, headless device authentication, `CODEX_HOME`, and confidential cached credentials.
- [Codex SDK](https://learn.chatgpt.com/docs/codex-sdk): stable Python and TypeScript APIs for starting and resuming local Codex threads.
- [Codex app server](https://learn.chatgpt.com/docs/app-server): richer thread, turn, approval, and streaming protocol for integrations that need more control than one CLI child per turn.

Re-open the official pages before implementation and deployment. Discord API behavior, library support, privileged-intent policy, rate limits, and application installation controls are time-sensitive.
