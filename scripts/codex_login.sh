#!/usr/bin/env sh

# Authenticate the worker's persistent CODEX_HOME volume with a ChatGPT plan.
# The device code is intentionally completed by the human in their browser.
set -eu

login_script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
login_project_root=$(dirname -- "$login_script_dir")
cd "$login_project_root"

exec docker compose run --rm --no-deps --entrypoint codex \
	codex-agent-worker login --device-auth
