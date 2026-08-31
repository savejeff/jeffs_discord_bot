# Work on the Prepared Task

## Purpose

`work_on_prepared_task.ps1` launches Codex in the prepared project with explicit execution guarantees suited to a run without an interactive UI.

The default task prompt tells the agent to complete the prepared task, or its first coherent useful step, and make its final response a complete Markdown report. It also identifies the project by name, applies the project-island mutation boundary, confines discovery to the selected workspace, requires the exact implementation target to come from `brief.md`, and makes project-local Python isolation mandatory.

For non-interactive runs, the launcher saves the final response under `docs/reports/<timestamp>_codex_run.md` and the complete emitted conversation record under `logs/<timestamp>_codex_conversation.jsonl`. The first JSONL object preserves the effective prompt; subsequent objects are the Codex event stream. Native diagnostic output is kept separately in `logs/<timestamp>_codex_stderr.log`, so it cannot corrupt the JSONL. The launcher returns an error when the report is missing or when Codex emits no conversation events.

## Usage

Run Codex non-interactively:

```powershell
.\scripts\work_on_prepared_task.ps1 -NonInteractive
```

Start an interactive Codex session:

```powershell
.\scripts\work_on_prepared_task.ps1
```

Replace the task-specific prompt text:

```powershell
.\scripts\work_on_prepared_task.ps1 -NonInteractive -Prompt 'Review the implementation and run its tests.'
```

Select a project or Codex executable explicitly:

```powershell
.\scripts\work_on_prepared_task.ps1 `
	-ProjectRoot 'C:\Projects\prepared-project' `
	-ConversationTitle 'Prepared Project' `
	-CodexPath 'C:\Tools\codex.exe' `
	-NonInteractive
```

## Parameters

| Parameter | Meaning |
|---|---|
| `-Prompt <text>` | Replaces the task-specific part of the default prompt. Mandatory memory-hygiene and report-capture instructions remain active. |
| `-ProjectRoot <path>` | Workspace passed to Codex with `-C`. Defaults to the parent of this script's `scripts/` directory. |
| `-CodexPath <path>` | Uses a specific Codex executable. Otherwise the script checks PATH and known Codex desktop/VS Code extension locations. |
| `-ConversationTitle <text>` | Project identity placed at the beginning of the initial prompt. Defaults to the workspace directory name. This improves automatic titles but cannot force a title in clients that expose no rename operation. |
| `-NonInteractive` | Uses `codex exec`, captures the final response as a report, and exits when the turn finishes. |

## Execution Policy

- Non-interactive mode uses `workspace-write` with approval policy `never`. Codex can edit the prepared project but cannot obtain broader permissions when no user interface is available.
- Interactive mode uses `workspace-write` with approval policy `on-request`.
- The workspace passed with `-ProjectRoot` is the search and write boundary. The prompt prohibits searching other drives or sibling repositories for an alternative checkout unless the human prompt or `brief.md` provides an exact external path.
- The project-island prompt distinguishes observation and communication from mutation: research, authorized project-local downloads, task-relevant system reads, outgoing text, authorized peripheral interaction, and execution of installed tools and toolchains remain available, while global toolchain modification, outside-project modification, file upload, Git push, and external database mutation require explicit human approval.
- When Python is needed, the prompt requires the primary implementation target's `scripts/.venv`. An existing compatible system Python is used only to bootstrap that environment. The agent must perform read-only interpreter discovery when aliases fail, verify `sys.executable` and `sys.prefix` are inside the resulting environment, and invoke its interpreter explicitly for dependency installation and project work. It may not install into the bootstrap interpreter.
- The launcher asks the agent to use `-ConversationTitle`, but the installed Codex CLI has no explicit thread-title option. Title selection therefore remains client-dependent.
- The memory feature is disabled for the invocation because prepared handoffs are self-contained. The prompt also prohibits reading the complete global `MEMORY.md` registry.
- The launcher never enables `danger-full-access` or an approval/sandbox bypass.
- Git receives a process-local `safe.directory` entry for the exact project root. No global Git configuration is changed.
- Native-process input/output is set to UTF-8 during the Codex invocation and restored afterward.

## Report Behavior

In non-interactive mode, `--output-last-message` saves the final agent response to a unique report path. This gives the run a durable record even when the agent is blocked before it can create files itself. The report should include scope, work, validation, decisions, blockers, completion state, and the recommended next step.

The launcher verifies that the report exists and is not empty. A missing report changes an otherwise successful launcher exit to code `2`. A nonzero Codex exit code remains nonzero even when a partial report exists.

## Conversation Log Behavior

In non-interactive mode, `--json` emits Codex events as JSONL. The launcher first records its effective prompt as a `launcher.prompt` object, then mirrors every stdout event to `logs/<timestamp>_codex_conversation.jsonl` while keeping stderr in a separate companion log. The JSONL is the reviewable raw record of input, agent messages, reasoning events exposed by Codex, tool activity, and results. A missing log or a run with no Codex events changes an otherwise successful launcher exit to code `3`.

Interactive mode uses inline terminal rendering and starts a best-effort PowerShell transcript under `logs/`. Terminal hosts do not guarantee that raw keystrokes or every screen-control update is transcriptable, so use `-NonInteractive` when a complete machine-readable run record is required.

Conversation logs can contain source fragments, commands, tool results, and user input. Do not enter or print credentials, personal data, or other secrets during a logged run. Keep `logs/` ignored unless a reviewed log is intentionally promoted as evidence.

## Codex Discovery

The launcher resolves Codex in this order:

1. explicit `-CodexPath`;
2. `codex` available on PATH;
3. versioned binaries bundled with the Codex desktop application;
4. versioned binaries bundled with the stable or Insiders VS Code OpenAI extension.

A standalone CLI on PATH remains preferable because application and extension bundle paths change during updates.
