# Launches the installed Codex CLI in this project with a safe prepared-task configuration.

[CmdletBinding()]
param(
	[string] $Prompt,
	[string] $ProjectRoot = (Split-Path -Parent $PSScriptRoot),
	[string] $CodexPath,
	[string] $ConversationTitle,
	[switch] $NonInteractive
)

$defaultPrompt = @'
Work on the prepared task described by this project's AGENTS.md, brief.md, TODO, and relevant documentation.

Complete the whole task when that is feasible in this run. Otherwise, complete the first coherent and useful step that reduces uncertainty or advances the project without prematurely implementing later decisions.

Before finishing, make your final response a complete Markdown run report containing:
- the task or proposal addressed and the scope selected for this run;
- work performed and important files changed;
- validation performed, results, and anything not validated;
- decisions, assumptions, uncertainties, and blockers;
- whether the prepared task is complete; and
- the concrete recommended next step when work remains.

Also create a timestamped report under docs/reports/ when filesystem access permits. Follow all project agent instructions, preserve unrelated work, never write to a Git remote, and do not make unapproved persistent external mutations. Task-scoped outgoing text communication remains allowed by the project-island model.
'@

if ([string]::IsNullOrWhiteSpace($Prompt)) {
	$Prompt = $defaultPrompt
}

try {
	$resolvedProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot -ErrorAction Stop).Path
} catch {
	Write-Error "Project root was not found: $ProjectRoot"
	exit 1
}

if ([string]::IsNullOrWhiteSpace($ConversationTitle)) {
	$ConversationTitle = Split-Path -Leaf $resolvedProjectRoot
}

# Prefer an explicit path or PATH command, then discover binaries bundled with
# the Codex desktop application or VS Code extension. Bundled paths are
# versioned and therefore unsuitable as permanent PATH entries.
$resolvedCodexPath = $null
if (-not [string]::IsNullOrWhiteSpace($CodexPath)) {
	try {
		$resolvedCodexPath = (Resolve-Path -LiteralPath $CodexPath -ErrorAction Stop).Path
	} catch {
		Write-Error "Codex executable was not found: $CodexPath"
		exit 1
	}
} else {
	$codexCommand = Get-Command -Name 'codex' -CommandType Application,ExternalScript -ErrorAction SilentlyContinue | Select-Object -First 1
	if ($codexCommand) {
		$resolvedCodexPath = $codexCommand.Source
	}
}

if (-not $resolvedCodexPath) {
	$codexCandidates = @()
	$searchPatterns = @(
		(Join-Path $env:LOCALAPPDATA 'OpenAI\Codex\bin\*\codex.exe'),
		(Join-Path $env:USERPROFILE '.vscode\extensions\openai.chatgpt-*-win32-x64\bin\windows-x86_64\codex.exe'),
		(Join-Path $env:USERPROFILE '.vscode-insiders\extensions\openai.chatgpt-*-win32-x64\bin\windows-x86_64\codex.exe')
	)
	foreach ($pattern in $searchPatterns) {
		$codexCandidates += Get-ChildItem -Path $pattern -File -ErrorAction SilentlyContinue
	}
	$resolvedCodexPath = $codexCandidates |
		Sort-Object -Property LastWriteTime -Descending |
		Select-Object -First 1 -ExpandProperty FullName
}

if (-not $resolvedCodexPath) {
	Write-Error 'Codex CLI was not found on PATH or in known Codex application/extension locations. Install the standalone CLI or pass -CodexPath.'
	exit 1
}

$effectivePrompt = @"
Project: $ConversationTitle
Requested conversation title: $ConversationTitle

Treat the resolved workspace root as the authoritative search and write boundary. Inspect its immediate children before any broader search. Resolve the exact primary implementation target from the Execution Context in brief.md. Do not search outside the workspace for another checkout, even if one exists, unless the current human prompt or brief.md names its exact external path. If the target declaration is missing, contradictory, or absent on disk, stop before making changes and report the ambiguity.

