# Compiled Agent Guidelines

## Scope and Change Safety

- Understand the requested outcome and inspect existing work before editing.
- Preserve unrelated user changes and keep modifications focused on the task.
- Prefer established architecture and ownership boundaries over introducing parallel structures.
- Never write to a Git remote. Treat other persistent external mutations according to the project-island boundary; task-scoped outgoing text communication is the explicit standing exception.
- Ask before an action would materially expand scope, alter external state, or require a decision that cannot be recovered from project context.

## Project Island Boundary

- Model the project as an island-like function block: task briefings, project files, supplied resources, authorized observations, and research are inputs; implementation, documentation, reports, logs, data, and other deliverables are outputs inside the declared working directory.
- The working directory is a mutation boundary, not an observation boundary. Task-relevant internet research, authorized downloads into the project, read access elsewhere on the computer, outgoing text communication, and interaction with task-authorized peripherals remain available when otherwise safe.
- Discover and execute already installed system or user-level tools and toolchains when they are relevant to the task. Reading or invoking an existing compiler, SDK, interpreter, debugger, package manager, or command-line utility is allowed; installing components into it, updating it, or changing its global configuration remains an external mutation that requires approval.
- External visibility does not grant external write authority. Without explicit current human approval, do not install global/user Python packages, system software, drivers, services, or privileged components; modify outside projects or directories; upload files to cloud services, Git hosts, or permanent archives; push Git changes; or mutate externally hosted databases.
- Sending text status, results, or questions through an approved channel is allowed, but does not authorize attachments, project-file uploads, disclosure of secrets, or unrelated persistent service changes.
- When an external mutation is genuinely required, stop before it, identify the exact target, intended change, data involved, persistence, risks, alternatives, and recovery path, and request narrow human approval. Follow `docs/agent/PROJECT_ISLAND_MODEL.md`.

## Documentation and Implementation

- Treat `docs/` as durable project knowledge and update it when architecture, behavior, or development procedures change.
- Treat `agent/` as compiled operational guidance. Keep it concise, actionable, and derived from the maintained project documentation rather than copying extensive rationale into it.
- Treat `agent/TIPS.md` as a concise registry of recurring, specific traps and proven workarounds. Do not turn it into a second general guideline document.
- Document integration plans before substantial hardware-facing or architecture-changing work.
- Use `docs/reports/` for run-specific conclusions and `logs/` for raw captures.
- Treat `docs/ideas.md` and `docs/notes.md` as primarily human-managed inputs. Agents may improve formatting and clarity while preserving intent; do not silently promote an idea or note into an approved task or requirement.
- Use `docs/whitepaper/` for agent-compiled considerations, alternatives, tradeoffs, and concept studies that are broader than one run report but are not yet settled project requirements or architecture decisions.
- Treat `res/` as runtime-read-only and `tmp/` as disposable unversioned material. Put persistent manual runner playgrounds under ignored `develop/`, machine-local testcase projects under ignored `test/`, and automated version-controlled checks under `tests/`.
- Keep optional tools in `toolbox/` with origin, dependencies, assumptions, and validation status; copy them into a project only when its concrete workflow justifies the added surface area.

## Validation and Evidence

- Validate changes at the level they affect and state the boundary of the evidence.
- Do not present a build, static check, simulation, network probe, or visual inspection as proof of a different validation level.
- Record the exact environment, command, target, and important limitations when results need to remain useful later.
- Report checks that were not run and distinguish implementation completion from external, device, or human validation still required.

## Python Environment Isolation

- Treat the primary implementation target's `scripts/.venv` as the only permitted Python environment for package installation, project commands, tests, and Python-based helper tools.
- Create or activate it through the matching `scripts/activate_venv.ps1`, `.bat`, or `.sh` helper before Python work. In wrapper projects, resolve the primary target from `brief.md`; do not mistakenly use a wrapper, reference, payload, global, or unrelated environment.
- Use an existing compatible system or user-level Python installation as the bootstrap executable that runs `-m venv`. This is the intended use of the installed interpreter and does not violate isolation because the created environment and all installed project dependencies remain under `scripts/.venv`.
- If the activation helper cannot find Python, perform read-only discovery of installed interpreters and reconcile the helper's result before declaring Python absent or proposing an installation. Check command resolution, launcher-reported interpreter paths, and normal platform installation locations; then invoke a discovered compatible interpreter directly to create `scripts/.venv` or improve the helper when that is within scope.
- Before any `pip install` and before relying on test or tool output, verify that `sys.executable` and `sys.prefix` resolve beneath the expected `scripts/.venv` path. Prefer invoking that environment's interpreter explicitly in automation.
- Never use bare `pip`, `pip3`, or an unverified `python -m pip` for project dependency installation. Do not run project commands or tests in the bootstrap interpreter. If local environment creation or dependency installation still fails after interpreter discovery and diagnosis, report the specific blocker instead of installing packages into a user, system, or global interpreter.

## Code Quality

- Follow repository formatting, language, generated-file, and comment rules from `AGENTS.md` and the project briefing.
- Prefer clear ownership, small cohesive changes, and existing abstractions.
- Add dependencies only when justified by the task and document any new setup requirement.
- Avoid generated artifacts in version control unless the project explicitly treats them as source.
