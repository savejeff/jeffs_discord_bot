#!/usr/bin/env bash

# Creates the project-local Python environment when needed and activates it in
# the current Linux or macOS shell. Source this file so activation persists.

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
	echo "This script must be sourced so the virtual environment remains active."
	echo "Run: source scripts/activate_venv.sh"
	exit 1
fi

_activate_venv_script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
_activate_venv_dir="${_activate_venv_script_dir}/.venv"
_activate_venv_requirements="${_activate_venv_script_dir}/requirements.txt"

# Creates the virtual environment and installs the project's Python packages.
_create_project_venv() {
	if ! command -v python3 >/dev/null 2>&1; then
		echo "Python 3 was not found. Install it and ensure 'python3' is on PATH." >&2
		return 1
	fi

	if [[ ! -f "${_activate_venv_requirements}" ]]; then
		echo "Requirements file not found: ${_activate_venv_requirements}" >&2
		return 1
	fi

	echo "Creating Python virtual environment in ${_activate_venv_dir}..."
	python3 -m venv "${_activate_venv_dir}" || return 1

	echo "Installing packages from ${_activate_venv_requirements}..."
	"${_activate_venv_dir}/bin/python" -m pip install -r "${_activate_venv_requirements}" || return 1
}

if [[ -e "${_activate_venv_dir}" && ! -x "${_activate_venv_dir}/bin/python" ]]; then
	echo "An incomplete virtual environment exists at ${_activate_venv_dir}." >&2
	echo "Remove it manually and run this script again." >&2
	unset _activate_venv_script_dir _activate_venv_dir _activate_venv_requirements
	return 1
fi

if [[ ! -x "${_activate_venv_dir}/bin/python" ]]; then
	_create_project_venv || {
		unset -f _create_project_venv
		unset _activate_venv_script_dir _activate_venv_dir _activate_venv_requirements
		return 1
	}
fi

# shellcheck disable=SC1091
source "${_activate_venv_dir}/bin/activate"
echo "Activated Python virtual environment: ${VIRTUAL_ENV}"

unset -f _create_project_venv
unset _activate_venv_script_dir _activate_venv_dir _activate_venv_requirements