Apply the project-island model: use the working directory as the default mutation boundary. Task-relevant internet research, authorized downloads into the project, read access elsewhere on the system, outgoing text communication, task-authorized peripheral interaction, and discovery and execution of already installed system or user-level tools and toolchains are allowed when otherwise safe. Normal use of an installed compiler, SDK, interpreter, debugger, package manager, or command-line utility is not an installation. Without an explicit current human request or approval, do not install into, update, or reconfigure a global toolchain; install new software or drivers; modify another project or outside directory; upload files to a cloud service, Git host, or permanent archive; push Git changes; or mutate an externally hosted database.

If this task uses Python, first create or activate the primary implementation target's project-local scripts/.venv through its platform-specific scripts/activate_venv helper. Use an existing compatible system or user-level Python installation as the bootstrap executable that runs -m venv; this is required use of the installed toolchain, not a prohibited fallback. If the helper reports Python missing, perform read-only interpreter discovery and reconcile that result before proposing an installation. Before installing any package or running project Python commands, verify that both sys.executable and sys.prefix resolve inside that exact scripts/.venv directory. Use that local environment's interpreter explicitly for automation. Never install project packages into or run project work with the bootstrap, global, system, user-site, wrapper, payload, reference-project, or unrelated environment. Never use bare pip or pip3. If the local environment still cannot be created or used after discovery and diagnosis, stop and report the specific blocker.

$Prompt

"@ + @'


Execution-context rule: this prepared project is self-contained. Do not read the global MEMORY.md file. If a concrete missing fact genuinely requires historical memory, search MEMORY.md for the project name or exact topic and read only the matching lines; never dump the complete memory registry or unrelated rollout summaries into context.
'@

$reportPath = $null
$conversationLogPath = $null
$stderrLogPath = $null
$terminalTranscriptPath = $null
$runStamp = Get-Date -Format 'yyyy-MM-dd_HHmmss'
if ($NonInteractive) {
	$reportDirectory = Join-Path $resolvedProjectRoot 'docs\reports'
	$logDirectory = Join-Path $resolvedProjectRoot 'logs'
	New-Item -ItemType Directory -Path $reportDirectory -Force | Out-Null
	New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
	$reportName = '{0}_codex_run.md' -f $runStamp
	$reportPath = Join-Path $reportDirectory $reportName
	$conversationLogPath = Join-Path $logDirectory ('{0}_codex_conversation.jsonl' -f $runStamp)
	$stderrLogPath = Join-Path $logDirectory ('{0}_codex_stderr.log' -f $runStamp)
	$effectivePrompt += "`n`nThe launcher will save your final response to $reportName. Make that final response self-contained because it is the durable fallback report when direct report-file creation fails."
} else {
	$logDirectory = Join-Path $resolvedProjectRoot 'logs'
	New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
	$terminalTranscriptPath = Join-Path $logDirectory ('{0}_codex_terminal_transcript.txt' -f $runStamp)
}

if ($NonInteractive) {
	$codexArguments = @(
		'--disable', 'memories',
		'--sandbox', 'workspace-write',
		'--ask-for-approval', 'never',
		'exec',
		'--json',
		'--output-last-message', $reportPath
	)
} else {
	$codexArguments = @(
		'--disable', 'memories',
		'--sandbox', 'workspace-write',
		'--ask-for-approval', 'on-request',
		'--no-alt-screen'
	)
}
$codexArguments += @('-C', $resolvedProjectRoot, $effectivePrompt)

# Trust only this prepared repository for Git commands in the child process.
# This avoids a global safe.directory change when preparation and execution use
# different Windows sandbox identities.
$previousGitConfigCount = $env:GIT_CONFIG_COUNT
$gitConfigIndex = 0
if ($previousGitConfigCount -match '^\d+$') {
	$gitConfigIndex = [int] $previousGitConfigCount
}
$gitConfigKeyName = "GIT_CONFIG_KEY_$gitConfigIndex"
$gitConfigValueName = "GIT_CONFIG_VALUE_$gitConfigIndex"
Set-Item -Path "Env:$gitConfigKeyName" -Value 'safe.directory'
Set-Item -Path "Env:$gitConfigValueName" -Value $resolvedProjectRoot
$env:GIT_CONFIG_COUNT = ($gitConfigIndex + 1).ToString()

