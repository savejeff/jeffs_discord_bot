"""Moderator-only operational report for the isolated Codex worker."""

from __future__ import annotations

import re

from discord_agent_bot.commands.base import (
	AgentStatus,
	AgentStatusError,
	CommandContext,
	CommandDefinition,
	CommandError,
	CommandOption,
	STRING_OPTION_TYPE,
)

MAX_REPORT_LENGTH = 2_000
MAX_AGENT_TAG_LENGTH = 64
AGENT_TAG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def _format_report(status: AgentStatus) -> str:
	"""Render worker counters and recent non-content commands as bounded monospace text."""
	profile_scope = {
		"current": "CURRENT",
		"most_recent": "MOST RECENT",
		"unavailable": "NOT YET OBSERVED",
	}[status.runtime_profile_scope]
	lines = [
		"CODEX AGENT STATUS",
		f"agent tag          : {status.agent_tag}",
		f"state              : {status.state.upper()}",
		f"runtime profile    : {profile_scope}",
		f"model              : {status.model or 'unknown'}",
		f"reasoning level    : {status.reasoning_level or 'unknown'}",
		f"messages queued    : {status.queued}",
		f"messages processing: {status.processing}",
		f"messages processed : {status.processed}",
		f"completed          : {status.completed}",
		f"failed             : {status.failed}",
		f"active minutes total: {status.total_active_seconds / 60:.1f}",
		f"active minutes today: {status.today_active_seconds / 60:.1f}",
		f"today time zone     : {status.time_zone}",
		"",
		"RECENT AGENT COMMANDS",
	]
	if not status.recent_commands:
		lines.append("(none)")
	else:
		for command in status.recent_commands:
			user_id = command.user_id or "unknown"
			channel_id = command.channel_id or "unknown"
			lines.append(
				f"{command.received_at} | /{command.command} | {command.status} | "
				f"user {user_id} | channel {channel_id}"
			)
	prefix = "```text\n"
	suffix = "\n```"
	maximum_body_length = MAX_REPORT_LENGTH - len(prefix) - len(suffix)
	return prefix + "\n".join(lines)[:maximum_body_length] + suffix


class AgentReportCommand(CommandDefinition):
	"""Show Codex activity and queue metrics only to configured moderator roles."""

	name = "agent_report"
	description = "Show one tagged agent's moderator-only worker status report."
	order = 92
	deferred = True
	mod_only = True
	options = (
		CommandOption(
			name="agent_tag",
			description="Agent tag to report.",
			option_type=STRING_OPTION_TYPE,
			required=True,
			max_length=MAX_AGENT_TAG_LENGTH,
		),
	)

	async def invoke(self, context: CommandContext) -> str:
		"""Request one tagged worker's non-agent status and format it for Discord."""
		context.require_options("agent_tag")
		agent_tag = context.string_option("agent_tag", MAX_AGENT_TAG_LENGTH)
		if not AGENT_TAG_PATTERN.fullmatch(agent_tag):
			raise CommandError("Agent tag is invalid")
		if context.agent_status_reader is None:
			return "Agent status reporting is not configured."
		try:
			status = await context.agent_status_reader(agent_tag)
		except AgentStatusError:
			return "Agent status is currently unavailable."
		return _format_report(status)
