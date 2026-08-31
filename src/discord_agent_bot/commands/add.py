"""Numeric-addition or text-concatenation command definition."""

from decimal import Decimal, DecimalException, InvalidOperation

from discord_agent_bot.commands.base import (
	CommandContext,
	CommandDefinition,
	CommandOption,
	STRING_OPTION_TYPE,
)

MAX_ADD_VALUE_LENGTH = 200


def _add_values(left: str, right: str) -> str:
	"""Add finite decimals, or concatenate the originals when either is nonnumeric."""
	try:
		left_number = Decimal(left)
		right_number = Decimal(right)
		if not left_number.is_finite() or not right_number.is_finite():
			raise InvalidOperation
		total = left_number + right_number
	except DecimalException:
		return left + right

	if total == 0:
		return "0"
	normalized = total.normalize()
	if abs(normalized.adjusted()) > 300:
		return str(normalized)
	return format(normalized, "f")


class AddCommand(CommandDefinition):
	"""Add two finite decimals or concatenate the original input strings."""

	name = "add"
	description = "Add two numbers or concatenate two text values."
	order = 40
	options = (
		CommandOption(
			name="left",
			description="First number or text value.",
			option_type=STRING_OPTION_TYPE,
			required=True,
			max_length=MAX_ADD_VALUE_LENGTH,
		),
		CommandOption(
			name="right",
			description="Second number or text value.",
			option_type=STRING_OPTION_TYPE,
			required=True,
			max_length=MAX_ADD_VALUE_LENGTH,
		),
	)

	async def invoke(self, context: CommandContext) -> str:
		"""Apply numeric addition only when both bounded arguments are finite decimals."""
		context.require_options("left", "right")
		return _add_values(
			context.string_option("left", MAX_ADD_VALUE_LENGTH),
			context.string_option("right", MAX_ADD_VALUE_LENGTH),
		)