# Normalize native-process text so UTF-8 punctuation survives Windows
# PowerShell capture and redirection.
$previousConsoleInputEncoding = [Console]::InputEncoding
$previousConsoleOutputEncoding = [Console]::OutputEncoding
$previousPowerShellOutputEncoding = $OutputEncoding
$utf8Encoding = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding = $utf8Encoding
[Console]::OutputEncoding = $utf8Encoding
$OutputEncoding = $utf8Encoding
$transcriptStarted = $false
$codexEventCount = 0

try {
	if ($NonInteractive) {
		# Preserve the effective input as a launcher-owned first event because
		# Codex's stdout stream begins with execution events rather than the prompt.
		$promptEvent = [ordered]@{
			type = 'launcher.prompt'
			timestamp = (Get-Date).ToString('o')
			conversation_title = $ConversationTitle
			workspace = $resolvedProjectRoot
			prompt = $effectivePrompt
		} | ConvertTo-Json -Compress
		[System.IO.File]::WriteAllText(
			$conversationLogPath,
			$promptEvent + [Environment]::NewLine,
			$utf8Encoding
		)

		# Codex JSONL contains agent messages, reasoning, tool calls, and results
		# needed to review the complete emitted non-interactive run later.
		& $resolvedCodexPath @codexArguments 2> $stderrLogPath | ForEach-Object {
			$eventLine = [string] $_
			$codexEventCount++
			[System.IO.File]::AppendAllText(
				$conversationLogPath,
				$eventLine + [Environment]::NewLine,
				$utf8Encoding
			)
			Write-Output $eventLine
		}
		$codexExitCode = $LASTEXITCODE
	} else {
		# Inline TUI mode lets PowerShell capture a best-effort terminal transcript.
		# Raw keystrokes and screen-control behavior can still vary by terminal host.
		try {
			Start-Transcript -LiteralPath $terminalTranscriptPath -Force -ErrorAction Stop | Out-Null
			$transcriptStarted = $true
		} catch {
			Write-Warning "Could not start the interactive terminal transcript: $($_.Exception.Message)"
		}
		& $resolvedCodexPath @codexArguments
		$codexExitCode = $LASTEXITCODE
	}
} finally {
	if ($transcriptStarted) {
		Stop-Transcript | Out-Null
	}
	[Console]::InputEncoding = $previousConsoleInputEncoding
	[Console]::OutputEncoding = $previousConsoleOutputEncoding
	$OutputEncoding = $previousPowerShellOutputEncoding
	Remove-Item -Path "Env:$gitConfigKeyName" -ErrorAction SilentlyContinue
	Remove-Item -Path "Env:$gitConfigValueName" -ErrorAction SilentlyContinue
	if ($null -eq $previousGitConfigCount) {
		Remove-Item -Path 'Env:GIT_CONFIG_COUNT' -ErrorAction SilentlyContinue
	} else {
		$env:GIT_CONFIG_COUNT = $previousGitConfigCount
	}
}

if ($null -eq $codexExitCode) {
	$codexExitCode = 0
}

if ($NonInteractive) {
	if (-not (Test-Path -LiteralPath $conversationLogPath -PathType Leaf) -or
		(Get-Item -LiteralPath $conversationLogPath).Length -eq 0 -or
		$codexEventCount -eq 0) {
		Write-Error "Codex did not produce the required conversation log: $conversationLogPath"
		if ($codexExitCode -eq 0) {
			$codexExitCode = 3
		}
	} else {
		Write-Host "Codex conversation log: $conversationLogPath"
		Write-Host "Codex stderr log: $stderrLogPath"
	}
	if (-not (Test-Path -LiteralPath $reportPath -PathType Leaf) -or
		(Get-Item -LiteralPath $reportPath).Length -eq 0) {
		Write-Error "Codex did not produce the required run report: $reportPath"
		if ($codexExitCode -eq 0) {
			$codexExitCode = 2
		}
	} else {
		Write-Host "Codex run report: $reportPath"
	}
} elseif ($transcriptStarted) {
	Write-Host "Codex terminal transcript: $terminalTranscriptPath"
}

exit $codexExitCode
