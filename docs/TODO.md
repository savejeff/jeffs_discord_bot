# Project Tasks

- [ ] Confirm the target webserver runtime, public route, reverse proxy, process manager, Python version, and approved secret-injection mechanism.
- [x] Select and document the milestone-1 Python web/Discord dependency stack. See `requirements.txt` and `docs/DEPLOYMENT_DOCKER.md`.
- [x] Implement and offline-test the signed Discord interaction endpoint and guild-scoped `/hello` command described in `brief.md`. See `src/discord_agent_bot/` and `tests/`.
- [ ] Validate the interaction endpoint and command in an authorized dedicated test channel using a contributor-controlled Discord application.
- [ ] Complete approved-location retrieval beyond the implemented `/dev_history` current-channel/thread read, including broader enumeration, pagination, search limits, and provenance behavior.
- [ ] Define project/thread/lead mappings and implement controlled status, question, and mention behavior.
- [ ] Decide the production confidentiality, retention, malware-scanning, cleanup, and model boundary before expanding beyond bounded `/summarize` and the document/image input plus outbound-ZIP agent-thread proof of concept, or adding indexing/search.
- [ ] Production-harden the Codex worker with authenticated transport, ownership beyond creator-bound threads, retention cleanup, restart-safe interaction-webhook delivery, pinned CLI installation, and reviewed repository/tool access.
- [ ] Define alert thresholds or an external watchdog for abnormal queue depth, failure rate, and daily/total active-agent minutes; `/agent_report` currently provides observation only.
