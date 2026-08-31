# Creates the project-local Python environment when needed and activates it in
# the current PowerShell session. Dot-source this file so activation persists.

if ($MyInvocation.InvocationName -ne '.') {
	Write-Error "This script must be dot-sourced. Run: . .\scripts\activate_venv.ps1"
	return
}

$activateVenvScriptDir = $PSScriptRoot
$activateVenvDir = Join-Path -Path $activateVenvScriptDir -ChildPath '.venv'
$activateVenvPython = Join-Path -Path $activateVenvDir -ChildPath 'Scripts\python.exe'
$activateVenvRequirements = Join-Path -Path $activateVenvScriptDir -ChildPath 'requirements.txt'
$activateVenvActivation = Join-Path -Path $activateVenvDir -ChildPath 'Scripts\Activate.ps1'

# Checks whether a command starts a usable Python 3 interpreter.
function Test-Python3Command {
	param([Parameter(Mandatory)] [PSCustomObject] $Command)

	try {
		$versionArguments = @($Command.Arguments) + @('--version')
		$versionOutput = & $Command.Executable @versionArguments 2>&1
		return $LASTEXITCODE -eq 0 -and "$versionOutput" -match '^Python 3\.'
	} catch {
		return $false
	}
}

# Returns the first available command that launches the system's default
# Python 3 interpreter.
function Get-DefaultPython3Command {
	$candidates = @(
		[PSCustomObject]@{ Executable = 'python3'; Arguments = @() },
		[PSCustomObject]@{ Executable = 'py'; Arguments = @('-3') },
		[PSCustomObject]@{ Executable = 'python'; Arguments = @() }
	)

	foreach ($candidate in $candidates) {
		if ((Get-Command -Name $candidate.Executable -ErrorAction SilentlyContinue) -and
			(Test-Python3Command -Command $candidate)) {
			return $candidate
		}
	}

	return $null
}

# Creates the virtual environment and installs the project's Python packages.
function New-ProjectVirtualEnvironment {
	$pythonCommand = Get-DefaultPython3Command
	if (-not $pythonCommand) {
		throw "Python 3 was not found. Install it and ensure it is available on PATH."
	}

	if (-not (Test-Path -LiteralPath $activateVenvRequirements -PathType Leaf)) {
		throw "Requirements file not found: $activateVenvRequirements"
	}

	Write-Host "Creating Python virtual environment in $activateVenvDir..."
	$pythonArguments = @($pythonCommand.Arguments) + @('-m', 'venv', $activateVenvDir)
	& $pythonCommand.Executable @pythonArguments
	if ($LASTEXITCODE -ne 0) {
		throw "Python failed to create the virtual environment."
	}

	Write-Host "Installing packages from $activateVenvRequirements..."
	& $activateVenvPython -m pip install -r $activateVenvRequirements
	if ($LASTEXITCODE -ne 0) {
		throw "Python failed to install the required packages."
	}
}

try {
	if ((Test-Path -LiteralPath $activateVenvDir) -and
		-not (Test-Path -LiteralPath $activateVenvPython -PathType Leaf)) {
		throw "An incomplete virtual environment exists at $activateVenvDir. Remove it manually and run this script again."
	}

	if (-not (Test-Path -LiteralPath $activateVenvPython -PathType Leaf)) {
		New-ProjectVirtualEnvironment
	}

	. $activateVenvActivation
	Write-Host "Activated Python virtual environment: $env:VIRTUAL_ENV"
} finally {
	Remove-Item -Path Function:\Test-Python3Command -ErrorAction SilentlyContinue
	Remove-Item -Path Function:\Get-DefaultPython3Command -ErrorAction SilentlyContinue
	Remove-Item -Path Function:\New-ProjectVirtualEnvironment -ErrorAction SilentlyContinue
	Remove-Variable -Name activateVenvScriptDir, activateVenvDir, activateVenvPython, activateVenvRequirements, activateVenvActivation -ErrorAction SilentlyContinue
}
