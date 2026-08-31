"""Container health probe for recent Discord Gateway activity."""

from __future__ import annotations

import os
from pathlib import Path
from time import monotonic

MAX_HEALTH_AGE_SECONDS = 90.0


def main() -> None:
	"""Fail unless READY, RESUMED, or heartbeat acknowledgement was recently observed."""
	health_file = Path(
		os.environ.get(
			"DISCORD_GATEWAY_HEALTH_FILE",
			"/var/lib/discord-gateway/healthy",
		)
	)
	try:
		updated_at = float(health_file.read_text(encoding="ascii"))
	except (OSError, ValueError):
		raise SystemExit(1) from None
	age_seconds = monotonic() - updated_at
	if not 0 <= age_seconds <= MAX_HEALTH_AGE_SECONDS:
		raise SystemExit(1)


if __name__ == "__main__":
	main()
