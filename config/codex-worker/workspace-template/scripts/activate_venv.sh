#!/usr/bin/env bash

# Create the workspace-local Python environment when needed and activate it in
# the current shell. Source this file so activation persists.

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
	echo "This script must be sourced. Run: source scripts/activate_venv.sh"
	exit 1
fi

_worker_venv_script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
_worker_venv_dir="${_worker_venv_script_dir}/.venv"
_worker_venv_requirements="${_worker_venv_script_dir}/requirements.txt"

# Create the isolated environment without modifying the container Python.
_create_worker_venv() {
	if ! command -v python3 >/dev/null 2>&1; then
		echo "Python 3 is not available in this worker image." >&2
		return 1
	fi
	if [[ ! -f "${_worker_venv_requirements}" ]]; then
		echo "Requirements file not found: ${_worker_venv_requirements}" >&2
		return 1
	fi
	python3 -m venv "${_worker_venv_dir}" || return 1
	"${_worker_venv_dir}/bin/python" -m pip install \
		--requirement "${_worker_venv_requirements}" || return 1
}

if [[ -e "${_worker_venv_dir}" && ! -x "${_worker_venv_dir}/bin/python" ]]; then
	echo "The local Python environment is incomplete: ${_worker_venv_dir}" >&2
	return 1
fi

if [[ ! -x "${_worker_venv_dir}/bin/python" ]]; then
	_create_worker_venv || return 1
fi

# shellcheck disable=SC1091
source "${_worker_venv_dir}/bin/activate"
echo "Activated Python virtual environment: ${VIRTUAL_ENV}"

unset -f _create_worker_venv
unset _worker_venv_script_dir _worker_venv_dir _worker_venv_requirements

