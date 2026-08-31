FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
	PYTHONUNBUFFERED=1 \
	PYTHONPATH=/app/src

WORKDIR /app

# Install only the pinned runtime dependency set; development and agent tooling
# are deliberately absent from the production image.
COPY requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir --requirement requirements.txt \
	&& useradd --create-home --uid 10001 appuser \
	&& mkdir --parents /var/lib/discord-gateway \
	&& chown appuser:appuser /var/lib/discord-gateway

COPY src/ ./src/
COPY scripts/generate_command_config.py scripts/register_commands.py ./scripts/

# Materialize the reviewable JSON catalog from the same discoverable command
# classes used by runtime dispatch and deliberate guild registration.
RUN python /app/scripts/generate_command_config.py /app/config/discord_commands.json

USER appuser
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
	CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=2).read()"]

CMD ["uvicorn", "discord_agent_bot.application:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--workers", "1", "--no-access-log"]
