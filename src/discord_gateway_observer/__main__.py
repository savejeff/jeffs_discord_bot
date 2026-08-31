"""Process entry point for the Discord Gateway observer container."""

from __future__ import annotations

import asyncio
import logging

from discord_gateway_observer.application import create_observer


def main() -> None:
	"""Configure redacted operational logging and run the observer event loop."""
	logging.basicConfig(
		level=logging.INFO,
		format="%(asctime)s %(levelname)s %(name)s %(message)s",
	)
	asyncio.run(create_observer().run())


if __name__ == "__main__":
	main()
