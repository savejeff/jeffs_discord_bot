#!/usr/bin/env sh

# Rebuild and start the application, then optionally synchronize Discord's
# guild-command list from the definitions bundled into the new image.
set -eu

update_script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
update_project_root=$(dirname -- "$update_script_dir")
cd "$update_project_root"

echo "Building and starting the Discord services and local Codex worker..."
docker compose up --detach --build --wait --wait-timeout 60

# Reload settings sourced from the bind-mounted secrets file even when Docker
# did not need to recreate the Discord gateway container during this update.
echo "Restarting the Discord services to reload secrets..."
docker compose restart discord-agent-bot discord-gateway-observer

echo "Waiting for the restarted Discord services to become healthy..."
docker compose up --detach --wait --wait-timeout 60

printf "The updated containers are healthy. Re-register all configured guild commands? [y/N] "
if ! IFS= read -r update_answer; then
	echo "No input received; command registration skipped."
	exit 0
fi

case "$update_answer" in
	y|Y|yes|YES|Yes)
		docker compose run --rm --no-deps discord-agent-bot \
			python /app/scripts/register_commands.py \
			/run/secrets/discord-agent-bot.json \
			--yes
		;;
	*)
		echo "Command registration skipped."
		;;
esac
